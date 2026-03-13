#!/usr/bin/env python3
"""Validate handoff documents conform to required format.

Usage: python3 scripts/validate_handoff.py <path_to_handoff.md>
Exit: 0=valid, 1=invalid
"""
import sys
import re

REQUIRED_SECTIONS = [
    "Context",
    "Deliverables",
    "Key Decisions Made",
    "Files Modified",
    "Known Risks",
    "Open Questions",
    "Recommendations",
]

def validate(path):
    with open(path) as f:
        content = f.read()

    errors = []

    # Check HANDOFF header
    if not re.search(r"##\s*HANDOFF:", content):
        errors.append("Missing '## HANDOFF:' header")

    # Check required sections
    for section in REQUIRED_SECTIONS:
        pattern = rf"###\s*{re.escape(section)}"
        match = re.search(pattern, content)
        if not match:
            errors.append(f"Missing section: ### {section}")
        else:
            # Check section has content
            start = match.end()
            next_section = re.search(r"\n###\s", content[start:])
            section_content = content[start:start + next_section.start()] if next_section else content[start:]
            if not section_content.strip():
                errors.append(f"Empty section: ### {section}")

    # Check Files Modified has file paths
    files_match = re.search(r"###\s*Files Modified\n(.*?)(?=\n###|\Z)", content, re.DOTALL)
    if files_match:
        files_content = files_match.group(1).strip()
        if files_content and not re.search(r"[/.]", files_content):
            errors.append("Files Modified section doesn't contain file paths (expected / or . characters)")

    if errors:
        for e in errors:
            print(f"  ERROR: {e}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 scripts/validate_handoff.py <path>", file=sys.stderr)
        sys.exit(1)
    sys.exit(validate(sys.argv[1]))
