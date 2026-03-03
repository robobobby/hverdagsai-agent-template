# HverdagsAI Agent Template Repo — Build Plan

## Goal
Create a private, reusable GitHub template repo that lets new HverdagsAI agents bootstrap with tested infrastructure (memory hybrid + maintenance + guardrails) without leaking personal/sensitive data.

## Scope
1. Create clean template repo structure.
2. Add bootstrap + verification scripts.
3. Include tested memory system scripts and agent operating files.
4. Add clear README instructions for humans and agents.
5. Add skills/tools guidance relevant to setup and upgrade.
6. Run Codex review + optimization pass.
7. Run local validation.
8. Publish private GitHub repo.

## Safety Gates
- Secret scan must pass.
- Placeholder scan must pass after customization.
- No personal artifacts (TickTick, Raindrop, house, portfolio flows).
- Verification script must return success on dry run.

## Deliverables
- Private GitHub repo: `<org>/hverdagsai-agent-template`.
- `README.md` with end-to-end setup + upgrade flow.
- `scripts/bootstrap_workspace.py` and `scripts/verify_workspace.py`.
- Core template files (AGENTS/SOUL/USER/MEMORY/HEARTBEAT/TOOLS/BOOTSTRAP).
- `skills/RECOMMENDED_SKILLS.md` and `docs/TOOLS_GUIDE.md`.
- Codex review report and applied optimizations.
