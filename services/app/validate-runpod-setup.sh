#!/bin/bash
# validate-runpod-setup.sh
# Comprehensive validation of RunPod migration implementation
# Run this to verify all code changes are in place before building Docker image

set -e

echo "========================================="
echo "RunPod Migration Validation Script"
echo "========================================="
echo ""

ERRORS=0

APP_ROOT="/Users/christopherwebster/Projects/wood_league_app"
STOCKFISH_RUNPOD_ROOT="/Users/christopherwebster/Projects/wood_league_stockfish_runpod"
DISPATCHERS_ROOT="/Users/christopherwebster/Projects/wood_league_dispatchers"

# Check 1: Alembic migration exists
echo "Checking Alembic migration..."
if [ -f "$APP_ROOT/alembic/versions/b3c9f1a04e87_add_runpod_tracking_columns.py" ]; then
    echo "✓ Alembic migration exists"
else
    echo "✗ Alembic migration not found"
    ERRORS=$((ERRORS + 1))
fi

# Check 2: stockfish_pipeline copied
echo "Checking stockfish_pipeline copy..."
if [ -d "$STOCKFISH_RUNPOD_ROOT/stockfish_pipeline" ]; then
    COUNT=$(find "$STOCKFISH_RUNPOD_ROOT/stockfish_pipeline" -type f -name "*.py" | wc -l)
    if [ "$COUNT" -gt 10 ]; then
        echo "✓ stockfish_pipeline copied ($COUNT Python files)"
    else
        echo "✗ stockfish_pipeline appears incomplete ($COUNT Python files)"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo "✗ stockfish_pipeline not found"
    ERRORS=$((ERRORS + 1))
fi

# Check 3: job_submitter exists and has lazy init
echo "Checking job_submitter.py..."
if grep -q "_ensure_initialized" "$STOCKFISH_RUNPOD_ROOT/stockfish_pipeline/ingest/job_submitter.py"; then
    echo "✓ job_submitter.py has lazy initialization"
else
    echo "✗ job_submitter.py missing lazy initialization"
    ERRORS=$((ERRORS + 1))
fi

# Check 4: analyse_game function exists
echo "Checking analyse_game wrapper..."
if grep -q "def analyse_game" "$STOCKFISH_RUNPOD_ROOT/stockfish_pipeline/services/stockfish_service.py"; then
    echo "✓ analyse_game wrapper function exists"
else
    echo "✗ analyse_game wrapper not found"
    ERRORS=$((ERRORS + 1))
fi

# Check 5: AnalysisJob model has new columns
echo "Checking AnalysisJob model updates..."
if grep -q "runpod_job_id.*String(64)" "$STOCKFISH_RUNPOD_ROOT/stockfish_pipeline/storage/models.py"; then
    echo "✓ AnalysisJob has runpod_job_id column"
else
    echo "✗ AnalysisJob missing runpod_job_id column"
    ERRORS=$((ERRORS + 1))
fi

if grep -q "submitted_at.*DateTime" "$STOCKFISH_RUNPOD_ROOT/stockfish_pipeline/storage/models.py"; then
    echo "✓ AnalysisJob has submitted_at column"
else
    echo "✗ AnalysisJob missing submitted_at column"
    ERRORS=$((ERRORS + 1))
fi

# Check 6: start_workers.py routes to job_submitter
echo "Checking start_workers.py routing..."
if grep -q "RUNPOD_.*ENDPOINT_ID" "$DISPATCHERS_ROOT/start_workers.py"; then
    echo "✓ start_workers.py checks for RUNPOD_ENDPOINT_ID"
else
    echo "✗ start_workers.py not updated for RunPod routing"
    ERRORS=$((ERRORS + 1))
fi

# Check 7: handler.py exists and is complete
echo "Checking handler.py..."
if [ -f "$STOCKFISH_RUNPOD_ROOT/handler.py" ]; then
    if grep -q "def handler(job:" "$STOCKFISH_RUNPOD_ROOT/handler.py"; then
        echo "✓ handler.py exists with handler function"
    else
        echo "✗ handler.py missing handler function"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo "✗ handler.py not found"
    ERRORS=$((ERRORS + 1))
fi

# Check 8: Dockerfile exists and is valid
echo "Checking Dockerfile..."
if [ -f "$STOCKFISH_RUNPOD_ROOT/Dockerfile" ]; then
    if grep -q "FROM python" "$STOCKFISH_RUNPOD_ROOT/Dockerfile" && \
       grep -q "COPY handler.py" "$STOCKFISH_RUNPOD_ROOT/Dockerfile"; then
        echo "✓ Dockerfile exists and is valid"
    else
        echo "✗ Dockerfile incomplete"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo "✗ Dockerfile not found"
    ERRORS=$((ERRORS + 1))
fi

# Check 9: requirements.txt has runpod
echo "Checking requirements.txt..."
if grep -q "runpod" "$STOCKFISH_RUNPOD_ROOT/requirements.txt"; then
    echo "✓ requirements.txt includes runpod"
else
    echo "✗ requirements.txt missing runpod"
    ERRORS=$((ERRORS + 1))
fi

# Check 10: Documentation files exist
echo "Checking documentation..."
DOCS=(
    "$APP_ROOT/RUNPOD_DEPLOYMENT.md"
    "$APP_ROOT/RUNPOD_SETUP_CHECKLIST.md"
    "$APP_ROOT/RUNPOD_MIGRATION_SUMMARY.md"
)
for doc in "${DOCS[@]}"; do
    if [ -f "$doc" ]; then
        echo "✓ $(basename $doc) exists"
    else
        echo "✗ $(basename $doc) not found"
        ERRORS=$((ERRORS + 1))
    fi
done

# Check 11: Build script exists and is executable
echo "Checking build script..."
if [ -x "$STOCKFISH_RUNPOD_ROOT/build-and-push-runpod-image.sh" ]; then
    echo "✓ build-and-push-runpod-image.sh is executable"
else
    echo "✗ build-and-push-runpod-image.sh not executable"
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "========================================="
if [ $ERRORS -eq 0 ]; then
    echo "✅ All validation checks passed!"
    echo ""
    echo "Next steps:"
    echo "  1. Ensure Docker is running"
    echo "  2. Run: cd $STOCKFISH_RUNPOD_ROOT"
    echo "  3. Run: ./build-and-push-runpod-image.sh <docker-username>"
    echo "  4. Follow RUNPOD_SETUP_CHECKLIST.md for RunPod + Railway setup"
    exit 0
else
    echo "❌ Validation failed with $ERRORS error(s)"
    echo "Please review the items marked with ✗ above"
    exit 1
fi
