#!/usr/bin/env python3
"""Bootstrap a new or existing OpenClaw workspace from this template."""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
from pathlib import Path

from human_inputs import load_human_inputs

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "workspace"
INPUT_TEMPLATE = TEMPLATE / "HUMAN_INPUTS.example.yaml"


def render(text: str, values: dict[str, str]) -> str:
    out = text
    for k, v in values.items():
        out = out.replace(f"{{{{{k}}}}}", v)
    return out


def ensure_inputs_file(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(INPUT_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")


def pick_value(cli_val: str | None, payload: dict, section: str, key: str) -> str | None:
    if cli_val:
        return cli_val
    sec = payload.get(section, {})
    if isinstance(sec, dict):
        val = sec.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def copy_template(workspace: Path, values: dict[str, str], upgrade: bool) -> None:
    workspace.mkdir(parents=True, exist_ok=True)

    required_dirs = [
        workspace / "memory",
        workspace / "memory" / "reference",
        workspace / "memory" / "people",
        workspace / "memory" / "projects",
        workspace / "scripts",
    ]
    for d in required_dirs:
        d.mkdir(parents=True, exist_ok=True)

    for src in sorted(TEMPLATE.iterdir()):
        if not src.is_file():
            continue
        # HUMAN_INPUTS is user-owned, do not overwrite unless missing
        if src.name == "HUMAN_INPUTS.example.yaml":
            continue
        dst = workspace / src.name
        if dst.exists() and not upgrade:
            continue
        content = src.read_text(encoding="utf-8")
        dst.write_text(render(content, values), encoding="utf-8")

    # Copy scripts (always refresh for deterministic upgrades)
    scripts_src = ROOT / "scripts"
    scripts_dst = workspace / "scripts"
    for py in scripts_src.glob("*.py"):
        dst_py = scripts_dst / py.name
        if py.resolve() == dst_py.resolve():
            continue
        shutil.copy2(py, dst_py)

    # Seed work context if absent
    wc = workspace / "memory" / "reference" / "work-context.md"
    if not wc.exists():
        wc.write_text(
            render((ROOT / "memory" / "reference" / "work-context.md").read_text(encoding="utf-8"), values),
            encoding="utf-8",
        )

    # Seed today's daily memory file for first-session dual-write hygiene
    daily = workspace / "memory" / f"{values['DATE']}.md"
    if not daily.exists():
        daily.write_text(f"# Daily Memory — {values['DATE']}\n\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Bootstrap OpenClaw workspace")
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--inputs", help="Path to HUMAN_INPUTS.yaml (default: <workspace>/HUMAN_INPUTS.yaml)")
    ap.add_argument("--init-inputs", action="store_true", help="Create HUMAN_INPUTS.yaml template and exit")
    ap.add_argument("--agent-name")
    ap.add_argument("--human-name")
    ap.add_argument("--company")
    ap.add_argument("--timezone")
    ap.add_argument("--upgrade", action="store_true", help="overwrite template files")
    args = ap.parse_args()

    ws = Path(args.workspace).expanduser().resolve()
    inputs_path = Path(args.inputs).expanduser().resolve() if args.inputs else ws / "HUMAN_INPUTS.yaml"

    if args.init_inputs:
        ensure_inputs_file(inputs_path)
        print(f"✅ Created input template: {inputs_path}")
        print("Fill it out, then run bootstrap again with --inputs (or rely on default location).")
        return 0

    ensure_inputs_file(inputs_path)
    payload = load_human_inputs(inputs_path)

    agent_name = pick_value(args.agent_name, payload, "identity", "agent_name")
    human_name = pick_value(args.human_name, payload, "identity", "human_name")
    company = pick_value(args.company, payload, "identity", "company")
    timezone = pick_value(args.timezone, payload, "identity", "timezone")

    missing = [
        name
        for name, value in [
            ("identity.agent_name", agent_name),
            ("identity.human_name", human_name),
            ("identity.company", company),
            ("identity.timezone", timezone),
        ]
        if not value
    ]

    if missing:
        print(f"❌ Missing required inputs in {inputs_path}:")
        for item in missing:
            print(f"  - {item}")
        print("Fill HUMAN_INPUTS.yaml, then rerun bootstrap.")
        return 2

    now = dt.datetime.now().date().isoformat()
    values = {
        "AGENT_NAME": agent_name or "",
        "HUMAN_NAME": human_name or "",
        "COMPANY": company or "",
        "TIMEZONE": timezone or "",
        "DATE": now,
    }

    # Keep canonical human inputs in workspace root
    ws.mkdir(parents=True, exist_ok=True)
    canonical_inputs = ws / "HUMAN_INPUTS.yaml"
    if inputs_path != canonical_inputs:
        shutil.copy2(inputs_path, canonical_inputs)

    copy_template(ws, values, upgrade=args.upgrade)

    print(f"✅ Workspace bootstrapped: {ws}")
    print(f"✅ Inputs source: {canonical_inputs}")
    print("Next:")
    print("  1) python3 scripts/verify_workspace.py --workspace", ws, "--check-inputs")
    print("  2) openclaw gateway status")
    print("  3) open an orientation chat and verify behavior")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
