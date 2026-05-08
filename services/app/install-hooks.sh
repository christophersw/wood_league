#!/usr/bin/env bash
# install-hooks.sh — install the snyk code pre-commit hook in all wood_league_* repos.
# Run once after cloning: ./install-hooks.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

REPOS=(
    "$ROOT/wood_league_app"
    "$ROOT/wood_league_stockfish_runpod"
    "$ROOT/wood_league_dispatchers"
    "$ROOT/wood_league_lc0_runpod"
)

# ── Colours ────────────────────────────────────────────────────────────────────
G='\033[0;32m'; Y='\033[0;33m'; B='\033[1;34m'; NC='\033[0m'

HOOK_BODY='#!/usr/bin/env bash
# pre-commit hook — run snyk code scan on this repo before every commit.
# Blocks the commit if any Medium or High severity code issues are found.
set -e
echo ""
echo "Running snyk code scan (medium+ severity)..."
snyk code test --severity-threshold=medium
'

for repo in "${REPOS[@]}"; do
    name="$(basename "$repo")"
    hook="$repo/.git/hooks/pre-commit"

    if [ ! -d "$repo/.git" ]; then
        echo -e "${Y}⚠  $name — no .git directory found, skipping${NC}"
        continue
    fi

    printf '%s' "$HOOK_BODY" > "$hook"
    chmod +x "$hook"
    echo -e "${G}✔${NC}  Installed pre-commit hook in ${B}$name${NC}"
done

echo ""
echo -e "${G}Done.${NC} Snyk code scan will run automatically on every git commit."
echo "To skip the hook for a single commit: git commit --no-verify"
