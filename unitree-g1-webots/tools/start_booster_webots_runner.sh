#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACT_DIR="${ROOT_DIR}/external/booster_runner"
LOG_DIR="${ROOT_DIR}/.logs"
LOG_FILE="${LOG_DIR}/booster-webots-runner.log"
PID_FILE="${LOG_DIR}/booster-webots-runner.pid"

# Allow env-driven configuration for host IP, port, and robot name
WEBOTS_HOST_IP="${WEBOTS_HOST_IP:-127.0.0.1}"
WEBOTS_PORT="${WEBOTS_PORT:-1234}"
ROBOT_NAME="${ROBOT_NAME:-T1_release}"
export WEBOTS_CONTROLLER_URL="${WEBOTS_CONTROLLER_URL:-tcp://${WEBOTS_HOST_IP}:${WEBOTS_PORT}/${ROBOT_NAME}}"

resolve_runner() {
  local runner

  if [[ -n "${BOOSTER_RUNNER_PATH:-}" ]]; then
    printf '%s\n' "${BOOSTER_RUNNER_PATH}"
    return
  fi

  runner="$(find "${ARTIFACT_DIR}" -maxdepth 1 -type f \
    \( -name 'booster-runner-webots-full-*.run' -o -name 'booster-runner-full-*.run' \) \
    ! -name '*7dof*' \
    | sort \
    | tail -n 1)"

  if [[ -n "${runner}" ]]; then
    printf '%s\n' "${runner}"
    return
  fi

  printf '%s\n' "${ARTIFACT_DIR}/booster-runner-full-0.0.10.run"
}

RUNNER="$(resolve_runner)"

"${ROOT_DIR}/tools/check_booster_runner_assets.sh"

if [[ "$(uname -s)" != "Linux" ]]; then
  printf 'ERROR: Booster Webots runner is expected to run on Ubuntu 22.04/Linux, not %s\n' "$(uname -s)" >&2
  printf 'Run this script inside the supported Linux simulation environment.\n' >&2
  exit 1
fi

mkdir -p "${LOG_DIR}"

if [[ -f "${PID_FILE}" ]]; then
  old_pid="$(cat "${PID_FILE}")"
  if [[ "${old_pid}" =~ ^[0-9]+$ ]]; then
    if kill -0 "${old_pid}" >/dev/null 2>&1; then
      if runner_command="$(ps -p "${old_pid}" -o command= 2>/dev/null)"; then
        if [[ "${runner_command}" == *"$(basename "${RUNNER}")"* ]]; then
          printf 'Booster Webots runner already running with PID %s\n' "${old_pid}"
          printf 'Log: %s\n' "${LOG_FILE}"
          exit 0
        fi
      else
        printf 'Booster Webots runner already running with PID %s\n' "${old_pid}"
        printf 'Log: %s\n' "${LOG_FILE}"
        exit 0
      fi
    fi
  fi
  rm -f "${PID_FILE}"
fi

cd "${ARTIFACT_DIR}"
nohup "${RUNNER}" webots > "${LOG_FILE}" 2>&1 &
runner_pid="$!"
printf '%s\n' "${runner_pid}" > "${PID_FILE}"
sleep 1

if ! kill -0 "${runner_pid}" >/dev/null 2>&1; then
  rm -f "${PID_FILE}"
  printf 'ERROR: Booster Webots runner exited during startup\n' >&2
  printf 'Log: %s\n' "${LOG_FILE}" >&2
  exit 1
fi

printf 'Started Booster Webots runner with PID %s\n' "${runner_pid}"
printf 'Log: %s\n' "${LOG_FILE}"
