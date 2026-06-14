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
ZONES = ["lobby", "server_room", "lab", "corridor", "exterior"]

# Sensor modalities available per zone (from the design table).
# Used by the threat-fusion rules and to warn on impossible injections.
ZONE_MODALITIES = {
    "lobby":       {"motion", "camera"},
    "server_room": {"motion", "camera", "cyber"},
    "lab":         {"motion", "cyber"},
    "corridor":    {"motion"},
    "exterior":    {"motion", "camera"},
}

# ── 2D map layout (top-down dashboard) ───────────────────────
# Positions on a 0..100 grid (y grows downwards), used to draw the floor plan
# and to move the patrol robot between rooms.
ZONE_POS = {
    "exterior":    (50, 13),
    "server_room": (22, 35),
    "lab":         (78, 35),
    "corridor":    (50, 57),
    "lobby":       (50, 83),
}
PATROL_BASE_POS = (50, 70)      # robot dock (idle position)

# Patrol movement — lower speed = slower robot = easier to watch on the map.
PATROL_SPEED = 3.0              # map units per second  (era 7.0 — mais lento = mais fácil de observar)
PATROL_SCAN_SECONDS = 5.0       # time spent inspecting a zone (era 3.0)

# Contract Net: when demand first appears, the auctioneer waits this long
# before sending the CFP, so zones that are still escalating (e.g. a combo
# that needs to settle) can also bid — prevents priority inversion.
AUCTION_GATHER_SECONDS = 5.0

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
