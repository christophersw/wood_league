#!/usr/bin/env bash
# security-scan.sh — run all Snyk scans across all wood_league_* repos.
#
# Usage:
#   ./security-scan.sh          standard scan (skips slow CUDA container pull)
#   ./security-scan.sh --full   also runs the nvidia/cuda container scan
#
# Severity policy:
#   Dep scans:       all severities (currently all clean; any vuln blocks)
#   Code scans:      medium+ (LOW sha1 findings are known/accepted)
#   Container scans: medium+ (base-image ambient LOWs are not actionable)
#
# Exit code 0 = clean, 1 = issues found or scan error.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

APP="$ROOT/wood_league_app"
STOCKFISH="$ROOT/wood_league_stockfish_runpod"
DISPATCHERS="$ROOT/wood_league_dispatchers"
LC0="$ROOT/wood_league_lc0_runpod"

FULL=false
for arg in "$@"; do [ "$arg" = "--full" ] && FULL=true; done

# ── Colours ────────────────────────────────────────────────────────────────────
R='\033[0;31m'; G='\033[0;32m'; Y='\033[0;33m'; B='\033[1;34m'; NC='\033[0m'

pass=0; fail=0; warn=0
summary=""

# ── Helpers ────────────────────────────────────────────────────────────────────
section() { echo -e "\n${B}  $*${NC}"; }
header()  { echo -e "\n${B}── $*${NC}"; }

record() {
    local code=$1 label="$2"
    if [ "$code" -eq 0 ]; then
        echo -e "   ${G}✔ clean${NC}"
        pass=$((pass + 1))
        summary="${summary}\n  ${G}✔${NC}  $label"
    elif [ "$code" -eq 1 ]; then
        echo -e "   ${R}✘ issues found${NC}"
        fail=$((fail + 1))
        summary="${summary}\n  ${R}✘${NC}  $label"
    else
        echo -e "   ${Y}⚠ scan error (exit $code)${NC}"
        warn=$((warn + 1))
        summary="${summary}\n  ${Y}⚠${NC}  $label  (scan error — check output above)"
    fi
}

run_scan() {
    local label="$1" dir="$2"; shift 2
    header "$label"
    cd "$dir"
    "$@"
    record $? "$label"
}

# ── Venv setup ─────────────────────────────────────────────────────────────────
setup_venv() {
    local dir="$1" mode="${2:-requirements}"
    if [ ! -d "$dir/.snyk-venv" ]; then
        echo -e "   ${Y}Creating .snyk-venv in $(basename "$dir")...${NC}"
        python3 -m venv "$dir/.snyk-venv" >/dev/null
        if [ "$mode" = "editable" ]; then
            "$dir/.snyk-venv/bin/pip" install -q -e "$dir"
            "$dir/.snyk-venv/bin/pip" freeze > "$dir/.snyk-requirements.txt"
        else
            "$dir/.snyk-venv/bin/pip" install -q -r "$dir/requirements.txt"
        fi
        echo -e "   ${G}Done.${NC}"
    fi
}

# ── Banner ─────────────────────────────────────────────────────────────────────
echo -e "\n${B}══════════════════════════════════════════${NC}"
echo -e "${B}  Wood League — Snyk Security Scan${NC}"
echo -e "${B}══════════════════════════════════════════${NC}"
if $FULL; then
    echo    "  Mode: full (includes CUDA container scan)"
else
    echo    "  Mode: standard  (--full to include CUDA scan)"
fi
echo      "  Severity: dep=all  code=medium+  container=medium+"

# ── Dependency scans ───────────────────────────────────────────────────────────
section "DEPENDENCY SCANS"
header "Preparing scan environments"
setup_venv "$APP"         requirements
setup_venv "$STOCKFISH"   requirements
setup_venv "$DISPATCHERS" editable
setup_venv "$LC0"         editable

run_scan "Dep: wood_league_app" "$APP" \
    snyk test \
        --file=requirements.txt \
        --package-manager=pip \
        "--command=$APP/.snyk-venv/bin/python"

run_scan "Dep: wood_league_stockfish_runpod" "$STOCKFISH" \
    snyk test \
        --file=requirements.txt \
        --package-manager=pip \
        "--command=$STOCKFISH/.snyk-venv/bin/python"

run_scan "Dep: wood_league_dispatchers" "$DISPATCHERS" \
    snyk test \
        --file=.snyk-requirements.txt \
        --package-manager=pip \
        "--command=$DISPATCHERS/.snyk-venv/bin/python"

run_scan "Dep: wood_league_lc0_runpod" "$LC0" \
    snyk test \
        --file=.snyk-requirements.txt \
        --package-manager=pip \
        "--command=$LC0/.snyk-venv/bin/python"

# ── Code scans ─────────────────────────────────────────────────────────────────
section "CODE SCANS  (medium+ severity)"

run_scan "Code: wood_league_app"              "$APP"        snyk code test --severity-threshold=medium
run_scan "Code: wood_league_stockfish_runpod" "$STOCKFISH"  snyk code test --severity-threshold=medium
run_scan "Code: wood_league_dispatchers"      "$DISPATCHERS" snyk code test --severity-threshold=medium
run_scan "Code: wood_league_lc0_runpod"       "$LC0"        snyk code test --severity-threshold=medium

# ── Container scans ────────────────────────────────────────────────────────────
section "CONTAINER SCANS  (medium+ severity)"

run_scan "Container: python:3.11-slim (stockfish)" "$STOCKFISH" \
    snyk container test python:3.11-slim \
        --file=Dockerfile \
        --severity-threshold=medium

run_scan "Container: python:3.11-slim (dispatchers)" "$DISPATCHERS" \
    snyk container test python:3.11-slim \
        --file=Dockerfile \
        --severity-threshold=medium

if $FULL; then
    run_scan "Container: nvidia/cuda:12.8.1 (lc0)" "$LC0" \
        snyk container test nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04 \
            --file=Dockerfile \
            --severity-threshold=medium
else
    echo -e "\n   ${Y}⟳  CUDA container scan skipped — run with --full to include${NC}"
fi

# ── Summary ────────────────────────────────────────────────────────────────────
echo -e "\n${B}══════════════════════════════════════════${NC}"
echo -e "${B}  Summary${NC}"
echo -e "${B}══════════════════════════════════════════${NC}"
echo -e "$summary"
echo ""
echo -e "  Passed: ${G}$pass${NC}   Failed: ${R}$fail${NC}   Errors: ${Y}$warn${NC}"
echo -e "${B}══════════════════════════════════════════${NC}\n"

[ "$fail" -eq 0 ] && [ "$warn" -eq 0 ]
