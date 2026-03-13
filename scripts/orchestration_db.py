#!/usr/bin/env python3
"""Orchestration database library + CLI."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from typing import Any


DEFAULT_DB_PATH = os.path.expanduser("~/.openclaw/orchestration/state.db")
BUSY_RETRY_ATTEMPTS = 5
BUSY_INITIAL_BACKOFF_SECONDS = 0.05
ACTIVE_STATUSES = ("triaging", "building", "reviewing")
SELECTABLE_STATUSES = ("queued", "planned", "feedback")


class ConcurrentModificationError(Exception):
    pass


class InvalidTransitionError(Exception):
    pass


class PayloadValidationError(Exception):
    pass


class UnauthorizedError(Exception):
    pass


class GateBlockedError(Exception):
    pass


REQUIRED_FIELDS: dict[str, list[str]] = {
    "status_change": ["from", "to", "reason"],
    "context_missing": ["what", "why_needed", "blocking"],
    "assumption_invalidated": ["assumption", "evidence", "affected_tasks"],
    "review_failed": ["mode", "findings"],
    "escalated": ["reason", "attempted_fixes"],
    "feedback": ["from_user", "corrections"],
    "completed": ["result_path", "summary"],
    "memory_conflict_detected": ["entry_a", "entry_b", "conflict_type"],
    "policy_check_result": ["check_type", "gate", "passed", "details"],
    "instinct_extracted": ["instinct_id", "trigger", "confidence"],
}


def _connect(db_path: str | None = None) -> sqlite3.Connection:
    path = os.path.expanduser(db_path or DEFAULT_DB_PATH)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    out = dict(row)
    if "payload" in out and isinstance(out["payload"], str):
        try:
            out["payload"] = json.loads(out["payload"])
        except json.JSONDecodeError:
            pass
    return out


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [_row_to_dict(row) for row in rows if row is not None]


def _is_busy_error(exc: sqlite3.OperationalError) -> bool:
    code = getattr(exc, "sqlite_errorcode", None)
    if code == sqlite3.SQLITE_BUSY:
        return True
    text = str(exc).lower()
    return "database is locked" in text or "database is busy" in text


def _run_with_busy_retry(fn):
    delay = BUSY_INITIAL_BACKOFF_SECONDS
    for attempt in range(BUSY_RETRY_ATTEMPTS):
        try:
            return fn()
        except sqlite3.OperationalError as exc:
            if not _is_busy_error(exc) or attempt == BUSY_RETRY_ATTEMPTS - 1:
                raise
            time.sleep(delay)
            delay *= 2


def _validate_payload(event_type: str, payload: dict[str, Any]) -> None:
    if event_type not in REQUIRED_FIELDS:
        raise PayloadValidationError(f"Unknown event_type: {event_type}")
    if not isinstance(payload, dict):
        raise PayloadValidationError("Payload must be a dict")
    missing = [field for field in REQUIRED_FIELDS[event_type] if field not in payload]
    if missing:
        raise PayloadValidationError(f"Missing required payload fields for {event_type}: {', '.join(missing)}")


def _get_scheduler_int(conn: sqlite3.Connection, key: str, default: int) -> int:
    row = conn.execute("SELECT value FROM scheduler_config WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return int(row["value"])
    except (TypeError, ValueError):
        return default


def _can_start_task_with_conn(conn: sqlite3.Connection, task: dict[str, Any]) -> tuple[bool, str]:
    if task["status"] not in SELECTABLE_STATUSES:
        return False, f"task status {task['status']} is not startable"

    global_cap = _get_scheduler_int(conn, "global_max_active", 6)
    active_sessions = conn.execute(
        f"SELECT COUNT(*) AS c FROM tasks WHERE status IN ({','.join('?' for _ in ACTIVE_STATUSES)})",
        ACTIVE_STATUSES,
    ).fetchone()["c"]
    if active_sessions >= global_cap:
        return False, f"global cap reached ({active_sessions}/{global_cap})"

    project = task.get("project")
    if project:
        project_cap = _get_scheduler_int(conn, "project_max_active", 3)
        active_project = conn.execute(
            f"SELECT COUNT(*) AS c FROM tasks WHERE project = ? AND status IN ({','.join('?' for _ in ACTIVE_STATUSES)})",
            (project, *ACTIVE_STATUSES),
        ).fetchone()["c"]
        if active_project >= project_cap:
            return False, f"project cap reached for {project} ({active_project}/{project_cap})"

    agent = task.get("assigned_agent")
    if agent:
        row = conn.execute("SELECT status, reason FROM agent_status WHERE agent_id = ?", (agent,)).fetchone()
        if row and row["status"] in ("quarantined", "suspended"):
            return False, f"agent {agent} is {row['status']}: {row['reason'] or 'no reason provided'}"

    return True, "ok"


# Task CRUD

def create_task(
    task_id,
    title,
    project=None,
    priority=3,
    assigned_agent=None,
    parent_task_id=None,
    routing_confidence=None,
    contract_path=None,
    context_version=None,
    max_iterations=3,
) -> dict[str, Any]:
    def op():
        conn = _connect()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO tasks (
                        id, title, project, priority, assigned_agent, parent_task_id,
                        routing_confidence, contract_path, context_version, max_iterations
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        title,
                        project,
                        priority,
                        assigned_agent,
                        parent_task_id,
                        routing_confidence,
                        contract_path,
                        context_version,
                        max_iterations,
                    ),
                )
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return _row_to_dict(row)
        finally:
            conn.close()

    return _run_with_busy_retry(op)


def get_task(task_id) -> dict[str, Any] | None:
    def op():
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return _row_to_dict(row)
        finally:
            conn.close()

    return _run_with_busy_retry(op)


def list_tasks(project=None, status=None, agent=None, limit=50) -> list[dict[str, Any]]:
    def op():
        conn = _connect()
        try:
            clauses = ["1=1"]
            params: list[Any] = []
            if project is not None:
                clauses.append("project = ?")
                params.append(project)
            if status is not None:
                clauses.append("status = ?")
                params.append(status)
            if agent is not None:
                clauses.append("assigned_agent = ?")
                params.append(agent)
            params.append(limit)
            rows = conn.execute(
                f"SELECT * FROM tasks WHERE {' AND '.join(clauses)} ORDER BY priority ASC, created_at ASC LIMIT ?",
                params,
            ).fetchall()
            return _rows_to_dicts(rows)
        finally:
            conn.close()

    return _run_with_busy_retry(op)


# State transitions

def transition_task(task_id, new_status, expected_version, **kwargs) -> dict[str, Any]:
    def op():
        conn = _connect()
        try:
            assignments = ["status = ?"]
            params: list[Any] = [new_status]
            allowed = ["assigned_agent", "contract_path", "result_path", "escalation_reason"]
            for key in allowed:
                if key in kwargs and kwargs[key] is not None:
                    assignments.append(f"{key} = ?")
                    params.append(kwargs[key])

            if "tokens_consumed" in kwargs and kwargs["tokens_consumed"] is not None:
                assignments.append("tokens_consumed = COALESCE(tokens_consumed, 0) + ?")
                params.append(int(kwargs["tokens_consumed"]))

            if new_status == "building":
                assignments.append("started_at = COALESCE(started_at, strftime('%Y-%m-%dT%H:%M:%f','now'))")
            if new_status in ("done", "failed", "escalated"):
                assignments.append("completed_at = strftime('%Y-%m-%dT%H:%M:%f','now')")

            try:
                with conn:
                    cursor = conn.execute(
                        f"UPDATE tasks SET {', '.join(assignments)} WHERE id = ? AND version = ?",
                        (*params, task_id, expected_version),
                    )
                    if cursor.rowcount == 0:
                        raise ConcurrentModificationError(
                            f"Task {task_id} was modified concurrently or does not exist"
                        )
            except sqlite3.IntegrityError as exc:
                message = str(exc)
                if "Invalid task state transition" in message:
                    raise InvalidTransitionError(message) from exc
                raise

            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return _row_to_dict(row)
        finally:
            conn.close()

    return _run_with_busy_retry(op)


# Events

def write_event(
    task_id,
    event_type,
    source_agent,
    payload,
    target_agent=None,
    idempotency_key=None,
    causation_event_id=None,
    correlation_id=None,
) -> int:
    _validate_payload(event_type, payload)

    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)

    def op():
        conn = _connect()
        try:
            try:
                with conn:
                    cursor = conn.execute(
                        """
                        INSERT INTO task_events (
                            task_id, event_type, source_agent, target_agent, payload,
                            idempotency_key, causation_event_id, correlation_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            task_id,
                            event_type,
                            source_agent,
                            target_agent,
                            payload_json,
                            idempotency_key,
                            causation_event_id,
                            correlation_id,
                        ),
                    )
                    return int(cursor.lastrowid)
            except sqlite3.IntegrityError as exc:
                if idempotency_key and "UNIQUE constraint failed: task_events.idempotency_key" in str(exc):
                    row = conn.execute(
                        "SELECT id FROM task_events WHERE idempotency_key = ?", (idempotency_key,)
                    ).fetchone()
                    if row is not None:
                        return int(row["id"])
                raise
        finally:
            conn.close()

    return _run_with_busy_retry(op)


