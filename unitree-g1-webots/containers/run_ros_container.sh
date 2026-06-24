#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/docker_common.sh"

# ── Auto-detect platform and source matching .env override ───────────────────
PLATFORM="$(detect_platform)"
printf 'Detected platform: %s\n' "${PLATFORM}"
load_project_env "${PLATFORM}"

ensure_docker_state_dirs

DOCKER_RUNTIME_ARGS=(run --name "${CONTAINER_NAME}" --rm --interactive --tty)
append_runtime_args
DOCKER_RUNTIME_ARGS+=(--workdir /workspace/project/ros2_ws "${IMAGE_NAME}" bash -lc "source /opt/ros/humble/setup.bash && exec bash")

docker "${DOCKER_RUNTIME_ARGS[@]}"
