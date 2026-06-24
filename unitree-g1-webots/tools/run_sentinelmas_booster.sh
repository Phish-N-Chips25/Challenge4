#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# run_sentinelmas_booster.sh — Launch the Booster T1 walking in the
# SentinelMAS world.
#
# Usage:
#   ./tools/run_sentinelmas_booster.sh [command] [duration]
#
# Examples:
#   ./tools/run_sentinelmas_booster.sh safe_dock_path
#   ./tools/run_sentinelmas_booster.sh forward 2.0
#   ./tools/run_sentinelmas_booster.sh turn_left 5.0
#   ./tools/run_sentinelmas_booster.sh stop
#
# Prerequisites:
#   1. Webots R2025a installed on the host
#   2. Docker image/container built from this repository:
#      ./containers/build_ros_container.sh && ./containers/run_ros_container.sh
#   3. Booster Runner binaries copied to external/booster_runner/
# ─────────────────────────────────────────────────────────────────────────────

CHALLENGE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# shellcheck disable=SC1091
source "${CHALLENGE_ROOT}/containers/docker_common.sh"

PLATFORM="$(detect_platform)"
load_project_env "${PLATFORM}"
printf 'Detected platform: %s\n' "${PLATFORM}"

# ── Configuration ────────────────────────────────────────────────────────────
COMMAND="${1:-safe_dock_path}"
DURATION="${2:-5.0}"
CONTAINER_NAME="${CONTAINER_NAME:-booster-t1-ros}"
WEBOTS_HOST_IP="${WEBOTS_HOST_IP:-$(auto_webots_host_ip "${PLATFORM}")}"
WEBOTS_PORT="${WEBOTS_PORT:-1234}"
ROBOT_NAME="${ROBOT_NAME:-T1_release}"
WEBOTS_BIN="${WEBOTS_PATH:-webots}"
WEBOTS_BATCH="${WEBOTS_BATCH:-1}"
WEBOTS_EXTERN_URLS="${WEBOTS_EXTERN_URLS:-0}"
WEBOTS_HOLD_SECONDS="${WEBOTS_HOLD_SECONDS:-0}"
WEBOTS_CLEANUP_AFTER_HOLD="${WEBOTS_CLEANUP_AFTER_HOLD:-1}"
WEBOTS_MODE="${WEBOTS_MODE:-realtime}"
LOG_DIR="${CHALLENGE_ROOT}/.logs"
RUNNER_LOG="${LOG_DIR}/booster-webots-runner.log"
SERVICE_TIMEOUT="${SERVICE_TIMEOUT:-120}"

mkdir -p "${LOG_DIR}"
printf "Resetting runtime bridge logs in %s...\n" "${LOG_DIR}"
: > "${LOG_DIR}/booster_missions.jsonl"
: > "${LOG_DIR}/booster_status.jsonl"
: > "${LOG_DIR}/booster_target_pos.jsonl"
rm -f "${LOG_DIR}/booster_pose.json"

# ── Auto-detect Webots binary ────────────────────────────────────────────────
auto_detect_webots() {
  local candidates=()
  case "${PLATFORM}" in
    linux)
      candidates=( /usr/local/webots/webots /snap/bin/webots /opt/webots/webots )
      ;;
    macos)
      candidates=( /Applications/Webots.app/Contents/MacOS/webots )
      ;;
    windows)
      candidates=( "/mnt/c/Program Files/Webots/msys64/mingw64/bin/webots.exe" )
      ;;
  esac
  for c in "${candidates[@]}"; do
    if [[ -x "${c}" ]]; then
      printf '%s\n' "${c}"
      return
    fi
  done
  printf 'webots\n'
}

if [[ "${WEBOTS_BIN}" == "webots" ]]; then
  WEBOTS_BIN="$(auto_detect_webots)"
fi

