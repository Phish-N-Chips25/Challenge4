"""Webots controller for simulated office people.

Each person follows a route built from SCENARIO config below.
All characters share this single controller file; the robot's
NAME field (set in the .wbt) selects which scenario entry to use.

Authorization is implicit in the character name:
  Alice / Bruno / Carla  → recognised employee (face cam identifies them)
  Intruder               → unknown person (triggers alert + patrol dispatch)
"""

import math
from controller import Supervisor

TIME_STEP = 256     # ms — must match WorldInfo.basicTimeStep
SPEED      = 0.6    # m/s  — walking pace
THRESHOLD  = 0.15   # m    — distance to consider a waypoint reached
PAUSE_AT   = 60     # steps to pause at final waypoint before looping


# ═══════════════════════════════════════════════════════════════
#  SCENARIO CONFIG — edita aqui para configurar o cenário
# ═══════════════════════════════════════════════════════════════
#
#  active      : True  = entra em cena
#                False = fica fora do mapa (não aparece)
#
#  delay       : segundos a aguardar antes de começar a andar (0 = imediato)
#
#  destination : sala de destino após passar pelo lobby/checkpoint
#                "lobby"       — fica no lobby
#                "work_room_1" — Sala de Trabalho 1
#                "work_room_2" — Sala de Trabalho 2
#                "work_room_3" — Sala de Trabalho 3
#                "work_room_4" — Sala de Trabalho 4
#                "server_room" — Datacenter
#
#  Autorização (câmera de reconhecimento facial):
#    Alice / Bruno / Carla  → funcionário reconhecido → sem alerta
#    Intruder               → pessoa NÃO reconhecida  → alerta + patrulha
#
# ═══════════════════════════════════════════════════════════════
SCENARIO = {
    # ── Pessoas autorizadas (nomes = pastas em pessoas_permitidas/) ──
    "Arsénio":    {"active": False, "delay":  0, "destination": "work_room_1"},
    "César":      {"active": False, "delay":  0, "destination": "work_room_2"},
    "Gonçalo":    {"active": False, "delay":  0, "destination": "work_room_3"},
    "Rui Soares": {"active": False, "delay":  0, "destination": "work_room_4"},
    "Rynalde":    {"active": False, "delay":  0, "destination": "server_room"},
    # ── Intrusos ──────────────────────────────────────────────────────
    "Intruder":   {"active": False,  "delay":  0, "destination": "server_room"},
    "Intruder2":  {"active": True,  "delay": 30, "destination": "work_room_1"},
    "Intruder3":  {"active": False, "delay":  0, "destination": "work_room_3"},
    "Intruder4":  {"active": False, "delay":  0, "destination": "work_room_4"},
}
# ═══════════════════════════════════════════════════════════════


# ── Internal route building ────────────────────────────────────
# Door / corridor waypoints (from building geometry)
_COMMON_ENTRY = [
    (-5.0, -6.0, 0.0),   # entrance door (south wall gap)
    (-5.0, -3.5, 0.0),   # lobby centre  (PIR + facecam)
    (-5.0, -1.0, 0.0),   # checkpoint door
]

_DEST_WAYPOINTS = {
    "lobby":       [],
    "work_room_1": [(-8.0,  1.0, 0.0), (-8.0,  4.5, 0.0)],
    "work_room_2": [(-4.0,  1.0, 0.0), (-4.0,  4.5, 0.0)],
    "work_room_3": [( 0.0,  1.0, 0.0), ( 0.0,  4.5, 0.0)],
    "work_room_4": [( 4.0,  1.0, 0.0), ( 4.0,  4.5, 0.0)],
    "server_room": [( 8.0,  0.0, 0.0), ( 8.0,  1.0, 0.0), ( 8.0,  3.5, 0.0)],
}

# Each character starts at a slightly different X so they don't overlap
_START_X = {
    "Arsénio":    -5.0,
    "César":      -3.5,
    "Gonçalo":    -6.5,
    "Rui Soares": -4.8,
    "Rynalde":    -6.0,
    "Intruder":   -5.0,
    "Intruder2":  -4.5,
    "Intruder3":  -5.5,
    "Intruder4":  -4.0,
}

_OFF_SCENE = (0.0, -40.0, 0.0)   # far off-map spawn point


def _build_route(name: str) -> list[tuple]:
    cfg  = SCENARIO.get(name)
    if cfg is None or not cfg.get("active", False):
        return [_OFF_SCENE]

    dest = cfg.get("destination", "lobby")
    sx   = _START_X.get(name, -5.0)
    start = [(sx, -9.5, 0.0)]
    dest_wps = [tuple(wp) for wp in _DEST_WAYPOINTS.get(dest, [])]

    if dest == "lobby":
        # Only goes as far as lobby centre, skips the checkpoint
        return start + [(-5.0, -6.0, 0.0), (-5.0, -3.5, 0.0)]

    return start + [tuple(wp) for wp in _COMMON_ENTRY] + dest_wps


def main():
    robot = Supervisor()
    name  = robot.getName()

    route = _build_route(name)

    self_node   = robot.getSelf()
    translation = self_node.getField("translation")

    cfg        = SCENARIO.get(name, {})
    dt         = TIME_STEP / 1000.0
    delay_steps = int(cfg.get("delay", 0) / dt) if cfg.get("active") else 0

    wp_idx = 0
    pause  = 0

    translation.setSFVec3f(list(route[0]))

    while robot.step(TIME_STEP) != -1:
        if delay_steps > 0:
            delay_steps -= 1
            continue

        if wp_idx >= len(route):
            continue

        if pause > 0:
            pause -= 1
            continue

        target  = route[wp_idx]
        current = translation.getSFVec3f()
        cx, cy, cz = current
        tx, ty, tz = target

        dx   = tx - cx
        dy   = ty - cy
        dist = math.hypot(dx, dy)

        if dist < THRESHOLD:
            wp_idx += 1
            if wp_idx >= len(route):
                pause = PAUSE_AT
            continue

        move  = min(SPEED * dt, dist)
        ratio = move / dist
        translation.setSFVec3f([cx + dx * ratio, cy + dy * ratio, cz])


if __name__ == "__main__":
    main()
