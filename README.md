# HverdagsAI Agent Template

Reusable template for bootstrapping HverdagsAI work-agent workspaces with strict safety defaults.

## What's in v2

**New: Specialist Sub-Agent System**
- **Blueprint** (planner), **Forge** (builder), **Scout** (researcher), **Sherlock** (reviewer), **Pixel** (designer)
- Orchestration database (SQLite) with state machine, admission control, loop guards
- Task contracts and handoff documents for structured specialist communication
- Instinct extraction for continuous learning from completed tasks
- Setup script for one-command specialist bootstrapping

**Carried from v1:**
- Work-only baseline files (`SOUL.md`, `USER.md`, `AGENTS.md`, `MEMORY.md`, `HEARTBEAT.md`)
- Reproducible bootstrap + verification scripts
- Hybrid memory stack (daily markdown + typed SQLite + reconciliation)
- Safety checks (placeholder validation + secret scan + human input policy checks)

## Quick Start

```bash
# Prerequisites
brew install openclaw gh jq
openclaw init

# Clone this template
cd ~/repos
git clone git@github.com:robobobby/hverdagsai-agent-template.git
cd hverdagsai-agent-template

# 1) Bootstrap workspace
python3 scripts/bootstrap_workspace.py --workspace ~/.openclaw/workspace --init-inputs

# 2) Fill HUMAN_INPUTS.yaml (see docs/HUMAN_INPUTS_GUIDE.md)

# 3) Run bootstrap
python3 scripts/bootstrap_workspace.py \
  --workspace ~/.openclaw/workspace \
  --inputs ~/.openclaw/workspace/HUMAN_INPUTS.yaml

# 4) Set up specialist agents
./scripts/setup_specialists.sh ~/.openclaw

# 5) Add specialists to openclaw.json (see docs/SPECIALISTS_GUIDE.md)

# 6) Verify
openclaw doctor
python3 scripts/verify_workspace.py --workspace ~/.openclaw/workspace --check-inputs
```

## Specialist System

See `docs/SPECIALISTS_GUIDE.md` for the full guide.

| Specialist | Role | What They Do |
|-----------|------|-------------|
| Blueprint | Planner | Task decomposition, architecture, risk analysis |
| Forge | Builder | Code implementation, testing, deployment |
| Scout | Researcher | Deep research, competitive analysis, fact verification |
| Sherlock | Reviewer | Code review, security audit, adversarial analysis |
| Pixel | Designer | UI/UX design, frontend implementation |

## Directory Structure

```
├── specialists/          # Specialist SOUL.md + AGENTS.md templates
│   ├── blueprint/
│   ├── forge/
│   ├── scout/
│   ├── sherlock/
│   └── pixel/
├── schemas/              # Database schemas
│   └── orchestration.sql
├── scripts/              # Bootstrap and orchestration scripts
│   ├── setup_specialists.sh
│   ├── orchestration_db.py
│   ├── instinct_extract.py
│   └── ...
├── templates/            # Task contract and handoff templates
│   ├── task-contract.md
│   └── handoff.md
├── docs/                 # Documentation
│   ├── SPECIALISTS_GUIDE.md
│   ├── ORCHESTRATION_REFERENCE.md
│   └── UPGRADE.md
└── examples/             # Example configs and task contracts
```

## Upgrading from v1

See `docs/UPGRADE.md` for step-by-step migration instructions.

## Security Rules
- Never store secrets in repo files
- In `HUMAN_INPUTS.yaml`, use only secret refs: `op://...` or `keychain:...`
- Run `python3 scripts/secret_scan.py --path .` before committing

## Docs
- `docs/SPECIALISTS_GUIDE.md` - How specialists work, how to add new ones
- `docs/ORCHESTRATION_REFERENCE.md` - Database CLI, events, admission control
- `docs/UPGRADE.md` - Migrating from v1 to v2
- `docs/HUMAN_INPUTS_GUIDE.md` - Filling in human inputs
- `docs/TOOLS_GUIDE.md` - Tool configuration
- `docs/AGENT_UPGRADE_PLAYBOOK.md` - Upgrade playbook
