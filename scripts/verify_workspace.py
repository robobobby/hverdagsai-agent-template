#!/usr/bin/env python3
"""Verify a workspace is fully bootstrapped and safe."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

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


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify OpenClaw workspace bootstrap")
    ap.add_argument("--workspace", required=True)
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
    code, out = run(["openclaw", "gateway", "status"], ws)
    if code == 0:
        print("✅ openclaw gateway status reachable")
    else:
        print("⚠️ openclaw gateway status check failed (non-blocking)")

    print("✅ Verification passed" if ok else "❌ Verification failed")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
