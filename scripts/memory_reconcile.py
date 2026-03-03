#!/usr/bin/env python3
"""
Memory Hybrid — Daily Reconciliation

Compares daily markdown files against the SQLite DB to detect drift.
Phase 2 shadow mode verification: are we actually dual-writing?

Usage:
    python3 memory_reconcile.py                  # Check today
    python3 memory_reconcile.py --date 2026-02-28  # Check specific date
    python3 memory_reconcile.py --days 7           # Check last 7 days

Reports:
    - DB entries with source_date matching the day(s)
    - Whether each entry's source_file exists and is readable
    - Whether the daily file has content that suggests entries NOT in DB
    - Write failure rate for the period

Exit codes:
    0 = clean (all checks pass)
    1 = drift detected (mismatches found)
    2 = error (couldn't run checks)
"""

import os
import sys
import re
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# Add scripts dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from memory_db import MemoryDB

def detect_workspace() -> str:
    explicit = os.getenv("OPENCLAW_WORKSPACE")
    if explicit:
        return os.path.expanduser(explicit)

    candidate = Path(__file__).resolve().parent.parent
    markers = ("AGENTS.md", "SOUL.md", "USER.md", "MEMORY.md")
    if all((candidate / m).exists() for m in markers):
        return str(candidate)

    return os.path.expanduser("~/.openclaw/workspace")


WORKSPACE = detect_workspace()
MEMORY_DIR = os.path.join(WORKSPACE, "memory")

# Keywords that suggest a typed entry should exist in the DB
TYPE_SIGNALS = {
    "decision": [
        r"(?i)\bdecision\b", r"(?i)\bdecided\b", r"(?i)\bchose\b",
        r"(?i)\bwill use\b", r"(?i)\bgoing with\b", r"(?i)\bpicked\b"
    ],
    "commitment": [
        r"(?i)\bcommit\b", r"(?i)\bpromised\b", r"(?i)\bwill do\b",
        r"(?i)\bagreed to\b", r"(?i)\btodo\b"
    ],
    "blocker": [
        r"(?i)\bblocked\b", r"(?i)\bblocker\b", r"(?i)\bcan't proceed\b",
        r"(?i)\bwaiting on\b", r"(?i)\bneeds .+ before\b"
    ],
    "preference": [
        r"(?i)\bprefers?\b", r"(?i)\bwants\b", r"(?i)\blikes?\b",
        r"(?i)\bhates?\b", r"(?i)\bdislikes?\b"
    ],
    "lesson": [
        r"(?i)\blesson\b", r"(?i)\blearned\b", r"(?i)\bnever again\b",
        r"(?i)\bmistake\b", r"(?i)\bgotcha\b"
    ],
}


def get_daily_file(date_str):
    """Get path to daily memory file for a date."""
    return os.path.join(MEMORY_DIR, f"{date_str}.md")


def scan_daily_file_for_signals(filepath):
    """Scan a daily file for lines that suggest typed entries should exist."""
    signals = []
    if not os.path.exists(filepath):
        return signals

    with open(filepath, "r") as f:
        lines = f.readlines()

    for i, line in enumerate(lines, 1):
        for entry_type, patterns in TYPE_SIGNALS.items():
            for pattern in patterns:
                if re.search(pattern, line):
                    # Avoid false positives from headers/metadata
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#") and len(stripped) > 20:
                        signals.append({
                            "line": i,
                            "type": entry_type,
                            "text": stripped[:100],
                            "pattern": pattern,
                        })
                        break  # One match per type per line is enough
            # Don't break outer loop — a line could signal multiple types

    return signals


def reconcile_date(db, date_str, verbose=False):
    """Reconcile a single date. Returns (issues, stats)."""
    issues = []
    stats = {"db_entries": 0, "file_signals": 0, "matched": 0, "unmatched_signals": 0}

    # Get DB entries for this date
    db_entries = [dict(r) for r in db.conn.execute(
        "SELECT * FROM memory_entries WHERE source_date = ?", (date_str,)
    ).fetchall()]
    stats["db_entries"] = len(db_entries)

    # Check source_file validity for each DB entry
    for entry in db_entries:
        if entry.get("source_file"):
            full_path = os.path.join(WORKSPACE, entry["source_file"])
            if not os.path.exists(full_path):
                issues.append({
                    "type": "orphan_source",
                    "entry_id": entry["id"][:12],
                    "title": entry["title"],
                    "source_file": entry["source_file"],
                    "detail": "Source file referenced by DB entry does not exist",
                })

    # Scan daily file for signals
    daily_file = get_daily_file(date_str)
    if not os.path.exists(daily_file):
        if len(db_entries) > 0:
            issues.append({
                "type": "no_daily_file",
                "detail": f"DB has {len(db_entries)} entries for {date_str} but no daily file exists",
            })
        return issues, stats

    signals = scan_daily_file_for_signals(daily_file)
    stats["file_signals"] = len(signals)

    # For each signal, check if a plausible DB entry exists
    # This is heuristic — we check if any DB entry for this date
    # matches the type and has overlapping keywords
    for signal in signals:
        matched = False
        signal_words = set(signal["text"].lower().split())
        for entry in db_entries:
            if entry["type"] == signal["type"]:
                entry_words = set(entry["title"].lower().split())
                if entry.get("body"):
                    entry_words.update(entry["body"].lower().split()[:20])
                overlap = signal_words & entry_words
                # Require at least 2 meaningful overlapping words
                meaningful = [w for w in overlap if len(w) > 3]
                if len(meaningful) >= 2:
                    matched = True
                    break
        if matched:
            stats["matched"] += 1
        else:
            stats["unmatched_signals"] += 1
            if verbose:
                issues.append({
                    "type": "possible_missed_entry",
                    "signal_type": signal["type"],
                    "line": signal["line"],
                    "text": signal["text"],
                    "detail": f"Line {signal['line']} suggests a {signal['type']} but no matching DB entry found",
                })

    # Check write failures for this date
    failures = db.conn.execute(
        "SELECT COUNT(*) as c FROM write_failures WHERE date(created_at) = ? AND resolved = 0",
        (date_str,)
    ).fetchone()["c"]
    if failures > 0:
        issues.append({
            "type": "unresolved_failures",
            "count": failures,
            "detail": f"{failures} unresolved write failures for {date_str}",
        })

    return issues, stats


