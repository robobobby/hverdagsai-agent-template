#!/bin/bash
# setup_specialists.sh — Bootstrap specialist workspaces for OpenClaw agents
# Usage: ./scripts/setup_specialists.sh [openclaw_dir]
#
# This script creates workspace directories for each specialist agent,
# populates them with SOUL.md, AGENTS.md, and the standard directory structure.

set -euo pipefail

OPENCLAW_DIR="${1:-$HOME/.openclaw}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SPECIALISTS_DIR="$SCRIPT_DIR/specialists"

SPECIALISTS=("blueprint" "forge" "scout" "sherlock" "pixel")

echo "Setting up specialist workspaces in $OPENCLAW_DIR..."

for specialist in "${SPECIALISTS[@]}"; do
    ws="$OPENCLAW_DIR/workspace-$specialist"
    src="$SPECIALISTS_DIR/$specialist"

    if [ ! -d "$src" ]; then
        echo "  ⚠️  No template for $specialist in $SPECIALISTS_DIR, skipping"
        continue
    fi

    echo "  📁 $specialist → $ws"

    # Create workspace structure
    mkdir -p "$ws"/{inbox,outbox,memory,shared,skills}

    # Copy SOUL.md and AGENTS.md
    cp "$src/SOUL.md" "$ws/SOUL.md"
    cp "$src/AGENTS.md" "$ws/AGENTS.md"

    # Create empty memory files if they don't exist
    [ -f "$ws/memory/runbooks.md" ] || echo "# Runbooks" > "$ws/memory/runbooks.md"
    [ -f "$ws/memory/lessons.md" ] || echo "# Lessons Learned" > "$ws/memory/lessons.md"

    echo "    ✅ Done"
done

# Set up orchestration DB if schema exists
SCHEMA="$SCRIPT_DIR/schemas/orchestration.sql"
DB_DIR="$OPENCLAW_DIR/orchestration"
DB="$DB_DIR/state.db"

if [ -f "$SCHEMA" ]; then
    echo ""
    echo "  🗄️  Setting up orchestration database..."
    mkdir -p "$DB_DIR"
    sqlite3 "$DB" < "$SCHEMA"
    echo "    ✅ Database at $DB"
fi

# Copy scripts
SCRIPTS_SRC="$SCRIPT_DIR"
SCRIPTS_DST="$OPENCLAW_DIR/workspace/scripts"
if [ -d "$SCRIPTS_DST" ]; then
    for script in orchestration_db.py instinct_extract.py shared_context_gen.py validate_handoff.py secret_scan.py; do
        if [ -f "$SCRIPTS_SRC/$script" ]; then
            cp "$SCRIPTS_SRC/$script" "$SCRIPTS_DST/$script"
            echo "  📄 Copied $script to workspace/scripts/"
        fi
    done
fi

# Copy templates
TEMPLATES_DST="$OPENCLAW_DIR/workspace/templates"
if [ -d "$TEMPLATES_DST" ] || mkdir -p "$TEMPLATES_DST"; then
    for tmpl in task-contract.md handoff.md; do
        if [ -f "$SCRIPTS_SRC/$tmpl" ]; then
            if [ -f "$TEMPLATES_DST/$tmpl" ]; then
                echo "  ⚠️  $tmpl already exists, skipping (won't overwrite)"
            else
                cp "$SCRIPTS_SRC/$tmpl" "$TEMPLATES_DST/$tmpl"
                echo "  📄 Copied $tmpl"
            fi
        fi
    done
fi

# Set up shared context directory
mkdir -p "$OPENCLAW_DIR/shared-context"

echo ""
echo "🎉 Specialist setup complete!"
echo ""
echo "Next steps:"
echo "  1. Add specialist agents to openclaw.json (see docs/SPECIALISTS_GUIDE.md)"
echo "  2. Populate shared context files in each workspace's shared/ directory"
echo "  3. Run 'openclaw doctor' to verify configuration"
