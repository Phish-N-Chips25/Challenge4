# Full-Stack Run Guide — SentinelMAS

This guide runs **all three layers** together: SIMAGIA decides → PPO navigates → Booster T1 walks in Webots.

## Prerequisites

| Item | Check |
|---|---|
| Webots R2025a installed | macOS: `/Applications/Webots.app` |
| Docker Desktop | Running, `linux/amd64` emulation enabled (macOS ARM) |
| Booster vendor assets | `booster-runner-webots-full-0.0.10.run` + `webots_simulation.zip` + `webots_updated.zip` in `unitree-g1-webots/external/booster_runner/` |
| Conda env `cyberpatrol` | `torch`, `stable-baselines3`, `gymnasium`, `spade`, `aiohttp`, `insightface`, `opencv-python` |
| ~10 GB free disk | Docker image + vendor assets |

---

## Step 1 — Build & start the Docker container

```bash
cd unitree-g1-webots
./containers/build_ros_container.sh
docker compose up -d ros2
```

This builds `booster-t1-webots-ros:humble` (ROS 2 Humble + torch + SB3) and starts it. The container bind-mounts both `unitree-g1-webots` (as `/workspace/project`) and `../cyber-physical-security-system/src/rl` (as `/workspace/rl`, read-only).

Verify:
```bash
docker exec booster-t1-ros ls /workspace/rl/policy_runner.py
```

---

## Step 2 — Launch the Booster stack (Webots + ROS 2)

```bash
cd unitree-g1-webots
USE_PPO_PATROL=1 ./tools/run_sentinelmas_booster.sh safe_dock_path
```

What this does (all automated by the script):

1. **Extracts** vendor assets to `.docker/`
2. **Builds** the ROS 2 workspace (`colcon build`)
3. **Launches Webots** on the host with `worlds/sentinelmas_office.wbt`
4. **Starts the Booster runner** (`mck` locomotion engine + DDS) inside the container
5. **Starts the ROS bridge** (`rpc_service_node` — ROS ↔ DDS)
6. **Starts odometry publisher** (Webots pose → `/booster_t1/odom`)
7. **Starts simulated lidar** (`sim_lidar_pointcloud_node`)
8. **Starts `ppo_patrol_node`** (PPO-driven mission patrol — reads missions from JSONL, drives robot via RPC)
9. **Sends `safe_dock_path`** movement as a demo (robot walks forward 20s)

Watch logs in separate terminals:
```bash
tail -f unitree-g1-webots/.logs/booster-patrol.log     # PPO patrol node
tail -f unitree-g1-webots/.logs/booster-webots-runner.log  # locomotion engine
tail -f unitree-g1-webots/.logs/host-webots-sentinelmas.log # Webots
```

---

## Step 3 — Start SIMAGIA (perception + decision)

In a **new terminal** (on the host, not inside Docker):

```bash
conda activate cyberpatrol
cd SIMAGIA/sentinel_mas
USE_BOOSTER_BRIDGE=1 python main.py --web
```

Key env vars for the bridge mode:

| Env var | Value | Effect |
|---|---|---|
| `USE_BOOSTER_BRIDGE=1` | REQUIRED | SIMAGIA writes missions to `unitree-g1-webots/.logs/booster_missions.jsonl` instead of simulating movement in-process |
| `USE_PPO_NAV=1` | (default) | In-process PPO fallback — irrelevant when bridge is on |
| `SENTINEL_SIM=1` | Optional | Enables simulated sensor events (motion, face, cyber) so the demo is self-driving |
| `SENTINEL_STRESS=1` | Optional | Fires all sensors in all zones simultaneously for auction stress-testing |

Open `http://localhost:8080` for the live dashboard — you'll see the office map, agent positions, and threat levels.

---

## Step 4 — Watch the pipeline in action

1. **SIMAGIA** generates sensor events (motion/camera/cyber) in random zones
2. **Threat fusion** escalates — when a zone hits HIGH/CRITICAL, a **Contract Net auction** runs
3. The winning zone dispatches a **mission** → written to `booster_missions.jsonl`
4. **`ppo_patrol_node`** polls the JSONL, plans an A\* route through doorways, and drives the **Booster T1** using the trained PPO policy
5. The robot arrives, scans, reports back via `booster_status.jsonl`
6. SIMAGIA's dashboard shows the robot moving in real time (pose mirrored from `booster_pose.json`)

---

## Step 5 — Inject a manual mission (optional)

While the stack runs, manually dispatch the robot to any zone:

```bash
echo '{"type":"DISPATCH","kind":"investigate","x":0.0,"y":0.0,"zone":"corridor","reason":"manual","target":null}' \
  >> unitree-g1-webots/.logs/booster_missions.jsonl
```

Zone coordinates for reference:

| Zone | X | Y |
|---|---|---|
| lobby | -5.0 | -3.5 |
| break_room | 5.0 | -3.5 |
| corridor | 0.0 | 0.0 |
| work_room_1 | -8.0 | 3.5 |
| work_room_2 | -4.0 | 3.5 |
| work_room_3 | 0.0 | 3.5 |
| work_room_4 | 4.0 | 3.5 |
| datacenter | 8.0 | 3.5 |

---

## Shutdown

```bash
# Stop SIMAGIA — Ctrl+C in its terminal

# Stop Webots + container processes
cd unitree-g1-webots
docker compose down

# Or just stop the container to keep it for next time:
docker stop booster-t1-ros
```

---

## Architecture data flow

```
  SIMAGIA (perception + auction)
     │  USE_BOOSTER_BRIDGE=1
     │  writes to .logs/booster_missions.jsonl
     ▼
  ppo_patrol_node (in Docker container)
     │  A* planner → PPO policy → (vx, vy, vyaw)
     │  calls /booster_rpc_service
     ▼
  rpc_service_node (ROS ↔ DDS bridge)
     │
     ▼
  mck locomotion engine → Booster T1 in Webots
     │
     ▼
  .logs/booster_pose.json ← SIMAGIA reads for dashboard
```

---

## Known caveat

The `run_sentinelmas_booster.sh` script sends a final `rpc_movement_client` command after launching the patrol node. When `USE_PPO_PATROL=1`, this causes an RPC collision (two consumers calling `/booster_rpc_service`). It does **not** crash the system but can slow robot movement. To avoid it, set `WEBOTS_HOLD_SECONDS=60` and inject missions manually instead.
