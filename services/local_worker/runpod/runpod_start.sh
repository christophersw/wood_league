#!/usr/bin/env bash
#
# Title: runpod_start.sh — Stock-CUDA-image bootstrap for RunPod
# Description:
#   Used when the pod runs on a stock nvidia/cuda:*-devel image rather
#   than the pre-built wood-league-worker image. Installs the runtime
#   prerequisites (Stockfish via apt, builds lc0 from source onto the
#   network volume, installs the worker package from PyPI), then fetches
#   and execs the canonical bootstrap.sh from this repo.
#
#   The lc0 binary is built ONCE per network volume and persisted at
#   /workspace/bin/lc0. Subsequent pod stop/start re-uses it, so only
#   the first boot pays the ~8–12 min build cost.
#
#   Requires the pod to use a CUDA *devel* image (e.g.
#   nvidia/cuda:12.4.1-devel-ubuntu22.04) so nvcc + CUDA headers are
#   present. The *runtime* image will fail at the lc0 build step.
#
# Changelog:
#   2026-05-14 (#93): Initial creation for API-driven RunPod deploys.
#   2026-05-14: Build lc0 from source — upstream ships no Linux binary,
#       so the prebuilt-download path never worked. Binary now persisted
#       on the network volume at /workspace/bin/lc0.

set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
export PATH=/usr/local/cuda/bin:${PATH}

WLW_VERSION="${WLW_VERSION:-0.9.1}"
LC0_VERSION="${LC0_VERSION:-0.31.2}"
BOOTSTRAP_URL="${WLW_BOOTSTRAP_URL:-https://raw.githubusercontent.com/christophersw/wood_league/main/services/local_worker/runpod/bootstrap.sh}"

# Persist the lc0 binary on the network volume so we only build once.
LC0_BIN="/workspace/bin/lc0"

log() { printf '[runpod-start %s] %s\n' "$(date -u +%FT%TZ)" "$*" >&2; }

# ---- 1. Apt prereqs (runtime + build tools) ---------------------------
if ! command -v stockfish >/dev/null 2>&1; then
    log "installing apt prerequisites (runtime + lc0 build tools)"
    apt-get update
    apt-get install -y --no-install-recommends \
        ca-certificates curl wget xz-utils git \
        stockfish python3.11 python3.11-venv python3-pip \
        build-essential meson ninja-build pkg-config \
        libprotobuf-dev protobuf-compiler \
        libeigen3-dev zlib1g-dev
    apt-get clean
    rm -rf /var/lib/apt/lists/*
    update-alternatives --install /usr/bin/python  python  /usr/bin/python3.11 1 || true
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 || true
fi

# ---- 2. Build lc0 from source (one-time per volume) -------------------
# Upstream lc0 doesn't ship Linux binaries — releases are Windows + Android
# only. We build cuda-fp16 from source. The resulting binary is dynamically
# linked against /usr/local/cuda runtime libs (already in the devel image),
# so it'll keep working across pod stop/start as long as the volume + image
# pair survives.
mkdir -p /workspace/bin
if [ ! -x "${LC0_BIN}" ]; then
    log "building lc0 v${LC0_VERSION} from source — this takes ~8–12 min the first time"
    src_dir="/workspace/build/lc0"
    rm -rf "${src_dir}"
    mkdir -p "${src_dir%/*}"
    git clone --depth 1 --branch "v${LC0_VERSION}" \
        https://github.com/LeelaChessZero/lc0.git "${src_dir}"
    cd "${src_dir}"
    # Release build, gtest off. Other lc0 meson options vary between
    # versions, so we don't override them — defaults are correct (CUDA
    # backend on, python bindings off, etc.).
    meson setup build --buildtype=release -Dgtest=false
    ninja -C build -j "$(nproc)"
    install -m 0755 build/lc0 "${LC0_BIN}"
    cd /
    log "lc0 built and installed at ${LC0_BIN}"
    # Leave the source dir around — re-running the build later (e.g. for
    # an upgraded version) will rm -rf it and reclone. Cheap on a 10 GB
    # volume that's otherwise mostly empty.
else
    log "lc0 already built at ${LC0_BIN} — skipping build"
fi

# Tell bootstrap.sh where lc0 lives. bootstrap.sh defaults this to
# /usr/local/bin/lc0; override with the volume path.
export WLW_LC0_PATH="${LC0_BIN}"

# ---- 3. wood-league-worker from PyPI ----------------------------------
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
