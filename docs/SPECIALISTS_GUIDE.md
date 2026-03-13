# Specialist Agent Guide

## Overview

The specialist system splits your main agent's workload across purpose-built sub-agents. Each specialist has a defined role, its own workspace, memory, and a strict IO contract.

## Specialists

| Name | Role | Default Model | What They Do |
|------|------|---------------|--------------|
| **Blueprint** | Planner | Opus | Breaks tasks into dependency-ordered plans with risk analysis |
| **Forge** | Builder | Opus | Writes code, runs tests, deploys. Follows Blueprint plans |
| **Scout** | Researcher | Opus | Deep research with sourced claims. Never fabricates |
| **Sherlock** | Reviewer | GPT-5.4 | Code review, security audit. Adversarial by nature |
| **Pixel** | Designer | Opus | UI/UX design, frontend implementation, accessibility |

## Architecture

```
Human ←→ Orchestrator (main agent)
              ↓
    ┌─────────┼─────────┐
    ↓         ↓         ↓
Blueprint → Forge → Sherlock
    ↓                   ↓
  Scout            Pixel
```

The orchestrator:
1. Receives tasks from the human
2. Routes to the right specialist via task contracts
3. Monitors events (completed, context_missing, escalated)
4. Reviews output and surfaces results

## Workspace Layout

Each specialist workspace follows this structure:

```
workspace-{name}/
├── SOUL.md          # Identity and behavior
├── AGENTS.md        # IO contract and protocols
├── IDENTITY.md      # Quick metadata
├── inbox/           # Task contracts land here
├── outbox/          # Results go here
├── memory/
│   ├── runbooks.md  # How to handle recurring tasks
│   └── lessons.md   # Accumulated learnings
├── shared/          # Shared context (read-only for specialist)
│   ├── USER.md
│   ├── PROJECTS.md
│   ├── STANDARDS.md
│   └── FACTS.md
└── skills/          # Specialist-specific skills
```

## Task Flow

1. **Orchestrator creates task contract** in `{specialist}/inbox/{task_id}.md`
2. **Orchestrator creates DB record** via `orchestration_db.py create-task`
3. **Orchestrator spawns specialist** with instructions to read SOUL.md, then execute
4. **Specialist reads context**, executes task, writes to `outbox/{task_id}.md`
5. **Specialist emits event** (completed/context_missing/escalated)
6. **Orchestrator processes event**, surfaces to human if needed

## Adding a New Specialist

1. Create `specialists/{name}/SOUL.md` and `AGENTS.md`
2. Run `scripts/setup_specialists.sh`
3. Add agent entry to `openclaw.json`:
   ```json
   {
     "id": "{name}",
     "name": "{Name} ({Role})",
     "workspace": "/path/to/.openclaw/workspace-{name}",
     "model": { "primary": "...", "fallbacks": [...] },
     "tools": { "deny": [...] }
   }
   ```
4. Add to main agent's `subagents.allowAgents`
5. Run `openclaw doctor` to verify

## Cognitive Diversity

The model assignment strategy uses different models for different roles:
- **Creators** (Blueprint, Forge, Scout): Opus for deep reasoning
- **Critics** (Sherlock): GPT-5.4 for different perspective

This compensates for blind spots. A model reviewing its own output catches fewer issues than a different model would.

## Routing Rules

The orchestrator uses this priority order:
1. Research/analysis → Scout
2. Code/backend/infra → Forge
3. UI/design/frontend → Pixel
4. Planning/architecture → Blueprint
5. Review/audit → Sherlock
6. Quick task (< 5 min) → Orchestrator handles directly

## Loop Guards

- Max 3 iterations per task
- After iteration 2: Sherlock must classify root cause
- After iteration 3: automatic escalation to orchestrator
