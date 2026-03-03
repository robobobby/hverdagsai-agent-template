#!/usr/bin/env python3
"""Bootstrap a new or existing OpenClaw workspace from this template."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "workspace"


def render(text: str, values: dict[str, str]) -> str:
    out = text
    for k, v in values.items():
        out = out.replace(f"{{{{{k}}}}}", v)
    return out


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

    for src in sorted(TEMPLATE.glob("*")):
        if not src.is_file():
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
        shutil.copy2(py, scripts_dst / py.name)

    # Seed work context if absent
    wc = workspace / "memory" / "reference" / "work-context.md"
    if not wc.exists():
        wc.write_text(
            render((ROOT / "memory" / "reference" / "work-context.md").read_text(encoding="utf-8"), values),
            encoding="utf-8",
        )

    # Seed today's daily memory file for first-session dual-write hygiene.
    daily = workspace / "memory" / f"{values['DATE']}.md"
    if not daily.exists():
        daily.write_text(f"# Daily Memory — {values['DATE']}\n\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Bootstrap OpenClaw workspace")
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--agent-name", required=True)
    ap.add_argument("--human-name", required=True)
    ap.add_argument("--company", required=True)
    ap.add_argument("--timezone", required=True)
    ap.add_argument("--upgrade", action="store_true", help="overwrite template files")
    args = ap.parse_args()

    now = dt.datetime.now().date().isoformat()
    values = {
        "AGENT_NAME": args.agent_name,
        "HUMAN_NAME": args.human_name,
        "COMPANY": args.company,
        "TIMEZONE": args.timezone,
        "DATE": now,
    }

    ws = Path(args.workspace).expanduser().resolve()
    copy_template(ws, values, upgrade=args.upgrade)

    print(f"✅ Workspace bootstrapped: {ws}")
    print("Next:")
    print("  1) python3 scripts/verify_workspace.py --workspace", ws)
    print("  2) openclaw gateway status")
    print("  3) open an orientation chat and verify behavior")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
