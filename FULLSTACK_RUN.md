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

## Start everything

Run this from the repository root:

```bash
./scripts/run_fullstack.py
```

The launcher replaces the old terminal-by-terminal sequence. It:

1. Checks the repo layout, Docker, Docker Compose, Webots, Booster assets, and SIMAGIA Python.
2. Uses the existing `.venv-simagia310` or `SIMALGIA_PYTHON` when available, and skips `pip install` when `spade`, `aiohttp`, `loguru`, and `pyjabber` already import.
3. Starts/reuses the Booster Docker container first (`docker compose up -d ros2`).
4. Verifies the RL mount (`/workspace/rl/policy_runner.py`).
5. Runs `unitree-g1-webots/tools/run_sentinelmas_booster.sh`, which starts Webots, Booster runner, ROS bridge, odometry, lidar, and PPO patrol.
6. Starts SIMAGIA with `USE_BOOSTER_BRIDGE=1 python main.py --web` and writes logs to `unitree-g1-webots/.logs/simagia.log`.

Useful options:

```bash
./scripts/run_fullstack.py --dry-run                  # print the plan without starting anything
./scripts/run_fullstack.py --detach                   # leave SIMAGIA running and return
./scripts/run_fullstack.py --rebuild-booster          # force Docker image rebuild
./scripts/run_fullstack.py --simagia-python /path/to/python
./scripts/run_fullstack.py --no-install-simagia-deps  # check imports only
```

Watch logs in separate terminals:
```bash
tail -f unitree-g1-webots/.logs/booster-patrol.log     # PPO patrol node
tail -f unitree-g1-webots/.logs/booster-webots-runner.log  # locomotion engine
tail -f unitree-g1-webots/.logs/host-webots-sentinelmas.log # Webots
tail -f unitree-g1-webots/.logs/simagia.log            # SIMAGIA
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

## Watch the pipeline in action

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
# Foreground run: Ctrl+C stops SIMAGIA.

# Detached run:
kill "$(cat unitree-g1-webots/.logs/simagia.pid)"

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

`run_sentinelmas_booster.sh` now starts PPO patrol by default and skips the final manual `rpc_movement_client` command. Set `USE_PPO_PATROL=0` for the lidar patrol node, or `BOOSTER_SEND_MANUAL_COMMAND=1` only when you deliberately want to send a manual RPC command after startup.