def get_task_events(
    task_id=None,
    event_type=None,
    source_agent=None,
    unacknowledged_only=False,
    limit=100,
) -> list[dict[str, Any]]:
    def op():
        conn = _connect()
        try:
            clauses = ["1=1"]
            params: list[Any] = []
            if task_id is not None:
                clauses.append("task_id = ?")
                params.append(task_id)
            if event_type is not None:
                clauses.append("event_type = ?")
                params.append(event_type)
            if source_agent is not None:
                clauses.append("source_agent = ?")
                params.append(source_agent)
            if unacknowledged_only:
                clauses.append("acknowledged_at IS NULL")
            params.append(limit)
            rows = conn.execute(
                f"SELECT * FROM task_events WHERE {' AND '.join(clauses)} ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
            return _rows_to_dicts(rows)
        finally:
            conn.close()

    return _run_with_busy_retry(op)


def claim_pending_events(bobby_session_id, limit=20) -> list[dict[str, Any]]:
    def op():
        conn = _connect()
        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                rows = conn.execute(
                    """
                    SELECT id FROM task_events
                    WHERE acknowledged_at IS NULL
                      AND (
                        claimed_by IS NULL OR
                        julianday('now') - julianday(claimed_at) > 5.0/(24*60)
                      )
                    ORDER BY created_at ASC, id ASC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                ids = [row["id"] for row in rows]
                if not ids:
                    return []

                placeholders = ",".join("?" for _ in ids)
                conn.execute(
                    f"""
                    UPDATE task_events
                    SET claimed_by = ?,
                        claimed_at = strftime('%Y-%m-%dT%H:%M:%f','now'),
                        delivery_attempts = delivery_attempts + 1
                    WHERE id IN ({placeholders})
                    """,
                    (bobby_session_id, *ids),
                )

                claimed_rows = conn.execute(
                    f"SELECT * FROM task_events WHERE id IN ({placeholders}) ORDER BY created_at ASC, id ASC",
                    ids,
                ).fetchall()
                return _rows_to_dicts(claimed_rows)
        finally:
            conn.close()

    return _run_with_busy_retry(op)


def peek_pending_events(limit=20) -> list[dict[str, Any]]:
    def op():
        conn = _connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM task_events
                WHERE acknowledged_at IS NULL
                  AND (
                    claimed_by IS NULL OR
                    julianday('now') - julianday(claimed_at) > 5.0/(24*60)
                  )
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return _rows_to_dicts(rows)
        finally:
            conn.close()

    return _run_with_busy_retry(op)


def acknowledge_event(event_id, bobby_session_id) -> None:
    def op():
        conn = _connect()
        try:
            with conn:
                row = conn.execute(
                    "SELECT claimed_by FROM task_events WHERE id = ?", (event_id,)
                ).fetchone()
                if row is None:
                    raise ValueError(f"Event {event_id} not found")
                if row["claimed_by"] != bobby_session_id:
                    raise UnauthorizedError(
                        f"Event {event_id} is claimed by {row['claimed_by']}, not {bobby_session_id}"
                    )
                conn.execute(
                    "UPDATE task_events SET acknowledged_at = strftime('%Y-%m-%dT%H:%M:%f','now') WHERE id = ?",
                    (event_id,),
                )
        finally:
            conn.close()

    _run_with_busy_retry(op)


# Monitoring

def get_stale_tasks(hours=1) -> list[dict[str, Any]]:
    def op():
        conn = _connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM tasks
                WHERE status NOT IN ('done', 'failed')
                  AND julianday('now') - julianday(updated_at) > ?/24.0
                ORDER BY updated_at ASC
                """,
                (hours,),
            ).fetchall()
            return _rows_to_dicts(rows)
        finally:
            conn.close()

    return _run_with_busy_retry(op)


def get_admission_status() -> dict[str, Any]:
    def op():
        conn = _connect()
        try:
            active_sessions = conn.execute(
                f"SELECT COUNT(*) AS c FROM tasks WHERE status IN ({','.join('?' for _ in ACTIVE_STATUSES)})",
                ACTIVE_STATUSES,
            ).fetchone()["c"]
            priority_rows = conn.execute(
                f"""
                SELECT priority, COUNT(*) AS c FROM tasks
                WHERE status IN ({','.join('?' for _ in ACTIVE_STATUSES)})
                GROUP BY priority
                """,
                ACTIVE_STATUSES,
            ).fetchall()
            project_rows = conn.execute(
                f"""
                SELECT COALESCE(project, '__none__') AS project_name, COUNT(*) AS c FROM tasks
                WHERE status IN ({','.join('?' for _ in ACTIVE_STATUSES)})
                GROUP BY COALESCE(project, '__none__')
                """,
                ACTIVE_STATUSES,
            ).fetchall()
            return {
                "active_sessions": int(active_sessions),
                "per_priority": {str(row["priority"]): int(row["c"]) for row in priority_rows},
                "per_project": {row["project_name"]: int(row["c"]) for row in project_rows},
            }
        finally:
            conn.close()

    return _run_with_busy_retry(op)


# Admission control

def can_start_task(task_id) -> tuple[bool, str]:
    def op():
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                return False, "task not found"
            return _can_start_task_with_conn(conn, dict(row))
        finally:
            conn.close()

    return _run_with_busy_retry(op)


def select_next_task() -> dict[str, Any] | None:
    def op():
        conn = _connect()
        try:
            starvation_hours = _get_scheduler_int(conn, "starvation_hours", 4)
            rows = conn.execute(
                f"""
                SELECT
                    t.*,
                    MAX(
                        1,
                        t.priority - CAST(
                            ((julianday('now') - julianday(t.created_at)) * 24.0) / ? AS INTEGER
                        )
                    ) AS effective_priority,
                    ((julianday('now') - julianday(t.created_at)) * 24.0) AS queue_hours
                FROM tasks t
                WHERE t.status IN ({','.join('?' for _ in SELECTABLE_STATUSES)})
                ORDER BY effective_priority ASC, queue_hours DESC, t.created_at ASC
                LIMIT 1
                """,
                (starvation_hours, *SELECTABLE_STATUSES),
            ).fetchall()
            if not rows:
                return None
            return _row_to_dict(rows[0])
        finally:
            conn.close()

    return _run_with_busy_retry(op)


def start_task(task_id, expected_version) -> dict[str, Any]:
    def op():
        conn = _connect()
        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT * FROM tasks WHERE id = ? AND version = ?", (task_id, expected_version)
                ).fetchone()
                if row is None:
                    raise ConcurrentModificationError(
                        f"Task {task_id} was modified concurrently or does not exist"
                    )
                can, reason = _can_start_task_with_conn(conn, dict(row))
                if not can:
                    raise RuntimeError(reason)
                try:
                    updated = conn.execute(
                        """
                        UPDATE tasks
                        SET status = 'building',
                            started_at = COALESCE(started_at, strftime('%Y-%m-%dT%H:%M:%f','now'))
                        WHERE id = ? AND version = ?
                        """,
                        (task_id, expected_version),
                    )
                    if updated.rowcount == 0:
                        raise ConcurrentModificationError(
                            f"Task {task_id} was modified concurrently or does not exist"
                        )
                except sqlite3.IntegrityError as exc:
                    if "Invalid task state transition" in str(exc):
                        raise InvalidTransitionError(str(exc)) from exc
                    raise

                out = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
                return _row_to_dict(out)
        finally:
            conn.close()

    return _run_with_busy_retry(op)


