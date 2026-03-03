# HverdagsAI Agent Template (Private)

Reusable template for bootstrapping HverdagsAI work-agent workspaces with strict safety defaults.

## What this template provides
- Work-only baseline files (`SOUL.md`, `USER.md`, `AGENTS.md`, `MEMORY.md`, `HEARTBEAT.md`)
- Reproducible bootstrap + verification scripts
- Hybrid memory stack (daily markdown + typed SQLite + reconciliation)
- Safety checks (placeholder validation + secret scan + human input policy checks)

No personal-assistant flows are included.

## One human step
Fill one file:
- `~/.openclaw/workspace/HUMAN_INPUTS.yaml`

Everything else is automated by agent scripts.

## Quick start

```bash
# Prerequisites
brew install openclaw gh jq
openclaw init

# Clone this private template repo
cd ~/repos
git clone git@github.com:<your-org>/hverdagsai-agent-template.git
cd hverdagsai-agent-template

# 1) Create the single human-input document
python3 scripts/bootstrap_workspace.py --workspace ~/.openclaw/workspace --init-inputs

# 2) Fill ~/.openclaw/workspace/HUMAN_INPUTS.yaml
#    (non-secrets + secret refs only, see docs/HUMAN_INPUTS_GUIDE.md)

# 3) Agent runs bootstrap from the file
python3 scripts/bootstrap_workspace.py \
  --workspace ~/.openclaw/workspace \
  --inputs ~/.openclaw/workspace/HUMAN_INPUTS.yaml

# 4) Verify
python3 scripts/verify_workspace.py --workspace ~/.openclaw/workspace --check-inputs
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
- `HUMAN_INPUTS.yaml` (human-owned)
- `memory/reference/work-context.md`
- `scripts/` (`human_inputs.py`, `memory_db.py`, `memory_query.py`, `memory_reconcile.py`, `graph_summary.py`, `secret_scan.py`, `verify_workspace.py`)

## Upgrade existing workspace

```bash
python3 scripts/bootstrap_workspace.py \
  --workspace ~/.openclaw/workspace \
  --inputs ~/.openclaw/workspace/HUMAN_INPUTS.yaml \
  --upgrade

python3 scripts/verify_workspace.py --workspace ~/.openclaw/workspace --check-inputs
```

`--upgrade` refreshes template-controlled files and scripts while preserving daily memory files.

Detailed rollout and rollback steps: `docs/AGENT_UPGRADE_PLAYBOOK.md`.

## Security rules
- Never store secrets in repo files.
- Keep this repo private.
- In `HUMAN_INPUTS.yaml`, use only secret refs: `op://...` or `keychain:...`.
- Run `python3 scripts/secret_scan.py --path .` before committing or pushing.

## Validation gates
- `python3 scripts/verify_workspace.py --workspace <workspace> --check-inputs` passes
- `python3 <workspace>/scripts/memory_reconcile.py --days 7` passes
- Gateway status check is reachable (recommended)
