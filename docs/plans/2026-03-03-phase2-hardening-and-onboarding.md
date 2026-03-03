# Template Phase 2 Hardening + Onboarding Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add missing CI guardrails and make human-provided setup details (especially integration credentials like Brave API) simple, safe, and repeatable.

**Architecture:** Keep one primary operator path: `HUMAN_INPUTS.yaml` (non-secrets + secret pointers), `bootstrap_workspace.py` for setup, `verify_workspace.py` for strict checks, and one CI workflow that mirrors local validation.

**Tech Stack:** Python 3, GitHub Actions, YAML, markdown docs

---

### Task 1: Add CI guardrails (single workflow)

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `README.md`

**Step 1: Create CI workflow**
- Trigger: `pull_request`, `push` to `main`.
- Jobs: `validate-template`, `secret-scan`, `smoke-bootstrap`.

**Step 2: Add validate-template checks**
Run:
```bash
python3 -m compileall scripts
```
Expected: success.

**Step 3: Add secret-scan checks**
Run:
```bash
python3 scripts/secret_scan.py --path .
```
Expected: `Clean: no secrets found`.

**Step 4: Add smoke-bootstrap check**
Run:
```bash
TMP_WS=$(mktemp -d /tmp/hai-template.XXXXXX)
python3 scripts/bootstrap_workspace.py --workspace "$TMP_WS" --agent-name "CI Agent" --human-name "CI Owner" --company "HverdagsAI" --timezone "Europe/Copenhagen"
python3 scripts/verify_workspace.py --workspace "$TMP_WS"
```
Expected: verification passes.

**Step 5: Commit**
```bash
git add .github/workflows/ci.yml README.md
git commit -m "ci: add template validation, secret scan, and bootstrap smoke test"
```

---

### Task 2: Add canonical human input manifest

**Files:**
- Create: `templates/workspace/HUMAN_INPUTS.example.yaml`
- Create: `docs/HUMAN_INPUTS_GUIDE.md`
- Modify: `README.md`

**Step 1: Create example manifest schema**
Include:
- required non-secret fields: `agent_name`, `human_name`, `company`, `timezone`, `github_username`
- optional non-secret fields: `google_workspace_email`, `default_model`
- integrations map with pointer fields only (no raw values)

Example pointers:
- `brave_api_key_ref: "op://Work Vault/Brave API/key"`
- `openai_api_key_ref: "keychain:openai-api-key"`

**Step 2: Create human inputs guide**
Define:
- canonical location of real file: `<workspace>/HUMAN_INPUTS.yaml`
- allowed pointer schemes: `op://...` and `keychain:<name>`
- explicit rule: never paste raw tokens in YAML
- examples for Brave, OpenAI, Firecrawl

**Step 3: Update README onboarding section**
Add quick path:
1) create/fill `HUMAN_INPUTS.yaml`
2) bootstrap
3) verify

**Step 4: Commit**
```bash
git add templates/workspace/HUMAN_INPUTS.example.yaml docs/HUMAN_INPUTS_GUIDE.md README.md
git commit -m "docs: add human input manifest schema and credential pointer guide"
```

---

### Task 3: Extend bootstrap for human inputs and portability

**Files:**
- Modify: `scripts/bootstrap_workspace.py`
- Modify: `README.md`

**Step 1: Add `--inputs` flag**
- Accept path to `HUMAN_INPUTS.yaml`.
- Populate missing CLI identity fields from YAML.

**Step 2: Add `--init-inputs` flag**
- Copy example manifest into workspace when absent.
- Print next-step instructions for Luka/Elias.

**Step 3: Fix template copy behavior for dotfiles**
- Replace `glob("*")` loop with `iterdir()` and `is_file()` filtering to include hidden template files if added later.

**Step 4: Commit**
```bash
git add scripts/bootstrap_workspace.py README.md
git commit -m "feat: add inputs-driven bootstrap and dotfile-safe template copying"
```

---

### Task 4: Extend verify for input policy enforcement

**Files:**
- Modify: `scripts/verify_workspace.py`
- Modify: `docs/HUMAN_INPUTS_GUIDE.md`

**Step 1: Add `--check-inputs` mode**
Validate `<workspace>/HUMAN_INPUTS.yaml`:
- required non-secret fields present
- integration entries use pointer format only

**Step 2: Secret-inline guard**
Fail if suspicious inline secret patterns appear in manifest values.

**Step 3: Keep policy strict but simple**
- allow only `op://` and `keychain:` prefixes for secret refs
- print actionable error messages with exact missing/invalid keys

**Step 4: Commit**
```bash
git add scripts/verify_workspace.py docs/HUMAN_INPUTS_GUIDE.md
git commit -m "feat: enforce human input schema and pointer-only secret policy"
```

---

### Task 5: Final validation, review, and publish

**Files:**
- Create: `docs/reviews/2026-03-03-phase2-codex-review.md`
- Modify: as needed from review outcomes

**Step 1: Run local validation bundle**
```bash
python3 scripts/secret_scan.py --path .
python3 -m compileall scripts
TMP_WS=$(mktemp -d /tmp/hai-template.XXXXXX)
python3 scripts/bootstrap_workspace.py --workspace "$TMP_WS" --init-inputs
python3 scripts/bootstrap_workspace.py --workspace "$TMP_WS" --inputs "$TMP_WS/HUMAN_INPUTS.yaml" --agent-name "Template Agent" --human-name "Template Owner" --company "HverdagsAI" --timezone "Europe/Copenhagen"
python3 scripts/verify_workspace.py --workspace "$TMP_WS" --check-inputs
python3 scripts/verify_workspace.py --workspace "$TMP_WS"
```

**Step 2: Run Codex review on final diff**
Scope:
- CI guardrails
- human-input UX clarity
- secret pointer policy correctness
- agent upgrade instruction clarity

**Step 3: Document review outcomes**
- accepted changes
- rejected changes with reasons
- residual risks

**Step 4: Push and confirm repo privacy**
```bash
git push
gh repo view robobobby/hverdagsai-agent-template --json visibility,isPrivate,url
```
Expected: `PRIVATE`, `true`.

**Step 5: Commit final changes (if needed)**
```bash
git add .
git commit -m "chore: finalize phase-2 hardening and human-input onboarding"
```

---

Plan complete and saved to `docs/plans/2026-03-03-phase2-hardening-and-onboarding.md`. Two execution options:

1. Subagent-Driven (this session) - I dispatch per task and review between tasks.
2. Parallel Session (separate) - execute in one focused implementation run with checkpoints.

Which approach?