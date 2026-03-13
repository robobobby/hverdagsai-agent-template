#!/usr/bin/env python3
"""Generate shared context files for specialist agents.

Reads from Bobby's workspace and knowledge graph to produce condensed
context files that all specialists share.

Usage:
    python3 scripts/shared_context_gen.py [--dry-run]
"""

import argparse
import os
import sys
import subprocess
import json
from pathlib import Path

SHARED_DIR = os.path.expanduser("~/.openclaw/shared-context")
WORKSPACE = os.path.expanduser("~/.openclaw/workspace")
MAX_CHARS = {
    "LUKA.md": 3200,      # ~800 tokens
    "PROJECTS.md": 2400,   # ~600 tokens
    "STANDARDS.md": 2000,  # ~500 tokens
    "DECISIONS.md": 2400,  # ~600 tokens
    "PRIORITIES.md": 2000, # ~500 tokens
}
TOTAL_TARGET = 12288  # 3000 tokens ~ 12KB


def generate_luka(dry_run=False):
    """Condensed user profile from USER.md."""
    user_md = os.path.join(WORKSPACE, "USER.md")
    if not os.path.exists(user_md):
        return "# Luka\n\nUSER.md not found. Ask Bobby for context.\n"

    with open(user_md) as f:
        content = f.read()

    # Extract key sections
    sections_to_keep = [
        "Personality & Communication",
        "Working Style",
        "Voice Preferences",
        "Values",
    ]

    lines = content.split("\n")
    output = ["# Luka (Condensed Profile)", ""]
    in_section = False
    current_section = ""

    for line in lines:
        if line.startswith("## "):
            section_name = line[3:].strip()
            in_section = any(s in section_name for s in sections_to_keep)
            if in_section:
                current_section = section_name
                output.append(line)
        elif in_section:
            output.append(line)

    result = "\n".join(output)
    if len(result) > MAX_CHARS["LUKA.md"]:
        result = result[:MAX_CHARS["LUKA.md"]] + "\n\n[truncated]"
    return result


def generate_projects(dry_run=False):
    """Active project registry from knowledge graph."""
    try:
        result = subprocess.run(
            ["python3", "scripts/memory_query.py", "entities"],
            capture_output=True, text=True, cwd=WORKSPACE, timeout=30
        )
        lines = result.stdout.strip().split("\n")
        projects = [l for l in lines if "project" in l.lower()]
    except Exception:
        projects = []

    if not projects:
        # Fallback: extract from MEMORY.md
        memory_md = os.path.join(WORKSPACE, "MEMORY.md")
        if os.path.exists(memory_md):
            with open(memory_md) as f:
                content = f.read()
            # Find Active Projects section
            in_projects = False
            output = ["# Active Projects", ""]
            for line in content.split("\n"):
                if "## Active Projects" in line:
                    in_projects = True
                    continue
                elif line.startswith("## ") and in_projects:
                    break
                elif in_projects:
                    output.append(line)
            return "\n".join(output)

    output = ["# Active Projects", "", "| Project | Type | Status |", "|---------|------|--------|"]
    for p in projects:
        output.append(f"| {p.strip()} |")

    result = "\n".join(output)
    if len(result) > MAX_CHARS["PROJECTS.md"]:
        result = result[:MAX_CHARS["PROJECTS.md"]] + "\n\n[truncated]"
    return result


def generate_standards(dry_run=False):
    """Universal standards from AGENTS.md + SOUL.md."""
    output = ["# Universal Standards", ""]

    # Extract writing rules from SOUL.md
    soul_md = os.path.join(WORKSPACE, "SOUL.md")
    if os.path.exists(soul_md):
        with open(soul_md) as f:
            content = f.read()
        in_writing = False
        for line in content.split("\n"):
            if "## Writing Rules" in line:
                in_writing = True
                output.append(line)
            elif line.startswith("## ") and in_writing:
                in_writing = False
            elif in_writing:
                output.append(line)

    # Add coding standards
    output.extend([
        "",
        "## Coding Standards",
        "- No em dashes in any output",
        "- Mobile-first with 44px+ tap targets",
        "- CSS theme variables only, no hardcoded hex colors",
        "- TypeScript strict mode",
        "- All SQL parameterized, zero string interpolation",
        "- No single-file components over 200 lines without decomposition",
        "- PR-only workflow: branch, commit, PR (unless MC/Sofa1 where main push is OK)",
        "",
        "## Communication Standards",
        "- Reports and structured output: ALWAYS English",
        "- Danish only for casual conversation",
        "- Be specific, not vague",
        "- Have a point of view",
    ])

    result = "\n".join(output)
    if len(result) > MAX_CHARS["STANDARDS.md"]:
        result = result[:MAX_CHARS["STANDARDS.md"]] + "\n\n[truncated]"
    return result


