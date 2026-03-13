# Orchestration Reference

## Database CLI

All orchestration state lives in SQLite at `~/.openclaw/orchestration/state.db`.

### Task Management

```bash
# Create a task
python3 scripts/orchestration_db.py create-task {id} "title" \
    --project {project} --priority {1-4} --agent {specialist} \
    --confidence {high|medium|low}

# Transition task status
python3 scripts/orchestration_db.py transition {task_id} {new_status}

# List tasks
python3 scripts/orchestration_db.py list-tasks
python3 scripts/orchestration_db.py list-tasks --status queued
python3 scripts/orchestration_db.py list-tasks --agent forge

# Start a task
python3 scripts/orchestration_db.py start-task {task_id}

# Select next task (priority + starvation)
python3 scripts/orchestration_db.py select-next
```

### Event Processing

```bash
# Peek at pending events
python3 scripts/orchestration_db.py pending-events --peek

# Claim events for processing
python3 scripts/orchestration_db.py pending-events --claim --session-id {sid}

# Write an event
python3 scripts/orchestration_db.py write-event {task_id} {type} {agent} '{json}'

# Acknowledge an event
python3 scripts/orchestration_db.py acknowledge {event_id} {session_id}
```

### Admission Control

```bash
# Check current capacity
python3 scripts/orchestration_db.py admission-status

# Check if a task can start
python3 scripts/orchestration_db.py can-start {task_id}

# Circuit breaker check
python3 scripts/orchestration_db.py circuit-breaker-check {agent}
```

### Stale Task Detection

```bash
# Find tasks stuck in active states too long
python3 scripts/orchestration_db.py stale-tasks
```

## Task States

```
queued → triaging → planned → building → reviewing → done
                                  ↓          ↓
                               failed    feedback → building
                                  ↓
                              escalated → queued/planned
```

## Event Types

| Event | Source | Meaning |
|-------|--------|---------|
| `completed` | Specialist | Task done, result in outbox |
| `context_missing` | Specialist | Needs info not in context |
| `assumption_invalidated` | Specialist | Plan step infeasible |
| `review_failed` | Sherlock | Code review rejected |
| `escalated` | Any | Beyond specialist scope |
| `feedback` | Orchestrator | Revision instructions |
| `instinct_extracted` | Orchestrator | Learning captured |

## Scripts

| Script | Purpose |
|--------|---------|
| `orchestration_db.py` | Task and event management |
| `instinct_extract.py` | Extract learnings from completed tasks |
| `shared_context_gen.py` | Regenerate shared context files |
| `validate_handoff.py` | Validate handoff document format |
| `secret_scan.py` | Scan for leaked secrets in output |

## Admission Control Rules

- Max 6 concurrent specialist sessions globally
- Max 3 sessions per project
- P1 tasks can preempt P3/P4 (graceful)
- Starvation prevention: +1 priority every 4h in queue
