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

  # Prefer the simulation-capable build. The 0.0.11 runner regressed: its
  # compiled motion_state_publisher hard-requires
  # /opt/booster/configs/robot_config.yaml (vendor per-robot calibration that is
  # NOT shipped), so it cannot walk in a bare sim. The 0.0.10 build (the one
  # socrob/booster_sim ships) falls back to its bundled default config and walks
  # without /opt/booster. Override with BOOSTER_RUNNER_PATH for a real robot.
  local preferred="${ARTIFACT_DIR}/booster-runner-webots-full-0.0.10.run"
  if [[ -f "${preferred}" ]]; then
    printf '%s\n' "${preferred}"
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

# ── Launch (hybrid graft) ────────────────────────────────────────────────────
# The runner self-extracts and runs booster-simulate-webots-run.sh, which starts
# the ROS<->DDS bridge (rpc_service_node) AND the mck locomotion engine, both
# bound to the SAME FastDDS profile in the extraction dir.
#
# The sim-capable 0.0.10 runner ships an EMPTY booster_ros2/ (no bridge); the
# bridge-capable 0.0.11 runner ships the built bridge but a regressed mck. So we
# extract the selected (motion) runner to a stable dir and, if it lacks a built
# bridge, graft booster_ros2/ + fastdds_profile.xml from a bridge-capable runner.
# Co-launching from one extraction guarantees mck and rpc_service_node share one
# DDS profile (the grafted 0.0.11 profile), which the host launcher also picks up
# for the ROS client.
MOTION_DIR="${BOOSTER_MOTION_DIR:-/tmp/booster_motion}"

resolve_bridge_runner() {
  if [[ -n "${BOOSTER_BRIDGE_RUNNER:-}" ]]; then
    printf '%s\n' "${BOOSTER_BRIDGE_RUNNER}"
    return
  fi
  find "${ARTIFACT_DIR}" -maxdepth 1 -type f -name 'booster-runner-webots-full-*.run' \
    ! -name '*7dof*' ! -name '*0.0.10*' | sort | tail -n 1
}

printf 'Extracting motion runner payload to %s ...\n' "${MOTION_DIR}"
rm -rf "${MOTION_DIR}"
sh "${RUNNER}" --noexec --keep --target "${MOTION_DIR}" >/dev/null 2>&1
if [[ ! -x "${MOTION_DIR}/mck" ]]; then
  printf 'ERROR: motion runner has no mck at %s\n' "${MOTION_DIR}" >&2
  exit 1
fi

if [[ ! -d "${MOTION_DIR}/booster_ros2/install" ]]; then
  BRIDGE_RUN="$(resolve_bridge_runner)"
  if [[ -z "${BRIDGE_RUN}" || ! -f "${BRIDGE_RUN}" ]]; then
    printf 'ERROR: %s ships no ROS bridge and no bridge-capable runner found to graft.\n' "$(basename "${RUNNER}")" >&2
    exit 1
  fi
  printf 'Grafting ROS bridge from %s ...\n' "$(basename "${BRIDGE_RUN}")"
  BRIDGE_DIR="${BOOSTER_BRIDGE_DIR:-/tmp/booster_bridge}"
  if [[ ! -d "${BRIDGE_DIR}/booster_ros2/install" ]]; then
    rm -rf "${BRIDGE_DIR}"
    sh "${BRIDGE_RUN}" --noexec --keep --target "${BRIDGE_DIR}" >/dev/null 2>&1
  fi
  cp -a "${BRIDGE_DIR}/booster_ros2" "${MOTION_DIR}/"
  [[ -f "${BRIDGE_DIR}/fastdds_profile.xml" ]] && cp -a "${BRIDGE_DIR}/fastdds_profile.xml" "${MOTION_DIR}/"
fi

cd "${MOTION_DIR}"
# webots-run.sh sources booster_ros2/install/setup.sh; that overlay was relocated
# from its build tree, so COLCON_CURRENT_PREFIX must be set for it to register.
export COLCON_CURRENT_PREFIX="${MOTION_DIR}/booster_ros2/install"
nohup ./booster-simulate-webots-run.sh webots > "${LOG_FILE}" 2>&1 &
runner_pid="$!"
printf '%s\n' "${runner_pid}" > "${PID_FILE}"
sleep 1

if ! kill -0 "${runner_pid}" >/dev/null 2>&1; then
  rm -f "${PID_FILE}"
  printf 'ERROR: Booster Webots runner exited during startup\n' >&2
  printf 'Log: %s\n' "${LOG_FILE}" >&2
  exit 1
fi

printf 'Started Booster Webots runner (mck + bridge) with PID %s\n' "${runner_pid}"
printf 'Log: %s\n' "${LOG_FILE}"
