#!/usr/bin/env python3
"""Instinct extraction from completed specialist tasks.

After a specialist completes a task, Bobby runs this to extract
reusable patterns (instincts) from the output and any Luka feedback.

Instinct lifecycle: candidate -> active -> core -> archived
Promotion: candidate->active after 2+ observations or Luka correction.
           active->core when confidence>=0.8 and no contradictions for 30 days.
           archived when confidence<0.2 or contradicted.
"""
import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = os.environ.get(
    "ORCHESTRATION_DB",
    os.path.expanduser("~/.openclaw/orchestration/state.db"),
)


def _get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db


def _ensure_instinct_table(db):
    """Create instinct table if it doesn't exist."""
    db.executescript("""
        CREATE TABLE IF NOT EXISTS instincts (
            id TEXT PRIMARY KEY,
            specialist TEXT NOT NULL,
            trigger_pattern TEXT NOT NULL,
            action TEXT NOT NULL,
            lifecycle TEXT NOT NULL DEFAULT 'candidate'
                CHECK(lifecycle IN ('candidate','active','core','archived')),
            confidence REAL NOT NULL DEFAULT 0.5
                CHECK(confidence >= 0.0 AND confidence <= 1.0),
            observation_count INTEGER NOT NULL DEFAULT 1,
            source_task_id TEXT,
            corrections TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            promoted_at TEXT,
            archived_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_instincts_specialist
            ON instincts(specialist);
        CREATE INDEX IF NOT EXISTS idx_instincts_lifecycle
            ON instincts(lifecycle);
    """)