assert_booster_runner_healthy() {
  local log_file="$1"
  local pattern
  local fatal_patterns=(
    "copy_robot_config.sh: No such file or directory"
    "Failed to load system settings config file"
    "/opt/booster/configs/system_settings_config.yaml"
    "/opt/booster/configs/robot_config.yaml"
    "Load robot config file failed"
  )

  [[ -f "${log_file}" ]] || return 0

  for pattern in "${fatal_patterns[@]}"; do
    if grep -Fq "${pattern}" "${log_file}"; then
      printf 'ERROR: Booster runner reported an unhealthy locomotion runtime: %s\n' "${pattern}" >&2
      printf 'The RPC service can still return status=0 in this state, but the robot will not walk reliably.\n' >&2
      printf 'See log: %s\n' "${log_file}" >&2
      exit 1
    fi
  done
}

# ── 1. Verify local runner assets ───────────────────────────────────────────
"${CHALLENGE_ROOT}/tools/check_booster_runner_assets.sh"

WEBOTS_UPDATED_ZIP="${CHALLENGE_ROOT}/external/booster_runner/webots_updated.zip"
if [[ ! -f "${WEBOTS_UPDATED_ZIP}" ]]; then
  printf 'ERROR: missing %s\n' "${WEBOTS_UPDATED_ZIP}" >&2
  exit 1
fi

# ── 2. Ensure Docker infrastructure ─────────────────────────────────────────
printf "Ensuring Docker container '%s' is running...\n" "${CONTAINER_NAME}"
if ! docker inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
  printf 'Container "%s" not found. Build and start it from this repository:\n' "${CONTAINER_NAME}"
  printf '  ./containers/build_ros_container.sh\n'
  printf '  ./containers/run_ros_container.sh\n'
  exit 1
fi

if ! container_is_running; then
  printf "Starting stopped container '%s'...\n" "${CONTAINER_NAME}"
  docker start "${CONTAINER_NAME}" >/dev/null
  sleep 2
fi

# ── 3. Prepare local vendor assets ──────────────────────────────────────────
mkdir -p "${CHALLENGE_ROOT}/.docker" "${CHALLENGE_ROOT}/.docker/booster_runner" "${CHALLENGE_ROOT}/.docker/home"

if [[ ! -d "${CHALLENGE_ROOT}/.docker/webots/lib/controller" ]]; then
  printf "Extracting webots_updated.zip for controller libraries...\n"
  unzip -q "${WEBOTS_UPDATED_ZIP}" -d "${CHALLENGE_ROOT}/.docker"
fi

if [[ ! -d "${CHALLENGE_ROOT}/.docker/booster_runner/webots_simulation/worlds" ]]; then
  printf "Extracting webots_simulation.zip for simulation assets...\n"
  unzip -q -o "${CHALLENGE_ROOT}/external/booster_runner/webots_simulation.zip" -d "${CHALLENGE_ROOT}/.docker/booster_runner"
fi

# ── 3b. Install Booster /opt/booster locomotion config ──────────────────────
# Replacement for the vendor copy_robot_config.sh that the runner does not ship.
# The default 0.0.10 simulation runner walks with its bundled simulation
# defaults. The 0.0.11 runner and real robot deployments still need /opt/booster.
printf "Installing Booster locomotion config (only the 0.0.11 runner / real robot need it)...\n"
if ! BOOSTER_OPT_OPTIONAL=1 "${CHALLENGE_ROOT}/tools/install_booster_opt.sh"; then
  printf 'NOTE: continuing without Booster locomotion config. The default 0.0.10 runner walks in simulation using its bundled default config; only the 0.0.11 runner or a real robot require the vendor /opt/booster files.\n' >&2
  printf 'See ./tools/install_booster_opt.sh if you need to supply them.\n' >&2
fi

# ── 4. Build the local ROS 2 service/client workspace ───────────────────────
printf "Building local Booster ROS 2 workspace...\n"
docker exec "${CONTAINER_NAME}" bash -lc '
  set -euo pipefail
  set +u
  source /opt/ros/humble/setup.bash
  set -u
  cd /workspace/project/ros2_ws
  colcon build --symlink-install --packages-select booster_interface booster_t1_webots_test
