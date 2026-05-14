# syntax=docker/dockerfile:1.6
#
# Title: Dockerfile — wood-league-worker RunPod image
# Description:
#   Builds a CUDA-enabled container that ships Stockfish (apt) and a
#   prebuilt lc0 cuda-fp16 binary, then installs the ``wood-league-worker``
#   Python package from the working tree. The bootstrap script is the
#   entrypoint; it downloads weights / tablebases at first boot and execs
#   ``wood-league-worker run --engine both``.
#
#   Weights and Syzygy tablebases are NOT baked into the image — they live
#   on a mounted RunPod network volume (typically /workspace). API
#   credentials (WLW_API_URL / WLW_API_KEY) are supplied at pod create
#   time, never baked in.
#
# Changelog:
#   2026-05-14: Initial creation for issue #79.

FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

ARG DEBIAN_FRONTEND=noninteractive
ARG LC0_VERSION=0.31.2

# Minimal runtime + a thin set of tools needed to fetch lc0 + tablebases.
# We deliberately avoid a full build toolchain — we install a prebuilt lc0
# release tarball instead — to keep the image well under 2 GB.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        wget \
        tar \
        xz-utils \
        stockfish \
        python3.11 \
        python3.11-venv \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Make python3.11 the default ``python``/``python3``.
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

# Install the lc0 cuda-fp16 prebuilt release. The official GitHub release
# ships a tarball with the binary plus the required shared libs. We extract
# the ``lc0`` binary to /usr/local/bin and prune the rest.
RUN set -eux; \
    tmpdir="$(mktemp -d)"; \
    cd "$tmpdir"; \
    curl -fsSL -o lc0.tar.xz \
        "https://github.com/LeelaChessZero/lc0/releases/download/v${LC0_VERSION}/lc0-v${LC0_VERSION}-linux-gpu-nvidia-cuda.tar.xz" \
        || curl -fsSL -o lc0.tar.xz \
        "https://github.com/LeelaChessZero/lc0/releases/download/v${LC0_VERSION}/lc0-${LC0_VERSION}-linux-cuda.tar.xz"; \
    tar -xJf lc0.tar.xz; \
    install -m 0755 ./lc0 /usr/local/bin/lc0 || install -m 0755 "$(find . -name lc0 -type f | head -n1)" /usr/local/bin/lc0; \
    cd /; \
    rm -rf "$tmpdir"

# Copy the worker package source and install it system-wide. Using
# --no-cache-dir keeps the wheel cache off the layer.
COPY services/local_worker /build/local_worker
RUN pip3 install --no-cache-dir /build/local_worker \
    && rm -rf /build

# Bootstrap script — fetches weights/tablebases then execs the worker.
COPY services/local_worker/runpod/bootstrap.sh /usr/local/bin/wlw-bootstrap
RUN chmod +x /usr/local/bin/wlw-bootstrap

# RunPod mounts the network volume at /workspace by default.
WORKDIR /workspace

# Sensible defaults — these can all be overridden via RunPod env vars.
ENV WLW_DATA_DIR=/workspace/data \
    WLW_LC0_PATH=/usr/local/bin/lc0 \
    WLW_STOCKFISH_PATH=/usr/games/stockfish \
    WLW_LC0_BACKEND=cuda-fp16 \
    WLW_SYZYGY_PATH=/workspace/syzygy \
    WLW_DEFAULT_ENGINES=stockfish,lc0

ENTRYPOINT ["/usr/local/bin/wlw-bootstrap"]
