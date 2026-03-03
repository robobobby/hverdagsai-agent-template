# Tools Guide for Template Users

## Core CLI
- `openclaw`
- `gh` (GitHub CLI)
- `python3`

## Optional but recommended
- `op` (1Password CLI)
- `jq`

## Setup checks
```bash
openclaw --version
gh auth status
python3 --version
```

## Security notes
- Use Keychain/1Password for secrets.
- Never store tokens in repo files.
- Run `python3 scripts/secret_scan.py --path .` before pushing.
