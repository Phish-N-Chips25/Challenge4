#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/docker_common.sh"

# ── Auto-detect platform and source matching .env override ───────────────────
PLATFORM="$(detect_platform)"
printf 'Detected platform: %s\n' "${PLATFORM}"

ENV_OVERRIDE="${PROJECT_ROOT}/.env.${PLATFORM}"
if [[ -f "${ENV_OVERRIDE}" ]]; then
  printf 'Loading platform env overrides from %s\n' "${ENV_OVERRIDE}"
  # shellcheck disable=SC1090
  set -a  # auto-export all sourced variables
  source "${ENV_OVERRIDE}"
  set +a
fi

ensure_docker_state_dirs

args=(run --name "${CONTAINER_NAME}" --rm --interactive --tty)
append_runtime_args args
args+=(--workdir /workspace/project/ros2_ws "${IMAGE_NAME}" bash -lc "source /opt/ros/humble/setup.bash && exec bash")

docker "${args[@]}"
