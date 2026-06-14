#!/usr/bin/env bash
set -euo pipefail

# --- ROS 2 Humble Entrypoint ---
# Sources ROS and workspace setup, configures FastDDS, then execs user command.

# Source base ROS 2 installation
# shellcheck disable=SC1091
set +u  # setup.bash may reference unset variables
source /opt/ros/humble/setup.bash
set -u

# Source workspace install overlay if it exists
WORKSPACE_INSTALL="${WORKSPACE_INSTALL:-/workspace/project/ros2_ws/install}"
if [[ -f "${WORKSPACE_INSTALL}/setup.bash" ]]; then
  # shellcheck disable=SC1091
  set +u  # setup.bash may reference unset variables
  source "${WORKSPACE_INSTALL}/setup.bash"
  set -u
fi

# Auto-detect and export FastDDS profile XML if present in /tmp
FASTDDS_PROFILE="$(find /tmp -maxdepth 2 -name 'fastdds_profile.xml' 2>/dev/null | head -n 1 || true)"
if [[ -n "${FASTDDS_PROFILE}" ]]; then
  export FASTRTPS_DEFAULT_PROFILES_FILE="${FASTDDS_PROFILE}"
fi

# Set WEBOTS_HOME from env if provided (used by Booster runner for controller libs)
if [[ -n "${WEBOTS_HOME:-}" ]]; then
  export WEBOTS_HOME
  # Ensure controller libraries are on LD_LIBRARY_PATH
  export LD_LIBRARY_PATH="${WEBOTS_HOME}/lib/controller${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
fi

# If arguments are provided, exec them; otherwise drop into bash
if [[ $# -gt 0 ]]; then
  exec "$@"
else
  exec bash
fi
