#!/usr/bin/env bash
#
# Title: runpod_start.sh — Stock-CUDA-image bootstrap for RunPod
# Description:
#   Used when the pod runs on a stock nvidia/cuda:*-runtime (or devel)
#   image rather than the pre-built wood-league-worker image. Installs
#   the runtime prerequisites (Stockfish via apt, downloads a prebuilt
#   lc0 binary onto the network volume, installs the worker package
#   from PyPI), then fetches and execs the canonical bootstrap.sh from
#   this repo.
#
#   The lc0 binary is downloaded ONCE per network volume from a GitHub
#   release built by .github/workflows/lc0-build.yml and persisted at
#   /workspace/bin/lc0. Subsequent pod stop/start re-uses it.
#
# Changelog:
#   2026-05-14 (#93): Initial creation for API-driven RunPod deploys.
#   2026-05-14: Build lc0 from source — upstream ships no Linux binary,
#       so the prebuilt-download path never worked. Binary now persisted
#       on the network volume at /workspace/bin/lc0.
#   2026-05-14 (#96): Replace source build with download of CI-built lc0
#       release asset (see .github/workflows/lc0-build.yml). Drops the
#       build toolchain from the apt step; pod boots in seconds, not
#       minutes, and no longer requires a CUDA *devel* image.

set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
export PATH=/usr/local/cuda/bin:${PATH}

WLW_VERSION="${WLW_VERSION:-0.9.5}"
BOOTSTRAP_URL="${WLW_BOOTSTRAP_URL:-https://raw.githubusercontent.com/christophersw/wood_league/main/services/local_worker/runpod/bootstrap.sh}"

log() { printf '[runpod-start %s] %s\n' "$(date -u +%FT%TZ)" "$*" >&2; }

# cuda-fp16 (default) or trt. The trt tarball bundles onnxruntime (MIT)
# under ./lib; TensorRT is fetched separately below (NVIDIA license — not
# redistributed by us).
export LC0_VARIANT="${LC0_VARIANT:-cuda-fp16}"
LC0_REF="${LC0_REF:-release/0.32}"
LC0_SLUG="$(echo "${LC0_REF}" | tr '/' '-')"
TRT_VERSION="${TRT_VERSION:-10.4.0.26}"   # must match the ORT build; see lc0-build.yml header
LC0_DIR="/workspace/bin/lc0-${LC0_VARIANT}"
LC0_BIN="${LC0_DIR}/lc0"
LC0_TARBALL="lc0-${LC0_SLUG}-linux-${LC0_VARIANT}.tar.gz"
LC0_RELEASE_URL="${WLW_LC0_RELEASE_URL:-https://github.com/christophersw/wood_league/releases/download/lc0-${LC0_SLUG}/${LC0_TARBALL}}"

