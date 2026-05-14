#!/usr/bin/env bash
#
# Title: bootstrap.sh — RunPod container entrypoint for wood-league-worker
# Description:
#   Verifies that /workspace (the RunPod network volume) is mounted and
#   writable, lazily downloads the lc0 BT4 weights and Syzygy 3-4-5
#   tablebases on first boot, exports the WLW_* env vars consumed by
#   ``local_worker.config``, and finally execs the worker.
#
#   Designed to be idempotent: re-launching the pod skips any download
#   whose target file already exists on the volume.
#
# Changelog:
#   2026-05-14: Initial creation for issue #79.
#   2026-05-14 (#90): Launch Stockfish and Lc0 engines in parallel as
#       separate worker processes; bootstrap script handles the single
#       RunPod stop call after both finish.

set -euo pipefail

log() {
    # Timestamped log line on stderr so docker logs interleaves cleanly.
    printf '[wlw-bootstrap %s] %s\n' "$(date -u +%FT%TZ)" "$*" >&2
}

die() {
    log "FATAL: $*"
    exit 1
}

WORKSPACE="${WLW_WORKSPACE:-/workspace}"
WEIGHTS_DIR="${WORKSPACE}/weights"
SYZYGY_DIR="${WORKSPACE}/syzygy"
DATA_DIR="${WORKSPACE}/data"

# BT4 1024x15x32h smolgen — a well-known strong lc0 net used for analysis.
# Filename includes the -policytune-332 suffix as published on the mirror;
# this is the only BT4 .pb.gz currently available at networks-contrib.
BT4_FILENAME="${WLW_BT4_FILENAME:-BT4-1024x15x32h-swa-6147500-policytune-332.pb.gz}"
BT4_URL="${WLW_BT4_URL:-https://storage.lczero.org/files/networks-contrib/${BT4_FILENAME}}"
BT4_PATH="${WEIGHTS_DIR}/${BT4_FILENAME}"

# Syzygy 3-4-5 piece WDL+DTZ. Sesse mirrors the full set as individual
# files; we loop because there's no tarball at this tier.
SYZYGY_BASE_URL="${WLW_SYZYGY_BASE_URL:-https://tablebase.sesse.net/syzygy/3-4-5}"

# ---- 1. Workspace sanity ------------------------------------------------
log "verifying workspace at ${WORKSPACE}"
if [ ! -d "${WORKSPACE}" ]; then
    die "${WORKSPACE} does not exist — attach a RunPod network volume."
fi
if [ ! -w "${WORKSPACE}" ]; then
    die "${WORKSPACE} is not writable — check volume permissions."
fi
mkdir -p "${WEIGHTS_DIR}" "${SYZYGY_DIR}" "${DATA_DIR}"

# ---- 2. lc0 weights -----------------------------------------------------
if [ -s "${BT4_PATH}" ]; then
    log "lc0 weights already present at ${BT4_PATH}"
else
    log "downloading lc0 weights ${BT4_FILENAME}"
    # Atomic write: download to .part, rename on success so a killed pod
    # never leaves a half-written file that looks valid on next boot.
    tmp="${BT4_PATH}.part"
    curl -fL --retry 5 --retry-delay 10 -o "${tmp}" "${BT4_URL}" \
        || die "failed to download lc0 weights from ${BT4_URL}"
    mv "${tmp}" "${BT4_PATH}"
    log "lc0 weights ready at ${BT4_PATH}"
fi

# ---- 3. Syzygy 3-4-5 tablebases ----------------------------------------
# We treat the presence of any KPvK.rtbw + KPvK.rtbz as the marker that a
# previous boot completed the download. If either is missing, we fetch the
# full file index from the mirror and pull anything we don't already have.
need_syzygy=0
if [ ! -s "${SYZYGY_DIR}/KPvK.rtbw" ] || [ ! -s "${SYZYGY_DIR}/KPvK.rtbz" ]; then
    need_syzygy=1
fi

if [ "${need_syzygy}" -eq 1 ]; then
    log "fetching Syzygy 3-4-5 tablebase file list from ${SYZYGY_BASE_URL}"
    index_html="$(curl -fsSL "${SYZYGY_BASE_URL}/" || true)"
    if [ -z "${index_html}" ]; then
        die "could not read Syzygy file index at ${SYZYGY_BASE_URL}/"
    fi
    files="$(printf '%s\n' "${index_html}" \
        | grep -oE 'href="[A-Za-z0-9]+\.rtb[wz]"' \
        | sed -E 's/^href="(.*)"$/\1/' \
        | sort -u)"
    if [ -z "${files}" ]; then
        die "no .rtbw/.rtbz files discovered at ${SYZYGY_BASE_URL}"
    fi

    count=0
    while IFS= read -r fname; do
        [ -z "${fname}" ] && continue
        dest="${SYZYGY_DIR}/${fname}"
        if [ -s "${dest}" ]; then
            continue
        fi
        log "  download ${fname}"
        tmp="${dest}.part"
        curl -fL --retry 5 --retry-delay 5 -o "${tmp}" "${SYZYGY_BASE_URL}/${fname}" \
            || die "failed to download ${fname}"
        mv "${tmp}" "${dest}"
        count=$((count + 1))
    done <<EOF