# Policy gates

def create_policy_check(task_id, check_type, gate) -> int:
    def op():
        conn = _connect()
        try:
            with conn:
                cursor = conn.execute(
                    "INSERT INTO policy_checks (task_id, check_type, gate) VALUES (?, ?, ?)",
                    (task_id, check_type, gate),
                )
                return int(cursor.lastrowid)
        finally:
            conn.close()

    return _run_with_busy_retry(op)


def check_policy_gate(task_id, gate) -> bool:
    def op():
        conn = _connect()
        try:
            row = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN status IN ('pending', 'failed') THEN 1 ELSE 0 END) AS blocked,
                    COUNT(*) AS total
                FROM policy_checks
                WHERE task_id = ? AND gate = ?
                """,
                (task_id, gate),
            ).fetchone()
            total = int(row["total"] or 0)
            blocked = int(row["blocked"] or 0)
            if total == 0:
                return True
            return blocked == 0
        finally:
            conn.close()

    return _run_with_busy_retry(op)


def waive_policy_check(check_id, reason, waived_by) -> None:
    def op():
        conn = _connect()
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE policy_checks
                    SET status = 'waived',
                        checked_by = ?,
                        checked_at = strftime('%Y-%m-%dT%H:%M:%f','now'),
                        waive_reason = ?
                    WHERE id = ?
                    """,
                    (waived_by, reason, check_id),
                )
        finally:
            conn.close()

    _run_with_busy_retry(op)


