-- Specialist Agent Architecture: Orchestration Database Schema
-- Version: 1.0 (from architecture v3)
-- Apply: sqlite3 ~/.openclaw/orchestration/state.db < schemas/orchestration.sql

PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;

-- Tasks with optimistic concurrency control
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK(status IN ('queued','triaging','planned','building','reviewing','feedback','done','failed','escalated')),
    version INTEGER NOT NULL DEFAULT 1,
    assigned_agent TEXT,
    parent_task_id TEXT REFERENCES tasks(id),
    project TEXT,
    priority INTEGER NOT NULL DEFAULT 3 CHECK(priority BETWEEN 1 AND 4),
    contract_path TEXT,
    result_path TEXT,
    context_version TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    started_at TEXT,
    completed_at TEXT,
    iteration INTEGER NOT NULL DEFAULT 0,
    max_iterations INTEGER NOT NULL DEFAULT 3,
    routing_confidence TEXT CHECK(routing_confidence IN ('high','medium','low')),
    escalation_reason TEXT,
    tokens_consumed INTEGER DEFAULT 0
);

-- Auto-update updated_at and version on change
-- Safe: recursive_triggers is OFF by default in SQLite
CREATE TRIGGER IF NOT EXISTS tasks_update_timestamp
    AFTER UPDATE ON tasks FOR EACH ROW
BEGIN
    UPDATE tasks SET
        updated_at = strftime('%Y-%m-%dT%H:%M:%f','now'),
        version = OLD.version + 1
    WHERE id = NEW.id;
END;

-- Legal state transitions
CREATE TABLE IF NOT EXISTS task_transitions (
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    PRIMARY KEY (from_status, to_status)
);

INSERT OR IGNORE INTO task_transitions VALUES
    ('queued', 'triaging'), ('queued', 'planned'), ('queued', 'building'),
    ('triaging', 'queued'), ('triaging', 'planned'), ('triaging', 'escalated'),
    ('planned', 'building'), ('planned', 'escalated'),
    ('building', 'reviewing'), ('building', 'done'), ('building', 'failed'), ('building', 'escalated'),
    ('reviewing', 'done'), ('reviewing', 'feedback'), ('reviewing', 'failed'), ('reviewing', 'escalated'),
    ('feedback', 'building'), ('feedback', 'planned'), ('feedback', 'escalated'),
    ('failed', 'queued'), ('escalated', 'queued'), ('escalated', 'planned');

-- Enforce valid transitions
CREATE TRIGGER IF NOT EXISTS enforce_task_transition
    BEFORE UPDATE OF status ON tasks
    FOR EACH ROW WHEN OLD.status != NEW.status
BEGIN
    SELECT RAISE(ABORT, 'Invalid task state transition')
    WHERE NOT EXISTS (
        SELECT 1 FROM task_transitions WHERE from_status = OLD.status AND to_status = NEW.status
    );
END;

-- Events with causality and delivery semantics
CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    event_type TEXT NOT NULL CHECK(event_type IN (
        'status_change', 'context_missing', 'assumption_invalidated',
        'review_failed', 'escalated', 'feedback', 'completed',
        'memory_conflict_detected', 'policy_check_result', 'instinct_extracted'
    )),
    source_agent TEXT NOT NULL,
    target_agent TEXT,
    payload TEXT NOT NULL DEFAULT '{}',
    payload_version INTEGER NOT NULL DEFAULT 1,
    idempotency_key TEXT UNIQUE,
    task_event_seq INTEGER,
    causation_event_id INTEGER REFERENCES task_events(id),
    correlation_id TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    acknowledged_at TEXT,
    claimed_by TEXT,
    claimed_at TEXT,
    delivery_attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    last_error TEXT
);

-- Per-task event sequence auto-assign
CREATE TRIGGER IF NOT EXISTS task_events_seq AFTER INSERT ON task_events FOR EACH ROW
BEGIN
    UPDATE task_events SET task_event_seq = (
        SELECT COALESCE(MAX(task_event_seq), 0) + 1
        FROM task_events WHERE task_id = NEW.task_id
    ) WHERE id = NEW.id;
END;

-- Policy checks at gates
CREATE TABLE IF NOT EXISTS policy_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    check_type TEXT NOT NULL CHECK(check_type IN (
        'security', 'cost', 'ux_consistency', 'test_coverage', 'deploy_safety'
    )),
    gate TEXT NOT NULL CHECK(gate IN ('pre_plan', 'pre_build', 'pre_merge', 'pre_deploy')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','passed','failed','waived')),
    details TEXT,
    checked_by TEXT,
    checked_at TEXT,
    waive_reason TEXT
);

-- Agent status (quarantine/circuit-breaker)
CREATE TABLE IF NOT EXISTS agent_status (
    agent_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'quarantined', 'suspended')),
    reason TEXT,
    quarantined_at TEXT,
    recovery_benchmark_id TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

INSERT OR IGNORE INTO agent_status VALUES ('blueprint', 'active', NULL, NULL, NULL, strftime('%Y-%m-%dT%H:%M:%f','now'));
INSERT OR IGNORE INTO agent_status VALUES ('forge', 'active', NULL, NULL, NULL, strftime('%Y-%m-%dT%H:%M:%f','now'));
INSERT OR IGNORE INTO agent_status VALUES ('scout', 'active', NULL, NULL, NULL, strftime('%Y-%m-%dT%H:%M:%f','now'));
INSERT OR IGNORE INTO agent_status VALUES ('sherlock', 'active', NULL, NULL, NULL, strftime('%Y-%m-%dT%H:%M:%f','now'));
INSERT OR IGNORE INTO agent_status VALUES ('pixel', 'active', NULL, NULL, NULL, strftime('%Y-%m-%dT%H:%M:%f','now'));

-- Scheduler config
CREATE TABLE IF NOT EXISTS scheduler_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR IGNORE INTO scheduler_config VALUES ('global_max_active','6');
INSERT OR IGNORE INTO scheduler_config VALUES ('project_max_active','3');
INSERT OR IGNORE INTO scheduler_config VALUES ('starvation_hours','4');

-- Indexes
CREATE INDEX IF NOT EXISTS idx_tasks_status_priority ON tasks(status, priority, updated_at);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project, status);
CREATE INDEX IF NOT EXISTS idx_tasks_agent ON tasks(assigned_agent, status);
CREATE INDEX IF NOT EXISTS idx_events_task_seq ON task_events(task_id, task_event_seq);
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_task_seq_unique ON task_events(task_id, task_event_seq);
CREATE INDEX IF NOT EXISTS idx_events_target_unack ON task_events(target_agent, acknowledged_at, id) WHERE acknowledged_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_events_unclaimed ON task_events(claimed_by, created_at) WHERE claimed_by IS NULL AND acknowledged_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_policy_task_gate ON policy_checks(task_id, gate, status);
