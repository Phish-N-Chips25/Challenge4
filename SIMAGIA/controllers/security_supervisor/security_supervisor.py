"""Webots supervisor controller — thin HTTP relay to the SentinelMAS dashboard.

Receives sensor events from the other controllers via Webots Emitter/Receiver
(channel 1) and forwards them to the SentinelMAS dashboard running at
http://localhost:8081/api/webots_event.

Also:
  - Polls /api/patrol_cmd for patrol commands from the MAS.
  - Moves the PATROL_ROBOT node (teleportation) when commanded.
  - POSTs /api/patrol_arrived when the robot reaches its target.
  - Asks the patrol_robot controller to scan; waits for its report and
    POSTs /api/scan_result back to the dashboard.

Start order:
    1. python SIMAGIA/sentinel_mas/webots_dashboard.py
    2. Open Webots and press Play.
"""

import json
import math
import urllib.request
import urllib.error
import os
import sys

from controller import Supervisor

TIME_STEP = 256    # ms — must match WorldInfo.basicTimeStep
PATROL_SPEED   = 0.7   # m/s for teleport interpolation
CMD_POLL_STEP  = 3     # check for patrol commands every N steps (~0.4 s sim)
DASHBOARD_URL  = "http://localhost:8081"

# Webots zone name → MAS zone name
_ZONE_MAP = {
    "lobby":       "lobby",
    "checkpoint":  "lobby",
    "break_room":  "exterior",
    "work_room_1": "work_room_1",
    "work_room_2": "work_room_2",
    "work_room_3": "work_room_3",
    "work_room_4": "work_room_4",
    "datacenter":  "server_room",
}

# MAS zone → Webots 3D position (x, y, z)
_PATROL_POS = {
    "lobby":       (-5.0, -3.5, 0.0),
    "exterior":    ( 5.0, -3.5, 0.0),
    "work_room_1": (-8.0,  5.5, 0.0),   # beyond desk (y=4.5) so camera faces intruder
    "work_room_2": (-4.0,  5.5, 0.0),
    "work_room_3": ( 0.0,  5.5, 0.0),
    "work_room_4": ( 4.0,  5.5, 0.0),
    "server_room": ( 8.0,  3.5, 0.0),
    "__base__":    ( 9.0,  0.0, 0.0),
}

# MAS zone → canonical Webots room name (for display labels)
_MAS_TO_WEBOTS_ROOM = {
    "lobby":       "lobby",
    "exterior":    "break_room",
    "work_room_1": "work_room_1",
    "work_room_2": "work_room_2",
    "work_room_3": "work_room_3",
    "work_room_4": "work_room_4",
    "server_room": "datacenter",
}

# MAS zone → facecam robot name (for reverify relay)
_GATE_CAM = {
    "lobby":       "facecam_checkpoint",
    "exterior":    "facecam_break_room",
    "lab":         "facecam_work_room_1",
    "server_room": "facecam_datacenter",
}


# ── HTTP helpers ──────────────────────────────────────────────────────────

def _post(path: str, payload: dict) -> bool:
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        DASHBOARD_URL + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=0.5):
            return True
    except Exception:
        return False


def _get_json(path: str):
    try:
        with urllib.request.urlopen(DASHBOARD_URL + path, timeout=0.5) as r:
            return json.loads(r.read())
    except Exception:
        return None


# ── Patrol navigation ──────────────────────────────────────────────────────

