#!/usr/bin/env python3
"""
Structured Memory Layer

Provides typed, queryable memory alongside existing markdown files.
Uses SQLite for reliability, speed, and zero dependencies.

Design doc: memory/projects/memory-hybrid-design.md
Codex-reviewed: 2026-02-28 (7+8 issues found and fixed)

Usage:
    from memory_db import MemoryDB

    db = MemoryDB()
    db.add("decision", "Use SQLite for memory", body="...", project="memory")
    db.query(type="decision", status="active")
    db.resolve("entry_id", "Completed: SQLite deployed")
    db.search("token refresh")
"""

import sqlite3
import os
import json
import time
import uuid
import re
from datetime import datetime, timedelta
from contextlib import contextmanager
from pathlib import Path

DEFAULT_WRITER = os.getenv("OPENCLAW_MEMORY_WRITER", "agent")


def detect_workspace_root() -> Path | None:
    """Detect workspace root when running from <workspace>/scripts."""
    candidate = Path(__file__).resolve().parent.parent
    markers = ("AGENTS.md", "SOUL.md", "USER.md", "MEMORY.md")
    if all((candidate / m).exists() for m in markers):
        return candidate
    return None


def default_db_path() -> str:
    """Resolve DB path with env override, then workspace-local, then global fallback."""
    explicit = os.getenv("OPENCLAW_MEMORY_DB")
    if explicit:
        return os.path.expanduser(explicit)

    workspace_env = os.getenv("OPENCLAW_WORKSPACE")
    if workspace_env:
        return os.path.join(os.path.expanduser(workspace_env), "memory", "memory.db")

    workspace_root = detect_workspace_root()
    if workspace_root:
        return str(workspace_root / "memory" / "memory.db")

    return os.path.expanduser("~/.openclaw/memory/agent_memory.db")

# Valid types and statuses (enforced at app level too)
VALID_TYPES = ("decision", "commitment", "blocker", "preference", "pattern", "lesson", "observation")
VALID_STATUSES = ("active", "resolved", "superseded", "archived")
VALID_RELATIONS = ("relates_to", "supersedes", "blocks", "follows_from")

# Knowledge graph types
VALID_ENTITY_TYPES = ("person", "project", "tool", "company", "concept", "place", "event")
VALID_ENTITY_RELATIONS = (
    "works_at", "works_on", "owns", "manages", "depends_on", "deployed_on",
    "built_with", "related_to", "blocked_by", "parent_of", "child_of",
    "invested_in", "uses", "created_by", "partner_of", "lives_at"
)
VALID_ENTITY_ENTRY_ROLES = ("subject", "related", "author", "about")


def generate_ulid():
    """Generate a ULID-like ID (timestamp prefix + random suffix for sortability).
    Monotonic within same millisecond via incrementing random suffix."""
    ts = int(time.time() * 1000)
    random_part = uuid.uuid4().hex[:12]
    return f"{ts:013x}-{random_part}"


def generate_event_id():
    """Generate a stable event ID for idempotency (written to both markdown and DB)."""
    return f"evt-{generate_ulid()}"


SCHEMA_SQL = """
-- Memory entries: the heart of the system
CREATE TABLE IF NOT EXISTS memory_entries (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL CHECK(type IN ('decision','commitment','blocker','preference','pattern','lesson','observation')),
    title TEXT NOT NULL,
    body TEXT,
    project TEXT,
    person TEXT,
    status TEXT DEFAULT 'active' CHECK(status IN ('active','resolved','superseded','archived')),
    source_date TEXT NOT NULL,
    source_file TEXT,
    source_line INTEGER,
    writer TEXT DEFAULT 'agent',
    confidence REAL DEFAULT 1.0,
    backfilled INTEGER DEFAULT 0,
    external_refs TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    resolved_at TEXT
);

-- Composite indexes matching actual query patterns
CREATE INDEX IF NOT EXISTS idx_entries_type_status_date ON memory_entries(type, status, source_date DESC);
CREATE INDEX IF NOT EXISTS idx_entries_project_status_date ON memory_entries(project, status, source_date DESC);
CREATE INDEX IF NOT EXISTS idx_entries_person_status_date ON memory_entries(person, status, source_date DESC);

-- Normalized tags
CREATE TABLE IF NOT EXISTS entry_tags (
    entry_id TEXT NOT NULL REFERENCES memory_entries(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY (entry_id, tag)
);

-- Context links
CREATE TABLE IF NOT EXISTS memory_links (
    id TEXT PRIMARY KEY,
    from_id TEXT NOT NULL REFERENCES memory_entries(id) ON DELETE CASCADE,
    to_id TEXT NOT NULL REFERENCES memory_entries(id) ON DELETE CASCADE,
    relation TEXT NOT NULL CHECK(relation IN ('relates_to','supersedes','blocks','follows_from')),
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(from_id, to_id, relation),
    CHECK(from_id <> to_id)
);
CREATE INDEX IF NOT EXISTS idx_links_from ON memory_links(from_id);
CREATE INDEX IF NOT EXISTS idx_links_to ON memory_links(to_id);

-- Write failure queue (for reconciliation)
CREATE TABLE IF NOT EXISTS write_failures (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    entry_json TEXT NOT NULL,
    error TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    retried_at TEXT,
    resolved INTEGER DEFAULT 0
);

-- Schema versioning
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT DEFAULT (datetime('now')),
    description TEXT
);

-- Knowledge graph: entities (people, projects, tools, etc.)
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL CHECK(length(trim(name)) > 0),
    name_lower TEXT NOT NULL CHECK(length(trim(name_lower)) > 0),
    type TEXT NOT NULL CHECK(type IN ('person','project','tool','company','concept','place','event')),
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_name_type ON entities(name_lower, type);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);

-- Entity aliases for deduplication (e.g., nickname -> canonical name)
CREATE TABLE IF NOT EXISTS entity_aliases (
    alias_lower TEXT NOT NULL CHECK(length(trim(alias_lower)) > 0),
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    PRIMARY KEY (alias_lower)
);
CREATE INDEX IF NOT EXISTS idx_entity_aliases_entity ON entity_aliases(entity_id);

-- Entity slots: scoped, bitemporal key-value pairs on entities
CREATE TABLE IF NOT EXISTS entity_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    key TEXT NOT NULL CHECK(length(trim(key)) > 0),
    value TEXT,
    scope TEXT NOT NULL DEFAULT 'global' CHECK(length(trim(scope)) > 0),
    valid_from TEXT NOT NULL DEFAULT (datetime('now')),
    valid_to TEXT,
    confidence REAL DEFAULT 1.0 CHECK(confidence >= 0.0 AND confidence <= 1.0)
);
CREATE INDEX IF NOT EXISTS idx_entity_slots_entity ON entity_slots(entity_id, key);
CREATE INDEX IF NOT EXISTS idx_entity_slots_lookup ON entity_slots(entity_id, key, scope, valid_from DESC, valid_to);

-- Entity observations: free-text notes attached to entities
CREATE TABLE IF NOT EXISTS entity_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    observation TEXT NOT NULL CHECK(length(trim(observation)) > 0),
    source TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_entity_obs_entity ON entity_observations(entity_id, created_at DESC);

-- Entity-to-entity relations (directed graph)
CREATE TABLE IF NOT EXISTS entity_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    to_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    relation TEXT NOT NULL CHECK(relation IN (
        'works_at','works_on','owns','manages','depends_on','deployed_on',
        'built_with','related_to','blocked_by','parent_of','child_of',
        'invested_in','uses','created_by','partner_of','lives_at'
    )),
    metadata TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(from_entity_id, to_entity_id, relation),
    CHECK(from_entity_id <> to_entity_id)
);
CREATE INDEX IF NOT EXISTS idx_entity_rel_from ON entity_relations(from_entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_rel_to ON entity_relations(to_entity_id);

-- Entity-to-entry links (connect graph entities to typed memory entries)
CREATE TABLE IF NOT EXISTS entity_entry_links (
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    entry_id TEXT NOT NULL REFERENCES memory_entries(id) ON DELETE CASCADE,
    role TEXT DEFAULT 'related' CHECK(role IN ('subject','related','author','about')),
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (entity_id, entry_id)
);
CREATE INDEX IF NOT EXISTS idx_eel_entity ON entity_entry_links(entity_id);
CREATE INDEX IF NOT EXISTS idx_eel_entry ON entity_entry_links(entry_id);

-- FTS5 full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    title, body, tags,
    content=memory_entries,
    content_rowid=rowid,
    tokenize='porter unicode61'
);
"""

