# SentinelMAS — Autonomous Security Patrol (Challenge 4)

A simulated office-security system that ties together **multi-agent decision
making**, **reinforcement-learning navigation**, **facial recognition**, and a
**bipedal robot** (Booster T1) in Webots. A recognised intruder triggers a
multi-agent auction that dispatches a patrol robot, which navigates to the zone
with a trained policy.

> **One-line status:** the full software pipeline (perception → decision →
> navigation) works today in pure Python; the physical-robot leg is integrated
> and renders in Webots, blocked only on a proprietary vendor walk-config.

---

## 1. Architecture

Three layers, each independently runnable, connected by thin bridges:

```
          PERCEPTION                 DECISION                  NAVIGATION                 ACTUATION
  ┌───────────────────────┐  ┌────────────────────┐  ┌────────────────────────┐  ┌──────────────────┐
  │ InsightFace recogniser │  │ SIMAGIA (SPADE MAS)│  │ PPO policy + A* planner│  │ Booster T1 (Webots│
  │ (alt1.py)              │─▶│ Contract Net auction│─▶│ (cyber-physical-...)   │─▶│  + ROS2 + runner) │
  │ known vs intruder      │  │ threat fusion       │  │ wall-aware waypoints   │  │  /booster_rpc_svc │
  └───────────────────────┘  └────────────────────┘  └────────────────────────┘  └──────────────────┘
        FaceIDAgent              ZoneCoordinators          PPONavigator              ppo_patrol_node
```

| Layer | Lives in | What it does |
|---|---|---|
| **Perception** | `SIMAGIA/alt1.py` + `face_bridge.py` | InsightFace (`buffalo_sc`) matches a face against known staff; unknown → intruder |
| **Decision** | `SIMAGIA/sentinel_mas/` | SPADE multi-agent system: ZoneCoordinators bid in a Contract Net auction; threat fusion keyed on each zone's sensor modalities |
| **Navigation** | `cyber-physical-security-system/src/rl/` | PPO policy drives between A*-planned, wall-free waypoints (layout-agnostic) |
| **Actuation** | `unitree-g1-webots/` | Booster T1 in Webots, driven over ROS2 `/booster_rpc_service` |

### Coordinate frame
All layers share **one frame**: the 8-zone office in Webots metres
(x∈[-10,10], y∈[-6,6]). The 8 zones — `lobby, break_room, corridor,
work_room_1..4, datacenter` — are identical across SIMAGIA, the RL env, and the
robot's `controllers/common/zones.py`.

---

## 2. The integration bridges

The three layers were built separately and are joined by two soft-failing
bridges (both degrade gracefully if their dependency is absent):

- **`SIMAGIA/sentinel_mas/bridges/face_bridge.py`** — loads the InsightFace
  model; if the ML deps are missing the FaceIDAgent falls back to a simulated
  sensor.
- **`SIMAGIA/sentinel_mas/bridges/nav_bridge.py`** — selects the navigator:
  `PPONavigator` (in-process PPO) by default, or `BoosterBridgeNavigator`
  (dispatch to the real robot) when `USE_BOOSTER_BRIDGE=1`.
- **`SIMAGIA/sentinel_mas/bridges/booster_mission_bridge.py`** (Part 1) —
  SIMAGIA writes missions to the JSONL seam `.logs/booster_missions.jsonl`;
  reads status/pose back. Byte-compatible with the robot's
  `patrol_mission_bridge.py`.
- **`unitree-g1-webots/.../ppo_patrol_node.py`** (Part 2) — on the robot side,
  reuses the colleague's `PatrolStateMachine` but swaps the lidar navigator for
  a PPO-backed one, so **the trained policy drives the Booster T1**.

### The "SIMAGIA decides, PPO drives" loop
```
SIMAGIA auction → booster_mission_bridge → .logs/booster_missions.jsonl
                                                    │
                                        ppo_patrol_node (in container)
                                          PPO policy + real odometry
                                                    │
                                    make_move_request(vx,vy,vyaw) → robot
                                                    │
                       .logs/booster_status.jsonl → SIMAGIA (mission done)
```
`detain` (chasing a moving target) stays on the robot's lidar
`booster_patrol_node` — PPO+A* only avoids *static* walls.