'

# ── 5. Clean up existing Webots processes ────────────────────────────────────
printf "Cleaning up old processes...\n"
pkill -f webots 2>/dev/null || true
docker exec "${CONTAINER_NAME}" pkill -f mck 2>/dev/null || true
docker exec "${CONTAINER_NAME}" pkill -9 -f rpc_service_node 2>/dev/null || true
docker exec "${CONTAINER_NAME}" pkill -f pose_file_odometry_publisher 2>/dev/null || true
docker exec "${CONTAINER_NAME}" pkill -f sim_lidar_pointcloud_node 2>/dev/null || true
docker exec "${CONTAINER_NAME}" pkill -f booster_patrol_node 2>/dev/null || true
sleep 1
printf "Resetting runtime bridge logs after cleanup...\n"
: > "${LOG_DIR}/booster_missions.jsonl"
: > "${LOG_DIR}/booster_status.jsonl"
: > "${LOG_DIR}/booster_target_pos.jsonl"
rm -f "${LOG_DIR}/booster_pose.json"
rm -f "${LOG_DIR}/booster_pointcloud.json" "${LOG_DIR}/booster_internal_map.json"

# ── 6. Start Webots on host with SentinelMAS world ──────────────────────────
WORLD_FILE="${CHALLENGE_ROOT}/worlds/sentinelmas_office.wbt"
# Windows Webots is a native .exe and cannot resolve WSL '/mnt/c/...' paths —
# convert to a Windows path (C:\...). On Linux/macOS the path is used as-is.
if [[ "${PLATFORM}" == "windows" ]] && command -v wslpath >/dev/null 2>&1; then
  WORLD_FILE="$(wslpath -w "${WORLD_FILE}")"
fi
printf "Starting Webots with SentinelMAS world: %s\n" "${WORLD_FILE}"
WEBOTS_ARGS=(--stdout --stderr "--mode=${WEBOTS_MODE}" "--port=${WEBOTS_PORT}")
if [[ "${WEBOTS_EXTERN_URLS}" != "0" && "${WEBOTS_EXTERN_URLS}" != "false" ]]; then
  WEBOTS_ARGS+=(--extern-urls)
fi
if [[ "${WEBOTS_BATCH}" != "0" && "${WEBOTS_BATCH}" != "false" ]]; then
  WEBOTS_ARGS=(--batch "${WEBOTS_ARGS[@]}")
fi
nohup "${WEBOTS_BIN}" "${WEBOTS_ARGS[@]}" "${WORLD_FILE}" > "${LOG_DIR}/host-webots-sentinelmas.log" 2>&1 < /dev/null &
WEBOTS_PID=$!
echo "${WEBOTS_PID}" > "${LOG_DIR}/host-webots-sentinelmas.pid"
printf "Webots started with PID %s\n" "${WEBOTS_PID}"
sleep 3

# ── 7. Start Booster runner inside the container ────────────────────────────
printf "Starting Booster runner inside the container...\n"
docker exec "${CONTAINER_NAME}" bash -lc "
  export WEBOTS_HOME=/workspace/project/.docker/webots
  export LD_LIBRARY_PATH=\${WEBOTS_HOME}/lib/controller
  export WEBOTS_CONTROLLER_URL=tcp://${WEBOTS_HOST_IP}:${WEBOTS_PORT}/${ROBOT_NAME}
  /workspace/project/tools/start_booster_webots_runner.sh
"
sleep 5
assert_booster_runner_healthy "${RUNNER_LOG}"

