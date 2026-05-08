#!/usr/bin/env bash
# build-runpod.sh — Build and push a RunPod worker Docker image from the monorepo root.
#
# Usage: ./scripts/build-runpod.sh <service> <tag> <registry>
#   service:  stockfish_worker | lc0_worker
#   tag:      image tag (e.g. v1.2.3 or latest)
#   registry: Docker registry prefix (e.g. docker.io/christophersw)
#
# Example:
#   ./scripts/build-runpod.sh stockfish_worker v1.0.0 docker.io/christophersw

set -euo pipefail

SERVICE="${1:?Usage: $0 <service> <tag> <registry>}"
TAG="${2:?Usage: $0 <service> <tag> <registry>}"
REGISTRY="${3:?Usage: $0 <service> <tag> <registry>}"

VALID_SERVICES=("stockfish_worker" "lc0_worker")
if [[ ! " ${VALID_SERVICES[*]} " =~ " ${SERVICE} " ]]; then
    echo "Error: service must be one of: ${VALID_SERVICES[*]}"
    exit 1
fi

IMAGE="${REGISTRY}/${SERVICE}:${TAG}"
DOCKERFILE="services/${SERVICE}/Dockerfile"

echo "Building ${IMAGE} from repo root using ${DOCKERFILE}..."
docker build -f "${DOCKERFILE}" -t "${IMAGE}" .

echo "Pushing ${IMAGE}..."
docker push "${IMAGE}"

echo "Done: ${IMAGE}"