# ---- 1. Apt prereqs (runtime only) ------------------------------------
if ! command -v stockfish >/dev/null 2>&1; then
    log "installing apt prerequisites (runtime)"
    apt-get update
    apt-get install -y --no-install-recommends \
        ca-certificates curl wget xz-utils git \
        stockfish python3.11 python3.11-venv python3-pip
    apt-get clean
    rm -rf /var/lib/apt/lists/*
    update-alternatives --install /usr/bin/python  python  /usr/bin/python3.11 1 || true
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 || true
fi

# ---- 2. Download prebuilt lc0 (one-time per volume) -------------------
# Upstream lc0 doesn't ship Linux binaries. We build our own in CI
# (.github/workflows/lc0-build.yml) and publish each version as a GitHub
# release asset. Download + checksum-verify here. The binary is
# dynamically linked against /usr/local/cuda runtime libs.
mkdir -p "${LC0_DIR}"
if [ ! -x "${LC0_BIN}" ]; then
    log "downloading lc0 ${LC0_REF} (${LC0_VARIANT}) from ${LC0_RELEASE_URL}"
    tmpdir="$(mktemp -d)"; cd "${tmpdir}"
    curl -fsSL -o "${LC0_TARBALL}" "${LC0_RELEASE_URL}"
    curl -fsSL -o "${LC0_TARBALL}.sha256" "${LC0_RELEASE_URL}.sha256" || true
    if [ -s "${LC0_TARBALL}.sha256" ]; then
        sha256sum -c "${LC0_TARBALL}.sha256" || { log "FATAL: lc0 sha256 mismatch"; exit 1; }
    fi
    # --no-same-owner: the tarball records the CI runner's uid/gid; as root
    # GNU tar would chown to it, which the RunPod network volume rejects.
    tar --no-same-owner -xzf "${LC0_TARBALL}" -C "${LC0_DIR}"
    chmod 0755 "${LC0_BIN}"
    cd /; rm -rf "${tmpdir}"
    log "lc0 installed at ${LC0_BIN}"
else
    log "lc0 already present at ${LC0_BIN} — skipping download"
fi
export WLW_LC0_PATH="${LC0_BIN}"
TRT_DIR="/workspace/trt"
if [ "${LC0_VARIANT}" = "trt" ]; then
    if [ ! -d "${TRT_DIR}/lib" ]; then
        log "fetching NVIDIA TensorRT ${TRT_VERSION} to ${TRT_DIR}"
        mkdir -p "${TRT_DIR}"
        trt_tmp="$(mktemp -d)"; cd "${trt_tmp}"
        # Pinned NVIDIA TensorRT Linux x86_64 tarball for the CUDA line the
        # RunPod image ships. WLW_TRT_URL overrides for mirror/air-gapped.
        : "${WLW_TRT_URL:?set WLW_TRT_URL to the NVIDIA TensorRT ${TRT_VERSION} linux tarball URL}"
        curl -fL --retry 5 --retry-delay 10 -o trt.tar.gz "${WLW_TRT_URL}"
        tar --no-same-owner -xzf trt.tar.gz --strip-components=1 -C "${TRT_DIR}"
        test -d "${TRT_DIR}/lib" || { log "FATAL: TensorRT lib/ missing after extract"; exit 1; }
        cd /; rm -rf "${trt_tmp}"
        log "TensorRT ready at ${TRT_DIR}"
    else
        log "TensorRT already present at ${TRT_DIR} — skipping"
    fi
    export LD_LIBRARY_PATH="${LC0_DIR}/lib:${TRT_DIR}/lib:${LD_LIBRARY_PATH:-}"
fi

# ---- 3. wood-league-worker from PyPI ----------------------------------
# Always run with --upgrade so a pod restart picks up new releases. Pip
# is a no-op when the requested version is already installed, so this
# stays cheap on warm volumes (issue #114).
log "installing/upgrading wood-league-worker==${WLW_VERSION}"
pip3 install --no-cache-dir --upgrade "wood-league-worker==${WLW_VERSION}"

# ---- 3b. Pre-write log-upload consent ---------------------------------
# `wood-league-worker run` prompts on first invocation for permission to
# upload session logs. In a headless container there is no TTY, the
# prompt aborts within seconds, and both engine processes exit before
# claiming any work. Pre-write the consent file so the prompt is skipped.
# Default: opt-in (1) — these uploads are how we debug pod failures.
CONSENT_DIR="${HOME:-/root}/.config/wood-league-worker"
CONSENT_FILE="${CONSENT_DIR}/config.json"
CONSENT_VALUE="${WLW_LOG_UPLOAD_CONSENT:-1}"
case "${CONSENT_VALUE}" in
    1|true|TRUE|yes|YES) consent_bool="true" ;;
    *)                    consent_bool="false" ;;
esac
if [ ! -f "${CONSENT_FILE}" ]; then
    log "writing log-upload consent (${consent_bool}) to ${CONSENT_FILE}"
    mkdir -p "${CONSENT_DIR}"
    printf '{"log_upload_consent": %s}\n' "${consent_bool}" > "${CONSENT_FILE}"
fi

# ---- 4. Pull the canonical bootstrap.sh -------------------------------
log "fetching bootstrap.sh from ${BOOTSTRAP_URL}"
curl -fsSL "${BOOTSTRAP_URL}" -o /usr/local/bin/wlw-bootstrap
chmod +x /usr/local/bin/wlw-bootstrap

# ---- 5. Hand off ------------------------------------------------------
log "handing control to wlw-bootstrap"
exec /usr/local/bin/wlw-bootstrap
