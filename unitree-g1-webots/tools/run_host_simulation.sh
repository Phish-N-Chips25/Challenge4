#!/usr/bin/env bash
set -euo pipefail

# ── Resolve project root (no hardcoded paths) ───────────────────────────────
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Source platform detection helpers from the containers module
# shellcheck disable=SC1091
source "${PROJECT_ROOT}/containers/docker_common.sh"

PLATFORM="$(detect_platform)"
printf 'Detected platform: %s\n' "${PLATFORM}"

# ── Auto-detect Webots binary path per OS ────────────────────────────────────
auto_detect_webots() {
  local candidates=()
  case "$(detect_platform)" in
    linux)
      candidates=(
        /usr/local/webots/webots
        /snap/bin/webots
        /opt/webots/webots
      )
      ;;
    macos)
      candidates=(
        /Applications/Webots.app/Contents/MacOS/webots
      )
      ;;
    windows)
      # WSL — common Windows install paths accessed via /mnt/c
      candidates=(
        "/mnt/c/Program Files/Webots/msys64/mingw64/bin/webots.exe"
      )
      ;;
  esac

  for c in "${candidates[@]}"; do
    if [[ -x "${c}" ]]; then
      printf '%s\n' "${c}"
      return
    fi
  done

  # Fallback: assume webots is on PATH
  printf 'webots\n'
}

COMMAND="${1:-forward}"
DURATION="${2:-0.5}"
SERVICE_TIMEOUT=120
CONTAINER_NAME="${CONTAINER_NAME:-booster-t1-ros}"
WEBOTS_HOST_IP="${WEBOTS_HOST_IP:-$(auto_webots_host_ip "${PLATFORM}")}"
WEBOTS_PORT="${WEBOTS_PORT:-1234}"
ROBOT_NAME="${ROBOT_NAME:-T1_release}"
WEBOTS_BIN="${WEBOTS_PATH:-$(auto_detect_webots)}"
LOG_DIR="${PROJECT_ROOT}/.logs"

mkdir -p "${LOG_DIR}"

# 1. Clean up existing processes
printf "Cleaning up old processes...\n"
pkill -f webots || true
docker exec "${CONTAINER_NAME}" pkill -f mck || true
sleep 1

# 1.5. Prepare directories and extract vendor assets if missing
mkdir -p "${PROJECT_ROOT}/.docker" "${PROJECT_ROOT}/.docker/booster_runner" "${PROJECT_ROOT}/.docker/home"

if [[ ! -d "${PROJECT_ROOT}/.docker/webots" ]]; then
  printf "Extracting webots_updated.zip for controller libraries...\n"
  unzip -q "${PROJECT_ROOT}/external/booster_runner/webots_updated.zip" -d "${PROJECT_ROOT}/.docker"
fi

if [[ ! -d "${PROJECT_ROOT}/.docker/booster_runner/webots_simulation" ]]; then
  printf "Extracting webots_simulation.zip for simulation assets...\n"
  unzip -q -o "${PROJECT_ROOT}/external/booster_runner/webots_simulation.zip" -d "${PROJECT_ROOT}/.docker/booster_runner"
fi

# Always copy the tracked, corrected world file to the runtime location
printf "Syncing corrected world file to simulation path...\n"
cp "${PROJECT_ROOT}/webots/worlds/T1_break_room.wbt" "${PROJECT_ROOT}/.docker/booster_runner/webots_simulation/worlds/T1_break_room.wbt"

# 2. Start Webots on host
printf "Starting Webots on host with T1_break_room.wbt...\n"
"${WEBOTS_BIN}" --batch --stdout --stderr --mode=fast "--port=${WEBOTS_PORT}" --extern-urls \
  "${PROJECT_ROOT}/.docker/booster_runner/webots_simulation/worlds/T1_break_room.wbt" \
  > "${LOG_DIR}/host-webots-break-room.log" 2>&1 &
WEBOTS_PID=$!
echo "${WEBOTS_PID}" > "${LOG_DIR}/host-webots-break-room.pid"
sleep 2

# 3. Start booster runner inside the container
printf "Starting booster runner inside the container...\n"
docker exec "${CONTAINER_NAME}" bash -lc "
  export WEBOTS_HOME=/workspace/project/.docker/webots
  export LD_LIBRARY_PATH=\${WEBOTS_HOME}/lib/controller
  export WEBOTS_CONTROLLER_URL=tcp://${WEBOTS_HOST_IP}:${WEBOTS_PORT}/${ROBOT_NAME}
  /workspace/project/tools/start_booster_webots_runner.sh
"
sleep 5

# 4. Wait for the service to be ready
printf "Waiting for /booster_rpc_service to be ready...\n"
sleep 6

# 5. Send movement command
printf "Sending movement command: %s for %s seconds...\n" "${COMMAND}" "${DURATION}"
docker exec --interactive "${CONTAINER_NAME}" bash -lc "
  set -euo pipefail
  set +u
  source /opt/ros/humble/setup.bash
  set -u
  set +u
  source /workspace/project/.docker/ros2_install/setup.bash
  set -u
  export FASTRTPS_DEFAULT_PROFILES_FILE=\$(find /tmp -maxdepth 2 -name \"fastdds_profile.xml\" | head -n 1)
  ros2 run booster_t1_webots_test rpc_movement_client --command '${COMMAND}' --duration '${DURATION}'
"

printf "Done!\n"
