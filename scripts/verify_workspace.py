#!/usr/bin/env python3
"""Verify a workspace is fully bootstrapped and safe."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from human_inputs import flatten_values, has_inline_secret, load_human_inputs

REQUIRED_FILES = [
    "AGENTS.md",
    "SOUL.md",
    "USER.md",
    "MEMORY.md",
    "HEARTBEAT.md",
    "BOOTSTRAP.md",
    "TOOLS.md",
    "pending-followups.md",
    "heartbeat-state.json",
    "memory/reference/work-context.md",
    "scripts/human_inputs.py",
    "scripts/memory_db.py",
    "scripts/memory_query.py",
    "scripts/memory_reconcile.py",
    "scripts/graph_summary.py",
    "scripts/secret_scan.py",
]

REQUIRED_DIRS = [
    "memory",
    "memory/reference",
    "memory/people",
    "memory/projects",
    "scripts",
]

PLACEHOLDER_MARKERS = ["{{", "}}", "REPLACE_ME", "TODO_FILL"]
REQUIRED_INPUT_KEYS = [
    "identity.agent_name",
    "identity.human_name",
    "identity.company",
    "identity.timezone",
]


def check_required(ws: Path) -> list[str]:
    missing = []
    for rel in REQUIRED_FILES:
        if not (ws / rel).exists():
            missing.append(rel)
    return missing


def check_required_dirs(ws: Path) -> list[str]:
    missing = []
    for rel in REQUIRED_DIRS:
        if not (ws / rel).is_dir():
            missing.append(rel)
    return missing


def check_placeholders(ws: Path) -> list[str]:
    offenders = []
    for rel in ["SOUL.md", "USER.md", "MEMORY.md", "AGENTS.md", "TOOLS.md"]:
        p = ws / rel
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        if any(m in text for m in PLACEHOLDER_MARKERS):
            offenders.append(rel)
    return offenders


def run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def check_inputs_file(ws: Path) -> tuple[bool, list[str]]:
    errors: list[str] = []
    inputs_path = ws / "HUMAN_INPUTS.yaml"
    if not inputs_path.exists():
        return False, ["HUMAN_INPUTS.yaml is missing"]

    try:
        payload = load_human_inputs(inputs_path)
    except Exception as exc:  # noqa: BLE001
        return False, [f"HUMAN_INPUTS.yaml parse error: {exc}"]

    flat = {k: v for k, v in flatten_values(payload)}

    for key in REQUIRED_INPUT_KEYS:
        if not flat.get(key, "").strip():
            errors.append(f"Missing required input: {key}")

    for key, value in flat.items():
        val = value.strip()
        if key.endswith("_ref"):
            if not (val.startswith("op://") or val.startswith("keychain:")):
                errors.append(f"Invalid secret reference format for {key} (use op:// or keychain:)")
        else:
            lowered = key.lower()
            if any(token in lowered for token in ["api_key", "token", "secret", "password"]):
                if val and not (val.startswith("op://") or val.startswith("keychain:")):
                    errors.append(f"Possible inline secret in {key}; use *_ref with op:// or keychain:")

    if has_inline_secret(inputs_path.read_text(encoding="utf-8", errors="ignore")):
        errors.append("HUMAN_INPUTS.yaml contains token-like secret values")

    return len(errors) == 0, errors


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify OpenClaw workspace bootstrap")
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--check-inputs", action="store_true", help="validate HUMAN_INPUTS.yaml schema and secret refs")
    args = ap.parse_args()

    ws = Path(args.workspace).expanduser().resolve()
    print(f"Verifying: {ws}")

    missing = check_required(ws)
    missing_dirs = check_required_dirs(ws)
    placeholders = check_placeholders(ws)

    ok = True
    if missing_dirs:
        ok = False
        print("❌ Missing directories:")
        for d in missing_dirs:
            print("  -", d)

    if missing:
        ok = False
        print("❌ Missing files:")
        for m in missing:
            print("  -", m)

    if placeholders:
        ok = False
        print("❌ Unresolved placeholders:")
        for p in placeholders:
            print("  -", p)

    if args.check_inputs:
        inputs_ok, input_errors = check_inputs_file(ws)
        if not inputs_ok:
            ok = False
            print("❌ HUMAN_INPUTS.yaml check failed:")
            for err in input_errors:
                print("  -", err)
        else:
            print("✅ HUMAN_INPUTS.yaml schema and refs look good")

    # memory DB health (best effort)
    mq = ws / "scripts" / "memory_query.py"
    if mq.exists():
        code, out = run(["python3", str(mq), "health"], ws)
        if code != 0:
            ok = False
            print("❌ memory_query health failed")
            print(out[:500])
        else:
            print("✅ memory_query health")

    # secret scan (blocking)
    secret_scan = ws / "scripts" / "secret_scan.py"
    if secret_scan.exists():
        code, out = run(["python3", str(secret_scan), "--path", str(ws)], ws)
        if code != 0:
            ok = False
            print("❌ secret scan failed")
            print(out[:500])
        else:
            print("✅ secret scan clean")

    # gateway status check (best effort)
    code, _ = run(["openclaw", "gateway", "status"], ws)
    if code == 0:
        print("✅ openclaw gateway status reachable")
    else:
        print("⚠️ openclaw gateway status check failed (non-blocking)")

    print("✅ Verification passed" if ok else "❌ Verification failed")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