def calculate_failure_rate(db, days=1):
    """Calculate write failure rate over a period. Returns (rate, total_writes, total_failures)."""
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    total_entries = db.conn.execute(
        "SELECT COUNT(*) as c FROM memory_entries WHERE date(created_at) >= ?",
        (since,)
    ).fetchone()["c"]

    total_failures = db.conn.execute(
        "SELECT COUNT(*) as c FROM write_failures WHERE date(created_at) >= ? AND resolved = 0",
        (since,)
    ).fetchone()["c"]

    total_writes = total_entries + total_failures
    rate = (total_failures / total_writes * 100) if total_writes > 0 else 0.0

    return rate, total_writes, total_failures


def main():
    parser = argparse.ArgumentParser(description="Memory hybrid reconciliation")
    parser.add_argument("--date", help="Specific date to check (YYYY-MM-DD)")
    parser.add_argument("--days", type=int, default=1, help="Number of days to check (default: 1 = today)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show possible missed entries")
    parser.add_argument("--rollback-threshold", type=float, default=5.0,
                        help="Failure rate %% that triggers rollback alert (default: 5.0)")
    args = parser.parse_args()

    db = MemoryDB()
    exit_code = 0

    # Determine dates to check
    if args.date:
        dates = [args.date]
    else:
        dates = []
        for i in range(args.days):
            d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            dates.append(d)

    print("=== Memory Hybrid Reconciliation ===\n")

    total_issues = []
    total_stats = {"db_entries": 0, "file_signals": 0, "matched": 0, "unmatched_signals": 0}

    for date_str in sorted(dates):
        issues, stats = reconcile_date(db, date_str, verbose=args.verbose)
        total_issues.extend(issues)
        for k in total_stats:
            total_stats[k] += stats[k]

        has_file = os.path.exists(get_daily_file(date_str))
        hard_issues = [i for i in issues if i["type"] in ("orphan_source", "no_daily_file", "unresolved_failures")]
        status = "✅" if not hard_issues else f"⚠️ {len(hard_issues)} issue(s)"

        # Flag days with content but zero DB entries as a drift warning
        if has_file and stats["db_entries"] == 0 and stats["file_signals"] > 0:
            status = "⚠️ daily file has content but 0 DB entries"

        print(f"  {date_str}: {stats['db_entries']} DB entries, {stats['file_signals']} file signals — {status}")

        for issue in hard_issues:
            print(f"    → {issue['detail']}")

        if args.verbose:
            soft_issues = [i for i in issues if i["type"] == "possible_missed_entry"]
            for issue in soft_issues:
                print(f"    ? {issue['detail']}")

    # Failure rate check
    print()
    rate, total_writes, total_failures = calculate_failure_rate(db, days=max(args.days, 1))
    print(f"  Write failure rate ({args.days}d): {rate:.1f}% ({total_failures}/{total_writes} writes)")

    if rate > args.rollback_threshold:
        print(f"\n  🚨 ROLLBACK TRIGGER: Failure rate {rate:.1f}% exceeds {args.rollback_threshold}% threshold!")
        print("  Action: Disable DB writes and alert the human owner.")
        exit_code = 1

    # Integrity check
    ok, result = db.integrity_check()
    print(f"  Integrity: {'✅ OK' if ok else '❌ ' + result}")
    if not ok:
        exit_code = 1

    # Graph health
    graph = db.graph_health()
    stats = db.stats()
    total_entries = stats.get("total_entries", 0)
    unlinked_entries = int(graph.get("unlinked_entries", 0))
    unlinked_pct = (unlinked_entries / total_entries * 100.0) if total_entries > 0 else 0.0
    orphan_entities = graph.get("orphan_entities", [])

    print(f"  Graph: {graph['total_entities']} entities, {graph['total_relations']} relations")
    print(f"  Unlinked entries: {unlinked_entries}/{total_entries} ({unlinked_pct:.1f}%)")
    print(f"  Orphan entities: {len(orphan_entities)}")

    if orphan_entities:
        sample = ", ".join(f"{e['name']} ({e['type']})" for e in orphan_entities[:5])
        more = " ..." if len(orphan_entities) > 5 else ""
        print(f"    → {sample}{more}")

    if graph.get("dangling_relations"):
        print(f"  ⚠️ Dangling relations: {len(graph['dangling_relations'])}")
        exit_code = 1

    if graph.get("duplicate_entities"):
        print(f"  ⚠️ Duplicate entities by name: {len(graph['duplicate_entities'])}")

    if unlinked_pct > 20.0:
        print("  Suggestion: run auto-linking (`MemoryDB().backfill_links()`) to reduce unlinked entries.")

    # Summary
    print(f"\n  Summary: {total_stats['db_entries']} DB entries across {len(dates)} day(s), "
          f"{len(total_issues)} issue(s) found")

    if total_stats["unmatched_signals"] > 0 and not args.verbose:
        print(f"  Note: {total_stats['unmatched_signals']} possible missed entries detected. "
              f"Run with --verbose to see details.")

    db.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
