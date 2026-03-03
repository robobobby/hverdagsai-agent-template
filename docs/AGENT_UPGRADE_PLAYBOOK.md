# Agent Upgrade Playbook

Use this when an existing workspace is upgraded from this template.

## Objective
Upgrade operating files and memory scripts safely without losing context.

## Procedure

1. Create a timestamped backup:
```bash
BACKUP_DIR=~/.openclaw/workspace.backup.$(date +%Y%m%d-%H%M%S)
cp -R ~/.openclaw/workspace "$BACKUP_DIR"
echo "$BACKUP_DIR"
```

2. Run bootstrap in upgrade mode:
```bash
python3 scripts/bootstrap_workspace.py \
  --workspace ~/.openclaw/workspace \
  --agent-name "<Agent Name>" \
  --human-name "<Human Name>" \
  --company "HverdagsAI" \
  --timezone "Europe/Copenhagen" \
  --upgrade
```

3. Run verification:
```bash
python3 scripts/verify_workspace.py --workspace ~/.openclaw/workspace
```

4. Run memory health checks in the upgraded workspace:
```bash
python3 ~/.openclaw/workspace/scripts/memory_query.py health
python3 ~/.openclaw/workspace/scripts/memory_reconcile.py --days 7
```

5. Smoke-test expected behavior:
- Summarize SOUL.md + USER.md + AGENTS.md in 10 bullets.
- Explain dual-write memory protocol.
- Explain when to ask for approval.
- Show how pending-followups prevents dropped commitments.

6. If the workspace is a git repo, review changed files before committing:
```bash
git -C ~/.openclaw/workspace status --short
```

## Rollback
If anything fails:
```bash
mv ~/.openclaw/workspace ~/.openclaw/workspace.failed.$(date +%Y%m%d-%H%M%S)
mv "$BACKUP_DIR" ~/.openclaw/workspace
```