def enforce_gate(task_id, gate) -> None:
    if not check_policy_gate(task_id, gate):
        raise GateBlockedError(f"Gate {gate} is blocked for task {task_id}")


# Iteration enforcement

def apply_feedback(task_id, expected_version, feedback_payload) -> dict[str, Any]:
    _validate_payload("feedback", feedback_payload)

    def op():
        conn = _connect()
        try:
            with conn:
                row = conn.execute(
                    "SELECT * FROM tasks WHERE id = ? AND version = ?", (task_id, expected_version)
                ).fetchone()
                if row is None:
                    raise ConcurrentModificationError(
                        f"Task {task_id} was modified concurrently or does not exist"
                    )

                task = dict(row)
                next_iteration = int(task["iteration"]) + 1
                max_iterations = int(task["max_iterations"])
                should_escalate = next_iteration >= max_iterations
                new_status = "escalated" if should_escalate else "feedback"
                escalation_reason = "max_iterations_reached" if should_escalate else None
                try:
                    cursor = conn.execute(
                        """
                        UPDATE tasks
                        SET iteration = ?,
                            status = ?,
                            escalation_reason = COALESCE(?, escalation_reason),
                            completed_at = CASE
                                WHEN ? = 'escalated' THEN strftime('%Y-%m-%dT%H:%M:%f','now')
                                ELSE completed_at
                            END
                        WHERE id = ? AND version = ?
                        """,
                        (next_iteration, new_status, escalation_reason, new_status, task_id, expected_version),
                    )
                    if cursor.rowcount == 0:
                        raise ConcurrentModificationError(
                            f"Task {task_id} was modified concurrently or does not exist"
                        )
                except sqlite3.IntegrityError as exc:
                    if "Invalid task state transition" in str(exc):
                        raise InvalidTransitionError(str(exc)) from exc
                    raise

                out = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            out_dict = _row_to_dict(out)
            if out_dict and out_dict["status"] == "escalated":
                write_event(
                    task_id,
                    "escalated",
                    "bobby",
                    {
                        "reason": "max_iterations_reached",
                        "attempted_fixes": feedback_payload.get("corrections", []),
                    },
                )
            return out_dict
        finally:
            conn.close()

    return _run_with_busy_retry(op)


