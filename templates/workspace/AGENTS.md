# AGENTS.md — Workspace Rules

## Session start
1. Read SOUL.md
2. Read USER.md
3. Read today + yesterday `memory/YYYY-MM-DD.md`
4. Read MEMORY.md

## Memory protocol
- Dual-write significant facts:
  - narrative in daily file
  - typed entry in SQLite via `memory_query.py`
- Reconcile regularly with `memory_reconcile.py`

## Work protocol
- Every task tracked in the task system.
- Prefer branch + PR flow for code changes.
- No destructive external actions without explicit approval.

## Security
- Never store secrets in files.
- Never include personal non-work data.
- Run secret scan before pushing.
