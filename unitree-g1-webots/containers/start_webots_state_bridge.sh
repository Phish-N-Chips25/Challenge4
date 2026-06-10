#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/docker_common.sh"

CONTAINER_NAME="${CONTAINER_NAME:-booster-t1-ros}"
WEBOTS_HOST_IP="${WEBOTS_HOST_IP:-127.0.0.1}"
WEBOTS_PORT="${WEBOTS_PORT:-1234}"
ROBOT_NAME="${ROBOT_NAME:-T1_release}"

docker exec "${CONTAINER_NAME}" bash -lc "
  set -euo pipefail
  set +u
  source /opt/ros/humble/setup.bash
  set -u
  cd /workspace/project/ros2_ws
  colcon build --symlink-install --parallel-workers \$(nproc) \
    --build-base /workspace/project/.docker/ros2_build \
    --install-base /workspace/project/.docker/ros2_install \
    --packages-select booster_t1_webots_test
  set +u
  source /workspace/project/.docker/ros2_install/setup.bash
  set -u
  WEBOTS_HOME=/opt/ros/humble \
    /opt/ros/humble/share/webots_ros2_driver/scripts/webots-controller \
      --protocol=tcp \
      --ip-address=${WEBOTS_HOST_IP} \
      --port=${WEBOTS_PORT} \
      --robot-name=${ROBOT_NAME} \
      /workspace/project/.docker/ros2_install/booster_t1_webots_test/lib/booster_t1_webots_test/webots_state_publisher
"
