#!/usr/bin/env python3
"""Scan files for leaked secrets.

Usage: python3 scripts/secret_scan.py [--path PATH] [--fix]
Exit: 0=clean, 1=secrets found
"""
import argparse
import os
import re
import sys

SECRET_PATTERNS = [
    (r"sk-[a-zA-Z0-9]{20,}", "OpenAI API key"),
    (r"ghp_[a-zA-Z0-9]{36}", "GitHub PAT"),
    (r"gho_[a-zA-Z0-9]{36}", "GitHub OAuth token"),
    (r"xoxb-[0-9]+-[a-zA-Z0-9]+", "Slack bot token"),
    (r"xoxp-[0-9]+-[a-zA-Z0-9]+", "Slack user token"),
    (r"AKIA[0-9A-Z]{16}", "AWS access key"),
    (r"(?i)(api[_-]?key|token|secret|password)\s*[=:]\s*['\"][a-zA-Z0-9+/=]{20,}['\"]", "Generic secret assignment"),
    (r"eyJ[a-zA-Z0-9_-]{50,}\.[a-zA-Z0-9_-]{50,}", "JWT token"),
]

SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", ".mypy_cache", ".pytest_cache"}
SCAN_EXTENSIONS = (".md", ".yaml", ".yml", ".json", ".txt", ".py", ".ts", ".js", ".sh", ".env", ".toml")


def scan_file(filepath):
    findings = []
    try:
        with open(filepath, encoding="utf-8") as f:
            content = f.read()
    except (UnicodeDecodeError, PermissionError):
        return findings

    for pattern, label in SECRET_PATTERNS:
        matches = re.finditer(pattern, content)
        for m in matches:
            findings.append({
                "file": filepath,
                "pattern": label,
                "match": m.group()[:20] + "...",
                "position": m.start(),
            })
    return findings

def main():
    parser = argparse.ArgumentParser(description="Scan a directory tree for potential secrets")
    parser.add_argument("--path", default=".", help="Path to scan (default: current directory)")
    parser.add_argument("--fix", action="store_true", help="Replace found secrets with [REDACTED]")
    args = parser.parse_args()

    scan_root = os.path.abspath(os.path.expanduser(args.path))
    if not os.path.isdir(scan_root):
        print(f"Path not found or not a directory: {scan_root}", file=sys.stderr)
        return 2

    all_findings = []

    for root, dirs, files in os.walk(scan_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fname in files:
            if fname.endswith(SCAN_EXTENSIONS):
                filepath = os.path.join(root, fname)
                findings = scan_file(filepath)
                all_findings.extend(findings)

    if all_findings:
        print(f"Found {len(all_findings)} potential secret(s):", file=sys.stderr)
        for f in all_findings:
            print(f"  {f['file']}: {f['pattern']} ({f['match']})", file=sys.stderr)

        if args.fix:
            for f in all_findings:
                with open(f['file'], encoding="utf-8") as fh:
                    content = fh.read()
                for pattern, _ in SECRET_PATTERNS:
                    content = re.sub(pattern, "[REDACTED]", content)
                with open(f['file'], 'w', encoding="utf-8") as fh:
                    fh.write(content)
            print(f"Redacted {len(all_findings)} finding(s)")

        return 1
    else:
        print("Clean: no secrets found")
        return 0

if __name__ == "__main__":
    sys.exit(main())
