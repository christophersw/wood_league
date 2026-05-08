# ── Stage 1: build lc0 from source against CUDA 12.8 ─────────────────────────
# No Linux pre-built lc0 binary exists — all release assets are Windows/Android.
# CUDA 12.8 devel image required for the nvcc compiler.
FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        meson \
        ninja-build \
        build-essential \
        libopenblas-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Build lc0 v0.32.1 with the cuDNN backend enabled. v0.32.1 does not support a
# "-Dbackends=cuda" option; the real Meson flags are plain_cuda/cudnn. We enable
# cuDNN explicitly because the worker defaults to the cudnn-fp16 runtime backend,
# and disable gtest to avoid unnecessary test build dependencies in CI.
RUN git clone --branch v0.32.1 --depth 1 --recurse-submodules https://github.com/LeelaChessZero/lc0.git /tmp/lc0 \
    && cd /tmp/lc0 \
    && ./build.sh -Dcudnn=true -Dgtest=false -Ddefault_backend=cudnn-fp16 \
    && cp build/release/lc0 /usr/local/bin/lc0 \
    && chmod +x /usr/local/bin/lc0 \
    && rm -rf /tmp/lc0

# ── Stage 2: slim runtime image ───────────────────────────────────────────────
# cudnn-runtime ships only the CUDA + cuDNN shared libs needed to run lc0.
FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LC0_NETWORK=/usr/local/share/lc0-network.pb.gz \
    LC0_PATH=/usr/local/bin/lc0 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        curl \
        libopenblas0 \
        zlib1g \
    && python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/bin/lc0 /usr/local/bin/lc0

RUN curl --connect-timeout 10 --max-time 60 -fsSL \
        "https://storage.lczero.org/files/networks-contrib/t1-512x15x8h-distilled-swa-3395000.pb.gz" \
        -o /usr/local/share/lc0-network.pb.gz || true

COPY pyproject.toml README.md ./
COPY lc0_worker ./lc0_worker
COPY handler.py ./

RUN /opt/venv/bin/pip install --no-cache-dir .

CMD ["python", "handler.py"]
