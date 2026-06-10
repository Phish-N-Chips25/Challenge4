# Final Report — Booster T1 Webots ROS 2 Test

## Summary

Created a minimal Booster T1 Webots + ROS 2 smoke-test setup. The repo was empty, so this includes a minimal `break_room.wbt`, a generated `BoosterT1.proto` from official Booster assets, Apple Container scripts, a ROS 2 Humble listener package, and setup/debugging docs.

## Files changed

- `.dockerignore`
- `.gitignore`
- `containers/Containerfile`
- `containers/build_ros_container.sh`
- `containers/run_ros_container.sh`
- `containers/enter_ros_container.sh`
- `tools/import_booster_t1_proto.sh`
- `webots/protos/BoosterT1.proto`
- `webots/worlds/break_room.wbt`
- `webots/controllers/booster_t1_external/booster_t1_external.py`
- `ros2_ws/src/booster_t1_webots_test/**`
- `docs/BOOSTER_T1_WEBOTS_ROS_SETUP.md`
- `docs/DEBUGGING.md`
- `docs/FINAL_REPORT.md`

## Commands run

```bash
git status --short
git branch --show-current
git log --oneline -5
find . -name "break_room.wbt"
sw_vers
/Applications/Webots.app/Contents/MacOS/webots --version
container --version
container system start
container system status
python3 --version
git --version
git clone --depth 1 https://github.com/BoosterRobotics/booster_assets.git webots/assets/booster_assets
git clone --depth 1 https://github.com/BoosterRobotics/booster_deploy.git external/booster_deploy
git clone --depth 1 https://github.com/BoosterRobotics/booster_robotics_sdk.git external/booster_robotics_sdk
git -c filter.lfs.process= -c filter.lfs.smudge= -c filter.lfs.required=false clone --depth 1 https://github.com/BoosterRobotics/robocup_demo.git external/robocup_demo
rg -n "Webots|webots|ROS 2|ros2|T1|low_state|joint_ctrl|joint_state|sim_start|sim2sim" webots/assets/booster_assets external
python3 -m venv .venv
. .venv/bin/activate && python -m pip install --upgrade pip && python -m pip install urdf2webots
python -m urdf2webots.importer --input webots/assets/booster_assets/robots/T1/T1_locomotion.urdf --output webots/protos/BoosterT1.proto --target R2025a
PYTHONPATH=ros2_ws/src/booster_t1_webots_test python3 -m unittest discover -s ros2_ws/src/booster_t1_webots_test/test -v
python3 -m py_compile ros2_ws/src/booster_t1_webots_test/booster_t1_webots_test/*.py webots/controllers/booster_t1_external/booster_t1_external.py
./containers/build_ros_container.sh
container run --rm --mount "type=bind,source=${PROJECT_ROOT},target=/workspace/project" --workdir /workspace/project/ros2_ws booster-t1-webots-ros:humble bash -lc "source /opt/ros/humble/setup.bash && ros2 topic list && colcon build --symlink-install"
container run --rm --mount "type=bind,source=${PROJECT_ROOT},target=/workspace/project" --workdir /workspace/project/ros2_ws booster-t1-webots-ros:humble bash -lc "source /opt/ros/humble/setup.bash && source install/setup.bash && ros2 pkg executables booster_t1_webots_test && timeout 5 ros2 run booster_t1_webots_test topic_listener"
container run --rm --mount "type=bind,source=${PROJECT_ROOT},target=/workspace/project" --workdir /workspace/project/ros2_ws booster-t1-webots-ros:humble bash -lc "ip route; cat /etc/resolv.conf; hostname -I || true; ping -c 3 host.containers.internal || true; ping -c 3 host.docker.internal || true"
container run --rm --mount "type=bind,source=${PROJECT_ROOT},target=/workspace/project" --workdir /workspace/project/ros2_ws booster-t1-webots-ros:humble bash -lc "source /opt/ros/humble/setup.bash && source install/setup.bash && timeout 3 ros2 run booster_t1_webots_test simple_command_publisher"
/Applications/Webots.app/Contents/MacOS/webots --batch --mode=fast --stdout --stderr webots/worlds/break_room.wbt
```

## What works

- Apple Container starts and reports its apiserver running.
- ROS 2 Humble image builds with `webots_ros2` and `webots_ros2_driver`.
- ROS 2 workspace builds inside Apple Container.
- ROS 2 package executables install correctly.
- `topic_listener` runs and sees baseline ROS topics.
- `simple_command_publisher` publishes zero `/cmd_vel` messages.
- Webots batch-loads `webots/worlds/break_room.wbt` and waits for an external controller connection for `booster_t1`.

## What does not work yet

- No live `/joint_states` or equivalent robot data was observed because the Webots ROS bridge is not connected yet.
- Booster-specific typed `/low_state` subscription is not implemented because the custom `booster_interface` package is not included.
- Host/container DNS aliases did not resolve in Apple Container.
- Manual GUI visual confirmation of robot placement was not performed.

## ROS topics observed

```txt
/parameter_events [rcl_interfaces/msg/ParameterEvent]
/rosout [rcl_interfaces/msg/Log]
```

## Screenshots or observations

No screenshots were captured. Webots batch mode reported:

```txt
INFO: 'booster_t1' extern controller: Waiting for local or remote connection on port 1234 targeting robot named 'booster_t1'.
INFO: 'booster_t1' extern controller: disconnected.
```

## How to run again

```bash
git clone https://github.com/BoosterRobotics/booster_assets.git webots/assets/booster_assets
./tools/import_booster_t1_proto.sh
/Applications/Webots.app/Contents/MacOS/webots webots/worlds/break_room.wbt
./containers/build_ros_container.sh
./containers/run_ros_container.sh
```

Inside the container:

```bash
cd /workspace/project/ros2_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash
ros2 launch booster_t1_webots_test booster_t1_break_room.launch.py
```

## Next recommended checkpoint

Make Booster T1 publish stable joint states and test one safe zero-command publisher.