def extract_instincts(task_id, specialist, corrections=None, dry_run=False):
    """Extract instincts from a completed task.

    Reads the task's result_path (handoff document) and extracts
    patterns that could become reusable instincts.

    Returns list of extracted instinct dicts.
    """
    db = _get_db()
    _ensure_instinct_table(db)

    # Get task info
    row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        print(f"Error: task {task_id} not found", file=sys.stderr)
        return []

    if row["status"] not in ("done", "completed", "failed", "escalated"):
        print(
            f"Warning: task {task_id} status is '{row['status']}', "
            "expected done/failed/escalated",
            file=sys.stderr,
        )

    # Read result/handoff if available
    result_text = ""
    if row["result_path"] and os.path.exists(row["result_path"]):
        result_text = Path(row["result_path"]).read_text()

    # Read task events for context
    events = db.execute(
        "SELECT * FROM task_events WHERE task_id = ? ORDER BY created_at",
        (task_id,),
    ).fetchall()

    instincts = []

    # Extract from task outcome
    instinct_data = {
        "specialist": specialist,
        "source_task_id": task_id,
        "corrections": corrections,
    }

    # Pattern: task completed successfully on first try
    if row["status"] in ("done", "completed") and row["iteration"] == 0:
        instincts.append({
            **instinct_data,
            "trigger_pattern": f"Task type: {row['project']} with {specialist}",
            "action": "First-pass success pattern. Review approach for reuse.",
            "confidence": 0.5,
        })

    # Pattern: task needed iterations
    if row["iteration"] > 0:
        feedback_events = [e for e in events if e["event_type"] == "review_failed"]
        for fe in feedback_events:
            payload = json.loads(fe["payload"]) if fe["payload"] else {}
            instincts.append({
                **instinct_data,
                "trigger_pattern": f"Review failure in {row['project']}: "
                    + payload.get("reason", "unknown"),
                "action": f"Iteration {row['iteration']} needed. "
                    "Check this pattern before submitting.",
                "confidence": 0.4,
            })

    # Pattern: task escalated
    if row["status"] == "escalated":
        instincts.append({
            **instinct_data,
            "trigger_pattern": f"Escalation: {row['escalation_reason'] or 'unknown'}",
            "action": "Flag similar tasks for early Bobby review.",
            "confidence": 0.6,
        })

    # Pattern: Luka gave corrections
    if corrections:
        instincts.append({
            **instinct_data,
            "trigger_pattern": f"Luka correction on {row['project']}/{specialist}",
            "action": corrections,
            "confidence": 0.7,
        })

    if dry_run:
        print(json.dumps(instincts, indent=2))
        return instincts

    # Write instincts to DB
    from ulid import ULID
    saved = []
    for inst in instincts:
        inst_id = str(ULID())
        db.execute(
            """INSERT INTO instincts
               (id, specialist, trigger_pattern, action, confidence,
                source_task_id, corrections)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                inst_id,
                inst["specialist"],
                inst["trigger_pattern"],
                inst["action"],
                inst["confidence"],
                inst["source_task_id"],
                inst.get("corrections"),
            ),
        )
        inst["id"] = inst_id
        saved.append(inst)

    # Write instinct_extracted event
    db.execute(
        """INSERT INTO task_events (task_id, event_type, payload, source_agent)
           VALUES (?, 'instinct_extracted', ?, ?)""",
        (
            task_id,
            json.dumps({"instinct_count": len(saved), "instinct_ids": [i["id"] for i in saved]}),
            "bobby",
        ),
    )
    db.commit()
    db.close()

    print(json.dumps(saved, indent=2))
    return saved


def promote_check(specialist=None):
    """Check which instincts qualify for promotion."""
    db = _get_db()
    _ensure_instinct_table(db)

    promotions = []

    # candidate -> active: observed >= 2 or has corrections
    candidates = db.execute(
        "SELECT * FROM instincts WHERE lifecycle = 'candidate'"
        + (" AND specialist = ?" if specialist else ""),
        (specialist,) if specialist else (),
    ).fetchall()

    for c in candidates:
        if c["observation_count"] >= 2 or c["corrections"]:
            promotions.append({
                "id": c["id"],
                "from": "candidate",
                "to": "active",
                "reason": "corrections" if c["corrections"] else f"observed {c['observation_count']}x",
            })

    # active -> core: confidence >= 0.8
    actives = db.execute(
        "SELECT * FROM instincts WHERE lifecycle = 'active'"
        + (" AND specialist = ?" if specialist else ""),
        (specialist,) if specialist else (),
    ).fetchall()

    for a in actives:
        if a["confidence"] >= 0.8:
            promotions.append({
                "id": a["id"],
                "from": "active",
                "to": "core",
                "reason": f"confidence {a['confidence']}",
            })

    # Demote: confidence < 0.2
    for_demotion = db.execute(
        "SELECT * FROM instincts WHERE lifecycle IN ('candidate','active') AND confidence < 0.2"
        + (" AND specialist = ?" if specialist else ""),
        (specialist,) if specialist else (),
    ).fetchall()

    for d in for_demotion:
        promotions.append({
            "id": d["id"],
            "from": d["lifecycle"],
            "to": "archived",
            "reason": f"low confidence {d['confidence']}",
        })

    db.close()
    print(json.dumps(promotions, indent=2))
    return promotions


def list_instincts(specialist=None, lifecycle=None):
    """List instincts with optional filters."""
    db = _get_db()
    _ensure_instinct_table(db)

    query = "SELECT * FROM instincts WHERE 1=1"
    params = []
    if specialist:
        query += " AND specialist = ?"
        params.append(specialist)
    if lifecycle:
        query += " AND lifecycle = ?"
        params.append(lifecycle)
    query += " ORDER BY updated_at DESC"

    rows = db.execute(query, params).fetchall()
    db.close()
    result = [dict(r) for r in rows]
    print(json.dumps(result, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description="Extract instincts from specialist tasks")
    sub = parser.add_subparsers(dest="command")

    ex = sub.add_parser("extract", help="Extract instincts from completed task")
    ex.add_argument("task_id", help="Task ID")
    ex.add_argument("specialist", help="Specialist agent ID")
    ex.add_argument("--corrections", help="Luka's corrections/feedback")
    ex.add_argument("--dry-run", action="store_true", help="Preview without saving")

    pc = sub.add_parser("promote-check", help="Check promotion candidates")
    pc.add_argument("--specialist", help="Filter by specialist")

    ls = sub.add_parser("list", help="List instincts")
    ls.add_argument("--specialist", help="Filter by specialist")
    ls.add_argument("--lifecycle", choices=["candidate", "active", "core", "archived"])

    args = parser.parse_args()

    if args.command == "extract":
        extract_instincts(args.task_id, args.specialist,
                         corrections=args.corrections, dry_run=args.dry_run)
    elif args.command == "promote-check":
        promote_check(specialist=args.specialist)
    elif args.command == "list":
        list_instincts(specialist=args.specialist, lifecycle=args.lifecycle)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
