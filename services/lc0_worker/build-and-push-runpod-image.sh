#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 <docker-username> [tag]"
  exit 1
fi

DOCKER_USER="$1"
TAG="${2:-latest}"
IMAGE="${DOCKER_USER}/wood-league-lc0-runpod:${TAG}"

echo "Building ${IMAGE}"
docker build -t "${IMAGE}" .

echo "Pushing ${IMAGE}"
docker push "${IMAGE}"

echo "Done. Update RunPod endpoint image to ${IMAGE}"