# ── 8. Wait for Webots and the RPC service ──────────────────────────────────
printf "Waiting for Webots external controller connection...\n"
connection_deadline=$((SECONDS + SERVICE_TIMEOUT))
until grep -Fq "INFO: '${ROBOT_NAME}' extern controller: connected." "${LOG_DIR}/host-webots-sentinelmas.log"; do
  assert_booster_runner_healthy "${RUNNER_LOG}"
  if ! kill -0 "${WEBOTS_PID}" >/dev/null 2>&1; then
    printf 'ERROR: Webots exited before the Booster runner connected\n' >&2
    printf 'See logs: %s\n' "${LOG_DIR}/host-webots-sentinelmas.log" >&2
    exit 1
  fi
  if (( SECONDS >= connection_deadline )); then
    printf 'ERROR: timed out waiting for Webots external controller connection after %s seconds\n' "${SERVICE_TIMEOUT}" >&2
    printf 'See logs: %s\n' "${LOG_DIR}/host-webots-sentinelmas.log" >&2
    exit 1
  fi
  sleep 1
done

printf "Waiting for Booster FastDDS profile...\n"
profile_deadline=$((SECONDS + SERVICE_TIMEOUT))
until docker exec "${CONTAINER_NAME}" bash -lc '
  test -n "$(find /tmp -maxdepth 3 -name "fastdds_profile.xml" 2>/dev/null | head -n 1)"
'; do
  assert_booster_runner_healthy "${RUNNER_LOG}"
  if (( SECONDS >= profile_deadline )); then
    printf 'ERROR: timed out waiting for Booster FastDDS profile after %s seconds\n' "${SERVICE_TIMEOUT}" >&2
    printf 'See logs: %s\n' "${RUNNER_LOG}" >&2
    exit 1
  fi
  sleep 1
done

# Start the ROS <-> DDS bridge (rpc_service_node) decoupled from mck: clean ROS
# libs (the motion runner's lib dirs poison the node's link path) but bound to
# mck's FastDDS profile. The motion runner ships no usable bridge on its own
# (0.0.10 booster_ros2/ is empty; 0.0.11's mck is config-broken), so the bridge
# runs as its own process and reaches mck over shared DDS.
printf "Starting Booster ROS bridge (rpc_service_node)...\n"
if ! docker exec "${CONTAINER_NAME}" bash -lc '/workspace/project/tools/start_booster_bridge.sh'; then
  printf 'ERROR: failed to start Booster ROS bridge (rpc_service_node)\n' >&2
  exit 1
fi

printf "Restarting ROS daemon with Booster FastDDS profile...\n"
docker exec "${CONTAINER_NAME}" bash -lc '
  set +u
  source /opt/ros/humble/setup.bash
  source /workspace/project/ros2_ws/install/setup.bash
  set -u
  profile="$(find /tmp -maxdepth 3 -name "fastdds_profile.xml" 2>/dev/null | head -n 1)"
  if [[ -z "${profile}" ]]; then
    printf "ERROR: Booster FastDDS profile was not found\n" >&2
    exit 1
  fi
  export FASTRTPS_DEFAULT_PROFILES_FILE="${profile}"
  export FASTDDS_DEFAULT_PROFILES_FILE="${profile}"
  ros2 daemon stop >/dev/null 2>&1 || true
  ros2 daemon start >/dev/null 2>&1 || true
'

printf "Starting Webots pose odometry publisher...\n"
docker exec "${CONTAINER_NAME}" bash -lc '
  set +u
  source /opt/ros/humble/setup.bash
  source /workspace/project/ros2_ws/install/setup.bash
  set -u
  profile="$(find /tmp -maxdepth 3 -name "fastdds_profile.xml" 2>/dev/null | head -n 1)"
  if [[ -n "${profile}" ]]; then
    export FASTRTPS_DEFAULT_PROFILES_FILE="${profile}"
    export FASTDDS_DEFAULT_PROFILES_FILE="${profile}"
  fi
  export BOOSTER_POSE_FILE=/workspace/project/.logs/booster_pose.json
  nohup ros2 run booster_t1_webots_test pose_file_odometry_publisher > /workspace/project/.logs/pose-file-odometry.log 2>&1 &
  printf "%s\n" "$!" > /workspace/project/.logs/pose-file-odometry.pid
'

