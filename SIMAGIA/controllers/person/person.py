"""Webots controller for simulated office people.

Each person follows a route built from SCENARIO config below.
All characters share this single controller file; the robot's
NAME field (set in the .wbt) selects which scenario entry to use.

Supports single-room destinations and multi-room looping routes.
"""

import math
from controller import Supervisor

TIME_STEP    = 256    # ms — must match WorldInfo.basicTimeStep
SPEED        = 0.6    # m/s — walking pace
THRESHOLD    = 0.15   # m   — distance to consider a waypoint reached
PAUSE_IN_ROOM = 45   # steps to pause inside each room before moving on (~12 s)


# ═══════════════════════════════════════════════════════════════
#  SCENARIO CONFIG
# ═══════════════════════════════════════════════════════════════
#
#  active  : True = entra em cena
#  delay   : segundos antes de começar a andar
#  route   : lista de salas a visitar em loop
#             ["work_room_1"]                    — fica numa sala
#             ["work_room_1", "work_room_2"]     — vai entre duas salas
#             ["work_room_1", "work_room_3", "server_room"]  — percurso
#
#  Salas disponíveis: lobby, work_room_1..4, server_room
#
# ═══════════════════════════════════════════════════════════════
SCENARIO = {
    "Arsénio":    {"active": False, "delay":  0, "route": ["work_room_1"]},
    "César":      {"active": False, "delay":  0, "route": ["work_room_2"]},
    "Gonçalo":    {"active": False, "delay":  0, "route": ["work_room_3"]},
    "Rui Soares": {"active": False, "delay":  0, "route": ["work_room_4"]},
    "Rynalde":    {"active": False, "delay":  0, "route": ["server_room"]},
    "Intruder":   {"active": True,  "delay":  0, "route": ["work_room_2"]},
    "Intruder2":  {"active": False, "delay":  0, "route": ["work_room_1"]},
    "Intruder3":  {"active": False, "delay":  0, "route": ["work_room_4"]},
    "Intruder4":  {"active": False, "delay":  0, "route": ["work_room_2"]},
}
# ═══════════════════════════════════════════════════════════════


# ── Geometry ───────────────────────────────────────────────────

_START_X = {
    "Arsénio":    -5.0,
    "César":      -3.5,
    "Gonçalo":    -6.5,
    "Rui Soares": -4.8,
    "Rynalde":    -6.0,
    "Intruder":   -3.0,
    "Intruder2":  -7.0,
    "Intruder3":  -4.5,
    "Intruder4":  -6.0,
}

_OFF_SCENE = (0.0, -40.0, 0.0)

# Corridor-level waypoint for each room (transition point between rooms)
_CORRIDOR = {
    "lobby":       (-5.0, -1.0, 0.0),
    "work_room_1": (-8.0,  1.0, 0.0),
    "work_room_2": (-4.0,  1.0, 0.0),
    "work_room_3": ( 0.0,  1.0, 0.0),
    "work_room_4": ( 4.0,  1.0, 0.0),
    "server_room": ( 8.0,  0.0, 0.0),
}

# Deep waypoint inside each room (where person stops)
_DEEP = {
    "lobby":       (-5.0, -3.5, 0.0),
    "work_room_1": (-8.0,  4.5, 0.0),
    "work_room_2": (-4.0,  4.5, 0.0),
    "work_room_3": ( 0.0,  4.5, 0.0),
    "work_room_4": ( 4.0,  4.5, 0.0),
    "server_room": ( 8.0,  3.5, 0.0),
}


def _build_route(name: str):
    """Returns (waypoints, loop_start, pause_indices).

    loop_start    : index to reset wp_idx to after the last waypoint
    pause_indices : set of waypoint indices where person pauses in room
    """
    cfg = SCENARIO.get(name)
    if cfg is None or not cfg.get("active", False):
        return [_OFF_SCENE], 0, set()

    rooms  = cfg.get("route", ["lobby"])
    sx     = _START_X.get(name, -5.0)
    wps    = [(sx, -9.5, 0.0)]
    pauses = set()

    if rooms == ["lobby"]:
        wps += [(sx, -6.0, 0.0), (-5.0, -3.5, 0.0)]
        pauses.add(len(wps) - 1)
        return wps, 1, pauses

    # Initial entry: each character walks their own lane through the lobby
    # and converges at the checkpoint door (-5.0, -1.0).
    wps += [(sx, -6.0, 0.0), (-5.0, -3.5, 0.0), (-5.0, -1.0, 0.0)]

    # First room: enter directly from checkpoint
    first = rooms[0]
    wps.append(_CORRIDOR[first])
    wps.append(_DEEP[first])
    pauses.add(len(wps) - 1)

    loop_start = len(wps) - 1  # stay at last waypoint forever

    # Subsequent rooms: exit previous, enter next
    for i, room in enumerate(rooms[1:], 1):
        prev = rooms[i - 1]
        wps.append(_CORRIDOR[prev])   # exit previous room to corridor
        wps.append(_CORRIDOR[room])   # walk to next room's corridor
        wps.append(_DEEP[room])       # go deep into room
        pauses.add(len(wps) - 1)

    return wps, loop_start, pauses


def main():
    robot = Supervisor()
    name  = robot.getName()

    route, loop_start, pause_indices = _build_route(name)

    self_node   = robot.getSelf()
    translation = self_node.getField("translation")

    cfg         = SCENARIO.get(name, {})
    dt          = TIME_STEP / 1000.0
    delay_steps = int(cfg.get("delay", 0) / dt) if cfg.get("active") else 0

    wp_idx = 0
    pause  = 0

    translation.setSFVec3f(list(route[0]))

    while robot.step(TIME_STEP) != -1:
        if delay_steps > 0:
            delay_steps -= 1
            continue

        if pause > 0:
            pause -= 1
            continue

        if wp_idx >= len(route):
            wp_idx = loop_start
            continue

        target  = route[wp_idx]
        current = translation.getSFVec3f()
        cx, cy, cz = current
        tx, ty, tz = target

        dx   = tx - cx
        dy   = ty - cy
        dist = math.hypot(dx, dy)

        if dist < THRESHOLD:
            if wp_idx in pause_indices:
                pause = PAUSE_IN_ROOM
            wp_idx += 1
            continue

        move  = min(SPEED * dt, dist)
        ratio = move / dist
        translation.setSFVec3f([cx + dx * ratio, cy + dy * ratio, cz])


if __name__ == "__main__":
    main()