def generate_decisions(dry_run=False):
    """Recent key decisions from memory DB."""
    try:
        result = subprocess.run(
            ["python3", "scripts/memory_query.py", "decisions"],
            capture_output=True, text=True, cwd=WORKSPACE, timeout=30
        )
        content = result.stdout.strip()
    except Exception:
        content = ""

    if not content:
        return "# Recent Decisions\n\nNo decisions found in memory DB.\n"

    # Take last 20 decisions, format as bullet list
    lines = content.split("\n")
    output = ["# Recent Decisions", ""]
    count = 0
    for line in lines:
        if line.strip():
            output.append(f"- {line.strip()}")
            count += 1
            if count >= 20:
                break

    result = "\n".join(output)
    if len(result) > MAX_CHARS["DECISIONS.md"]:
        result = result[:MAX_CHARS["DECISIONS.md"]] + "\n\n[truncated]"
    return result


def generate_priorities(dry_run=False):
    """Current priority stack from Todoist."""
    try:
        result = subprocess.run(
            ["python3", "scripts/todoist_workflow.py"],
            capture_output=True, text=True, cwd=WORKSPACE, timeout=30
        )
        content = result.stdout.strip()
    except Exception:
        content = ""

    if not content:
        return "# Current Priorities\n\nTodoist unavailable.\n"

    output = ["# Current Priorities", "", content]
    result = "\n".join(output)
    if len(result) > MAX_CHARS["PRIORITIES.md"]:
        result = result[:MAX_CHARS["PRIORITIES.md"]] + "\n\n[truncated]"
    return result


def main():
    parser = argparse.ArgumentParser(description="Generate shared context for specialist agents")
    parser.add_argument("--dry-run", action="store_true", help="Print without writing")
    args = parser.parse_args()

    os.makedirs(SHARED_DIR, exist_ok=True)

    generators = {
        "LUKA.md": generate_luka,
        "PROJECTS.md": generate_projects,
        "STANDARDS.md": generate_standards,
        "DECISIONS.md": generate_decisions,
        "PRIORITIES.md": generate_priorities,
    }

    total_bytes = 0
    for filename, gen_func in generators.items():
        content = gen_func(dry_run=args.dry_run)
        filepath = os.path.join(SHARED_DIR, filename)
        total_bytes += len(content.encode("utf-8"))

        if args.dry_run:
            print(f"\n{'='*60}")
            print(f"  {filename} ({len(content)} chars)")
            print(f"{'='*60}")
            print(content[:500] + ("..." if len(content) > 500 else ""))
        else:
            with open(filepath, "w") as f:
                f.write(content)
            print(f"  Generated {filename} ({len(content)} chars)")

    # Increment VERSION
    version_file = os.path.join(SHARED_DIR, "VERSION")
    current = 1
    if os.path.exists(version_file):
        try:
            current = int(open(version_file).read().strip())
        except (ValueError, FileNotFoundError):
            current = 1

    new_version = current + 1
    if not args.dry_run:
        with open(version_file, "w") as f:
            f.write(str(new_version))

    # Check FACTS.md exists (not generated, manually maintained)
    facts_path = os.path.join(SHARED_DIR, "FACTS.md")
    facts_exists = os.path.exists(facts_path)

    print(f"\n  Total: {total_bytes} bytes (~{total_bytes // 4} tokens)")
    print(f"  VERSION: {current} -> {new_version}")
    print(f"  FACTS.md: {'exists' if facts_exists else 'MISSING (create manually)'}")
    print(f"  Target: < {TOTAL_TARGET} bytes")
    print(f"  Status: {'OK' if total_bytes < TOTAL_TARGET else 'OVER LIMIT'}")

    if total_bytes >= TOTAL_TARGET:
        print("  WARNING: Total exceeds target. Consider trimming.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
