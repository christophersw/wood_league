#!/usr/bin/env bash
# Build from monorepo root so COPY packages/shared resolves correctly.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

DOCKER_USER="${1:-christophersw}"
TAG="${2:-latest}"
IMAGE="${DOCKER_USER}/wood-league-lc0-runpod:${TAG}"

echo "Building ${IMAGE} (build context: ${REPO_ROOT})"
echo "WARNING: lc0 compiles from source — expect 15-30 min on first build."
docker build -f "${SCRIPT_DIR}/Dockerfile" -t "${IMAGE}" "${REPO_ROOT}"

echo "Pushing ${IMAGE}"
docker push "${IMAGE}"

echo "Done. Update RunPod endpoint image to: ${IMAGE}"
