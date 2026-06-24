# Booster T1 Patrol Robot — Handoff Document

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Prerequisites & Setup](#2-prerequisites--setup)
3. [Building the Stack](#3-building-the-stack)
4. [Running the System](#4-running-the-system)
5. [Robot Movement System](#5-robot-movement-system)
6. [PPO-Based Navigation (Part 2)](#6-ppo-based-navigation-part-2)
7. [SIMAGIA Integration](#7-simagia-integration)
8. [Manual Mission Injection](#8-manual-mission-injection)
9. [ROS2 Architecture](#9-ros2-architecture)
10. [Troubleshooting](#10-troubleshooting)
11. [Bugs Fixed During Testing](#11-bugs-fixed-during-testing)

---

## 1. Project Overview

The system integrates a **Booster T1 bipedal humanoid robot** with:

- **Webots R2025a** simulation environment
- **ROS 2 Humble** for inter-process communication
- **SIMAGIA Multi-Agent System** for high-level decision making (Contract Net auction)
- **PPO Reinforcement Learning** policy for low-level navigation (Part 2)
- **Docker** container for the ROS 2 + RL stack

**Architecture layers (bottom-up):**

```
  SIMAGIA (Contract Net auction)
       |  writes missions to .logs/booster_missions.jsonl
       v
  PatrolStateMachine (mission queue / states / return-to-dock)
       |  calls go_to() on the navigation adapter
       v
  PPONavAdapter (PPO policy) OR NavigationManager (lidar-based)
       |  sends (vx, vy, vyaw) over RPC
       v
  /booster_rpc_service  →  Booster DDS bridge  →  mck locomotion engine
       |
       v
  Webots simulation (sentinelmas_office.wbt)
```

---

## 2. Prerequisites & Setup

### System Requirements
- macOS, Linux, or Windows (WSL2)
- Docker Desktop (macOS/Windows) or Docker Engine (Linux)
- Webots R2025a installed on host
- ~10 GB free disk for Docker image + vendor assets

### Required Software
| Component | macOS Path | Linux Path |
|-----------|-----------|------------|
| Webots | `/Applications/Webots.app/Contents/MacOS/webots` | `/usr/local/webots/webots` |
| Docker | Docker Desktop | Docker Engine |

### Vendor Assets (MUST download before first run)

Download these from the [Booster T1 Manual](https://www.booster.tech/open-source/) → "Development in Webots Simulation Environment":

| File | Size | Location |
|------|------|----------|
| `booster-runner-webots-full-0.0.10.run` | ~88 MB | `unitree-g1-webots/external/booster_runner/` |
| `booster-runner-webots-full-0.0.11.run` | ~88 MB | `unitree-g1-webots/external/booster_runner/` |
| `webots_simulation.zip` | ~9.7 MB | `unitree-g1-webots/external/booster_runner/` |
| `webots_updated.zip` | ~varies | `unitree-g1-webots/external/booster_runner/` |

Verify with: `./tools/check_booster_runner_assets.sh`

### Configuration Files

| File | Purpose |
|------|---------|
| `.env` | Default environment (overridden by platform) |
| `.env.macos` | macOS: `WEBOTS_PATH`, `WEBOTS_HOST_IP=host.docker.internal` |
| `.env.linux` | Linux: `WEBOTS_HOST_IP=127.0.0.1`, GPU support |
| `.env.windows` | Windows/WSL: host.docker.internal bridge |

---

## 3. Building the Stack

### Step 1: Build the Docker container

```bash
cd unitree-g1-webots
./containers/build_ros_container.sh
```

This builds `booster-t1-webots-ros:humble` from `containers/Containerfile`. Installs:
- ROS 2 Humble base + Webots ROS2 packages
- Python: `torch` (CPU), `stable-baselines3`, `gymnasium`, `pyyaml`
- `numpy>=2,<3` (pinned to avoid ABI conflicts — see bug fixes)

### Step 2: Start the container

```bash
# macOS/Windows (Docker Desktop bridge mode):
docker compose up -d ros2

# Linux (host network + GPU):
docker compose --profile linux up -d ros2
```

Or use the helper:
```bash
./containers/run_ros_container.sh
```

The container runs `sleep infinity` — stays alive for exec commands.

### Step 3: Verify the RL nav code mount

```bash
docker exec booster-t1-ros ls /workspace/rl/policy_runner.py
# Should show: /workspace/rl/policy_runner.py
```

The RL code is bind-mounted read-only from `../cyber-physical-security-system/src/rl` (set in `docker-compose.yml`).

---

## 4. Running the System

### Quick Start (PPO mode, patrol then dock movement)

```bash
USE_PPO_PATROL=1 ./tools/run_sentinelmas_booster.sh safe_dock_path
```

### Quick Start (Lidar mode, default patrol)

```bash
./tools/run_sentinelmas_booster.sh safe_dock_path
```

### What the script does (in order):

| Step | Action | Details |
|------|--------|---------|
| 1 | Asset check | Validates `.run` and `.zip` files |
| 2 | Log reset | Clears `booster_missions.jsonl`, `booster_status.jsonl`, etc. |
| 3 | ROS2 build | Runs `colcon build` inside container for `booster_interface` + `booster_t1_webots_test` |
| 4 | Webots start | Launches `worlds/sentinelmas_office.wbt` on host at `WEBOTS_PORT` (default 1234) |
| 5 | Booster runner | Extracts `.run` to `/tmp/booster_motion`, starts `mck` locomotion engine + DDS |
| 6 | ROS bridge | Starts `rpc_service_node` (ROS ↔ DDS bridge) |
| 7 | Odometry publisher | `pose_file_odometry_publisher` reads Webots JSON → `/booster_t1/odom` |
| 8 | Lidar simulator | `sim_lidar_pointcloud_node` publishes fake point cloud |
| 9 | Patrol node | Launches `ppo_patrol_node` (if `USE_PPO_PATROL=1`) or `booster_patrol_node` |
| 10 | Movement command | Sends `safe_dock_path` via `rpc_movement_client` (20s forward at 0.2 m/s) |

### Running with Mission Injection (demonstrates PPO driving)

```bash
# Terminal 1: Start infrastructure
USE_PPO_PATROL=1 ./tools/run_sentinelmas_booster.sh safe_dock_path

# Wait for "PPO patrol node started" in .logs/booster-patrol.log

# Terminal 2: Inject a mission to corridor (center of office)
echo '{"type":"DISPATCH","kind":"investigate","x":0.0,"y":0.0,"zone":"corridor","reason":"test_ppo","target":null}' \
  >> unitree-g1-webots/.logs/booster_missions.jsonl

# Monitor progress:
tail -f unitree-g1-webots/.logs/booster-patrol.log
```

### Available Movement Commands

| Command | vx | vy | vyaw | Duration |
|---------|----|----|------|----------|
| `forward` | 0.2 | 0.0 | 0.0 | `--duration` sec |
| `backward` | -0.1 | 0.0 | 0.0 | `--duration` sec |
| `left` | 0.0 | 0.1 | 0.0 | `--duration` sec |
| `right` | 0.0 | -0.1 | 0.0 | `--duration` sec |
| `turn_left` | 0.0 | 0.0 | 0.2 | `--duration` sec |
| `turn_right` | 0.0 | 0.0 | -0.2 | `--duration` sec |
| `stop` | 0.0 | 0.0 | 0.0 | N/A |

### Safe Path Commands

| Path | Steps | Description |
|------|-------|-------------|
| `safe_dock_path` | forward 20s | Dock → open corridor |
| `safe_lobby_path` | forward 2s | Short dock movement |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_PPO_PATROL` | (unset) | Set to `1` to use PPO-driven navigation |
| `WEBOTS_PORT` | `1234` | Webots external controller port |
| `ROBOT_NAME` | `T1_release` | Webots robot name |
| `SERVICE_TIMEOUT` | `120` | Seconds to wait for services |
| `WEBOTS_HOLD_SECONDS` | `0` | Keep Webots alive after command (monitoring) |
| `BOOSTER_RPC_KEEPALIVE_PERIOD` | `0.5` | RPC de-duplication window (seconds) |
| `BOOSTER_PATROL_TICK_PERIOD` | `0.1` | State machine tick interval |
| `PPO_RL_DIR` | `/workspace/rl` | RL nav code directory |
| `PPO_MODEL_PATH` | `<RL_DIR>/data/models/nav_ppo_final` | Trained PPO model |
| `SENTINEL_WBT_PATH` | `/workspace/project/worlds/sentinelmas_office.wbt` | World file for wall geometry |

---

## 5. Robot Movement System

### Movement Pipeline

```
PatrolStateMachine.tick(now)
  │
  ├─ State: idle → pop mission → start_mission() → navigate
  │
  ├─ State: navigate → for each waypoint:
  │     │
  │     ├─ If navigation_manager is set:
  │     │     navigation_manager.go_to(waypoint, now)
  │     │       │
  │     │       ├─ PPONavAdapter (PPO mode):
  │     │       │     pose + goal + prev_action → PPO policy → (vx, vy, vyaw)
  │     │       │     └─ send via RPC: make_move_request(vx, vy, vyaw)
  │     │       │
  │     │       └─ NavigationManager (lidar mode):
  │     │             lidar-based planner → (vx, vy, vyaw)
  │     │             └─ send via RPC: make_move_request(vx, vy, vyaw)
  │     │
  │     └─ If no manager: command_towards() → direct proportional control
  │
  ├─ State: onsite → wait INVESTIGATE_TIME (5s) or ASSIST_TIME (5s)
  │     → append_status("REPORT" or "ASSIST_DONE")
  │     → transition to "return"
  │
  ├─ State: return → follow waypoints back to dock
  │     → transition to "idle"
  │
  └─ State: guard → wait GUARD_TIME (10s) → return
```

### Mission State Machine (PatrolStateMachine)

File: `booster_t1_webots_test/booster_t1_webots_test/booster_patrol_node.py`

| State | Behavior |
|-------|----------|
| `idle` | Waits for missions from JSONL file. Pops highest priority mission. |
| `navigate` | Drives through waypoints toward target. PPO adapter produces velocity. |
| `pursue` | (detain only) Replans route every 1s toward live target position. |
| `onsite` | Arrived at zone. Waits then reports (investigate 5s / assist 5s). |
| `guard` | Waits 10s then returns to dock. |
| `return` | Follows waypoints back to dock coordinates. |

### RPC API

File: `booster_t1_webots_test/booster_t1_webots_test/rpc_commands.py`

| API ID | Function | Body |
|--------|----------|------|
| `2000` | Change mode | `{"mode": 0(damping), 1(prepare), 2(walking), 3(custom)}` |
| `2001` | Move | `{"vx": float, "vy": float, "vyaw": float}` |

### System Zones (World Coordinates)

From `cyber-physical-security-system/src/rl/env.py`:

| Zone | X | Y |
|------|---|---|
| Dock (start) | 9.0 | 0.0 |
| lobby | -5.0 | -3.5 |
| break_room | 5.0 | -3.5 |
| corridor | 0.0 | 0.0 |
| work_room_1 | -8.0 | 3.5 |
| work_room_2 | -4.0 | 3.5 |
| work_room_3 | 0.0 | 3.5 |
| work_room_4 | 4.0 | 3.5 |
| datacenter | 8.0 | 3.5 |

---

## 6. PPO-Based Navigation (Part 2)

### Overview

The `ppo_patrol_node.py` replaces the lidar-based `NavigationManager` with a **trained PPO policy** that produces body-frame velocity commands `(vx, vy, vyaw)` from:
1. Robot's real odometry pose `(x, y, heading)`
2. Goal position `(x, y)`
3. Previous action (for smoothness, kept in observation history)

### Two-Layer Architecture

```
GLOBAL:  path_planner.plan_path() — wall-aware A* route through doorways
         Returns waypoints that are guaranteed obstacle-free.

LOCAL:   PPO policy — drives between two consecutive waypoints
         Trained purely on open-space point-to-point navigation.
         No need to retrain for walled office — planner guarantees
         each leg is obstacle-free.
```

### Key Files

| File | Role |
|------|------|
| `ppo_patrol_node.py` | ROS2 node: PPONavAdapter + PatrolStateMachine wiring |
| `cyber-physical-security-system/src/rl/policy_runner.py` | PPONavigator: model loading + velocity_command + path planning |
| `cyber-physical-security-system/src/rl/env.py` | OfficeNavEnv: observation encoding, action rescale |
| `cyber-physical-security-system/src/rl/path_planner.py` | A* path planner through office layout |
| `cyber-physical-security-system/src/rl/office_map.py` | Office wall geometry from .wbt file |
| `cyber-physical-security-system/src/rl/data/models/nav_ppo_final.zip` | Trained PPO model (~150 KB) |

### PPONavAdapter

File: `ppo_patrol_node.py:57-113`

Implements the same interface as `NavigationManager`:
- `update_pose(pose, now)` — stores latest odometry
- `update_lidar(points, now)` — no-op (PPO ignores lidar)
- `go_to(target, now, ...)` — core method:
  1. Computes distance to target
  2. If arrived → `rpc.stop()` → return `ARRIVED`
  3. Calls `PPONavigator._predict_norm(pose, goal, prev_norm)`
  4. Rescales normalised action to real velocities via `env._rescale_action()`
  5. Sends `rpc.move(vx, vy, vyaw)`
  6. Returns `RUNNING`

### Scope

| Mission Type | Driver | Reason |
|-------------|--------|--------|
| `investigate` | PPO ✅ | Static zone target |
| `assist` | PPO ✅ | Static zone target |
| `detain` | Lidar ❌ | Needs dynamic obstacle avoidance for moving targets |

---

## 7. SIMAGIA Integration

### Data Flow

```
SIMAGIA Multi-Agent System
  │
  ├─ ConsoleInjector or patrol.py agent
  │   ↓ DISPATCH decision
  ├─ booster_mission_bridge.py
  │   ↓ appends JSONL line
  ├─ .logs/booster_missions.jsonl
  │   ↓ polled every 1s
  ├─ PatrolStateMachine._poll_missions()
  │   ↓ dequeues, plans route
  └─ PPONavAdapter/booster_patrol_node drives robot
```

### Mission JSONL Format

File: `booster_t1_webots_test/booster_t1_webots_test/patrol_mission_bridge.py`

```jsonl
{"time":123456.78,"type":"DISPATCH","kind":"investigate","x":0.0,"y":0.0,"target":null,"model":null,"zone":"corridor","reason":"test"}
```

Fields:
| Field | Type | Description |
|-------|------|-------------|
| `time` | float | Unix timestamp |
| `type` | string | Always `"DISPATCH"` for missions |
| `kind` | string | `"investigate"`, `"assist"`, or `"detain"` |
| `x`, `y` | float | Target coordinates (Webots metres) |
| `target` | string/null | Person name (for detain/assist) |
| `model` | string/null | Face model reference |
| `zone` | string/null | Zone name |
| `reason` | string | Mission reason/trigger |

### Status JSONL Format

Written by patrol node after zone arrival:

```jsonl
{"time":123457.00,"type":"REPORT","zone":"corridor","reason":"test"}
{"time":123458.00,"type":"ASSIST_DONE","name":"john","reason":"test"}
{"time":123459.00,"type":"DETAINED","name":"intruder","verified":false,"reason":"inconclusive — no camera/perception source"}
```

---

## 8. Manual Mission Injection

While the patrol node is running, inject a mission by appending to `booster_missions.jsonl`:

```bash
# Investigate corridor (simple, short distance from dock at 9,0)
echo '{"type":"DISPATCH","kind":"investigate","x":0.0,"y":0.0,"zone":"corridor","reason":"test_ppo","target":null}' \
  >> /path/to/unitree-g1-webots/.logs/booster_missions.jsonl

# Investigate work_room_1 (farther, through doorway)
echo '{"type":"DISPATCH","kind":"investigate","x":-8.0,"y":3.5,"zone":"work_room_1","reason":"test_ppo","target":null}' \
  >> /path/to/unitree-g1-webots/.logs/booster_missions.jsonl

# Assist a person at break_room
echo '{"type":"DISPATCH","kind":"assist","x":5.0,"y":-3.5,"zone":"break_room","target":"john","reason":"help_requested","model":null}' \
  >> /path/to/unitree-g1-webots/.logs/booster_missions.jsonl

# Detain (will use lidar node, not PPO)
echo '{"type":"DISPATCH","kind":"detain","x":-5.0,"y":-3.5,"zone":"lobby","target":"intruder","reason":"suspicious_activity","model":null}' \
  >> /path/to/unitree-g1-webots/.logs/booster_missions.jsonl
```

### Mission Priority

Lower number = higher priority (dequeued first):
- `detain`: priority 0
- `investigate`: priority 1
- `assist`: priority 2

Priority applies when multiple missions are queued simultaneously.

---

## 9. ROS2 Architecture

### ROS2 Services

| Service | Type | Provider | Description |
|---------|------|----------|-------------|
| `/booster_rpc_service` | `RpcService.srv` | `rpc_service_node` (Booster DDS bridge) | Send movement commands to locomotion engine |

### ROS2 Topics

| Topic | Type | Publisher | Description |
|-------|------|-----------|-------------|
| `/booster_t1/odom` | `Odometry` | `pose_file_odometry_publisher` | Robot pose from Webots simulation |
| `/booster_t1/imu` | `Imu` | `pose_file_odometry_publisher` | Simulated IMU data |
| `/booster_t1/joint_states` | `JointState` | Booster runner | Joint positions |
| `/booster_t1/low_state` | `LowState` (custom msg) | Booster runner | Motor states |

### ROS2 Nodes

| Node Executable | Source | Package | Purpose |
|----------------|--------|---------|---------|
| `topic_listener` | `topic_listener.py` | `booster_t1_webots_test` | Lists available topics |
| `joint_state_listener` | `joint_state_listener.py` | `booster_t1_webots_test` | Logs joint states |
| `imu_listener` | `imu_listener.py` | `booster_t1_webots_test` | Logs IMU data |
| `pose_file_odometry_publisher` | `pose_file_odometry_publisher.py` | `booster_t1_webots_test` | Pose JSON → ROS odometry |
| `sim_lidar_pointcloud_node` | `sim_lidar_pointcloud_node.py` | `booster_t1_webots_test` | Fake lidar data |
| `rpc_movement_client` | `rpc_movement_client.py` | `booster_t1_webots_test` | Manual movement via RPC |
| `booster_patrol_node` | `booster_patrol_node.py` | `booster_t1_webots_test` | Lidar-based mission patrol |
| `ppo_patrol_node` | `ppo_patrol_node.py` | `booster_t1_webots_test` | **PPO-driven mission patrol** |
| `booster_lidar_adapter` | `booster_lidar_adapter.py` | `booster_t1_webots_test` | Lidar data adapter |
| `booster_localization_node` | `booster_localization_node.py` | `booster_t1_webots_test` | Localization fusion |

### Infrastructure Scripts

| Script | Location | Purpose |
|--------|----------|---------|
| `build_ros_container.sh` | `containers/` | Build Docker image |
| `run_ros_container.sh` | `containers/` | Start interactive container |
| `enter_ros_container.sh` | `containers/` | Bash into running container |
| `run_sentinelmas_booster.sh` | `tools/` | **Main launcher** — starts everything |
| `start_booster_webots_runner.sh` | `tools/` | Inside container: extract + launch mck |
| `start_booster_bridge.sh` | `tools/` | Inside container: launch rpc_service_node |
| `check_booster_runner_assets.sh` | `tools/` | Verify vendor files |
| `install_booster_opt.sh` | `tools/` | Install /opt/booster config |

---

## 10. Troubleshooting

### Common Issues

| Problem | Symptom | Solution |
|---------|---------|----------|
| Bridge fails | `start_booster_bridge.sh: Permission denied` | `chmod +x tools/*.sh` |
| Model won't load | `ModuleNotFoundError: No module named 'numpy._core'` | Container has numpy 1.x; run `pip install "numpy>=2,<3"` inside |
| SB3 crashes | `AttributeError: _ARRAY_API not found` | Numpy 2.x vs OpenCV conflict; reinstall opencv-python-headless |
| Can't walk | "Walking mode ready." never appears | Check runner log for `/opt/booster` errors. Run `install_booster_opt.sh` if using 0.0.11 runner |
| RPC fails | `status=502` | Two consumers sending simultaneous RPC (patrol node + movement client). Kill one. |
| World not found | `Could not parse wall layout from...` | Set `SENTINEL_WBT_PATH` env var |
| Connection timeout | 120s timeout waiting for Webots | Check Webots is running, `WEBOTS_HOST_IP` is correct, port matches |

### Checking Logs

```bash
# Patrol node (PPO or lidar):
tail -f unitree-g1-webots/.logs/booster-patrol.log

# Webots host process:
tail -f unitree-g1-webots/.logs/host-webots-sentinelmas.log

# Booster runner (mck locomotion engine):
tail -f unitree-g1-webots/.logs/booster-webots-runner.log

# RPC bridge:
tail -f unitree-g1-webots/.logs/booster-bridge.log

# Pose odometry:
tail -f unitree-g1-webots/.logs/pose-file-odometry.log
```

### Quick Container Checks

```bash
# Verify RL code mount
docker exec booster-t1-ros ls /workspace/rl/

# Verify model loads
docker exec booster-t1-ros bash -lc 'python3 -c "
import sys; sys.path.insert(0, \"/workspace/rl\")
from policy_runner import PPONavigator
nav = PPONavigator(\"/workspace/rl/data/models/nav_ppo_final\")
print(\"OK:\", nav.velocity_command((0,0,0), (2,0)))
"'

# Check RPC service
docker exec booster-t1-ros bash -lc '
  source /opt/ros/humble/setup.bash
  source /workspace/project/ros2_ws/install/setup.bash
  ros2 service list | grep booster_rpc
'

# Rebuild workspace after code changes
docker exec booster-t1-ros bash -lc '
  source /opt/ros/humble/setup.bash
  cd /workspace/project/ros2_ws
  colcon build --symlink-install --packages-select booster_interface booster_t1_webots_test
'
```

---

## 11. Bugs Fixed During Testing

### Bug 1: Numpy Version Mismatch

**Problem**: PPO model was trained with numpy 2.x, but the Docker container had numpy 1.21.5 from Ubuntu 22.04 apt. Loading the model gave: `ModuleNotFoundError: No module named 'numpy._core'`

**Fix**: Updated `containers/Containerfile:71-72` to pin `numpy>=2,<3`:
```dockerfile
RUN pip3 install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip3 install --no-cache-dir "numpy>=2,<3" \
 && pip3 install --no-cache-dir stable-baselines3 gymnasium pyyaml
```

**Container rebuild required** after this change, or run in running container:
```bash
docker exec booster-t1-ros pip3 install "numpy>=2,<3"
```

### Bug 2: PatrolStateMachine.update_pose() Wrong Argument Count

**Problem**: `ppo_patrol_node.py:242` called `machine.update_pose(Pose2D(p.x, p.y, yaw), time.time())` but `PatrolStateMachine.update_pose()` only accepts `(self, pose)` — no timestamp parameter.

**Fix**: Removed the extra `time.time()` argument:
```python
# Before (broken):
machine.update_pose(Pose2D(p.x, p.y, yaw), time.time())

# After (fixed):
machine.update_pose(Pose2D(p.x, p.y, yaw))
```

The PPO adapter's own `update_pose()` (line 80) accepts a `now` parameter, but the state machine's method does not.

### Known Limitation: PPO Adapter RPC Collision

When running `run_sentinelmas_booster.sh`, the script launches both the PPO patrol node AND a separate `rpc_movement_client` that sends manual movement commands. The PPO adapter and the movement client both call the same `/booster_rpc_service`, causing `status=502` errors for one of them. This does **not** crash the system but slows robot progress.

To avoid this: either (a) run the infrastructure script with `WEBOTS_HOLD_SECONDS` and inject missions manually, or (b) modify the script to skip the movement command when `USE_PPO_PATROL=1`.
