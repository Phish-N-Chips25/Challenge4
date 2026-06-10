#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/docker_common.sh"

cd "${PROJECT_ROOT}"

# Prefer docker compose build if docker-compose.yml exists, otherwise fallback
# to plain docker build for CI or minimal setups.
if [[ -f "${PROJECT_ROOT}/docker-compose.yml" ]]; then
  printf 'Building with docker compose...\n'
  docker compose build
else
  printf 'No docker-compose.yml found — falling back to docker build...\n'
  docker build \
    -t "${IMAGE_NAME}" \
    -f containers/Containerfile \
    .
fi