---

## 3. How to run

### A. Pure-Python demo — works today, no robot needed
The complete perception → decision → navigation loop, with the live dashboard:
```bash
conda activate cyberpatrol
cd SIMAGIA/sentinel_mas
python main.py --web          # open http://localhost:8080
```
You'll see the office floor plan; the **FaceIDAgent recognises faces** (camera
zones), an **intruder escalates threat → auction → the PPO robot is dispatched**
and routes through doorways on the map.

Env requirements (one conda env, `cyberpatrol`): `torch`, `stable-baselines3`,
`gymnasium` (RL) · `spade`, `aiohttp`, `pyjabber`, `loguru` (MAS) ·
`insightface`, `opencv-python`, `scikit-learn`, `onnxruntime` (face). Each
bridge soft-falls-back if its group is missing.

### B. RL navigation — train / evaluate / demo
```bash
cd cyber-physical-security-system/src/rl
python eval_model.py             # per-zone arrival rate
python validate_trajectories.py  # wall-clearance of the real PPO trajectories
python live_demo.py              # click a zone, watch the robot drive there
```

### C. Webots + Booster T1 (Windows/WSL2)
Builds and **renders the office world with the T1**; walking needs the vendor
config (see §4):
```bash
# in WSL2 Ubuntu:
cd unitree-g1-webots
./tools/run_sentinelmas_booster.sh                 # lidar patrol node (their nav)
USE_PPO_PATROL=1 ./tools/run_sentinelmas_booster.sh  # PPO drives (Part 2)
```

---

## 4. Current status & the one blocker

| Component | State |
|---|---|
| RL navigation (PPO + A*) | ✅ 100% zone arrival, 0/56 wall-clearance failures |
| SIMAGIA MAS | ✅ Contract Net + modality-based threat fusion on the office |
| Face recognition | ✅ integrated & verified (known→authorised, intruder→threat→patrol) |
| Booster stack in Webots | ✅ builds, loads the office world, T1 renders & connects |
| **Robot walking** | 🔒 **blocked** — needs vendor `/opt/booster` calibration |
| Part 2 (PPO drives robot) | ✅ built, ⏳ untestable until the robot walks |

**The blocker:** the Booster 0.0.11 runner needs per-robot calibration
(`/opt/booster/configs/{robot_config,system_settings_config}.yaml`) that it does
not ship. Supply it via `tools/install_booster_opt.sh` (drop the vendor config
in `external/booster_runner/`) or use the `0.0.10` runner (bundled defaults).
Until then the robot stands but does not walk; everything else runs.

---

## 5. Results (headline)

- **PPO navigation:** layout-agnostic 8-D observation (no absolute position),
  100% arrival across all 8 zones from random starts, **0/56** routes within the
  robot radius of a wall (min clearance 0.39 m).
- **Face recognition:** known staff matched at score > 0.82, intruders < 0.11
  (threshold 0.65) — clean separation on the test pool.

---

## 6. Repository layout

```
Challenge4/
├── cyber-physical-security-system/   # RL navigation (PPO + A* planner)
│   └── src/rl/                        #   env, policy_runner, path_planner, models
├── SIMAGIA/                           # multi-agent system + perception
│   ├── alt1.py + faces/ + .cache/     #   InsightFace model + DB
│   └── sentinel_mas/                  #   SPADE agents, bridges, dashboard
└── unitree-g1-webots/                 # Booster T1 Webots + ROS2 stack
    ├── worlds/sentinelmas_office.wbt  #   office world with the T1
    ├── controllers/                   #   Webots supervisor + zones
    └── ros2_ws/.../ppo_patrol_node.py #   Part 2: PPO drives the robot
```

See each subproject's own notes; the integration-specific design is documented
in the bridges and `ppo_patrol_node.py` docstrings.
