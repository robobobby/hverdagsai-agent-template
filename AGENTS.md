# AGENTS.md — Template Repo Rules

## Purpose
This repo defines the baseline operating system for HverdagsAI work agents.

## Constraints
- Work-only context. No personal assistant flows.
- No secrets in files.
- No direct production mutations by agents.
- Branch + PR workflow required.

## Setup contract
After bootstrap, every agent workspace must contain:
- SOUL.md, USER.md, MEMORY.md, HEARTBEAT.md, AGENTS.md
- memory/ structure
- memory DB scripts
- verification pass from `scripts/verify_workspace.py`

## Memory contract
- Dual-write: daily markdown + typed SQLite entries
- Reconciliation must run regularly
- Team-critical decisions must also go to shared context repo

## Safety contract
- If uncertain on destructive actions, ask human first
- Never commit customer personal data
- Never send external communications without explicit permission