# Agent status

def quarantine_agent(agent_id, reason) -> None:
    def op():
        conn = _connect()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO agent_status (agent_id, status, reason, quarantined_at, updated_at)
                    VALUES (?, 'quarantined', ?, strftime('%Y-%m-%dT%H:%M:%f','now'), strftime('%Y-%m-%dT%H:%M:%f','now'))
                    ON CONFLICT(agent_id) DO UPDATE SET
                        status='quarantined',
                        reason=excluded.reason,
                        quarantined_at=excluded.quarantined_at,
                        updated_at=excluded.updated_at
                    """,
                    (agent_id, reason),
                )
        finally:
            conn.close()

    _run_with_busy_retry(op)


def unquarantine_agent(agent_id) -> None:
    def op():
        conn = _connect()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO agent_status (agent_id, status, reason, quarantined_at, updated_at)
                    VALUES (?, 'active', NULL, NULL, strftime('%Y-%m-%dT%H:%M:%f','now'))
                    ON CONFLICT(agent_id) DO UPDATE SET
                        status='active',
                        reason=NULL,
                        quarantined_at=NULL,
                        updated_at=strftime('%Y-%m-%dT%H:%M:%f','now')
                    """,
                    (agent_id,),
                )
        finally:
            conn.close()

    _run_with_busy_retry(op)


