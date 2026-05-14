#!/usr/bin/env bash
#
# Title: runpod_start.sh — Stock-CUDA-image bootstrap for RunPod
# Description:
#   Used when the pod runs on a stock nvidia/cuda image rather than the
#   pre-built wood-league-worker image. Installs the runtime prerequisites
#   (Stockfish via apt, lc0 cuda-fp16 binary from upstream, the
#   wood-league-worker package from PyPI), then fetches and execs the
#   canonical bootstrap.sh from this repo.
#
#   Idempotent: skips any step whose result is already present, so pod
#   stop/start is fast on subsequent boots once the container disk has the
#   installs.
#
# Changelog:
#   2026-05-14 (#93): Initial creation for API-driven RunPod deploys.

set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

WLW_VERSION="${WLW_VERSION:-0.9.1}"
LC0_VERSION="${LC0_VERSION:-0.31.2}"
BOOTSTRAP_URL="${WLW_BOOTSTRAP_URL:-https://raw.githubusercontent.com/christophersw/wood_league/main/services/local_worker/runpod/bootstrap.sh}"

log() { printf '[runpod-start %s] %s\n' "$(date -u +%FT%TZ)" "$*" >&2; }

# ---- 1. Apt prereqs ----------------------------------------------------
if ! command -v stockfish >/dev/null 2>&1; then
    log "installing apt prerequisites"
    apt-get update
    apt-get install -y --no-install-recommends \
        ca-certificates curl wget xz-utils \
        stockfish python3.11 python3.11-venv python3-pip
    update-alternatives --install /usr/bin/python  python  /usr/bin/python3.11 1 || true
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 || true
fi

# ---- 2. lc0 cuda-fp16 binary -------------------------------------------
if [ ! -x /usr/local/bin/lc0 ]; then
    log "installing lc0 ${LC0_VERSION}"
    tmpdir="$(mktemp -d)"
    cd "${tmpdir}"
    curl -fsSL -o lc0.tar.xz \
        "https://github.com/LeelaChessZero/lc0/releases/download/v${LC0_VERSION}/lc0-v${LC0_VERSION}-linux-gpu-nvidia-cuda.tar.xz" \
        || curl -fsSL -o lc0.tar.xz \
            "https://github.com/LeelaChessZero/lc0/releases/download/v${LC0_VERSION}/lc0-${LC0_VERSION}-linux-cuda.tar.xz"
    tar -xJf lc0.tar.xz
    install -m 0755 ./lc0 /usr/local/bin/lc0 \
        || install -m 0755 "$(find . -name lc0 -type f | head -n1)" /usr/local/bin/lc0
    cd /
    rm -rf "${tmpdir}"
fi

# ---- 3. wood-league-worker from PyPI -----------------------------------
if ! command -v wood-league-worker >/dev/null 2>&1; then
    log "installing wood-league-worker==${WLW_VERSION}"
    pip3 install --no-cache-dir "wood-league-worker==${WLW_VERSION}"
fi

# ---- 4. Pull the canonical bootstrap.sh -------------------------------
log "fetching bootstrap.sh from ${BOOTSTRAP_URL}"
curl -fsSL "${BOOTSTRAP_URL}" -o /usr/local/bin/wlw-bootstrap
chmod +x /usr/local/bin/wlw-bootstrap

# ---- 5. Hand off ------------------------------------------------------
log "handing control to wlw-bootstrap"
exec /usr/local/bin/wlw-bootstrap
