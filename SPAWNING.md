# Spawning Specialists

## The Mandatory Pattern

OpenClaw sub-agents inherit the parent workspace context. This means:
- SOUL.md, IDENTITY.md, USER.md, HEARTBEAT.md come from the PARENT (orchestrator)
- Only AGENTS.md and TOOLS.md come from the specialist workspace
- The specialist's working directory defaults to the parent's workspace

To make specialists work correctly, every spawn call needs three things:

### 1. Identity prefix in task prompt
Tell the specialist who it is. Without this, the parent's SOUL.md wins.

### 2. Absolute paths to the specialist workspace
The specialist's cwd is the parent workspace. Relative paths will read parent files.

### 3. AGENTS.md + TOOLS.md identity blocks (already in place)
These files contain override instructions that reinforce the specialist identity.

## Spawn Template

```
sessions_spawn(
  agentId="<specialist>",
  task="IMPORTANT: You are <Name>, a <role> specialist. You are NOT <orchestrator>. Your workspace is /absolute/path/to/workspace-<specialist>/. Read your AGENTS.md, then shared context from /absolute/path/to/workspace-<specialist>/shared/, then find and execute the task contract in /absolute/path/to/workspace-<specialist>/inbox/.",
  mode="run"
)
```

## Example (Scout)

```
sessions_spawn(
  agentId="scout",
  task="IMPORTANT: You are Scout, a research specialist. You are NOT Frank. Your workspace is /Users/agent/.openclaw/workspace-scout/. Read your AGENTS.md, then shared context from /Users/agent/.openclaw/workspace-scout/shared/, then find and execute the task contract in /Users/agent/.openclaw/workspace-scout/inbox/.",
  mode="run"
)
```

## Why This Is Necessary

OpenClaw injects parent workspace files as "Project Context" in the system prompt. The system prompt tells the model to "embody SOUL.md's persona." Without explicit overrides, specialists adopt the parent's identity.

The fix uses three reinforcement layers:
1. AGENTS.md: "IDENTITY OVERRIDE" block (disregard parent SOUL.md)
2. TOOLS.md: "CRITICAL IDENTITY CONTEXT" block (reinforces specialist identity)
3. Task prompt: explicit identity + absolute workspace paths

Tested and confirmed working as of 2026-03-13.
