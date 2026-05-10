#!/usr/bin/env bash
# Title: quality-gate.sh
# Description: Full LLM code quality pipeline for Python files.
# Runs in order: Ruff → Bandit+Semgrep → Radon/Xenon → mypy → pytest+coverage
# Triggered by PostToolUse Write|Edit hook. Exits 2 to rewake Claude if any check fails.
# Changelog:
#   2026-05-08 - Initial creation with full pipeline
#   2026-05-10 - Fix radon/xenon paths (python@3.9 removed, now use project venv)

set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR=$(cd "$SCRIPT_DIR/../.." && pwd)

RUFF=/opt/homebrew/bin/ruff
BANDIT=/Users/christopherwebster/.local/bin/bandit
SEMGREP=/opt/homebrew/bin/semgrep
RADON=$PROJECT_DIR/.venv/bin/radon
XENON=$PROJECT_DIR/.venv/bin/xenon
MYPY=$PROJECT_DIR/.venv/bin/mypy
PYTEST=$PROJECT_DIR/.venv/bin/pytest

# Thresholds
CC_MAX_ABSOLUTE=B        # Grade B = CC ≤ 10; grade C+ (CC > 10) triggers mandatory review
HALSTEAD_EFFORT_MAX=1000 # Effort > 1000 → flag for simplification
MI_MIN=20                # MI < 20 → reject / request regeneration

input=$(cat)
f=$(echo "$input" | jq -r '.tool_input.file_path // empty')

[[ "$f" == *.py ]] || exit 0
[[ -f "$f" ]] || exit 0

issues=""
output_lines=""

log_fail() {
    local label=$1 detail=$2
    issues="$label $issues"
    output_lines="$output_lines
[$label] $detail"
}

# ── 1. Ruff: syntax and style ────────────────────────────────────────────────
if ! ruff_out=$($RUFF check "$f" 2>&1); then
    log_fail "ruff:FAIL" "$ruff_out"
fi

# ── 2a. Bandit: security SAST ────────────────────────────────────────────────
if ! bandit_out=$($BANDIT -ll -q "$f" 2>&1); then
    log_fail "bandit:FAIL" "$bandit_out"
fi

# ── 2b. Semgrep: security SAST ───────────────────────────────────────────────
semgrep_out=$($SEMGREP --config=auto --quiet --timeout 20 "$f" 2>&1)
semgrep_exit=$?
if (( semgrep_exit == 1 )); then
    log_fail "semgrep:FAIL" "$semgrep_out"
fi

# ── 3a. Xenon: cyclomatic complexity threshold (CC > 10 = grade C+) ──────────
if ! xenon_out=$($XENON --max-absolute $CC_MAX_ABSOLUTE --max-modules A --max-average A "$f" 2>&1); then
    cc_detail=$($RADON cc -s "$f" 2>/dev/null | grep -E ' [C-F] \(' || true)
    log_fail "cc>10:FAIL" "Functions exceeding grade B:
$cc_detail"
fi

# ── 3b. Radon: Halstead effort > 1000 ────────────────────────────────────────
effort=$($RADON hal "$f" 2>/dev/null | awk '/effort:/{gsub(/[^0-9.]/,"",$2); printf "%d", $2}')
if [[ -n "$effort" ]] && (( effort > HALSTEAD_EFFORT_MAX )); then
    log_fail "halstead_effort(${effort}>1000):WARN" "Halstead effort ${effort} exceeds ${HALSTEAD_EFFORT_MAX} — simplify logic"
fi

# ── 3c. Radon: Maintainability index < 20 ────────────────────────────────────
mi_output=$($RADON mi -s "$f" 2>/dev/null)
if echo "$mi_output" | grep -qE ' - [BC] \('; then
    mi_score=$(echo "$mi_output" | grep -oE '\([0-9.]+\)' | tr -d '()')
    log_fail "mi(${mi_score}<20):FAIL" "Maintainability index ${mi_score} is below 20 — refactor or regenerate"
fi

# ── 4. mypy: type correctness ─────────────────────────────────────────────────
if [[ -x "$MYPY" ]]; then
    if ! mypy_out=$($MYPY --ignore-missing-imports --follow-imports=skip --no-error-summary "$f" 2>&1); then
        log_fail "mypy:FAIL" "$mypy_out"
    fi
fi

# ── 5. pytest + coverage: functional correctness (most important) ─────────────
if [[ -x "$PYTEST" ]]; then
    # Find the nearest test file for the edited module
    module_name=$(basename "$f" .py)
    module_dir=$(dirname "$f")

    test_file=""
    # Search: same dir, then tests/ subdir, then parent tests/ dir
    for search_dir in "$module_dir" "$module_dir/tests" "$(dirname "$module_dir")/tests"; do
        candidate="$search_dir/test_${module_name}.py"
        if [[ -f "$candidate" ]]; then
            test_file="$candidate"
            break
        fi
    done

    if [[ -n "$test_file" ]]; then
        if ! pytest_out=$($PYTEST "$test_file" -x --tb=short -q \
            --cov="$(dirname "$f")" --cov-report=term-missing:skip-covered \
            2>&1); then
            log_fail "pytest:FAIL" "$pytest_out"
        fi
    fi
fi

# ── Result ────────────────────────────────────────────────────────────────────
if [[ -z "$issues" ]]; then
    exit 0
fi

echo "Quality gate failures: $issues"
echo "$output_lines"
exit 2
