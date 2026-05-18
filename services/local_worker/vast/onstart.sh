#!/usr/bin/env bash
# Title: onstart.sh — vast.ai entrypoint for the bulk analysis worker
# Description:
#   Pulls the canonical eval cache (fail-soft), launches lc0 + Stockfish
#   worker processes concurrently against one shared WAL cache,
#   periodically and on exit snapshots+uploads this instance's cache
#   delta, and exits when both bounded workers finish. No host volume.
# Changelog:
#   2026-05-15: Initial creation (vast.ai bulk worker plan, A+B).
#   2026-05-16: Fix `python`→`python3` (image has no python symlink);
#               hard-require WLW_API_URL/WLW_API_KEY (worker is a pull
#               client and exits "Not configured" without them).
set -euo pipefail

: "${WL_CAMPAIGN_ID:?WL_CAMPAIGN_ID is required}"
# The worker is an HTTP pull client; without these it prints
# "Not configured. Run `wood-league-worker setup` first." and both
# engines exit immediately. Supply them as vast account env vars (they
# auto-inject) or per-launch -e, exactly like the bucket creds.
: "${WLW_API_URL:?WLW_API_URL is required (Wood League Worker API base URL)}"
: "${WLW_API_KEY:?WLW_API_KEY is required (worker API token)}"
export WL_INSTANCE_ID="${WL_INSTANCE_ID:-$(hostname)-$$}"
WL_CACHE_CHECKPOINT_MINUTES="${WL_CACHE_CHECKPOINT_MINUTES:-10}"
export WLW_DATA_DIR="${WLW_DATA_DIR:-/data/wlw}"
CACHE_DB="${WLW_DATA_DIR}/eval_cache.sqlite"
WORK_DIR="${WLW_DATA_DIR}/.sync"
mkdir -p "${WLW_DATA_DIR}" "${WORK_DIR}"

py() { python3 -c "$1"; }

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

# Pull this image's lc0 calibration (fail-soft; never blocks boot). A
# hit lets the lc0 worker skip the ~7.5-min MinibatchSize sweep (#150).
if [ "${WL_SKIP_LC0_TUNING_PULL:-0}" = "1" ]; then
  echo "onstart: WL_SKIP_LC0_TUNING_PULL=1, skipping lc0 calibration pull"
else
  wood-league-worker lc0-tuning-pull || true
fi

# --- compute Stockfish fan-out for this host ---
eval "$(wood-league-worker plan-sf-fanout)"
echo "onstart: fan-out SF_WORKERS=${SF_WORKERS} SF_THREADS=${SF_THREADS} SF_HASH_MB=${SF_HASH_MB} SF_JOB_SPLIT='${SF_JOB_SPLIT}'"

declare -a engine_pids=()

# lc0 — single GPU-bound process; own truncating log file (lc0.log).
WLW_LOG_BASENAME=lc0 \
WLW_WORKER_ID="vast-lc0-${WL_INSTANCE_ID}" \
  wood-league-worker --telemetry run --engine lc0 \
  ${WLW_MAX_JOBS:+--max-jobs "${WLW_MAX_JOBS}"} --batch-time "${WLW_BATCH_TIME:-1440}" &
engine_pids+=($!)

# Stockfish — N CPU workers sharing one appended log file (stockfish.log).
read -r -a _sf_split <<< "${SF_JOB_SPLIT}"
for ((i = 0; i < SF_WORKERS; i++)); do
  _cap_arg=""
  if [ -n "${SF_JOB_SPLIT}" ]; then
    _cap_arg="--max-jobs ${_sf_split[$i]}"
  elif [ -n "${WLW_MAX_JOBS:-}" ]; then
    _cap_arg="--max-jobs ${WLW_MAX_JOBS}"
  fi
  WLW_LOG_BASENAME=stockfish WLW_LOG_APPEND=1 \
  WLW_STOCKFISH_THREADS="${SF_THREADS}" WLW_STOCKFISH_HASH_MB="${SF_HASH_MB}" \
  WLW_WORKER_ID="vast-sf-${WL_INSTANCE_ID}-${i}" \
    wood-league-worker --telemetry run --engine stockfish \
    ${_cap_arg} --batch-time "${WLW_BATCH_TIME:-1440}" &
  engine_pids+=($!)
done

# --- periodic checkpoint loop ---
( while sleep "$((WL_CACHE_CHECKPOINT_MINUTES * 60))"; do push_delta; done ) &
ckpt_pid=$!

final_export() {
  kill "${ckpt_pid}" 2>/dev/null || true
  push_delta
}
trap 'final_export' TERM INT

# Wait for ALL engine processes (a crash of one does not strand the rest).
for _pid in "${engine_pids[@]}"; do
  wait "${_pid}" || true
done

kill "${ckpt_pid}" 2>/dev/null || true
trap - TERM INT
push_delta
echo "onstart: both engines exited; final delta uploaded; instance done"
