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
ZONES = ["lobby", "server_room", "work_room_1", "work_room_2", "work_room_3", "work_room_4", "exterior"]

# Sensor modalities available per zone (from the design table).
# Used by the threat-fusion rules and to warn on impossible injections.
ZONE_MODALITIES = {
    "lobby":       {"motion", "camera"},
    "server_room": {"motion", "camera", "cyber"},
    "work_room_1": {"motion", "camera", "cyber"},
    "work_room_2": {"motion", "camera", "cyber"},
    "work_room_3": {"motion", "camera", "cyber"},
    "work_room_4": {"motion", "camera", "cyber"},
    "exterior":    {"motion", "camera"},
}

# ── 2D map layout (top-down dashboard) ───────────────────────
# Positions on a 0..100 grid (y grows downwards), used to draw the floor plan
# and to move the patrol robot between rooms.
ZONE_POS = {
    "exterior":    (50, 13),
    "work_room_1": (12, 35),
    "work_room_2": (33, 35),
    "work_room_3": (55, 35),
    "work_room_4": (75, 35),
    "server_room": (92, 35),
    "lobby":       (50, 83),
}
PATROL_BASE_POS = (50, 70)      # robot dock (idle position)

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

# ── Webots integration ───────────────────────────────────────
# Set to True by security_supervisor.py before starting the MAS thread.
WEBOTS_ENABLED = False
WEBOTS_BRIDGE = None   # WebotsBridge instance, set at runtime

# Webots zone name → MAS zone name
# work_room_1..4 all aggregate into "lab"; break_room maps to "exterior".
WEBOTS_ZONE_MAP: dict[str, str] = {
    "lobby":        "lobby",
    "checkpoint":   "lobby",
    "break_room":   "exterior",
    "work_room_1":  "work_room_1",
    "work_room_2":  "work_room_2",
    "work_room_3":  "work_room_3",
    "work_room_4":  "work_room_4",
    "datacenter":   "server_room",
}

# Webots 3D patrol positions for each MAS zone (x, y, z).
# Derived from the zone-mark centres in sentinelmas_office.wbt.
WEBOTS_PATROL_POSITIONS: dict[str, tuple] = {
    "lobby":       (-5.0, -3.5, 0.0),
    "exterior":    ( 5.0, -3.5, 0.0),
    "work_room_1": (-8.0,  3.5, 0.0),
    "work_room_2": (-4.0,  3.5, 0.0),
    "work_room_3": ( 0.0,  3.5, 0.0),
    "work_room_4": ( 4.0,  3.5, 0.0),
    "server_room": ( 8.0,  3.5, 0.0),
}
WEBOTS_PATROL_BASE: tuple = (9.0, 0.0, 0.0)

# Reverse map: 2D dashboard position → MAS zone name (for WebotsNavigation)
WEBOTS_POS_TO_ZONE: dict[tuple, str] = {
    v: k for k, v in ZONE_POS.items()
}
WEBOTS_POS_TO_ZONE[PATROL_BASE_POS] = "__base__"
