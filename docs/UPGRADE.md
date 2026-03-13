# Upgrading to Template v2

## What's New in v2

- **Specialist sub-agent system**: Blueprint, Scotty, Columbo, Sherlock, Pixel
- **Orchestration database**: SQLite-based task tracking with state machine
- **Task contracts**: Structured input format for specialist tasks
- **Handoff documents**: Structured output format between specialists
- **Event system**: Specialists communicate via typed events
- **Instinct extraction**: Learning from completed tasks
- **Shared context**: Layered context system for specialists

## Migration Steps

### 1. Back Up Current Config
```bash
cp ~/.openclaw/openclaw.json ~/.openclaw/openclaw.json.bak
```

### 2. Run Setup Script
```bash
./scripts/setup_specialists.sh ~/.openclaw
```

This creates:
- Specialist workspaces with SOUL.md, AGENTS.md, directory structure
- Orchestration database at `~/.openclaw/orchestration/state.db`
- Templates in `~/.openclaw/workspace/templates/`

### 3. Update openclaw.json

Add each specialist to `agents.list`. See `docs/SPECIALISTS_GUIDE.md` for the JSON format.

Add specialist IDs to your main agent's `subagents.allowAgents`.

### 4. Populate Shared Context

Create shared context files that specialists will read:
```bash
mkdir -p ~/.openclaw/shared-context
# Create USER.md, PROJECTS.md, STANDARDS.md, FACTS.md
```

### 5. Verify
```bash
openclaw doctor
```

## Rollback

To revert to v1:
1. Restore `openclaw.json.bak`
2. Specialist workspaces can remain (they're harmless if not referenced)
3. Orchestration DB can be deleted: `rm ~/.openclaw/orchestration/state.db`
