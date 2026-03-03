#!/usr/bin/env python3
"""
Agent Memory Query CLI

Query structured memory entries from the SQLite database.

Usage:
    python3 memory_query.py decisions           # Active decisions
    python3 memory_query.py commitments         # Active commitments
    python3 memory_query.py blockers            # Active blockers
    python3 memory_query.py preferences         # All preferences
    python3 memory_query.py lessons             # All lessons
    python3 memory_query.py patterns            # All patterns
    python3 memory_query.py search "query"      # Full-text search
    python3 memory_query.py recent              # Last 7 days
    python3 memory_query.py recent --days 14    # Last 14 days
    python3 memory_query.py stale               # Stale commitments (>7d) + blockers (>14d)
    python3 memory_query.py new-since "2026-02-28 10:00:00"  # New entries since timestamp
    python3 memory_query.py --project myproject     # Filter by project
    python3 memory_query.py --person alice       # Filter by person
    python3 memory_query.py stats               # Memory statistics
    python3 memory_query.py add decision "Title" -p project --body "Details"
    python3 memory_query.py resolve <id>        # Mark as resolved
    python3 memory_query.py reactivate <id>     # Reactivate a resolved entry
    python3 memory_query.py health              # Integrity + failure queue + orphans

    # Knowledge Graph commands:
    python3 memory_query.py entity "Alice"               # Show entity profile
    python3 memory_query.py entities                    # List all entities
    python3 memory_query.py entities --type person      # List entities by type
    python3 memory_query.py entity-add "Alice" person    # Create entity
    python3 memory_query.py relate "Alice" person works_at "Acme" company
    python3 memory_query.py observe "Alice" person "Prefers concise communication"
    python3 memory_query.py slot "Alice" person role "Engineer"
    python3 memory_query.py entity-search "sofa"        # Search entities
    python3 memory_query.py alias "Alice" person "A. Smith"
    python3 memory_query.py graph-stats                 # Knowledge graph statistics
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from memory_db import MemoryDB, VALID_TYPES, VALID_ENTITY_TYPES, VALID_ENTITY_RELATIONS


def format_entry(entry, verbose=False):
    """Format a memory entry for display."""
    type_icons = {
        "decision": "🔷",
        "commitment": "🤝",
        "blocker": "🚧",
        "preference": "💡",
        "pattern": "🔄",
        "lesson": "📖",
        "observation": "👁️",
    }
    status_icons = {
        "active": "",
        "resolved": " ✅",
        "superseded": " ⏭️",
        "archived": " 📦",
    }

    icon = type_icons.get(entry["type"], "📝")
    status = status_icons.get(entry["status"], "")
    date = entry["source_date"]
    project = f" [{entry['project']}]" if entry.get("project") else ""
    refs = ""
    if entry.get("external_refs"):
        try:
            import json
            r = json.loads(entry["external_refs"])
            refs = " 🔗" + ",".join(r.keys())
        except Exception:
            pass

    line = f"  {icon} {entry['title']}{project}{status}{refs} ({date})"

    if verbose and entry.get("body"):
        body_preview = entry["body"][:200]
        if len(entry["body"]) > 200:
            body_preview += "..."
        line += f"\n     {body_preview}"

    if verbose:
        line += f"\n     ID: {entry['id'][:20]}..."

    return line


def main():
    parser = argparse.ArgumentParser(description="Agent Memory Query CLI")
    parser.add_argument("command", nargs="?", default="recent",
                        help="Command: decisions/commitments/blockers/preferences/lessons/patterns/search/recent/stale/new-since/stats/add/resolve/reactivate/health")
    parser.add_argument("args", nargs="*", help="Additional arguments")
    parser.add_argument("--project", "-p", help="Filter by project")
    parser.add_argument("--person", help="Filter by person")
    parser.add_argument("--status", "-s", default=None, help="Filter by status")
    parser.add_argument("--days", "-d", type=int, default=None, help="Filter by days")
    parser.add_argument("--limit", "-l", type=int, default=25, help="Max results")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show body and IDs")
    parser.add_argument("--body", "-b", help="Entry body (for add command)")
    parser.add_argument("--tags", "-t", help="Comma-separated tags (for add command)")
    parser.add_argument("--source-file", help="Source file (for add command)")
    parser.add_argument("--ref-type", help="External ref type (for add command)")
    parser.add_argument("--ref-id", help="External ref ID (for add command)")

    args = parser.parse_args()
    db = MemoryDB()

    try:
        # Type-specific queries
        type_commands = {
            "decisions": "decision",
            "commitments": "commitment",
            "blockers": "blocker",
            "preferences": "preference",
            "lessons": "lesson",
            "patterns": "pattern",
            "observations": "observation",
        }

        if args.command in type_commands:
            entry_type = type_commands[args.command]
            status = args.status or "active"
            entries = db.query(
                type=entry_type, status=status,
                project=args.project, person=args.person,
                days=args.days, limit=args.limit
            )
            label = args.command.title()
            print(f"=== {label} ({status}) ===\n")
            if entries:
                for e in entries:
                    print(format_entry(e, verbose=args.verbose))
            else:
                print(f"  No {args.command} found.")
            print(f"\n  Total: {len(entries)}")

        elif args.command == "search":
            if not args.args:
                print("Usage: memory_query.py search \"query text\"")
                return
            query = " ".join(args.args)
            entries = db.search(query, limit=args.limit)
            print(f"=== Search: \"{query}\" ===\n")
            if entries:
                for e in entries:
                    print(format_entry(e, verbose=True))
            else:
                print("  No results found.")
            print(f"\n  Total: {len(entries)}")

        elif args.command == "recent":
            days = args.days or 7
            entries = db.query(
                project=args.project, person=args.person,
                days=days, limit=args.limit
            )
            print(f"=== Recent ({days} days) ===\n")
            if entries:
                for e in entries:
                    print(format_entry(e, verbose=args.verbose))
            else:
                print("  No entries in this period.")
            print(f"\n  Total: {len(entries)}")

        elif args.command == "stale":
            entries = db.stale()
            print("=== Stale Entries (commitments >7d, blockers >14d) ===\n")
            if entries:
                for e in entries:
                    print(format_entry(e, verbose=True))
            else:
                print("  No stale entries. All clear!")
            print(f"\n  Total: {len(entries)}")

        elif args.command == "new-since":
            if not args.args:
                print("Usage: memory_query.py new-since \"2026-02-28 10:00:00\"")
                return
            since = " ".join(args.args)
            entries = db.new_since(since)
            print(f"=== New Since {since} ===\n")
            if entries:
                for e in entries:
                    print(format_entry(e, verbose=args.verbose))
            else:
                print("  No new entries.")
            print(f"\n  Total: {len(entries)}")

        elif args.command == "add":
            if len(args.args) < 2:
                print("Usage: memory_query.py add <type> \"Title\" [--body ...] [--project ...]")
                print(f"  Types: {', '.join(VALID_TYPES)}")
                return
            entry_type = args.args[0]
            title = " ".join(args.args[1:])
            tags = [t.strip() for t in args.tags.split(",")] if args.tags else None
            external_refs = None
            if args.ref_type and args.ref_id:
                external_refs = {args.ref_type: args.ref_id}

            result = db.add(
                type=entry_type, title=title,
                body=args.body, project=args.project,
                person=args.person, tags=tags,
                source_file=args.source_file,
                external_refs=external_refs
            )
            print(f"✅ Added {entry_type}: {title}")
            print(f"   ID: {result['id']}")
            print(f"   Event ID: {result['event_id']}")

        elif args.command == "resolve":
            if not args.args:
                print("Usage: memory_query.py resolve <entry_id>")
                return
            entry_id = args.args[0]
            # Support partial ID matching
            if len(entry_id) < 20:
                entries = db.conn.execute(
                    "SELECT id, title FROM memory_entries WHERE id LIKE ?",
                    (entry_id + "%",)
                ).fetchall()
                if len(entries) == 0:
                    print(f"❌ No entry found matching '{entry_id}'")
                    return
                elif len(entries) > 1:
                    print(f"⚠️ Multiple entries match '{entry_id}':")
                    for e in entries:
                        print(f"  {e['id']} — {e['title']}")
                    return
                entry_id = entries[0]["id"]

            success = db.resolve(entry_id)
            if success:
                entry = db.get(entry_id)
                print(f"✅ Resolved: {entry['title']}")
            else:
                print(f"❌ No entry found with ID '{entry_id}'")

        elif args.command == "reactivate":
            if not args.args:
                print("Usage: memory_query.py reactivate <entry_id>")
                return
            entry_id = args.args[0]
            # Support partial ID matching
            if len(entry_id) < 20:
                entries = db.conn.execute(
                    "SELECT id, title, status FROM memory_entries WHERE id LIKE ?",
                    (entry_id + "%",)
                ).fetchall()
                if len(entries) == 0:
                    print(f"❌ No entry found matching '{entry_id}'")
                    return
                elif len(entries) > 1:
                    print(f"⚠️ Multiple entries match '{entry_id}':")
                    for e in entries:
                        print(f"  {e['id']} — {e['title']} ({e['status']})")
                    return
                entry_id = entries[0]["id"]

            success = db.reactivate(entry_id)
            if success:
                entry = db.get(entry_id)
                print(f"✅ Reactivated: {entry['title']}")
            else:
                print(f"❌ Entry '{entry_id}' not found or already active")

        elif args.command == "stats":
            stats = db.stats()
            print("=== Memory Statistics ===\n")
            print(f"  Total entries: {stats['total_entries']}")
            print(f"\n  Active by type:")
            for t, c in stats["active_by_type"].items():
                icon = {"decision": "🔷", "commitment": "🤝", "blocker": "🚧",
                        "preference": "💡", "pattern": "🔄", "lesson": "📖",
                        "observation": "👁️"}.get(t, "📝")
                print(f"    {icon} {t}: {c}")
            print(f"\n  By status:")
            for s, c in stats["by_status"].items():
                print(f"    {s}: {c}")
            print(f"\n  Unresolved write failures: {stats['unresolved_failures']}")
            print(f"  Stale commitments (>7d): {stats['stale_commitments']}")
            print(f"  Stale blockers (>14d): {stats['stale_blockers']}")

        elif args.command == "health":
            ok, result = db.integrity_check()
            print(f"Integrity: {'✅ OK' if ok else '❌ ' + result}")
            stats = db.stats()
            print(f"Entries: {stats['total_entries']}")
            print(f"Unresolved failures: {stats['unresolved_failures']}")
            if stats["unresolved_failures"] > 0:
                retried, total = db.retry_failures()
                print(f"Retried: {retried}/{total}")
            print(f"Stale commitments (>7d): {stats['stale_commitments']}")
            print(f"Stale blockers (>14d): {stats['stale_blockers']}")
            orphans = db.orphan_entries()
            print(f"Orphan entries (no source_file): {len(orphans)}")

        # ── Knowledge Graph Commands ──────────────────────────────────

        elif args.command == "entity":
            if not args.args:
                print("Usage: memory_query.py entity \"Name\" [type]")
                return
            name = args.args[0]
            etype = args.args[1] if len(args.args) > 1 else None
            eid = db.find_entity(name, etype)
            if not eid:
                print(f"❌ Entity '{name}' not found")
                return
            profile = db.get_entity(eid)
            print(f"=== {profile['name']} ({profile['type']}) ===\n")
            if profile['aliases']:
                print(f"  Aliases: {', '.join(profile['aliases'])}")
            if profile['slots']:
                print(f"  Slots:")
                for k, v in profile['slots'].items():
                    print(f"    {k}: {v}")
            if profile['observations']:
                print(f"  Observations:")
                for obs in profile['observations']:
                    src = f" [{obs['source']}]" if obs.get('source') else ""
                    print(f"    - {obs['observation']}{src}")
            if profile['relations']:
                print(f"  Relations:")
                for r in profile['relations']:
                    if r['direction'] == 'outgoing':
                        print(f"    -> {r['relation']} -> {r['to_name']} ({r['to_type']})")
                    else:
                        print(f"    <- {r['relation']} <- {r['from_name']} ({r['from_type']})")
            if profile['linked_entries']:
                print(f"  Linked entries:")
                for le in profile['linked_entries']:
                    print(f"    [{le['role']}] {le['type']}: {le['title']} ({le['status']})")

        elif args.command == "entities":
            etype = args.args[0] if args.args else None
            entities = db.list_entities(entity_type=etype, limit=args.limit)
            label = f"Entities ({etype})" if etype else "All Entities"
            print(f"=== {label} ===\n")
            for e in entities:
                print(f"  [{e['type']}] {e['name']} (id:{e['id']})")
            print(f"\n  Total: {len(entities)}")

        elif args.command == "entity-add":
            if len(args.args) < 2:
                print(f"Usage: memory_query.py entity-add \"Name\" <type>")
                print(f"  Types: {', '.join(VALID_ENTITY_TYPES)}")
                return
            name, etype = args.args[0], args.args[1]
            eid = db.resolve_entity(name, etype)
            print(f"✅ Entity: {name} ({etype}) -> id:{eid}")

        elif args.command == "relate":
            if len(args.args) < 5:
                print("Usage: memory_query.py relate \"From\" from_type relation \"To\" to_type")
                print(f"  Relations: {', '.join(VALID_ENTITY_RELATIONS)}")
                return
            from_name, from_type, relation, to_name, to_type = args.args[:5]
            db.relate_entities(from_name, from_type, relation, to_name, to_type)
            print(f"✅ {from_name} ({from_type}) -> {relation} -> {to_name} ({to_type})")

        elif args.command == "observe":
            if len(args.args) < 3:
                print("Usage: memory_query.py observe \"Name\" type \"Observation text\"")
                return
            name, etype = args.args[0], args.args[1]
            observation = " ".join(args.args[2:])
            eid = db.resolve_entity(name, etype)
            db.add_entity_observation(eid, observation, source=args.source_file)
            print(f"✅ Observation added to {name}: {observation[:60]}...")

        elif args.command == "slot":
            if len(args.args) < 4:
                print("Usage: memory_query.py slot \"Name\" type key value")
                return
            name, etype, key = args.args[0], args.args[1], args.args[2]
            value = " ".join(args.args[3:])
            eid = db.resolve_entity(name, etype)
            db.set_entity_slot(eid, key, value)
            print(f"✅ {name}.{key} = {value}")

        elif args.command == "alias":
            if len(args.args) < 3:
                print("Usage: memory_query.py alias \"Name\" type \"Alias\"")
                return
            name, etype, alias = args.args[0], args.args[1], args.args[2]
            eid = db.find_entity(name, etype)
            if not eid:
                print(f"❌ Entity '{name}' ({etype}) not found")
                return
            db.add_entity_alias(eid, alias)
            print(f"✅ Alias '{alias}' added to {name}")

        elif args.command == "entity-search":
            if not args.args:
                print("Usage: memory_query.py entity-search \"query\"")
                return
            query = " ".join(args.args)
            results = db.search_entities(query, limit=args.limit)
            print(f"=== Entity Search: \"{query}\" ===\n")
            for e in results:
                print(f"  [{e['type']}] {e['name']} (id:{e['id']})")
            print(f"\n  Total: {len(results)}")

        elif args.command == "graph-stats":
            estats = db.entity_stats()
            print("=== Knowledge Graph Statistics ===\n")
            print(f"  Total entities: {estats['total_entities']}")
            if estats['by_type']:
                print(f"  By type:")
                for t, c in estats['by_type'].items():
                    print(f"    {t}: {c}")
            print(f"  Total relations: {estats['total_relations']}")
            print(f"  Total observations: {estats['total_observations']}")
            print(f"  Entity-entry links: {estats['entity_entry_links']}")

        else:
            print(f"Unknown command: {args.command}")
            print("Commands: decisions, commitments, blockers, preferences, lessons,")
            print("  patterns, search, recent, stale, new-since, stats, add,")
            print("  resolve, reactivate, health")
            print("Graph: entity, entities, entity-add, relate, observe, slot,")
            print("  alias, entity-search, graph-stats")

    finally:
        db.close()


if __name__ == "__main__":
    main()