class PatrolNav:
    def __init__(self, node):
        self._node   = node
        self._target: tuple | None = None

    def set_target(self, pos: tuple) -> None:
        self._target = pos

    def step(self, dt: float) -> bool:
        """Move one step. Returns True when the target is reached."""
        if self._target is None:
            return True
        field      = self._node.getField("translation")
        cx, cy, cz = field.getSFVec3f()
        tx, ty, tz = self._target
        dx, dy     = tx - cx, ty - cy
        dist       = math.hypot(dx, dy)
        if dist < 0.08:
            field.setSFVec3f([tx, ty, cz])
            self._target = None
            return True
        move = min(PATROL_SPEED * dt, dist)
        f    = move / dist
        field.setSFVec3f([cx + dx * f, cy + dy * f, cz])
        return False


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    supervisor = Supervisor()

    receiver = supervisor.getDevice("receiver")
    receiver.setChannel(1)
    receiver.enable(TIME_STEP)

    emitter = supervisor.getDevice("emitter")
    emitter.setChannel(1)

    patrol_node = supervisor.getFromDef("PATROL_ROBOT")
    nav         = PatrolNav(patrol_node)

    # All possible intruder DEF names — collect whichever exist in this world
    _ALL_INTRUDER_DEFS = [
        "PERSON_INTRUDER",
        "PERSON_INTRUDER_WR1",
        "PERSON_INTRUDER_2",
        "PERSON_INTRUDER_3",
        "PERSON_INTRUDER_4",
    ]
    intruder_nodes = []
    for def_name in _ALL_INTRUDER_DEFS:
        n = supervisor.getFromDef(def_name)
        if n is not None:
            intruder_nodes.append(n)

    # Zone bounding boxes  {zone: ((xmin, ymin), (xmax, ymax))}
    _ZONE_BBOX = {
        "lobby":       ((-10, -7), (-2,  0)),
        "exterior":    (( -2, -7), ( 9,  0)),
        "work_room_1": ((-10,  0), (-5.5, 6)),
        "work_room_2": ((-5.5, 0), (-1.5, 6)),
        "work_room_3": ((-1.5, 0), ( 2.5, 6)),
        "work_room_4": (( 2.5, 0), ( 6.5, 6)),
        "server_room": (( 6.5,-1), (11,   6)),
    }

    def _intruders_in_zone(zone: str) -> list:
        bbox = _ZONE_BBOX.get(zone)
        if bbox is None:
            return []
        (xmin, ymin), (xmax, ymax) = bbox
        found = []
        for node in intruder_nodes:
            try:
                pos = node.getField("translation").getSFVec3f()
            except Exception:
                continue
            x, y = pos[0], pos[1]
            if xmin <= x <= xmax and ymin <= y <= ymax:
                found.append(node)
        return found

    def _remove_intruders_in_zone(zone: str) -> None:
        for node in _intruders_in_zone(zone):
            try:
                node.getField("translation").setSFVec3f([0.0, -50.0, 0.0])
            except Exception:
                pass
            if node in intruder_nodes:
                intruder_nodes.remove(node)
            print(f"[Supervisor] intruso exilado de '{zone}'", flush=True)

    dt    = TIME_STEP / 1000.0
    state = "idle"      # idle | moving | scanning
    step  = 0

    print("[Supervisor] started — connecting to dashboard at", DASHBOARD_URL, flush=True)

    while supervisor.step(TIME_STEP) != -1:
        step += 1

        # ── 1. Read incoming sensor/report messages ───────────────
        while receiver.getQueueLength() > 0:
            try:
                data = json.loads(receiver.getString())
            except Exception:
                receiver.nextPacket()
                continue
            receiver.nextPacket()

            msg_type = data.get("type")

            if msg_type == "sensor":
                raw_zone = data.get("zone", "")
                mas_zone = _ZONE_MAP.get(raw_zone, raw_zone)
                # Send both the MAS zone (for agent routing) and the original
                # Webots room name (for per-room display in the dashboard)
                _post("/api/webots_event", {
                    **data,
                    "zone":        mas_zone,
                    "webots_zone": raw_zone,
                })

            elif msg_type == "report" and data.get("from") == "patrol_robot":
                if state == "scanning":
                    result      = data.get("result", "clear")
                    raw_zone    = data.get("zone", "")
                    mas_zone    = _ZONE_MAP.get(raw_zone, raw_zone)
                    webots_room = _MAS_TO_WEBOTS_ROOM.get(mas_zone, raw_zone)

                    # Camera fallback: position-based detection overrides "clear"
                    if result == "clear" and _intruders_in_zone(mas_zone):
                        result = "intruder_confirmed"
                        print(f"[Supervisor] câmara falhou — intruso confirmado por posição em '{mas_zone}'", flush=True)

                    _post("/api/scan_result", {
                        "result":      result,
                        "zone":        mas_zone,
                        "webots_zone": webots_room,
                    })
                    state = "idle"

                    if result == "intruder_confirmed":
                        _remove_intruders_in_zone(mas_zone)
                        webots_room = _MAS_TO_WEBOTS_ROOM.get(mas_zone, raw_zone)
                        _post("/api/webots_event", {
                            "type":        "sensor",
                            "event":       "patrol_report",
                            "zone":        mas_zone,
                            "webots_zone": webots_room,
                            "status":      "clear",
                        })

        # ── 2. Navigation step ────────────────────────────────────
        if state == "moving":
            # Check for cancel or relay commands even while in motion
            if step % CMD_POLL_STEP == 0:
                cmd = _get_json("/api/patrol_cmd")
                if cmd:
                    if cmd.get("action") == "cancel":
                        nav.set_target(None)      # freeze robot where it is
                        state = "idle"
                        _post("/api/patrol_preempted", {"zone": getattr(nav, "_current_zone", "")})
                        print("[Supervisor] patrol preempted mid-flight", flush=True)
                        continue
                    elif cmd.get("action") == "relay_cyber":
                        emitter.send(json.dumps({
                            "event": "cyber_anomaly",
                            "zone": cmd.get("zone", "datacenter"),
                        }))
                        print(f"[Supervisor] cyber relay → {cmd.get('zone')}", flush=True)

            if nav.step(dt):
                state = "idle"
                _post("/api/patrol_arrived", {"zone": getattr(nav, "_current_zone", "")})
            continue    # don't read new commands while moving

        # ── 3. Poll dashboard for patrol commands (idle only) ─────
        if step % CMD_POLL_STEP != 0:
            continue

        cmd = _get_json("/api/patrol_cmd")
        if not cmd:
            continue

        action = cmd.get("action")

        if action == "go_to":
            zone = cmd.get("zone", "__base__")
            pos  = _PATROL_POS.get(zone)
            if pos:
                nav.set_target(pos)
                nav._current_zone = zone
                state = "moving"
                _post("/api/patrol_moving", {"zone": zone})
                print(f"[Supervisor] patrol → {zone}", flush=True)

        elif action == "scan":
            zone  = cmd.get("zone", "")
            state = "scanning"
            emitter.send(json.dumps({
                "type": "cmd", "to": "patrol_robot",
                "action": "scan", "zone": zone,
            }))
            print(f"[Supervisor] scan → {zone}", flush=True)

        elif action == "reverify":
            zone = cmd.get("zone", "")
            cam  = _GATE_CAM.get(zone, "")
            if cam:
                emitter.send(json.dumps({
                    "type": "cmd", "to": cam,
                    "action": "reverify", "zone": zone,
                }))
                print(f"[Supervisor] reverify relay → {cam} ({zone})", flush=True)

        elif action == "relay_cyber":
            emitter.send(json.dumps({
                "event": "cyber_anomaly",
                "zone": cmd.get("zone", "datacenter"),
            }))
            print(f"[Supervisor] cyber relay → {cmd.get('zone')}", flush=True)


if __name__ == "__main__":
    main()