${files}
EOF
    log "syzygy: fetched ${count} new file(s) into ${SYZYGY_DIR}"
else
    log "syzygy tablebases already populated under ${SYZYGY_DIR}"
fi

# ---- 4. Exported settings ----------------------------------------------
# WLW_API_URL / WLW_API_KEY are intentionally NOT set here — they are
# supplied by the RunPod operator at pod create time and must not be
# baked into the image.
export WLW_DATA_DIR="${WLW_DATA_DIR:-${DATA_DIR}}"
export WLW_LC0_WEIGHTS_PATH="${WLW_LC0_WEIGHTS_PATH:-${BT4_PATH}}"
export WLW_SYZYGY_PATH="${WLW_SYZYGY_PATH:-${SYZYGY_DIR}}"
export WLW_LC0_PATH="${WLW_LC0_PATH:-/usr/local/bin/lc0}"
export WLW_STOCKFISH_PATH="${WLW_STOCKFISH_PATH:-/usr/games/stockfish}"
export WLW_LC0_BACKEND="${WLW_LC0_BACKEND:-cuda-fp16}"
export WLW_DEFAULT_ENGINES="${WLW_DEFAULT_ENGINES:-stockfish,lc0}"
export WLW_STOCKFISH_THREADS="${WLW_STOCKFISH_THREADS:-7}"

if [ -z "${WLW_API_URL:-}" ] || [ -z "${WLW_API_KEY:-}" ]; then
    log "WARNING: WLW_API_URL / WLW_API_KEY not set — worker will refuse to run."
fi

mkdir -p /workspace/logs
export WLW_LOG_DIR=/workspace/logs

# ---- 5. Launch both engines in parallel --------------------------------
# Each engine runs as its own worker process so they can saturate the GPU
# (lc0) and the CPU cores (Stockfish) simultaneously. Distinct WLW_WORKER_ID
# values keep their heartbeats from overwriting each other on the admin
# dashboard.
#
# Per-process self-stop is suppressed (WLW_RUNPOD_SELF_STOP=0): whichever
# engine drains its queue first must NOT kill the pod while the other is
# still working. The bootstrap script issues the single stop call below
# after both processes have exited.
log "launching parallel engines: stockfish + lc0 (batch-size=10 each)"

# --telemetry is the app-level Typer flag that opts in to log uploads
# without prompting. Required on a headless pod because the interactive
# consent prompt has no TTY and would abort the worker.
# --batch-time is required to skip the second interactive prompt
# ("Run for how many minutes?") in headless mode. 1440 = 24 hours, a
# safe ceiling well above the time needed to drain any realistic queue.
# The worker still exits early via the queue-empty path; this is just
# the absolute upper bound.
WLW_WORKER_ID=runpod-stockfish WLW_RUNPOD_SELF_STOP=0 \
    wood-league-worker --telemetry run --engine stockfish --batch-size 10 --batch-time 1440 &
sf_pid=$!

WLW_WORKER_ID=runpod-lc0 WLW_RUNPOD_SELF_STOP=0 \
    wood-league-worker --telemetry run --engine lc0 --batch-size 10 --batch-time 1440 &
lc_pid=$!

log "stockfish pid=${sf_pid}  lc0 pid=${lc_pid} — waiting for both to drain"
wait "${sf_pid}" || log "stockfish process exited non-zero"
wait "${lc_pid}" || log "lc0 process exited non-zero"
log "both engines have exited"

# ---- 6. Optional pod auto-stop -----------------------------------------
# Triggered when the operator sets WLW_RUNPOD_AUTOSTOP=1 on the pod env
# panel. Uses curl rather than the worker's Python stop_self() because the
# wrapper outlives both worker processes.
if [ "${WLW_RUNPOD_AUTOSTOP:-0}" = "1" ]; then
    pod_id="${RUNPOD_POD_ID:-${WLW_RUNPOD_POD_ID:-}}"
    api_key="${WLW_RUNPOD_API_KEY:-}"
    if [ -z "${pod_id}" ] || [ -z "${api_key}" ]; then
        log "WLW_RUNPOD_AUTOSTOP=1 but RUNPOD_POD_ID or WLW_RUNPOD_API_KEY missing — skipping stop"
    else
        log "calling RunPod stop-pod for ${pod_id}"
        status=$(curl -s -o /dev/null -w '%{http_code}' \
            -X POST \
            -H "Authorization: Bearer ${api_key}" \
            --max-time 10 \
            "https://rest.runpod.io/v1/pods/${pod_id}/stop" || echo "000")
        log "RunPod stop-pod returned HTTP ${status}"
    fi
else
    log "WLW_RUNPOD_AUTOSTOP not set — leaving pod running"
fi
