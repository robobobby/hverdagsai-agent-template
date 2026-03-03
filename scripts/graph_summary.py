#!/usr/bin/env python3
"""
Generate markdown summary of knowledge graph for memory_search indexing.
Output: memory/graph-summary.md
"""

import os
from datetime import datetime
from pathlib import Path

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
OUTPUT_PATH = os.path.join(WORKSPACE, "memory", "graph-summary.md")

TYPE_SECTIONS = [
    ("person", "People"),
    ("project", "Projects"),
    ("tool", "Tools"),
    ("company", "Companies"),
    ("concept", "Concepts"),
    ("place", "Places"),
    ("event", "Events"),
]


def _group_outgoing_relations(db, entity_id):
    rows = db.conn.execute(
        "SELECT er.relation, e.name, e.type "
        "FROM entity_relations er "
        "JOIN entities e ON e.id = er.to_entity_id "
        "WHERE er.from_entity_id = ? "
        "ORDER BY er.relation, e.name_lower",
        (entity_id,)
    ).fetchall()
    grouped = {}
    for row in rows:
        grouped.setdefault(row["relation"], []).append(f"{row['name']} ({row['type']})")
    return grouped


def _entity_block(db, entity):
    lines = [f"### {entity['name']} ({entity['type']})"]
    relations = _group_outgoing_relations(db, entity["id"])
    for relation, targets in relations.items():
        lines.append(f"- {relation}: {', '.join(targets)}")

    slots = db.get_entity_slots(entity["id"])
    if slots:
        slot_text = ", ".join(f"{k}={v}" for k, v in sorted(slots.items()))
        lines.append(f"- Slots: {slot_text}")

    observations = db.get_entity_observations(entity["id"], limit=10)
    if observations:
        obs_text = " | ".join(o["observation"] for o in observations)
        lines.append(f"- Observations: {obs_text}")

    aliases = db.conn.execute(
        "SELECT alias_lower FROM entity_aliases WHERE entity_id = ? ORDER BY alias_lower",
        (entity["id"],)
    ).fetchall()
    if aliases:
        alias_text = ", ".join(a["alias_lower"] for a in aliases)
        lines.append(f"- Aliases: {alias_text}")

    lines.append("")
    return lines


def generate_graph_summary():
    db = MemoryDB()
    try:
        lines = [
            "# Knowledge Graph Summary",
            f"Generated: {datetime.now().strftime('%Y-%m-%d')}",
            "",
        ]

        for entity_type, heading in TYPE_SECTIONS:
            entities = db.list_entities(entity_type=entity_type, limit=10000)
            lines.append(f"## {heading}")
            if not entities:
                lines.append("_None_")
                lines.append("")
                continue
            for entity in entities:
                lines.extend(_entity_block(db, entity))

        os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(lines).rstrip() + "\n")

        print(f"Generated: {OUTPUT_PATH}")
    finally:
        db.close()


if __name__ == "__main__":
    generate_graph_summary()
