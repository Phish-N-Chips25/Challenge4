#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# start_booster_bridge.sh — run the ROS 2 <-> Booster DDS bridge (rpc_service_node)
# from the 0.0.11 runner payload, so it can drive an mck locomotion engine from
# the 0.0.10 runner (which ships no bridge).
#
# Why: 0.0.10 walks (its motion stack loads with the bundled default config) but
# ships an EMPTY booster_ros2/, so it has no /booster_rpc_service. 0.0.11 ships
# the built bridge but its mck hard-requires the unshipped /opt/booster config.
# mck and rpc_service_node are decoupled DDS peers (domain 0), so the 0.0.11
# bridge can command the 0.0.10 mck over the default DDS transport.
#
# Runs INSIDE the container. Intended to be exec'd like start_booster_webots_runner.sh.
# ─────────────────────────────────────────────────────────────────────────────

ROOT_DIR="${PROJECT_IN_CONTAINER:-/workspace/project}"
ARTIFACT_DIR="${ROOT_DIR}/external/booster_runner"
BRIDGE_DIR="${BOOSTER_BRIDGE_DIR:-/tmp/booster_bridge}"
LOG_FILE="${ROOT_DIR}/.logs/booster-bridge.log"
PID_FILE="${ROOT_DIR}/.logs/booster-bridge.pid"

# The bridge build (booster_ros2/install) lives in a webots-full runner that
# actually bundles it. 0.0.11 does; 0.0.10 does not.
resolve_bridge_runner() {
  if [[ -n "${BOOSTER_BRIDGE_RUNNER:-}" ]]; then
    printf '%s\n' "${BOOSTER_BRIDGE_RUNNER}"
    return
  fi
  find "${ARTIFACT_DIR}" -maxdepth 1 -type f -name 'booster-runner-webots-full-*.run' \
    ! -name '*7dof*' ! -name '*0.0.10*' | sort | tail -n 1
}

mkdir -p "${ROOT_DIR}/.logs"

BRIDGE_RUN="$(resolve_bridge_runner)"
if [[ -z "${BRIDGE_RUN}" || ! -f "${BRIDGE_RUN}" ]]; then
  printf 'ERROR: no bridge-capable runner (.run with booster_ros2) found in %s\n' "${ARTIFACT_DIR}" >&2
  exit 1
fi

# Extract the bridge payload once (cached).
if [[ ! -d "${BRIDGE_DIR}/booster_ros2/install" ]]; then
  printf 'Extracting bridge payload from %s ...\n' "$(basename "${BRIDGE_RUN}")"
  rm -rf "${BRIDGE_DIR}"
  sh "${BRIDGE_RUN}" --noexec --keep --target "${BRIDGE_DIR}" >/dev/null 2>&1
fi

INSTALL_DIR="${BRIDGE_DIR}/booster_ros2/install"
if [[ ! -d "${INSTALL_DIR}" ]]; then
  printf 'ERROR: bridge payload has no booster_ros2/install at %s\n' "${INSTALL_DIR}" >&2
  exit 1
fi

# Always (re)start so the bridge binds the CURRENT FastDDS profile. A leftover
# instance from a prior run may be bound to a different/default profile and would
# fail to reach mck — never reuse it.
if [[ -f "${PID_FILE}" ]]; then
  kill -9 "$(cat "${PID_FILE}" 2>/dev/null)" >/dev/null 2>&1 || true
  rm -f "${PID_FILE}"
fi

set +u
source /opt/ros/humble/setup.bash
# setup.sh unsets COLCON_CURRENT_PREFIX at the end; export it so the relocated
# overlay (extracted to a path different from its build tree) registers.
export COLCON_CURRENT_PREFIX="${INSTALL_DIR}"
source "${INSTALL_DIR}/setup.sh" >/dev/null 2>&1
set -u

# Must share mck's FastDDS profile to interop. The hybrid motion launch grafts
# 0.0.11's fastdds_profile.xml into the motion dir and binds mck to it; align the
# bridge to the same profile. Fall back to default DDS only if it is absent.
MOTION_PROFILE="${BOOSTER_MOTION_DIR:-/tmp/booster_motion}/fastdds_profile.xml"
if [[ -f "${MOTION_PROFILE}" ]]; then
  export FASTRTPS_DEFAULT_PROFILES_FILE="${MOTION_PROFILE}"
  export FASTDDS_DEFAULT_PROFILES_FILE="${MOTION_PROFILE}"
else
  unset FASTRTPS_DEFAULT_PROFILES_FILE FASTDDS_DEFAULT_PROFILES_FILE || true
fi

pkill -9 -f rpc_service_node 2>/dev/null || true
sleep 1

nohup ros2 run booster_rpc_service rpc_service_node > "${LOG_FILE}" 2>&1 &
bridge_pid="$!"
printf '%s\n' "${bridge_pid}" > "${PID_FILE}"
sleep 4

if ! kill -0 "${bridge_pid}" >/dev/null 2>&1; then
  rm -f "${PID_FILE}"
  printf 'ERROR: rpc_service_node exited during startup. Log:\n' >&2
  tail -20 "${LOG_FILE}" >&2 || true
  exit 1
fi

printf 'Booster bridge (rpc_service_node) started with PID %s\n' "${bridge_pid}"
printf 'Log: %s\n' "${LOG_FILE}"