# FTS triggers on memory_entries handle title/body sync.
# Tags are rebuilt via _rebuild_fts_for_entry after tag changes.
TRIGGER_SQL = """
CREATE TRIGGER IF NOT EXISTS memory_fts_delete BEFORE DELETE ON memory_entries BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, title, body, tags)
    VALUES ('delete', old.rowid, old.title, old.body,
        COALESCE((SELECT group_concat(tag, ' ') FROM entry_tags WHERE entry_id = old.id), ''));
END;

CREATE TRIGGER IF NOT EXISTS memory_fts_update AFTER UPDATE ON memory_entries BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, title, body, tags)
    VALUES ('delete', old.rowid, old.title, old.body,
        COALESCE((SELECT group_concat(tag, ' ') FROM entry_tags WHERE entry_id = old.id), ''));
    INSERT INTO memory_fts(rowid, title, body, tags)
    VALUES (new.rowid, new.title, new.body,
        COALESCE((SELECT group_concat(tag, ' ') FROM entry_tags WHERE entry_id = new.id), ''));
END;
"""


class MemoryDB:
    """Structured memory database."""

    def __init__(self, db_path=None):
        self.db_path = db_path or default_db_path()
        # Handle :memory: and empty dirname gracefully
        dirname = os.path.dirname(self.db_path)
        if dirname and dirname != ':memory:':
            os.makedirs(dirname, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=5000")  # 5s busy timeout for concurrent access
        self._init_schema()

    def _init_schema(self):
        """Initialize database schema if not exists."""
        self.conn.executescript(SCHEMA_SQL)
        self._normalize_slot_actives()
        self.conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_slots_active_unique "
            "ON entity_slots(entity_id, key, scope) WHERE valid_to IS NULL"
        )
        try:
            self.conn.executescript(TRIGGER_SQL)
        except sqlite3.OperationalError:
            pass  # Triggers already exist
        # Drop legacy FTS insert trigger (we do manual FTS insert in add())
        try:
            self.conn.execute("DROP TRIGGER IF EXISTS memory_fts_insert")
        except Exception:
            pass
        # Migrate: add external_refs column if missing
        try:
            self.conn.execute("SELECT external_refs FROM memory_entries LIMIT 0")
        except sqlite3.OperationalError:
            self.conn.execute("ALTER TABLE memory_entries ADD COLUMN external_refs TEXT")
        # Migrate: make event_id NOT NULL (for new DBs it's already NOT NULL)
        # For existing DBs, fill any NULLs
        self.conn.execute("""
            UPDATE memory_entries SET event_id = ('evt-legacy-' || id)
            WHERE event_id IS NULL
        """)
        # Insert schema version if empty
        cur = self.conn.execute("SELECT MAX(version) FROM schema_version")
        max_ver = cur.fetchone()[0]
        if max_ver is None:
            self.conn.execute(
                "INSERT INTO schema_version (version, description) VALUES (1, 'Initial schema with FTS5, constraints, failure queue')"
            )
        if max_ver is None or max_ver < 2:
            self.conn.execute(
                "INSERT OR IGNORE INTO schema_version (version, description) VALUES (2, 'Bug fixes: transaction safety, FTS tag sync, failure queue, external_refs, reactivate')"
            )
        if max_ver is None or max_ver < 3:
            self.conn.execute(
                "INSERT OR IGNORE INTO schema_version (version, description) VALUES (3, 'Knowledge graph: entities, relations, slots, observations, entity-entry links')"
            )
        self.conn.commit()

    def _normalize_slot_actives(self):
        """Ensure at most one active row exists per (entity, key, scope)."""
        # Close duplicates while preserving the most recent active record.
        self.conn.execute("""
            UPDATE entity_slots
            SET valid_to = datetime('now')
            WHERE id IN (
                SELECT id
                FROM (
                    SELECT id,
                        ROW_NUMBER() OVER (
                            PARTITION BY entity_id, key, scope
                            ORDER BY valid_from DESC, id DESC
                        ) AS rn
                    FROM entity_slots
                    WHERE valid_to IS NULL
                )
                WHERE rn > 1
            )
        """)

    @contextmanager
    def _transaction(self, immediate=False):
        """Context manager for explicit transactions."""
        self.conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        try:
            yield
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def _normalize_non_empty_text(self, value, field_name):
        """Normalize user text input and reject empty/non-string values."""
        if not isinstance(value, str):
            raise ValueError(f"{field_name} must be a string")
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} must be a non-empty string")
        return normalized

    def _normalize_entity_type(self, entity_type):
        entity_type = self._normalize_non_empty_text(entity_type, "entity_type").lower()
        if entity_type not in VALID_ENTITY_TYPES:
            raise ValueError(f"Invalid entity type '{entity_type}'. Must be one of: {VALID_ENTITY_TYPES}")
        return entity_type

    def _normalize_relation(self, relation):
        relation = self._normalize_non_empty_text(relation, "relation").lower()
        if relation not in VALID_ENTITY_RELATIONS:
            raise ValueError(f"Invalid relation '{relation}'. Must be one of: {VALID_ENTITY_RELATIONS}")
        return relation

    def _normalize_role(self, role):
        role = self._normalize_non_empty_text(role, "role").lower()
        if role not in VALID_ENTITY_ENTRY_ROLES:
            raise ValueError(f"Invalid role '{role}'. Must be one of: {VALID_ENTITY_ENTRY_ROLES}")
        return role

    def _validate_entity_id(self, entity_id):
        if not isinstance(entity_id, int) or entity_id <= 0:
            raise ValueError("entity_id must be a positive integer")

    def _validate_entry_id(self, entry_id):
        if not isinstance(entry_id, str) or not entry_id.strip():
            raise ValueError("entry_id must be a non-empty string")
        return entry_id.strip()

    def _validate_confidence(self, confidence):
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            raise ValueError("confidence must be a number between 0.0 and 1.0") from None
        if confidence < 0.0 or confidence > 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return confidence

    def _entity_match_index(self):
        """Build a reusable index for entity matching by name/alias."""
        term_to_entities = {}
        rows = self.conn.execute(
            "SELECT e.id AS entity_id, e.name_lower AS term FROM entities e "
            "UNION ALL "
            "SELECT ea.entity_id AS entity_id, ea.alias_lower AS term FROM entity_aliases ea"
        ).fetchall()
        for row in rows:
            term = row["term"]
            if not term:
                continue
            if term not in term_to_entities:
                term_to_entities[term] = set()
            term_to_entities[term].add(row["entity_id"])

        scan_terms = []
        for term, entity_ids in term_to_entities.items():
            # Longest first prevents noisy short matches from dominating scans.
            pattern = re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.IGNORECASE)
            scan_terms.append((term, pattern, entity_ids))
        scan_terms.sort(key=lambda item: len(item[0]), reverse=True)

        return {
            "exact": term_to_entities,
            "scan": scan_terms,
        }

    def _scan_entity_ids_in_text(self, text, match_index):
        """Find entity ids mentioned in text via names/aliases."""
        if not text:
            return set()
        found = set()
        for _, pattern, entity_ids in match_index["scan"]:
            if pattern.search(text):
                found.update(entity_ids)
        return found

    def _insert_entity_entry_link_in_txn(self, entity_id, entry_id, role):
        """Insert a link inside an active transaction. Returns 1 if created, else 0."""
        role = self._normalize_role(role)
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO entity_entry_links (entity_id, entry_id, role) VALUES (?, ?, ?)",
            (entity_id, entry_id, role)
        )
        return 1 if cur.rowcount == 1 else 0

    def _auto_link_entry_in_txn(self, entry_id, match_index):
        """Auto-link one entry using a prebuilt index. Requires open transaction."""
        row = self.conn.execute(
            "SELECT id, project, person, title, body FROM memory_entries WHERE id = ?",
            (entry_id,)
        ).fetchone()
        if not row:
            return 0

        links_created = 0
        exact = match_index["exact"]

        project = (row["project"] or "").strip().casefold()
        if project and project in exact:
            for entity_id in exact[project]:
                links_created += self._insert_entity_entry_link_in_txn(entity_id, entry_id, "subject")

        person = (row["person"] or "").strip().casefold()
        if person and person in exact:
            for entity_id in exact[person]:
                links_created += self._insert_entity_entry_link_in_txn(entity_id, entry_id, "about")

        text = f"{row['title'] or ''}\n{row['body'] or ''}"
        related_ids = self._scan_entity_ids_in_text(text, match_index)
        for entity_id in related_ids:
            links_created += self._insert_entity_entry_link_in_txn(entity_id, entry_id, "related")

        return links_created

    def _resolve_entity_id_in_txn(self, name, entity_type):
        """Resolve entity id within an open transaction."""
        normalized_name = self._normalize_non_empty_text(name, "name")
        entity_type = self._normalize_entity_type(entity_type)
        name_lower = normalized_name.casefold()

        row = self.conn.execute(
            "SELECT id FROM entities WHERE name_lower = ? AND type = ?",
            (name_lower, entity_type)
        ).fetchone()
        if row:
            return row["id"]

        row = self.conn.execute(
            "SELECT e.id FROM entity_aliases ea JOIN entities e ON ea.entity_id = e.id "
            "WHERE ea.alias_lower = ? AND e.type = ?",
            (name_lower, entity_type)
        ).fetchone()
        if row:
            return row["id"]

        try:
            self.conn.execute(
                "INSERT INTO entities (name, name_lower, type) VALUES (?, ?, ?)",
                (normalized_name, name_lower, entity_type)
            )
        except sqlite3.IntegrityError:
            # Another writer may have inserted between read and write.
            pass

        row = self.conn.execute(
            "SELECT id FROM entities WHERE name_lower = ? AND type = ?",
            (name_lower, entity_type)
        ).fetchone()
        if row:
            return row["id"]

        raise RuntimeError("Failed to resolve entity due to concurrent write conflict")

    def _rebuild_fts_for_entry(self, entry_id):
        """Rebuild FTS index for a specific entry (handles tag sync)."""
        row = self.conn.execute(
            "SELECT rowid, title, body FROM memory_entries WHERE id = ?", (entry_id,)
        ).fetchone()
        if not row:
            return
        tags_str = self._get_tags_str(entry_id)
        # Delete old FTS entry
        try:
            self.conn.execute(
                "INSERT INTO memory_fts(memory_fts, rowid, title, body, tags) VALUES ('delete', ?, ?, ?, ?)",
                (row["rowid"], row["title"], row["body"], tags_str)
            )
        except Exception:
            pass  # May not exist yet
        # Insert new FTS entry
        self.conn.execute(
            "INSERT INTO memory_fts(rowid, title, body, tags) VALUES (?, ?, ?, ?)",
            (row["rowid"], row["title"], row["body"], tags_str)
        )

    def _get_tags_str(self, entry_id):
        """Get space-separated tags string for an entry."""
        rows = self.conn.execute(
            "SELECT tag FROM entry_tags WHERE entry_id = ?", (entry_id,)
        ).fetchall()
        return " ".join(r["tag"] for r in rows) if rows else ""

    def add(self, type, title, body=None, project=None, person=None,
            source_date=None, source_file=None, source_line=None,
            tags=None, writer=DEFAULT_WRITER, confidence=1.0, backfilled=False,
            event_id=None, external_refs=None):
        """Add a new memory entry. Returns the entry dict.
        
        Uses a proper transaction: either everything commits or nothing does.
        On failure, logs to write_failures queue with ALL kwargs for lossless retry.
        """
        if type not in VALID_TYPES:
            raise ValueError(f"Invalid type '{type}'. Must be one of: {VALID_TYPES}")

        entry_id = generate_ulid()
        if event_id is None:
            event_id = generate_event_id()
        if source_date is None:
            source_date = datetime.now().strftime("%Y-%m-%d")

        # Serialize ALL kwargs for failure queue (lossless)
        all_kwargs = {
            "type": type, "title": title, "body": body, "project": project,
            "person": person, "source_date": source_date, "source_file": source_file,
            "source_line": source_line, "tags": tags, "writer": writer,
            "confidence": confidence, "backfilled": backfilled,
            "external_refs": json.dumps(external_refs) if external_refs else None
        }

        try:
            # Begin explicit transaction
            self.conn.execute("BEGIN IMMEDIATE")

            # 1. Insert entry first (tags have FK on entry_id)
            ext_refs_json = json.dumps(external_refs) if external_refs else None
            self.conn.execute("""
                INSERT INTO memory_entries (id, event_id, type, title, body, project, person,
                    source_date, source_file, source_line, writer, confidence, backfilled, external_refs)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (entry_id, event_id, type, title, body, project, person,
                  source_date, source_file, source_line, writer, confidence,
                  1 if backfilled else 0, ext_refs_json))

            # 2. Insert tags (FK now valid)
            if tags:
                for tag in tags:
                    t = tag.strip().lower()
                    if t:
                        self.conn.execute(
                            "INSERT OR IGNORE INTO entry_tags (entry_id, tag) VALUES (?, ?)",
                            (entry_id, t)
                        )

            # 3. Manually insert FTS entry WITH tags (bypassing the trigger
            #    which would have fired on step 1 before tags existed)
            tags_str = " ".join(t.strip().lower() for t in tags if t.strip()) if tags else ""
            rowid = self.conn.execute(
                "SELECT rowid FROM memory_entries WHERE id = ?", (entry_id,)
            ).fetchone()[0]
            self.conn.execute(
                "INSERT INTO memory_fts(rowid, title, body, tags) VALUES (?, ?, ?, ?)",
                (rowid, title, body or "", tags_str)
            )

            self.conn.execute("COMMIT")

            return {
                "id": entry_id, "event_id": event_id, "type": type,
                "title": title, "status": "active", "source_date": source_date
            }

        except Exception as e:
            # Rollback the failed transaction
            try:
                self.conn.execute("ROLLBACK")
            except Exception:
                pass

            # Log to failure queue (lossless — all kwargs preserved)
            try:
                self.conn.execute("""
                    INSERT INTO write_failures (id, event_id, entry_json, error)
                    VALUES (?, ?, ?, ?)
                """, (generate_ulid(), event_id, json.dumps(all_kwargs), str(e)))
                self.conn.commit()
            except Exception:
                pass  # If even failure logging fails, we can't do much

            raise

    def resolve(self, entry_id, reason=None):
        """Mark an entry as resolved. Returns True if entry was found and updated."""
        cur = self.conn.execute("""
            UPDATE memory_entries
            SET status = 'resolved', resolved_at = datetime('now'), updated_at = datetime('now')
            WHERE id = ?
        """, (entry_id,))
        self.conn.commit()
        if cur.rowcount == 0:
            return False
        return True

    def reactivate(self, entry_id):
        """Reactivate a resolved/superseded/archived entry back to active."""
        cur = self.conn.execute("""
            UPDATE memory_entries
            SET status = 'active', resolved_at = NULL, updated_at = datetime('now')
            WHERE id = ? AND status != 'active'
        """, (entry_id,))
        self.conn.commit()
        if cur.rowcount == 0:
            return False
        return True

    def supersede(self, old_id, new_id):
        """Mark an entry as superseded by another."""
        self.conn.execute("""
            UPDATE memory_entries SET status = 'superseded', updated_at = datetime('now')
            WHERE id = ?
        """, (old_id,))
        self.link(new_id, old_id, "supersedes")
        self.conn.commit()

    def archive(self, entry_id):
        """Archive an entry."""
        self.conn.execute("""
            UPDATE memory_entries SET status = 'archived', updated_at = datetime('now')
            WHERE id = ?
        """, (entry_id,))
        self.conn.commit()

    def link(self, from_id, to_id, relation):
        """Create a link between two entries."""
        if relation not in VALID_RELATIONS:
            raise ValueError(f"Invalid relation '{relation}'. Must be one of: {VALID_RELATIONS}")
        self.conn.execute("""
            INSERT OR IGNORE INTO memory_links (id, from_id, to_id, relation)
            VALUES (?, ?, ?, ?)
        """, (generate_ulid(), from_id, to_id, relation))
        self.conn.commit()

    def add_tags(self, entry_id, tags):
        """Add tags to an existing entry and rebuild FTS."""
        for tag in tags:
            t = tag.strip().lower()
            if t:
                self.conn.execute(
                    "INSERT OR IGNORE INTO entry_tags (entry_id, tag) VALUES (?, ?)",
                    (entry_id, t)
                )
        self._rebuild_fts_for_entry(entry_id)
        self.conn.commit()

    def remove_tags(self, entry_id, tags):
        """Remove tags from an entry and rebuild FTS."""
        for tag in tags:
            t = tag.strip().lower()
            if t:
                self.conn.execute(
                    "DELETE FROM entry_tags WHERE entry_id = ? AND tag = ?",
                    (entry_id, t)
                )
        self._rebuild_fts_for_entry(entry_id)
        self.conn.commit()

    def set_external_ref(self, entry_id, ref_type, ref_id):
        """Set an external reference on an entry (todoist_task_id, feed_post_id, etc.)."""
        row = self.conn.execute(
            "SELECT external_refs FROM memory_entries WHERE id = ?", (entry_id,)
        ).fetchone()
        if not row:
            return False
        refs = json.loads(row["external_refs"]) if row["external_refs"] else {}
        refs[ref_type] = ref_id
        self.conn.execute("""
            UPDATE memory_entries SET external_refs = ?, updated_at = datetime('now')
            WHERE id = ?
        """, (json.dumps(refs), entry_id))
        self.conn.commit()
        return True

    def query(self, type=None, status=None, project=None, person=None,
              days=None, limit=50):
        """Query memory entries with filters."""
        conditions = []
        params = []

        if type:
            conditions.append("type = ?")
            params.append(type)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if project:
            conditions.append("project = ?")
            params.append(project)
        if person:
            conditions.append("person = ?")
            params.append(person)
        if days is not None:  # Fix: days=0 should work
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            conditions.append("source_date >= ?")
            params.append(cutoff)

        where = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        rows = self.conn.execute(f"""
            SELECT * FROM memory_entries
            WHERE {where}
            ORDER BY source_date DESC, created_at DESC
            LIMIT ?
        """, params).fetchall()

        return [dict(r) for r in rows]

    def stale(self, type=None, days=7):
        """Find stale active entries older than N days.
        Default: commitments >7 days, blockers >14 days."""
        if type is None:
            # Query both commitments and blockers with appropriate thresholds
            results = []
            results.extend(self.stale(type="commitment", days=7))
            results.extend(self.stale(type="blocker", days=14))
            return results

        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = self.conn.execute("""
            SELECT * FROM memory_entries
            WHERE type = ? AND status = 'active' AND source_date < ?
            ORDER BY source_date ASC
        """, (type, cutoff)).fetchall()
        return [dict(r) for r in rows]

    def new_since(self, since_datetime):
        """Get entries created since a specific datetime (for session continuity)."""
        rows = self.conn.execute("""
            SELECT * FROM memory_entries
            WHERE created_at > ?
            ORDER BY created_at DESC
        """, (since_datetime,)).fetchall()
        return [dict(r) for r in rows]

    def search(self, query_text, limit=20):
        """Full-text search across title, body, and tags.
        Wraps each term in quotes to handle hyphens and special chars."""
        # Quote individual terms to prevent FTS5 operator interpretation
        # e.g., "fts-test" becomes '"fts-test"' instead of 'fts NOT test'
        terms = query_text.strip().split()
        safe_query = " ".join(f'"{t}"' for t in terms)
        try:
            rows = self.conn.execute("""
                SELECT me.* FROM memory_fts
                JOIN memory_entries me ON memory_fts.rowid = me.rowid
                WHERE memory_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (safe_query, limit)).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            # Fallback to LIKE if FTS query fails
            rows = self.conn.execute("""
                SELECT * FROM memory_entries
                WHERE title LIKE ? OR body LIKE ?
                ORDER BY source_date DESC
                LIMIT ?
            """, (f"%{query_text}%", f"%{query_text}%", limit)).fetchall()
            return [dict(r) for r in rows]

    def get(self, entry_id):
        """Get a single entry by ID."""
        row = self.conn.execute(
            "SELECT * FROM memory_entries WHERE id = ?", (entry_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_by_event_id(self, event_id):
        """Get entry by event_id (for idempotency checks)."""
        row = self.conn.execute(
            "SELECT * FROM memory_entries WHERE event_id = ?", (event_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_links(self, entry_id):
        """Get all links for an entry."""
        rows = self.conn.execute("""
            SELECT ml.*, me.title as linked_title, me.type as linked_type
            FROM memory_links ml
            JOIN memory_entries me ON (
                CASE WHEN ml.from_id = ? THEN ml.to_id ELSE ml.from_id END = me.id
            )
            WHERE ml.from_id = ? OR ml.to_id = ?
        """, (entry_id, entry_id, entry_id)).fetchall()
        return [dict(r) for r in rows]

    def get_tags(self, entry_id):
        """Get tags for an entry."""
        rows = self.conn.execute(
            "SELECT tag FROM entry_tags WHERE entry_id = ?", (entry_id,)
        ).fetchall()
        return [r["tag"] for r in rows]

    def orphan_entries(self):
        """Find entries without source_file (for data quality)."""
        rows = self.conn.execute("""
            SELECT * FROM memory_entries
            WHERE source_file IS NULL AND backfilled = 0
            ORDER BY created_at DESC
        """).fetchall()
        return [dict(r) for r in rows]

    def stats(self):
        """Get memory statistics."""
        total = self.conn.execute("SELECT COUNT(*) as c FROM memory_entries").fetchone()["c"]
        by_type = self.conn.execute("""
            SELECT type, COUNT(*) as count FROM memory_entries
            WHERE status = 'active' GROUP BY type ORDER BY count DESC
        """).fetchall()
        by_status = self.conn.execute("""
            SELECT status, COUNT(*) as count FROM memory_entries
            GROUP BY status ORDER BY count DESC
        """).fetchall()
        failures = self.conn.execute(
            "SELECT COUNT(*) as c FROM write_failures WHERE resolved = 0"
        ).fetchone()["c"]
        stale_commitments = len(self.stale(type="commitment", days=7))
        stale_blockers = len(self.stale(type="blocker", days=14))

        return {
            "total_entries": total,
            "active_by_type": {r["type"]: r["count"] for r in by_type},
            "by_status": {r["status"]: r["count"] for r in by_status},
            "unresolved_failures": failures,
            "stale_commitments": stale_commitments,
            "stale_blockers": stale_blockers,
        }

    def integrity_check(self):
        """Run SQLite integrity check."""
        result = self.conn.execute("PRAGMA integrity_check").fetchone()[0]
        return result == "ok", result

    def backup(self, backup_path):
        """Safe backup using VACUUM INTO (WAL-safe). Path is sanitized."""
        safe_path = os.path.abspath(os.path.expanduser(backup_path))
        if not safe_path:
            raise ValueError("backup_path must be non-empty")
        # VACUUM INTO does not support parameter binding, so quote manually.
        sql_path = safe_path.replace("'", "''")
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        self.conn.execute(f"VACUUM INTO '{sql_path}'")
        return safe_path

    def retry_failures(self):
        """Retry entries in the failure queue. Separate path from add() to avoid loops."""
        failures = self.conn.execute(
            "SELECT * FROM write_failures WHERE resolved = 0"
        ).fetchall()
        retried = 0
        for f in failures:
            try:
                entry = json.loads(f["entry_json"])
                entry_id = generate_ulid()
                event_id = f["event_id"]

                # Check if event_id already exists (was actually written)
                existing = self.get_by_event_id(event_id)
                if existing:
                    # Entry already exists, just mark failure as resolved
                    self.conn.execute("""
                        UPDATE write_failures SET resolved = 1, retried_at = datetime('now')
                        WHERE id = ?
                    """, (f["id"],))
                    retried += 1
                    continue

                # Direct insert, NOT through add() to avoid recursive failure logging
                tags = entry.pop("tags", None)
                backfilled = entry.pop("backfilled", False)
                external_refs = entry.pop("external_refs", None)

                self.conn.execute("BEGIN IMMEDIATE")

                # 1. Entry FIRST (tags have FK on entry_id)
                self.conn.execute("""
                    INSERT INTO memory_entries (id, event_id, type, title, body, project, person,
                        source_date, source_file, source_line, writer, confidence, backfilled, external_refs)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (entry_id, event_id,
                      entry.get("type"), entry.get("title"), entry.get("body"),
                      entry.get("project"), entry.get("person"),
                      entry.get("source_date", datetime.now().strftime("%Y-%m-%d")),
                      entry.get("source_file"), entry.get("source_line"),
                      entry.get("writer", DEFAULT_WRITER), entry.get("confidence", 1.0),
                      1 if backfilled else 0, external_refs))

                # 2. Tags AFTER entry (FK now valid)
                if tags:
                    for tag in tags:
                        t = tag.strip().lower() if isinstance(tag, str) else str(tag)
                        if t:
                            self.conn.execute(
                                "INSERT OR IGNORE INTO entry_tags (entry_id, tag) VALUES (?, ?)",
                                (entry_id, t)
                            )

                # 3. FTS entry with tags
                tags_str = " ".join(t.strip().lower() for t in tags if t.strip()) if tags else ""
                rowid = self.conn.execute(
                    "SELECT rowid FROM memory_entries WHERE id = ?", (entry_id,)
                ).fetchone()[0]
                self.conn.execute(
                    "INSERT INTO memory_fts(rowid, title, body, tags) VALUES (?, ?, ?, ?)",
                    (rowid, entry.get("title", ""), entry.get("body", "") or "", tags_str)
                )

                self.conn.execute("COMMIT")

                # Mark failure as resolved
                self.conn.execute("""
                    UPDATE write_failures SET resolved = 1, retried_at = datetime('now')
                    WHERE id = ?
                """, (f["id"],))
                self.conn.commit()
                retried += 1

            except Exception as e:
                try:
                    self.conn.execute("ROLLBACK")
                except Exception:
                    pass
                # Mark as resolved anyway to prevent infinite loop
                # The entry data is preserved in entry_json for manual recovery
                self.conn.execute("""
                    UPDATE write_failures SET resolved = 1, retried_at = datetime('now'),
                        error = error || ' | retry_failed: ' || ?
                    WHERE id = ?
                """, (str(e), f["id"]))
                self.conn.commit()

        return retried, len(failures)

    # ── Knowledge Graph Methods ──────────────────────────────────────

    def resolve_entity(self, name, entity_type):
        """Find or create an entity. Case-insensitive. Returns entity id.
        Checks aliases too. Creates if not found."""
        with self._transaction(immediate=True):
            return self._resolve_entity_id_in_txn(name, entity_type)

    def add_entity_alias(self, entity_id, alias):
        """Add an alias for an entity (e.g., nickname for canonical name)."""
        self._validate_entity_id(entity_id)
        alias_norm = self._normalize_non_empty_text(alias, "alias").casefold()

        with self._transaction(immediate=True):
            owner = self.conn.execute(
                "SELECT entity_id FROM entity_aliases WHERE alias_lower = ?",
                (alias_norm,)
            ).fetchone()
            if owner and owner["entity_id"] != entity_id:
                raise ValueError(
                    f"Alias '{alias_norm}' is already assigned to entity_id={owner['entity_id']}"
                )
            self.conn.execute(
                "INSERT OR IGNORE INTO entity_aliases (alias_lower, entity_id) VALUES (?, ?)",
                (alias_norm, entity_id)
            )

    def set_entity_slot(self, entity_id, key, value, scope="global", confidence=1.0):
        """Set a key-value slot on an entity. Bitemporally archived: old values get valid_to set."""
        self._validate_entity_id(entity_id)
        key = self._normalize_non_empty_text(key, "key")
        scope = self._normalize_non_empty_text(scope, "scope")
        confidence = self._validate_confidence(confidence)
        value_to_store = None if value is None else str(value)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self._transaction(immediate=True):
            current = self.conn.execute(
                "SELECT id, value, confidence FROM entity_slots "
                "WHERE entity_id = ? AND key = ? AND scope = ? AND valid_to IS NULL "
                "ORDER BY valid_from DESC LIMIT 1",
                (entity_id, key, scope)
            ).fetchone()
            if current and current["value"] == value_to_store and float(current["confidence"]) == confidence:
                return
            if current:
                self.conn.execute(
                    "UPDATE entity_slots SET valid_to = ? WHERE id = ?",
                    (now, current["id"])
                )
            self.conn.execute(
                "INSERT INTO entity_slots (entity_id, key, value, scope, valid_from, confidence) VALUES (?, ?, ?, ?, ?, ?)",
                (entity_id, key, value_to_store, scope, now, confidence)
            )

    def get_entity_slot(self, entity_id, key, scope="global", at_time=None):
        """Get current (or historical) value of an entity slot."""
        self._validate_entity_id(entity_id)
        key = self._normalize_non_empty_text(key, "key")
        scope = self._normalize_non_empty_text(scope, "scope")
        if at_time:
            row = self.conn.execute(
                "SELECT value FROM entity_slots WHERE entity_id = ? AND key = ? AND scope = ? "
                "AND valid_from <= ? AND (valid_to IS NULL OR valid_to > ?) ORDER BY valid_from DESC LIMIT 1",
                (entity_id, key, scope, at_time, at_time)
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT value FROM entity_slots WHERE entity_id = ? AND key = ? AND scope = ? "
                "AND valid_to IS NULL ORDER BY valid_from DESC LIMIT 1",
                (entity_id, key, scope)
            ).fetchone()
        return row["value"] if row else None

    def get_entity_slots(self, entity_id, scope="global"):
        """Get all current slots for an entity."""
        self._validate_entity_id(entity_id)
        scope = self._normalize_non_empty_text(scope, "scope")
        rows = self.conn.execute(
            "SELECT key, value, scope, confidence FROM entity_slots "
            "WHERE entity_id = ? AND (scope = ? OR scope = 'global') AND valid_to IS NULL "
            "ORDER BY CASE WHEN scope = ? THEN 0 ELSE 1 END, valid_from DESC",
            (entity_id, scope, scope)
        ).fetchall()
        merged = {}
        for r in rows:
            if r["key"] not in merged:
                merged[r["key"]] = r["value"]
        return merged

    def add_entity_observation(self, entity_id, observation, source=None):
        """Add a free-text observation to an entity."""
        self._validate_entity_id(entity_id)
        observation = self._normalize_non_empty_text(observation, "observation")
        if source is not None:
            source = self._normalize_non_empty_text(source, "source")
        self.conn.execute(
            "INSERT INTO entity_observations (entity_id, observation, source) VALUES (?, ?, ?)",
            (entity_id, observation, source)
        )
        self.conn.commit()

    def get_entity_observations(self, entity_id, limit=20):
        """Get observations for an entity."""
        self._validate_entity_id(entity_id)
        limit = int(limit)
        if limit <= 0:
            raise ValueError("limit must be a positive integer")
        rows = self.conn.execute(
            "SELECT * FROM entity_observations WHERE entity_id = ? ORDER BY created_at DESC LIMIT ?",
            (entity_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]

    def relate_entities(self, from_name, from_type, relation, to_name, to_type, metadata=None):
        """Create a relation between two entities. Resolves (or creates) both entities."""
        relation = self._normalize_relation(relation)
        metadata_json = None
        if metadata is not None:
            metadata_json = metadata if isinstance(metadata, str) else json.dumps(metadata, ensure_ascii=True)

        with self._transaction(immediate=True):
            from_id = self._resolve_entity_id_in_txn(from_name, from_type)
            to_id = self._resolve_entity_id_in_txn(to_name, to_type)
            if from_id == to_id:
                raise ValueError("Self-relations are not allowed")
            self.conn.execute(
                "INSERT OR IGNORE INTO entity_relations (from_entity_id, to_entity_id, relation, metadata) VALUES (?, ?, ?, ?)",
                (from_id, to_id, relation, metadata_json)
            )

    def get_entity_relations(self, entity_id, direction="both"):
        """Get relations for an entity. Direction: 'outgoing', 'incoming', or 'both'."""
        self._validate_entity_id(entity_id)
        if direction not in {"incoming", "outgoing", "both"}:
            raise ValueError("direction must be one of: incoming, outgoing, both")
        results = []
        if direction in ("outgoing", "both"):
            rows = self.conn.execute(
                "SELECT er.*, e.name as to_name, e.type as to_type FROM entity_relations er "
                "JOIN entities e ON er.to_entity_id = e.id WHERE er.from_entity_id = ?",
                (entity_id,)
            ).fetchall()
            results.extend({"direction": "outgoing", **dict(r)} for r in rows)
        if direction in ("incoming", "both"):
            rows = self.conn.execute(
                "SELECT er.*, e.name as from_name, e.type as from_type FROM entity_relations er "
                "JOIN entities e ON er.from_entity_id = e.id WHERE er.to_entity_id = ?",
                (entity_id,)
            ).fetchall()
            results.extend({"direction": "incoming", **dict(r)} for r in rows)
        return results

    def link_entity_to_entry(self, entity_id, entry_id, role="related"):
        """Link an entity to a memory entry."""
        self._validate_entity_id(entity_id)
        entry_id = self._validate_entry_id(entry_id)
        role = self._normalize_role(role)
        self.conn.execute(
            "INSERT OR IGNORE INTO entity_entry_links (entity_id, entry_id, role) VALUES (?, ?, ?)",
            (entity_id, entry_id, role)
        )
        self.conn.commit()

    def auto_link_entry(self, entry_id):
        """Auto-link one memory entry to matching entities. Returns number of links created."""
        entry_id = self._validate_entry_id(entry_id)
        match_index = self._entity_match_index()
        with self._transaction(immediate=True):
            return self._auto_link_entry_in_txn(entry_id, match_index)

    def backfill_links(self):
        """Backfill entity links for entries that currently have no links."""
        match_index = self._entity_match_index()
        rows = self.conn.execute(
            "SELECT me.id FROM memory_entries me "
            "LEFT JOIN entity_entry_links eel ON eel.entry_id = me.id "
            "GROUP BY me.id HAVING COUNT(eel.entity_id) = 0"
        ).fetchall()
        entry_ids = [r["id"] for r in rows]
        if not entry_ids:
            return 0

        created = 0
        with self._transaction(immediate=True):
            for entry_id in entry_ids:
                created += self._auto_link_entry_in_txn(entry_id, match_index)
        return created

    def graph_health(self):
        """Return integrity and quality metrics for the knowledge graph."""
        total_entities = self.conn.execute(
            "SELECT COUNT(*) AS c FROM entities"
        ).fetchone()["c"]
        total_relations = self.conn.execute(
            "SELECT COUNT(*) AS c FROM entity_relations"
        ).fetchone()["c"]

        orphan_rows = self.conn.execute(
            "SELECT e.id, e.name, e.type FROM entities e "
            "WHERE NOT EXISTS (SELECT 1 FROM entity_relations er WHERE er.from_entity_id = e.id OR er.to_entity_id = e.id) "
            "AND NOT EXISTS (SELECT 1 FROM entity_slots es WHERE es.entity_id = e.id) "
            "AND NOT EXISTS (SELECT 1 FROM entity_observations eo WHERE eo.entity_id = e.id) "
            "ORDER BY e.type, e.name_lower"
        ).fetchall()

        dangling_rows = self.conn.execute(
            "SELECT er.id, er.from_entity_id, er.to_entity_id, er.relation "
            "FROM entity_relations er "
            "LEFT JOIN entities ef ON ef.id = er.from_entity_id "
            "LEFT JOIN entities et ON et.id = er.to_entity_id "
            "WHERE ef.id IS NULL OR et.id IS NULL"
        ).fetchall()

        unlinked_entries = self.conn.execute(
            "SELECT COUNT(*) AS c FROM memory_entries me "
            "LEFT JOIN entity_entry_links eel ON eel.entry_id = me.id "
            "WHERE eel.entry_id IS NULL"
        ).fetchone()["c"]

        duplicate_rows = self.conn.execute(
            "SELECT name_lower, GROUP_CONCAT(type, ', ') AS types, COUNT(*) AS count "
            "FROM entities GROUP BY name_lower HAVING COUNT(DISTINCT type) > 1 "
            "ORDER BY name_lower"
        ).fetchall()

        return {
            "total_entities": total_entities,
            "total_relations": total_relations,
            "orphan_entities": [dict(r) for r in orphan_rows],
            "dangling_relations": [dict(r) for r in dangling_rows],
            "unlinked_entries": unlinked_entries,
            "duplicate_entities": [dict(r) for r in duplicate_rows],
        }

    def export_graph(self):
        """Export the full knowledge graph to a JSON-serializable dict."""
        entities = [dict(r) for r in self.conn.execute(
            "SELECT id, name, name_lower, type, created_at, updated_at "
            "FROM entities ORDER BY type, name_lower"
        ).fetchall()]
        aliases = [dict(r) for r in self.conn.execute(
            "SELECT entity_id, alias_lower FROM entity_aliases ORDER BY entity_id, alias_lower"
        ).fetchall()]
        slots = [dict(r) for r in self.conn.execute(
            "SELECT entity_id, key, value, scope, valid_from, valid_to, confidence "
            "FROM entity_slots ORDER BY entity_id, key, valid_from"
        ).fetchall()]
        observations = [dict(r) for r in self.conn.execute(
            "SELECT entity_id, observation, source, created_at FROM entity_observations "
            "ORDER BY entity_id, created_at"
        ).fetchall()]

        alias_map = {}
        for row in aliases:
            alias_map.setdefault(row["entity_id"], []).append(row["alias_lower"])
        slot_map = {}
        for row in slots:
            slot_map.setdefault(row["entity_id"], []).append(row)
        observation_map = {}
        for row in observations:
            observation_map.setdefault(row["entity_id"], []).append(row)

        for entity in entities:
            entity_id = entity["id"]
            entity["aliases"] = alias_map.get(entity_id, [])
            entity["slots"] = slot_map.get(entity_id, [])
            entity["observations"] = observation_map.get(entity_id, [])

        relations = [dict(r) for r in self.conn.execute(
            "SELECT id, from_entity_id, to_entity_id, relation, metadata, created_at "
            "FROM entity_relations ORDER BY id"
        ).fetchall()]
        entry_links = [dict(r) for r in self.conn.execute(
            "SELECT entity_id, entry_id, role, created_at FROM entity_entry_links "
            "ORDER BY entity_id, entry_id"
        ).fetchall()]

        return {
            "entities": entities,
            "relations": relations,
            "entry_links": entry_links,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
        }

    def import_graph(self, data):
        """Import graph backup data. Skips existing entities by (name_lower, type)."""
        if not isinstance(data, dict):
            raise ValueError("data must be a dict")

        entities_data = data.get("entities")
        relations_data = data.get("relations")
        entry_links_data = data.get("entry_links")
        if not isinstance(entities_data, list) or not isinstance(relations_data, list) or not isinstance(entry_links_data, list):
            raise ValueError("data must include list fields: entities, relations, entry_links")

        entity_id_map = {}
        imported_entities = 0

        with self._transaction(immediate=True):
            for entity in entities_data:
                if not isinstance(entity, dict):
                    continue
                name = self._normalize_non_empty_text(entity.get("name", ""), "name")
                entity_type = self._normalize_entity_type(entity.get("type", ""))
                name_lower = name.casefold()

                existing = self.conn.execute(
                    "SELECT id FROM entities WHERE name_lower = ? AND type = ?",
                    (name_lower, entity_type)
                ).fetchone()
                if existing:
                    resolved_id = existing["id"]
                else:
                    self.conn.execute(
                        "INSERT INTO entities (name, name_lower, type) VALUES (?, ?, ?)",
                        (name, name_lower, entity_type)
                    )
                    resolved_id = self.conn.execute(
                        "SELECT id FROM entities WHERE name_lower = ? AND type = ?",
                        (name_lower, entity_type)
                    ).fetchone()["id"]
                    imported_entities += 1

                source_id = entity.get("id")
                if isinstance(source_id, int):
                    entity_id_map[source_id] = resolved_id

                aliases = entity.get("aliases", [])
                if isinstance(aliases, list):
                    for alias in aliases:
                        if not isinstance(alias, str) or not alias.strip():
                            continue
                        alias_norm = alias.strip().casefold()
                        owner = self.conn.execute(
                            "SELECT entity_id FROM entity_aliases WHERE alias_lower = ?",
                            (alias_norm,)
                        ).fetchone()
                        if owner and owner["entity_id"] != resolved_id:
                            continue
                        self.conn.execute(
                            "INSERT OR IGNORE INTO entity_aliases (alias_lower, entity_id) VALUES (?, ?)",
                            (alias_norm, resolved_id)
                        )

                slots = entity.get("slots", [])
                if isinstance(slots, list):
                    for slot in slots:
                        if not isinstance(slot, dict):
                            continue
                        key = slot.get("key")
                        scope = slot.get("scope", "global")
                        if not isinstance(key, str) or not key.strip():
                            continue
                        if not isinstance(scope, str) or not scope.strip():
                            continue
                        valid_from = slot.get("valid_from")
                        if not isinstance(valid_from, str) or not valid_from.strip():
                            continue
                        existing_slot = self.conn.execute(
                            "SELECT id FROM entity_slots WHERE entity_id = ? AND key = ? AND scope = ? "
                            "AND valid_from = ? AND COALESCE(valid_to, '') = COALESCE(?, '') "
                            "AND COALESCE(value, '') = COALESCE(?, '')",
                            (resolved_id, key.strip(), scope.strip(), valid_from.strip(), slot.get("valid_to"), slot.get("value"))
                        ).fetchone()
                        if existing_slot:
                            continue
                        confidence = slot.get("confidence", 1.0)
                        try:
                            confidence = float(confidence)
                        except (TypeError, ValueError):
                            confidence = 1.0
                        self.conn.execute(
                            "INSERT INTO entity_slots (entity_id, key, value, scope, valid_from, valid_to, confidence) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (
                                resolved_id,
                                key.strip(),
                                None if slot.get("value") is None else str(slot.get("value")),
                                scope.strip(),
                                valid_from.strip(),
                                slot.get("valid_to"),
                                max(0.0, min(1.0, confidence)),
                            )
                        )

                observations = entity.get("observations", [])
                if isinstance(observations, list):
                    for obs in observations:
                        if not isinstance(obs, dict):
                            continue
                        observation = obs.get("observation")
                        if not isinstance(observation, str) or not observation.strip():
                            continue
                        source = obs.get("source")
                        created_at = obs.get("created_at")
                        existing_obs = self.conn.execute(
                            "SELECT id FROM entity_observations WHERE entity_id = ? "
                            "AND observation = ? AND COALESCE(source, '') = COALESCE(?, '') "
                            "AND COALESCE(created_at, '') = COALESCE(?, '')",
                            (resolved_id, observation.strip(), source, created_at)
                        ).fetchone()
                        if existing_obs:
                            continue
                        self.conn.execute(
                            "INSERT INTO entity_observations (entity_id, observation, source, created_at) VALUES (?, ?, ?, ?)",
                            (resolved_id, observation.strip(), source, created_at)
                        )

            for relation in relations_data:
                if not isinstance(relation, dict):
                    continue
                from_id = relation.get("from_entity_id")
                to_id = relation.get("to_entity_id")
                if not isinstance(from_id, int) or not isinstance(to_id, int):
                    continue
                mapped_from = entity_id_map.get(from_id, from_id)
                mapped_to = entity_id_map.get(to_id, to_id)
                if mapped_from == mapped_to:
                    continue
                rel = relation.get("relation")
                try:
                    rel = self._normalize_relation(rel)
                except ValueError:
                    continue
                from_exists = self.conn.execute(
                    "SELECT 1 FROM entities WHERE id = ?",
                    (mapped_from,)
                ).fetchone()
                to_exists = self.conn.execute(
                    "SELECT 1 FROM entities WHERE id = ?",
                    (mapped_to,)
                ).fetchone()
                if not from_exists or not to_exists:
                    continue
                self.conn.execute(
                    "INSERT OR IGNORE INTO entity_relations (from_entity_id, to_entity_id, relation, metadata) VALUES (?, ?, ?, ?)",
                    (mapped_from, mapped_to, rel, relation.get("metadata"))
                )

            for link in entry_links_data:
                if not isinstance(link, dict):
                    continue
                source_entity_id = link.get("entity_id")
                entry_id = link.get("entry_id")
                role = link.get("role", "related")
                if not isinstance(source_entity_id, int):
                    continue
                mapped_entity_id = entity_id_map.get(source_entity_id, source_entity_id)
                try:
                    entry_id = self._validate_entry_id(entry_id)
                    role = self._normalize_role(role)
                except ValueError:
                    continue
                entity_exists = self.conn.execute(
                    "SELECT 1 FROM entities WHERE id = ?",
                    (mapped_entity_id,)
                ).fetchone()
                entry_exists = self.conn.execute(
                    "SELECT 1 FROM memory_entries WHERE id = ?",
                    (entry_id,)
                ).fetchone()
                if not entity_exists or not entry_exists:
                    continue
                self.conn.execute(
                    "INSERT OR IGNORE INTO entity_entry_links (entity_id, entry_id, role) VALUES (?, ?, ?)",
                    (mapped_entity_id, entry_id, role)
                )

        return {"imported_entities": imported_entities, "mapped_entities": len(entity_id_map)}

    def get_entity(self, entity_id):
        """Get full entity profile: basic info, slots, observations, relations."""
        self._validate_entity_id(entity_id)
        row = self.conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
        if not row:
            return None
        entity = dict(row)
        entity["slots"] = self.get_entity_slots(entity_id)
        entity["observations"] = self.get_entity_observations(entity_id, limit=10)
        entity["relations"] = self.get_entity_relations(entity_id)
        entity["aliases"] = [r["alias_lower"] for r in self.conn.execute(
            "SELECT alias_lower FROM entity_aliases WHERE entity_id = ?", (entity_id,)
        ).fetchall()]
        # Linked memory entries
        entries = self.conn.execute(
            "SELECT eel.role, me.id, me.type, me.title, me.status FROM entity_entry_links eel "
            "JOIN memory_entries me ON eel.entry_id = me.id WHERE eel.entity_id = ? ORDER BY me.source_date DESC LIMIT 10",
            (entity_id,)
        ).fetchall()
        entity["linked_entries"] = [dict(r) for r in entries]
        return entity

    def find_entity(self, name, entity_type=None):
        """Find an entity by name (case-insensitive). Checks aliases. Returns entity id or None."""
        name_lower = self._normalize_non_empty_text(name, "name").casefold()
        if entity_type:
            entity_type = self._normalize_entity_type(entity_type)
            row = self.conn.execute(
                "SELECT id FROM entities WHERE name_lower = ? AND type = ?",
                (name_lower, entity_type)
            ).fetchone()
            if not row:
                row = self.conn.execute(
                    "SELECT e.id FROM entity_aliases ea JOIN entities e ON ea.entity_id = e.id "
                    "WHERE ea.alias_lower = ? AND e.type = ?",
                    (name_lower, entity_type)
                ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT id FROM entities WHERE name_lower = ?", (name_lower,)
            ).fetchone()
            if not row:
                row = self.conn.execute(
                    "SELECT entity_id as id FROM entity_aliases WHERE alias_lower = ?",
                    (name_lower,)
                ).fetchone()
        return row["id"] if row else None

    def list_entities(self, entity_type=None, limit=50):
        """List entities, optionally filtered by type."""
        limit = int(limit)
        if limit <= 0:
            raise ValueError("limit must be a positive integer")
        if entity_type:
            entity_type = self._normalize_entity_type(entity_type)
            rows = self.conn.execute(
                "SELECT * FROM entities WHERE type = ? ORDER BY name_lower LIMIT ?",
                (entity_type, limit)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM entities ORDER BY type, name_lower LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def search_entities(self, query, limit=20):
        """Search entities by name or observation text."""
        query = self._normalize_non_empty_text(query, "query")
        limit = int(limit)
        if limit <= 0:
            raise ValueError("limit must be a positive integer")
        name_lower = f"%{query.casefold()}%"
        rows = self.conn.execute(
            "SELECT DISTINCT e.* FROM entities e "
            "LEFT JOIN entity_observations eo ON e.id = eo.entity_id "
            "LEFT JOIN entity_aliases ea ON e.id = ea.entity_id "
            "WHERE e.name_lower LIKE ? OR eo.observation LIKE ? OR ea.alias_lower LIKE ? "
            "ORDER BY e.type, e.name_lower LIMIT ?",
            (name_lower, name_lower, name_lower, limit)
        ).fetchall()
        return [dict(r) for r in rows]

    def entity_stats(self):
        """Get knowledge graph statistics."""
        total = self.conn.execute("SELECT COUNT(*) as c FROM entities").fetchone()["c"]
        by_type = self.conn.execute(
            "SELECT type, COUNT(*) as count FROM entities GROUP BY type ORDER BY count DESC"
        ).fetchall()
        total_relations = self.conn.execute("SELECT COUNT(*) as c FROM entity_relations").fetchone()["c"]
        total_observations = self.conn.execute("SELECT COUNT(*) as c FROM entity_observations").fetchone()["c"]
        total_links = self.conn.execute("SELECT COUNT(*) as c FROM entity_entry_links").fetchone()["c"]
        return {
            "total_entities": total,
            "by_type": {r["type"]: r["count"] for r in by_type},
            "total_relations": total_relations,
            "total_observations": total_observations,
            "entity_entry_links": total_links,
        }

    def delete_entity(self, entity_id):
        """Delete an entity and all its associated data (cascading)."""
        self._validate_entity_id(entity_id)
        self.conn.execute("DELETE FROM entities WHERE id = ?", (entity_id,))
        self.conn.commit()

    def close(self):
        """Close the database connection."""
        self.conn.close()


# CLI usage
if __name__ == "__main__":
    db = MemoryDB()
    ok, result = db.integrity_check()
    print(f"Integrity: {'✅ OK' if ok else '❌ ' + result}")
    stats = db.stats()
    print(f"Total entries: {stats['total_entries']}")
    print(f"Active by type: {stats['active_by_type']}")
    print(f"By status: {stats['by_status']}")
    print(f"Unresolved failures: {stats['unresolved_failures']}")
    print(f"Stale commitments (>7d): {stats['stale_commitments']}")
    print(f"Stale blockers (>14d): {stats['stale_blockers']}")
    db.close()
