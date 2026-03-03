# HverdagsAI Agent Template (Private)

Reusable template for bootstrapping HverdagsAI work-agent workspaces with strict safety defaults.

## What this template provides
- Work-only baseline files (`SOUL.md`, `USER.md`, `AGENTS.md`, `MEMORY.md`, `HEARTBEAT.md`)
- Reproducible bootstrap + verification scripts
- Hybrid memory stack (daily markdown + typed SQLite + reconciliation)
- Safety checks (placeholder validation and secret scan)

No personal-assistant flows are included.

## Quick start

```bash
# Prerequisites
brew install openclaw gh jq
openclaw init

# Clone this private template repo
cd ~/repos
git clone git@github.com:<your-org>/hverdagsai-agent-template.git

# Bootstrap a workspace
python3 hverdagsai-agent-template/scripts/bootstrap_workspace.py \
  --workspace ~/.openclaw/workspace \
  --agent-name "<Agent Name>" \
  --human-name "<Human Name>" \
  --company "<Company>" \
  --timezone "<IANA Timezone>"

# Verify workspace integrity
python3 hverdagsai-agent-template/scripts/verify_workspace.py --workspace ~/.openclaw/workspace
```

## Installed into workspace
- `AGENTS.md`
- `SOUL.md`
- `USER.md`
- `MEMORY.md`
- `HEARTBEAT.md`
- `BOOTSTRAP.md`
- `TOOLS.md`
- `pending-followups.md`
- `heartbeat-state.json`
- `memory/reference/work-context.md`
- `scripts/` (`memory_db.py`, `memory_query.py`, `memory_reconcile.py`, `graph_summary.py`, `secret_scan.py`, `verify_workspace.py`)

## Required manual follow-up
1. Configure GitHub identity and authentication (`gh auth login`, SSH key).
2. Fill `USER.md` for the actual owner/operator.
3. Fill `memory/reference/work-context.md` with real repos, standards, and escalation paths.
4. Add maintenance cron jobs from `examples/cron-examples.json`.
5. Run one orientation chat and confirm behavior against `AGENTS.md`.

## Upgrade existing workspace

```bash
python3 scripts/bootstrap_workspace.py \
  --workspace ~/.openclaw/workspace \
  --agent-name "<Agent Name>" \
  --human-name "<Human Name>" \
  --company "<Company>" \
  --timezone "<IANA Timezone>" \
  --upgrade

python3 scripts/verify_workspace.py --workspace ~/.openclaw/workspace
```

`--upgrade` refreshes template-controlled files and scripts while preserving daily memory files.

Detailed rollout and rollback steps: `docs/AGENT_UPGRADE_PLAYBOOK.md`.

## Security rules
- Never store secrets in repo files.
- Keep this repo private.
- Run `python3 scripts/secret_scan.py --path .` before committing or pushing.

## Validation gates
- `python3 scripts/verify_workspace.py --workspace <workspace>` passes
- `python3 <workspace>/scripts/memory_reconcile.py --days 7` passes
- Gateway status check is reachable (recommended)