printf "Starting simulated Booster point cloud publisher...\n"
docker exec "${CONTAINER_NAME}" bash -lc '
  set +u
  source /opt/ros/humble/setup.bash
  source /workspace/project/ros2_ws/install/setup.bash
  set -u
  profile="$(find /tmp -maxdepth 3 -name "fastdds_profile.xml" 2>/dev/null | head -n 1)"
  if [[ -n "${profile}" ]]; then
    export FASTRTPS_DEFAULT_PROFILES_FILE="${profile}"
    export FASTDDS_DEFAULT_PROFILES_FILE="${profile}"
  fi
  export BOOSTER_POSE_FILE=/workspace/project/.logs/booster_pose.json
  export BOOSTER_POINTCLOUD_FILE=/workspace/project/.logs/booster_pointcloud.json
  nohup ros2 run booster_t1_webots_test sim_lidar_pointcloud_node > /workspace/project/.logs/sim-lidar-pointcloud.log 2>&1 &
  printf "%s\n" "$!" > /workspace/project/.logs/sim-lidar-pointcloud.pid
'

printf "Waiting for /booster_rpc_service to be ready...\n"
deadline=$((SECONDS + SERVICE_TIMEOUT))
until docker exec "${CONTAINER_NAME}" bash -lc '
  set +u
  source /opt/ros/humble/setup.bash
  source /workspace/project/ros2_ws/install/setup.bash
  set -u
  profile="$(find /tmp -maxdepth 3 -name "fastdds_profile.xml" 2>/dev/null | head -n 1)"
  if [[ -z "${profile}" ]]; then
    exit 1
  fi
  export FASTRTPS_DEFAULT_PROFILES_FILE="${profile}"
  export FASTDDS_DEFAULT_PROFILES_FILE="${profile}"
  ros2 service list | grep -qx /booster_rpc_service
'; do
  assert_booster_runner_healthy "${RUNNER_LOG}"
  if (( SECONDS >= deadline )); then
    printf 'ERROR: timed out waiting for /booster_rpc_service after %s seconds\n' "${SERVICE_TIMEOUT}" >&2
    printf 'See logs: %s\n' "${RUNNER_LOG}" >&2
    exit 1
  fi
  sleep 2
done
assert_booster_runner_healthy "${RUNNER_LOG}"

# ── 8b. Start the Booster patrol node ────────────────────────────────────────
printf "Starting Booster patrol node...\n"
docker exec "${CONTAINER_NAME}" bash -lc '
  set +u
  source /opt/ros/humble/setup.bash
  source /workspace/project/ros2_ws/install/setup.bash
  set -u
  profile="$(find /tmp -maxdepth 3 -name "fastdds_profile.xml" 2>/dev/null | head -n 1)"
  if [[ -n "${profile}" ]]; then
    export FASTRTPS_DEFAULT_PROFILES_FILE="${profile}"
    export FASTDDS_DEFAULT_PROFILES_FILE="${profile}"
  fi
  export PATROL_LOG_DIR=/workspace/project/.logs
  nohup ros2 run booster_t1_webots_test booster_patrol_node > /workspace/project/.logs/booster-patrol.log 2>&1 &
  printf "%s\n" "$!" > /workspace/project/.logs/booster-patrol.pid
'

printf "Waiting for Booster patrol walking mode...\n"
patrol_deadline=$((SECONDS + SERVICE_TIMEOUT))
until grep -Fq "Walking mode ready." "${LOG_DIR}/booster-patrol.log" 2>/dev/null; do
  assert_booster_runner_healthy "${RUNNER_LOG}"
  if (( SECONDS >= patrol_deadline )); then
    printf 'ERROR: timed out waiting for Booster patrol walking mode after %s seconds\n' "${SERVICE_TIMEOUT}" >&2
    printf 'See log: %s\n' "${LOG_DIR}/booster-patrol.log" >&2
    exit 1
  fi
  sleep 1
done