def get_agent_status(agent_id=None) -> dict[str, Any] | list[dict[str, Any]]:
    def op():
        conn = _connect()
        try:
            if agent_id is not None:
                row = conn.execute("SELECT * FROM agent_status WHERE agent_id = ?", (agent_id,)).fetchone()
                return _row_to_dict(row)
            rows = conn.execute("SELECT * FROM agent_status ORDER BY agent_id ASC").fetchall()
            return _rows_to_dicts(rows)
        finally:
            conn.close()

    return _run_with_busy_retry(op)


def circuit_breaker_check() -> list[dict[str, Any]]:
    def op():
        conn = _connect()
        try:
            rows = conn.execute(
                """
                SELECT
                    assigned_agent AS agent_id,
                    COUNT(*) AS total_tasks,
                    SUM(CASE WHEN status IN ('failed', 'escalated') THEN 1 ELSE 0 END) AS failed_tasks,
                    CAST(SUM(CASE WHEN status IN ('failed', 'escalated') THEN 1 ELSE 0 END) AS REAL) / COUNT(*) AS failure_rate
                FROM tasks
                WHERE assigned_agent IS NOT NULL
                  AND julianday('now') - julianday(updated_at) <= 7.0
                  AND status IN ('done', 'failed', 'escalated')
                GROUP BY assigned_agent
                HAVING failure_rate > 0.5
                ORDER BY failure_rate DESC, total_tasks DESC
                """
            ).fetchall()
            return _rows_to_dicts(rows)
        finally:
            conn.close()

    return _run_with_busy_retry(op)


# CLI

