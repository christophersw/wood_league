#!/usr/bin/env bash
# Title: onstart.sh — vast.ai entrypoint for the bulk analysis worker
# Description:
#   Pulls the canonical eval cache (fail-soft), launches lc0 + Stockfish
#   worker processes concurrently against one shared WAL cache,
#   periodically and on exit snapshots+uploads this instance's cache
#   delta, and exits when both bounded workers finish. No host volume.
# Changelog:
#   2026-05-15: Initial creation (vast.ai bulk worker plan, A+B).
set -euo pipefail

: "${WL_CAMPAIGN_ID:?WL_CAMPAIGN_ID is required}"
export WL_INSTANCE_ID="${WL_INSTANCE_ID:-$(hostname)-$$}"
WL_CACHE_CHECKPOINT_MINUTES="${WL_CACHE_CHECKPOINT_MINUTES:-10}"
export WLW_DATA_DIR="${WLW_DATA_DIR:-/data/wlw}"
CACHE_DB="${WLW_DATA_DIR}/eval_cache.sqlite"
WORK_DIR="${WLW_DATA_DIR}/.sync"
mkdir -p "${WLW_DATA_DIR}" "${WORK_DIR}"

py() { python -c "$1"; }

pull_cache() {
  if [ "${WL_SKIP_CACHE_PULL:-0}" = "1" ]; then
    echo "onstart: WL_SKIP_CACHE_PULL=1, starting with empty cache"
    return 0
  fi
  py "
import os
from pathlib import Path
from local_worker.cache_sync import make_s3_client, pull_canonical
c,b = make_s3_client()
ok = pull_canonical(c, b, Path(os.environ['_CACHE_DB']))
print('onstart: canonical pull ok' if ok else 'onstart: canonical pull failed (empty)')
" || true
}

push_delta() {
  py "
import os
from pathlib import Path
from local_worker.cache_sync import make_s3_client, upload_delta
c,b = make_s3_client()
upload_delta(c, b, Path(os.environ['_CACHE_DB']),
             os.environ['WL_CAMPAIGN_ID'], os.environ['WL_INSTANCE_ID'],
             Path(os.environ['_WORK_DIR']))
" || true
}

export _CACHE_DB="${CACHE_DB}" _WORK_DIR="${WORK_DIR}"

pull_cache

# --- launch both engines concurrently (mirrors runpod/bootstrap.sh) ---
WLW_WORKER_ID="vast-lc0-${WL_INSTANCE_ID}" \
  wood-league-worker --telemetry run --engine lc0 \
  ${WLW_MAX_JOBS:+--max-jobs "${WLW_MAX_JOBS}"} --batch-time "${WLW_BATCH_TIME:-1440}" &
lc_pid=$!

WLW_WORKER_ID="vast-sf-${WL_INSTANCE_ID}" \
  wood-league-worker --telemetry run --engine stockfish \
  ${WLW_MAX_JOBS:+--max-jobs "${WLW_MAX_JOBS}"} --batch-time "${WLW_BATCH_TIME:-1440}" &
sf_pid=$!

# --- periodic checkpoint loop ---
( while sleep "$((WL_CACHE_CHECKPOINT_MINUTES * 60))"; do push_delta; done ) &
ckpt_pid=$!

final_export() {
  kill "${ckpt_pid}" 2>/dev/null || true
  push_delta
}
trap 'final_export' TERM INT

# Wait for BOTH engine processes (a crash of one does not strand the other).
wait "${lc_pid}" || true
wait "${sf_pid}" || true

kill "${ckpt_pid}" 2>/dev/null || true
trap - TERM INT
push_delta
echo "onstart: both engines exited; final delta uploaded; instance done"