# ── 9. Send movement command ────────────────────────────────────────────────
printf "Sending Booster command: %s (duration argument: %s seconds)...\n" "${COMMAND}" "${DURATION}"
docker exec --interactive \
  --env BOOSTER_COMMAND="${COMMAND}" \
  --env BOOSTER_DURATION="${DURATION}" \
  "${CONTAINER_NAME}" bash -lc '
  set -euo pipefail
  set +u
  source /opt/ros/humble/setup.bash
  set -u
  set +u
  source /workspace/project/ros2_ws/install/setup.bash
  set -u
  profile=$(find /tmp -maxdepth 3 -name "fastdds_profile.xml" 2>/dev/null | head -n 1)
  if [[ -n "${profile}" ]]; then
    export FASTRTPS_DEFAULT_PROFILES_FILE="${profile}"
    export FASTDDS_DEFAULT_PROFILES_FILE="${profile}"
  fi
  ros2 run booster_t1_webots_test rpc_movement_client --command "${BOOSTER_COMMAND}" --duration "${BOOSTER_DURATION}" --no-prepare
'

printf "\nDone! The Booster T1 executed '%s'.\n" "${COMMAND}"
if kill -0 "${WEBOTS_PID}" >/dev/null 2>&1; then
  printf "Webots is still running (PID %s). Kill with: kill %s\n" "${WEBOTS_PID}" "${WEBOTS_PID}"
else
  printf "WARNING: Webots process %s is no longer running. See log: %s\n" "${WEBOTS_PID}" "${LOG_DIR}/host-webots-sentinelmas.log" >&2
fi

if (( WEBOTS_HOLD_SECONDS > 0 )); then
  printf "Monitoring Webots for %s seconds...\n" "${WEBOTS_HOLD_SECONDS}"
  monitor_deadline=$((SECONDS + WEBOTS_HOLD_SECONDS))
  last_pose_time=""
  stagnant_since=${SECONDS}
  while (( SECONDS < monitor_deadline )); do
    if ! kill -0 "${WEBOTS_PID}" >/dev/null 2>&1; then
      printf 'ERROR: Webots exited during monitoring. See log: %s\n' "${LOG_DIR}/host-webots-sentinelmas.log" >&2
      exit 1
    fi
    pose_time="$(python3 - "${LOG_DIR}/booster_pose.json" <<'PY' 2>/dev/null || true
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    payload = json.load(fh)
print(payload.get("time", ""))
PY
)"
    if [[ -n "${pose_time}" && "${pose_time}" != "${last_pose_time}" ]]; then
      last_pose_time="${pose_time}"
      stagnant_since=${SECONDS}
      printf "Webots pose advancing: sim_time=%s\n" "${pose_time}"
    elif (( SECONDS - stagnant_since > 5 )); then
      printf 'ERROR: Webots pose file stopped advancing for more than 5 seconds. Last sim_time=%s\n' "${last_pose_time:-unknown}" >&2
      printf 'See log: %s\n' "${LOG_DIR}/host-webots-sentinelmas.log" >&2
      exit 1
    fi
    sleep 1
  done
  if [[ "${WEBOTS_CLEANUP_AFTER_HOLD}" != "0" && "${WEBOTS_CLEANUP_AFTER_HOLD}" != "false" ]]; then
    printf "Cleaning up monitored Webots/ROS runtime...\n"
    docker exec "${CONTAINER_NAME}" pkill -f booster_patrol_node 2>/dev/null || true
    docker exec "${CONTAINER_NAME}" pkill -f pose_file_odometry_publisher 2>/dev/null || true
    docker exec "${CONTAINER_NAME}" pkill -f sim_lidar_pointcloud_node 2>/dev/null || true
    docker exec "${CONTAINER_NAME}" pkill -9 -f rpc_service_node 2>/dev/null || true
    docker exec "${CONTAINER_NAME}" pkill -f mck 2>/dev/null || true
    kill "${WEBOTS_PID}" 2>/dev/null || true
  fi
fi
