#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/docker_common.sh"

docker exec --interactive --tty "${CONTAINER_NAME}" bash -lc "source /opt/ros/humble/setup.bash && exec bash"
