"""SentinelMAS — global configuration."""

import os

# ── Simulated sensors ────────────────────────────────────────
# When True, the reactive agents emit random events on their own.
# Set the env var SENTINEL_SIM=0 to disable them and drive the MAS
# only through trigger.py (manual events).
SIMULATED_SENSORS = False

# ── XMPP Server ──────────────────────────────────────────────
XMPP_SERVER = "localhost"
XMPP_PASSWORD = "sentinel"          # shared dev password
# Ports 5222 and 5269 are blocked on Windows (Hyper-V reserved range 5211–5310)
XMPP_PORT        = 5322   # client port (replaces 5222)
XMPP_SERVER_PORT = 5326   # S2S port    (replaces 5269)

# ── Zone definitions ─────────────────────────────────────────
# The 8 zones of the Webots office (sentinelmas_office.wbt), the single source
# of truth shared with the RL navigation stack (env.py DEFAULT_ZONE_POS).
ZONES = ["lobby", "break_room", "corridor",
         "work_room_1", "work_room_2", "work_room_3", "work_room_4", "datacenter"]

# Sensor modalities available per zone. These DRIVE the threat-fusion logic
# (threat_fusion.py keys off capability, not zone name), so the threat model
# follows whatever sensors a room has:
#   motion+camera+cyber → can reach CRITICAL (the datacenter / crown jewel)
#   motion+cyber        → HIGH  (workstations, no camera to verify a face)
#   motion+camera       → HIGH  (public space, visual ID but no cyber assets)
#   motion              → MEDIUM (transit only)
ZONE_MODALITIES = {
    "lobby":       {"motion", "camera"},
    "break_room":  {"motion", "camera"},
    "corridor":    {"motion"},
    "work_room_1": {"motion", "cyber"},
    "work_room_2": {"motion", "cyber"},
    "work_room_3": {"motion", "cyber"},
    "work_room_4": {"motion", "cyber"},
    "datacenter":  {"motion", "camera", "cyber"},
}

# ── 2D map layout ────────────────────────────────────────────
# Zone-centre positions in Webots world METRES (x in [-10,10], y in [-6,6]),
# identical to env.DEFAULT_ZONE_POS so the MAS, the planner and the policy all
# agree on where each zone is. The dashboard transforms these into its SVG
# viewBox for rendering (see dashboard.py).
ZONE_POS = {
    "lobby":       (-5.0, -3.5),
    "break_room":  ( 5.0, -3.5),
    "corridor":    ( 0.0,  0.0),
    "work_room_1": (-8.0,  3.5),
    "work_room_2": (-4.0,  3.5),
    "work_room_3": ( 0.0,  3.5),
    "work_room_4": ( 4.0,  3.5),
    "datacenter":  ( 8.0,  3.5),
}
PATROL_BASE_POS = (9.0, 0.0)    # PATROL_ROBOT spawn/dock in sentinelmas_office.wbt


def zones_with(modality: str) -> list[str]:
    """Zones whose sensor suite includes `modality` (e.g. "camera", "cyber").
    Lets reactive sensors target only the zones they can actually sense,
    without hardcoding zone names."""
    return [z for z in ZONES if modality in ZONE_MODALITIES.get(z, set())]

# Patrol movement — lower speed = slower robot = easier to watch on the map.
PATROL_SPEED = 3.0              # map units per second  (era 7.0 — mais lento = mais fácil de observar)
PATROL_SCAN_SECONDS = 5.0       # time spent inspecting a zone (era 3.0)

# Contract Net: when demand first appears, the auctioneer waits this long
# before sending the CFP, so zones that are still escalating (e.g. a combo
# that needs to settle) can also bid — prevents priority inversion.
AUCTION_GATHER_SECONDS = 1.0

# ── Auction stress-test mode ──────────────────────────────────
# When True, a StressBurstSensor fires ALL sensor types in ALL zones
# simultaneously (every STRESS_BURST_INTERVAL seconds).  This guarantees
# that multiple ZoneCoordinators escalate at the same time, so every auction
# round has real competition — ideal for validating Contract Net correctness.
# Set the env var SENTINEL_STRESS=1 to enable at runtime without editing code.
import os as _os
AUCTION_STRESS_TEST   = _os.getenv("SENTINEL_STRESS", "0") == "1"
STRESS_BURST_INTERVAL = 45   # seconds between full-system bursts (largo o suficiente para o robot completar a missão)

# ── Agent JIDs (auto-generated per zone) ─────────────────────
def jid(name: str) -> str:
    return f"{name}@{XMPP_SERVER}"

ZONE_COORDINATOR_JIDS = {z: jid(f"zc_{z}") for z in ZONES}
PATROL_JID            = jid("patrol")
MOTION_JID            = jid("motion")
FACEID_JID            = jid("faceid")
CYBER_JID             = jid("cyber_sentinel")
STAFF_REQUEST_JID     = jid("staff_request")
ALERT_JID             = jid("alert")

# ── FIPA-ACL Performatives used ──────────────────────────────
# inform   → sensor data, status updates
# request  → action commands (patrol, lock-down)
# propose  → plan suggestions between coordinators
# cfp      → call-for-proposals (auction-based task allocation)
# agree    → acceptance of a request
# refuse   → rejection of a request
# failure  → action failed notification

# ── RL navigation layer ──────────────────────────────────────
# Where the trained PPO policy and the RL modules (policy_runner, path_planner,
# env, ...) live, relative to this repo's sibling cyber-physical-security-system.
# patrol.py adds RL_DIR to sys.path and loads NAV_MODEL_PATH. Set USE_PPO_NAV=0
# to keep the legacy NavigationStub (no model / Webots needed).
_HERE = os.path.dirname(os.path.abspath(__file__))                       # .../config
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))      # .../Challenge4
RL_DIR = os.path.join(_REPO_ROOT, "cyber-physical-security-system", "src", "rl")
NAV_MODEL_PATH = os.path.join(RL_DIR, "data", "models", "nav_ppo_final")
USE_PPO_NAV = os.getenv("USE_PPO_NAV", "1") == "1"

# ── ROS 2 bridge ─────────────────────────────────────────────
ROS2_ENABLED = False                 # flip when ROS2 node is up
ROS2_CMD_VEL_TOPIC  = "/cmd_vel"
ROS2_ODOM_TOPIC     = "/odom"
ROS2_CAMERA_TOPIC   = "/camera/image_raw"
ROS2_LIDAR_TOPIC    = "/scan"

# ── Threat-level thresholds ──────────────────────────────────
THREAT_LOW    = 0
THREAT_MEDIUM = 1
THREAT_HIGH   = 2
THREAT_CRITICAL = 3