def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def _parse_payload(payload_json: str) -> dict[str, Any]:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError as exc:
        raise PayloadValidationError(f"Invalid JSON payload: {exc}") from exc
    if not isinstance(payload, dict):
        raise PayloadValidationError("Payload JSON must decode to an object")
    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Specialist agent orchestration DB")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-task")
    p.add_argument("id")
    p.add_argument("title")
    p.add_argument("--project")
    p.add_argument("--priority", type=int, default=3)
    p.add_argument("--agent")
    p.add_argument("--confidence")
    p.add_argument("--contract")
    p.add_argument("--context-version")

    p = sub.add_parser("get-task")
    p.add_argument("id")

    p = sub.add_parser("list-tasks")
    p.add_argument("--project")
    p.add_argument("--status")
    p.add_argument("--agent")
    p.add_argument("--limit", type=int, default=50)

    p = sub.add_parser("transition")
    p.add_argument("id")
    p.add_argument("new_status")
    p.add_argument("--version", type=int)

    p = sub.add_parser("write-event")
    p.add_argument("task_id")
    p.add_argument("type")
    p.add_argument("source")
    p.add_argument("payload_json")
    p.add_argument("--idempotency-key")
    p.add_argument("--target")

    p = sub.add_parser("task-events")
    p.add_argument("--task")
    p.add_argument("--type")
    p.add_argument("--source")
    p.add_argument("--unacked", action="store_true")

    p = sub.add_parser("pending-events")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--peek", action="store_true")
    g.add_argument("--claim", action="store_true")
    p.add_argument("--session-id")

    p = sub.add_parser("acknowledge")
    p.add_argument("event_id", type=int)
    p.add_argument("session_id")

    p = sub.add_parser("stale-tasks")
    p.add_argument("--hours", type=float, default=1)

    sub.add_parser("admission-status")

    p = sub.add_parser("can-start")
    p.add_argument("task_id")

    sub.add_parser("select-next")

    p = sub.add_parser("start-task")
    p.add_argument("task_id")
    p.add_argument("--version", type=int, required=True)

    p = sub.add_parser("create-check")
    p.add_argument("task_id")
    p.add_argument("type")
    p.add_argument("gate")

    p = sub.add_parser("check-gate")
    p.add_argument("task_id")
    p.add_argument("gate")

    p = sub.add_parser("waive-check")
    p.add_argument("check_id", type=int)
    p.add_argument("reason")
    p.add_argument("waived_by")

    p = sub.add_parser("enforce-gate")
    p.add_argument("task_id")
    p.add_argument("gate")

    p = sub.add_parser("apply-feedback")
    p.add_argument("task_id")
    p.add_argument("payload_json")
    p.add_argument("--version", type=int, required=True)

    p = sub.add_parser("quarantine")
    p.add_argument("agent_id")
    p.add_argument("reason")

    p = sub.add_parser("unquarantine")
    p.add_argument("agent_id")

    p = sub.add_parser("agent-status")
    p.add_argument("agent_id", nargs="?")

    sub.add_parser("circuit-breaker-check")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "create-task":
            out = create_task(
                args.id,
                args.title,
                project=args.project,
                priority=args.priority,
                assigned_agent=args.agent,
                routing_confidence=args.confidence,
                contract_path=args.contract,
                context_version=args.context_version,
            )
            print(f"Created task {out['id']} (status={out['status']}, version={out['version']})")
            return 0

        if args.command == "get-task":
            _print_json(get_task(args.id))
            return 0

        if args.command == "list-tasks":
            _print_json(
                list_tasks(
                    project=args.project,
                    status=args.status,
                    agent=args.agent,
                    limit=args.limit,
                )
            )
            return 0

        if args.command == "transition":
            version = args.version
            if version is None:
                task = get_task(args.id)
                if task is None:
                    raise ValueError(f"Task {args.id} not found")
                version = int(task["version"])
            out = transition_task(args.id, args.new_status, version)
            print(f"Transitioned {args.id} to {out['status']} (version={out['version']})")
            return 0

        if args.command == "write-event":
            payload = _parse_payload(args.payload_json)
            event_id = write_event(
                args.task_id,
                args.type,
                args.source,
                payload,
                target_agent=args.target,
                idempotency_key=args.idempotency_key,
            )
            print(f"Wrote event {event_id}")
            return 0

        if args.command == "task-events":
            _print_json(
                get_task_events(
                    task_id=args.task,
                    event_type=args.type,
                    source_agent=args.source,
                    unacknowledged_only=args.unacked,
                )
            )
            return 0

        if args.command == "pending-events":
            if args.claim and not args.session_id:
                raise PayloadValidationError("--session-id is required with --claim")
            if args.peek:
                _print_json(peek_pending_events())
            else:
                _print_json(claim_pending_events(args.session_id))
            return 0

        if args.command == "acknowledge":
            acknowledge_event(args.event_id, args.session_id)
            print(f"Acknowledged event {args.event_id}")
            return 0

        if args.command == "stale-tasks":
            _print_json(get_stale_tasks(hours=args.hours))
            return 0

        if args.command == "admission-status":
            _print_json(get_admission_status())
            return 0

        if args.command == "can-start":
            can, reason = can_start_task(args.task_id)
            _print_json({"can_start": can, "reason": reason})
            return 0

        if args.command == "select-next":
            _print_json(select_next_task())
            return 0

        if args.command == "start-task":
            out = start_task(args.task_id, args.version)
            print(f"Started task {out['id']} (status={out['status']}, version={out['version']})")
            return 0

        if args.command == "create-check":
            check_id = create_policy_check(args.task_id, args.type, args.gate)
            print(f"Created policy check {check_id}")
            return 0

        if args.command == "check-gate":
            _print_json({"passed": check_policy_gate(args.task_id, args.gate)})
            return 0

        if args.command == "waive-check":
            waive_policy_check(args.check_id, args.reason, args.waived_by)
            print(f"Waived policy check {args.check_id}")
            return 0

        if args.command == "enforce-gate":
            enforce_gate(args.task_id, args.gate)
            print(f"Gate {args.gate} passed for task {args.task_id}")
            return 0

        if args.command == "apply-feedback":
            payload = _parse_payload(args.payload_json)
            out = apply_feedback(args.task_id, args.version, payload)
            print(f"Applied feedback to {out['id']} (status={out['status']}, iteration={out['iteration']})")
            return 0

        if args.command == "quarantine":
            quarantine_agent(args.agent_id, args.reason)
            print(f"Quarantined {args.agent_id}")
            return 0

        if args.command == "unquarantine":
            unquarantine_agent(args.agent_id)
            print(f"Unquarantined {args.agent_id}")
            return 0

        if args.command == "agent-status":
            _print_json(get_agent_status(args.agent_id))
            return 0

        if args.command == "circuit-breaker-check":
            _print_json(circuit_breaker_check())
            return 0

        raise ValueError(f"Unknown command: {args.command}")

    except (PayloadValidationError, json.JSONDecodeError) as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 2
    except argparse.ArgumentError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
