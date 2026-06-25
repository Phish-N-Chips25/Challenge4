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

import http.client
import json
import math
import queue
import threading
import time

from controller import Supervisor

TIME_STEP    = 256   # ms — must match WorldInfo.basicTimeStep
PATROL_SPEED = 0.7   # m/s for teleport interpolation
DASHBOARD_HOST = "localhost"
DASHBOARD_PORT = 8081

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
    "work_room_1": (-8.0,  5.5, 0.0),
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


# ── Non-blocking HTTP ─────────────────────────────────────────────────────

_post_queue: queue.Queue = queue.Queue()
_cmd_queue:  queue.Queue = queue.Queue()  # FIFO — never overwrites


def _post_worker():
    """Background thread: drain post queue using a persistent connection."""
    conn = None
    while True:
        try:
            path, payload = _post_queue.get(timeout=1.0)
        except queue.Empty:
            continue
        data = json.dumps(payload).encode()
        for attempt in range(3):
            try:
                if conn is None:
                    conn = http.client.HTTPConnection(DASHBOARD_HOST, DASHBOARD_PORT, timeout=1.0)
                conn.request("POST", path, data, {"Content-Type": "application/json"})
                conn.getresponse().read()
                break
            except Exception:
                conn = None
                if attempt < 2:
                    time.sleep(0.05)


def _cmd_poll_worker():
    """Background thread: poll /api/patrol_cmd every 100 ms, enqueue each command."""
    conn = None
    while True:
        try:
            if conn is None:
                conn = http.client.HTTPConnection(DASHBOARD_HOST, DASHBOARD_PORT, timeout=1.0)
            conn.request("GET", "/api/patrol_cmd")
            r = conn.getresponse()
            raw = r.read()
            if raw:
                data = json.loads(raw)
                if data:
                    _cmd_queue.put(data)
        except Exception:
            conn = None
        time.sleep(0.1)


def _post(path: str, payload: dict) -> None:
    """Non-blocking POST — queued to background thread."""
    _post_queue.put((path, payload))


def _take_cmd() -> dict | None:
    """Return the next patrol command from the FIFO queue (non-blocking)."""
    try:
        return _cmd_queue.get_nowait()
    except queue.Empty:
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
    # Start background HTTP threads
    threading.Thread(target=_post_worker,     daemon=True).start()
    threading.Thread(target=_cmd_poll_worker, daemon=True).start()

    supervisor = Supervisor()

    receiver = supervisor.getDevice("receiver")
    receiver.setChannel(1)
    receiver.enable(TIME_STEP)

    emitter = supervisor.getDevice("emitter")
    emitter.setChannel(1)

    patrol_node = supervisor.getFromDef("PATROL_ROBOT")
    nav         = PatrolNav(patrol_node)

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
    state = "idle"

    print("[Supervisor] started — connecting to dashboard at",
          f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}", flush=True)

    while supervisor.step(TIME_STEP) != -1:

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
                        _post("/api/webots_event", {
                            "type":        "sensor",
                            "event":       "patrol_report",
                            "zone":        mas_zone,
                            "webots_zone": webots_room,
                            "status":      "clear",
                        })

        # ── 2. Navigation step ────────────────────────────────────
        if state == "moving":
            # Cancel check BEFORE nav.step — same order as original sync version.
            # If cancel arrives first, skip moving so patrol_arrived is never sent.
            cmd = _take_cmd()
            if cmd:
                if cmd.get("action") == "cancel":
                    nav.set_target(None)
                    state = "idle"
                    _post("/api/patrol_preempted", {"zone": getattr(nav, "_current_zone", "")})
                    print("[Supervisor] patrol preempted mid-flight", flush=True)
                    continue
                elif cmd.get("action") == "relay_cyber":
                    emitter.send(json.dumps({
                        "event": "cyber_anomaly",
                        "zone": cmd.get("zone", "datacenter"),
                    }))
            if nav.step(dt):
                state = "idle"
                _post("/api/patrol_arrived", {"zone": getattr(nav, "_current_zone", "")})
            continue

        # ── 3. Process latest patrol command (idle) ───────────────
        cmd = _take_cmd()
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
