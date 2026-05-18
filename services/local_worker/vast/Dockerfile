# Baked private image for vast.ai bulk analysis. NOT for public registry
# (TensorRT operator tarball is baked; keep registry private).
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

# No default: a stale hardcoded version silently baked the wrong worker
# into freshly tagged images (#133). CI resolves this from the tag; a
# manual build must pass --build-arg WORKER_VERSION=<ver> explicitly.
ARG WORKER_VERSION
ARG BT4_URL=https://storage.lczero.org/files/networks-contrib/BT4-1024x15x32h-swa-6147500-policytune-332.pb.gz
ARG LC0_URL
ARG WLW_TRT_URL
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3.11 python3-pip stockfish curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1

# lc0 (TRT build) — baked, not volume-fetched.
RUN curl -fsSL "${LC0_URL}" -o /tmp/lc0.tar.gz \
    && mkdir -p /opt/lc0 && tar -xzf /tmp/lc0.tar.gz -C /opt/lc0 \
    && rm /tmp/lc0.tar.gz

# TensorRT libraries (operator tarball; baked because registry is private).
# The NVIDIA tarball extracts to /opt/trt/TensorRT-<ver>/targets/<arch>/lib,
# but LD_LIBRARY_PATH expects a stable /opt/trt/lib — symlink the real
# lib dir there (version-agnostic via the libnvinfer.so.10 location).
RUN if [ -n "${WLW_TRT_URL}" ]; then \
      curl -fsSL "${WLW_TRT_URL}" -o /tmp/trt.tar.gz \
      && mkdir -p /opt/trt && tar -xzf /tmp/trt.tar.gz -C /opt/trt \
      && rm /tmp/trt.tar.gz \
      && _trtlib="$(dirname "$(find /opt/trt -name 'libnvinfer.so.10' | head -1)")" \
      && test -n "${_trtlib}" \
      && ln -sfn "${_trtlib}" /opt/trt/lib ; fi

# Build-time guard: the TRT lib path has silently broken before. Fail the
# BUILD (no GPU needed) instead of discovering it after a paid launch.
RUN if [ -n "${WLW_TRT_URL}" ]; then \
      test -e /opt/trt/lib/libnvinfer.so.10 \
        || { echo "FATAL: /opt/trt/lib/libnvinfer.so.10 missing — TRT lib path wrong"; \
             ls -lL /opt/trt/lib 2>&1 | head; exit 1; } ; \
      echo "OK: /opt/trt/lib/libnvinfer.so.10 resolves" ; fi

# BT4 weights + Syzygy 3-4-5 — baked.
RUN mkdir -p /opt/weights /opt/syzygy \
    && curl -fsSL "${BT4_URL}" -o /opt/weights/BT4.pb.gz
RUN set -eu; \
    base="http://tablebase.sesse.net/syzygy/3-4-5/"; \
    names="$(curl -fsSL "$base" | grep -oE '[A-Za-z0-9_]+\.(rtbw|rtbz)' | sort -u)"; \
    want="$(printf '%s\n' "$names" | grep -c .)"; \
    test "$want" -gt 0 || { echo "FATAL: Syzygy listing empty (http fetch failed)"; exit 1; }; \
    for t in $names; do curl -fsSL "${base}${t}" -o "/opt/syzygy/$t"; done; \
    got="$(ls -1 /opt/syzygy | grep -cE '\.(rtbw|rtbz)$' || true)"; \
    echo "Syzygy: listed=$want downloaded=$got"; \
    test "$got" -eq "$want" || { echo "FATAL: Syzygy incomplete ($got/$want)"; exit 1; }

RUN test -n "${WORKER_VERSION}" \
      || { echo "FATAL: WORKER_VERSION build-arg is empty — refusing to bake an unpinned worker (#133)"; exit 1; }
RUN python3.11 -m pip install --no-cache-dir "wood-league-worker==${WORKER_VERSION}"

# Bake a known-good L40S lc0 calibration so a fresh instance is a cache
# hit and skips the ~7.5-min MinibatchSize sweep (#150, Phase 1). The
# fingerprint uses the weights *basename* + backend (gpu/lc0_version
# empty, exactly as lc0.py calls get_tuned_opts), so this hits on any
# GPU running this image's BT4 / onnx-trt config; a mismatch silently
# falls back to a correct full sweep. Build-time guard (same
# philosophy as the TRT/Syzygy/WORKER_VERSION guards): fail the BUILD
# if the bake is missing or malformed rather than discover a silent
# full-sweep regression after a paid launch.
COPY vast/lc0_tuning.l40s.json /data/wlw/lc0_tuning.json
RUN python3.11 - <<'PY'
import json, sys
d = json.load(open("/data/wlw/lc0_tuning.json"))
fp = d["fingerprint"]
ok = (
    bool(fp.get("backend"))
    and fp.get("weights") == "BT4.pb.gz"
    and isinstance(d.get("minibatch_size"), int)
    and d["minibatch_size"] >= 1
)
sys.exit(0 if ok else "FATAL: baked lc0_tuning.json malformed (#150)")
PY

COPY vast/onstart.sh /usr/local/bin/wlw-vast-onstart
RUN chmod +x /usr/local/bin/wlw-vast-onstart

# Worker asset paths point at the in-image bake locations.
ENV WLW_LC0_PATH=/opt/lc0/lc0 \
    WLW_LC0_WEIGHTS_PATH=/opt/weights/BT4.pb.gz \
    WLW_SYZYGY_PATH=/opt/syzygy \
    WLW_STOCKFISH_PATH=/usr/games/stockfish \
    WLW_LC0_BACKEND=onnx-trt \
    LD_LIBRARY_PATH=/opt/trt/lib:${LD_LIBRARY_PATH:-} \
    WLW_DATA_DIR=/data/wlw

ENTRYPOINT ["/usr/local/bin/wlw-vast-onstart"]
