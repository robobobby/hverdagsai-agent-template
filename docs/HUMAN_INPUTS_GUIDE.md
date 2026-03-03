# HUMAN_INPUTS Guide

This is the single human step.

## 1) Create the file

```bash
python3 scripts/bootstrap_workspace.py --workspace ~/.openclaw/workspace --init-inputs
```

This creates:
- `~/.openclaw/workspace/HUMAN_INPUTS.yaml`

## 2) Fill required non-secret fields

Required:
- `identity.agent_name`
- `identity.human_name`
- `identity.company`
- `identity.timezone`

Recommended:
- `accounts.github_username`
- `accounts.google_workspace_email`

## 3) Add secret pointers (never raw secrets)

Allowed pointer formats:
- `op://...` (1Password reference)
- `keychain:<item-name>` (macOS Keychain reference)

Examples:
- `integrations.brave_api_key_ref: op://Work Vault/Brave API/key`
- `integrations.openai_api_key_ref: keychain:openai-api-key`
- `integrations.firecrawl_api_key_ref: keychain:firecrawl-api-key`

## 4) Agent runs the rest

```bash
python3 scripts/bootstrap_workspace.py --workspace ~/.openclaw/workspace --inputs ~/.openclaw/workspace/HUMAN_INPUTS.yaml
python3 scripts/verify_workspace.py --workspace ~/.openclaw/workspace --check-inputs
```

If `--check-inputs` fails, fix only the listed fields and rerun.
