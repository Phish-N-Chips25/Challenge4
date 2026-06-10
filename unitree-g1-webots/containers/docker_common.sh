#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_NAME="${IMAGE_NAME:-booster-t1-webots-ros:humble}"
CONTAINER_NAME="${CONTAINER_NAME:-booster-t1-ros}"

# ── Platform Detection ───────────────────────────────────────────────────────

detect_platform() {
  # Returns 'linux', 'macos', or 'windows' based on the host OS.
  # On WSL (Windows Subsystem for Linux) returns 'windows'.
  local uname_s
  uname_s="$(uname -s)"
  case "${uname_s}" in
    Linux*)
      # Check for WSL (Windows Subsystem for Linux)
      if grep -qiE '(microsoft|wsl)' /proc/version 2>/dev/null; then
        printf 'windows\n'
      else
        printf 'linux\n'
      fi
      ;;
    Darwin*)
      printf 'macos\n'
      ;;
    CYGWIN*|MINGW*|MSYS*)
      printf 'windows\n'
      ;;
    *)
      printf 'linux\n'  # Default fallback
      ;;
  esac
}

auto_webots_host_ip() {
  # Returns the correct IP for the container to reach Webots on the host.
  # Linux: 127.0.0.1 (host network mode)
  # macOS/Windows: host.docker.internal (Docker Desktop bridge)
  local platform="${1:-$(detect_platform)}"
  case "${platform}" in
    linux)   printf '127.0.0.1\n' ;;
    macos)   printf 'host.docker.internal\n' ;;
    windows) printf 'host.docker.internal\n' ;;
    *)       printf '127.0.0.1\n' ;;
  esac
}

auto_webots_path() {
  # Returns the default Webots binary path for the detected platform.
  local platform="${1:-$(detect_platform)}"
  case "${platform}" in
    linux)   printf '/usr/local/webots/webots\n' ;;
    macos)   printf '/Applications/Webots.app/Contents/MacOS/webots\n' ;;
    windows) printf 'C:\\Program Files\\Webots\\msys64\\mingw64\\bin\\webots.exe\n' ;;
    *)       printf 'webots\n' ;;
  esac
}

# ── Docker State Directories ─────────────────────────────────────────────────

ensure_docker_state_dirs() {
  mkdir -p \
    "${PROJECT_ROOT}/.docker/home" \
    "${PROJECT_ROOT}/.docker/webots" \
    "${PROJECT_ROOT}/.docker/booster_runner" \
    "${PROJECT_ROOT}/.logs"
}

# ── GPU Detection ────────────────────────────────────────────────────────────

docker_gpu_available() {
  command -v nvidia-smi >/dev/null 2>&1 || return 1
  nvidia-smi >/dev/null 2>&1 || return 1
  docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q '"nvidia"'
}

# ── Docker Desktop Detection ────────────────────────────────────────────────

docker_daemon_is_desktop() {
  docker info --format '{{.Name}} {{.OperatingSystem}}' 2>/dev/null | grep -qi 'docker-desktop\|Docker Desktop'
}

# ── Runtime Argument Builder ─────────────────────────────────────────────────

append_runtime_args() {
  local -n args_ref="$1"
  local platform
  platform="$(detect_platform)"

  # Network mode: --network host only on native Linux (not WSL/Docker Desktop)
  if [[ "${platform}" == "linux" ]]; then
    args_ref+=(
      --network host
      --ipc host
    )
  fi

  args_ref+=(
    --privileged
    --shm-size 4g
    --ulimit memlock=-1:-1
    --ulimit stack=67108864
  )

  # User mapping: skip on Windows/WSL where uid/gid mapping doesn't apply
  if [[ "${platform}" != "windows" ]]; then
    args_ref+=(
      --user "$(id -u):$(id -g)"
    )
  fi

  args_ref+=(
    --env "HOME=/workspace/project/.docker/home"
    --env "USER=${USER:-booster}"
    --env "USERNAME=${USER:-booster}"
    --env "DISPLAY=${DISPLAY:-}"
    --env "QT_X11_NO_MITSHM=1"
    --env "USE_XVFB=${USE_XVFB:-auto}"
    --env "MAKEFLAGS=-j$(nproc)"
    --env "WEBOTS_HOST_IP=${WEBOTS_HOST_IP:-$(auto_webots_host_ip "${platform}")}"
    --env "WEBOTS_PORT=${WEBOTS_PORT:-1234}"
    --env "ROBOT_NAME=${ROBOT_NAME:-T1_release}"
    --mount "type=bind,source=${PROJECT_ROOT},target=/workspace/project"
  )

  # X11 socket forwarding: only on native Linux with X11 present
  if [[ "${USE_X11:-auto}" != "0" && -d /tmp/.X11-unix ]] && ! docker_daemon_is_desktop; then
    args_ref+=(--mount "type=bind,source=/tmp/.X11-unix,target=/tmp/.X11-unix")
  fi

  if [[ -n "${XAUTHORITY:-}" && -f "${XAUTHORITY}" ]] && ! docker_daemon_is_desktop; then
    args_ref+=(
      --env "XAUTHORITY=/tmp/.docker.xauth"
      --mount "type=bind,source=${XAUTHORITY},target=/tmp/.docker.xauth,readonly"
    )
  fi

  if [[ -e /dev/dri ]]; then
    args_ref+=(--device /dev/dri)
  fi

  if [[ -n "${DOCKER_GPU_ARGS:-}" ]]; then
    # shellcheck disable=SC2206
    local gpu_args=( ${DOCKER_GPU_ARGS} )
    args_ref+=("${gpu_args[@]}")
  elif docker_gpu_available; then
    args_ref+=(
      --gpus all
      --env NVIDIA_VISIBLE_DEVICES=all
      --env NVIDIA_DRIVER_CAPABILITIES=all,graphics,display,compute,utility
    )
  else
    printf 'Docker GPU passthrough disabled: NVIDIA runtime or host nvidia-smi is not healthy.\n' >&2
  fi
}

# ── Container State Helpers ──────────────────────────────────────────────────

container_is_running() {
  docker inspect -f '{{.State.Running}}' "${CONTAINER_NAME}" 2>/dev/null | grep -q '^true$'
}

ensure_container_running() {
  ensure_docker_state_dirs

  if container_is_running; then
    return
  fi

  if docker inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
    docker rm "${CONTAINER_NAME}" >/dev/null
  fi

  local args=(run --name "${CONTAINER_NAME}" --detach)
  append_runtime_args args
  args+=(--workdir /workspace/project/ros2_ws "${IMAGE_NAME}" sleep infinity)

  docker "${args[@]}" >/dev/null
}
