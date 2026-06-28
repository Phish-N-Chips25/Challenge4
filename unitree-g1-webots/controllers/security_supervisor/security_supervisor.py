"""Supervisor de seguranca — coordenacao das zonas e dos alertas.

Implementa, de forma centralizada para efeitos de simulacao, os papeis dos
ZoneCoordinatorAgents e do AlertAgent do artigo (no sistema real este
raciocinio BDI corre descentralizado em SPADE/FIPA-ACL):

  - decide os pedidos de acesso dos gates de reconhecimento facial
    (checkpoint do lobby e porta do datacenter) e abre/fecha as portas;
  - funde os eventos MOTION dos PIR com a ocupacao das zonas;
  - ao detetar uma cara desconhecida, despacha o robo de patrulha para
    deter o intruso e transmite a posicao do alvo durante a perseguicao;
  - ao receber um CYBER_ALERT de um servidor, decreta LOCKDOWN: fecha
    TODAS as portas e envia o robo investigar o datacenter; apos o relatorio
    do robo, escala para o operador e
    normaliza o sistema;
  - arbitra tambem os pedidos de assistencia dos funcionarios
    (StaffRequestAgent), pela mesma via dos alertas autonomos;
  - mostra o estado e o registo de eventos como overlay na janela 3D.
"""

import json
import math
import os
import sys

from controller import Supervisor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))
from zones import DOORS, GATE_DOOR, zone_of, route  # noqa: E402
from heading import yaw_from_orientation  # noqa: E402
from pathlib import Path as _Path

EMPLOYEES = {"Alice", "Bruno", "Carla"}
DATACENTER_AUTHORIZED = {"Bruno"}

PERSON_DEFS = {
    "Alice": "PERSON_ALICE",
    "Bruno": "PERSON_BRUNO",
    "Carla": "PERSON_CARLA",
    "Intruder": "PERSON_INTRUDER",
}

DOOR_OPEN_POSITION = -1.0
DOOR_OPEN_TIME = 5.0          # s que uma porta fica aberta apos acesso concedido
FACE_VALIDITY = 4.0           # s de validade de uma observacao FACE
ROBOT_DOOR_RADIUS = 1.3       # m: o robo em missao abre a porta mais proxima
TARGET_BROADCAST_PERIOD = 0.5
LOCKDOWN_CLEAR_DELAY = 10.0   # s entre o relatorio do robo e a normalizacao
MOTION_LOG_COOLDOWN = 6.0     # s entre registos de movimento da mesma zona
BOOSTER_POSE_LOG_PERIOD = 1.0
BOOSTER_POSE_LOG_UNTIL = 180.0
BOOSTER_POSE_FILE_PERIOD = 0.1

WHITE, GREEN, ORANGE, RED = 0xFFFFFF, 0x00CC44, 0xFF8800, 0xFF2222


def main():
    sup = Supervisor()
    timestep = int(sup.getBasicTimeStep())

    emitter = sup.getDevice("emitter")
    receiver = sup.getDevice("receiver")
    receiver.enable(timestep)

    persons = {name: sup.getFromDef(d) for name, d in PERSON_DEFS.items()}
    doors = {}
    for door_def in DOORS:
        node = sup.getFromDef(door_def)
        doors[door_def] = {
            "node": node,
            "position": node.getField("position"),
            "default": DOOR_OPEN_POSITION if door_def in ("DOOR_ENTRANCE",
                                                          "DOOR_BREAK") else 0.0,
            "close_at": None,
            "robot_opened": False,
        }
    active_robot = sup.getFromDef("BOOSTER_T1")

    last_face = {}           # gate -> (identity, model, instante)
    lockdown = False
    lockdown_clear_at = None
    pursuit_target = None    # nome da pessoa a ser perseguida
    last_broadcast = -1e9
    last_motion_log = {}     # zona -> instante
    last_booster_pose_log = -1e9
    last_booster_pose_file = -1e9
    event_log = []
    pose_file = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            ".logs",
            "booster_pose.json",
        )
    )
    mission_file = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            ".logs",
            "booster_missions.jsonl",
        )
    )
    status_file = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            ".logs",
            "booster_status.jsonl",
        )
    )
    target_pos_file = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            ".logs",
            "booster_target_pos.jsonl",
        )
    )
    status_offset = 0

    # Setup Path Visualization (Trail & Plan)
    root_children = sup.getRoot().getField("children")
    root_children.importMFNodeFromString(-1, '''
    Transform {
      translation 0 0 0.02
      children [
        Shape {
          appearance Appearance { material Material { emissiveColor 0 1 1 } }
          geometry DEF TRAIL_LINE IndexedLineSet {
            coord Coordinate { point [0 0 0, 0 0 0] }
            coordIndex [0 1 -1]
          }
        }
      ]
    }
    ''')
    root_children.importMFNodeFromString(-1, '''
    Transform {
      translation 0 0 0.05
      children [
        Shape {
          appearance Appearance { material Material { emissiveColor 1 0.5 0 } }
          geometry DEF PLAN_LINE IndexedLineSet {
            coord Coordinate { point [0 0 0, 0 0 0] }
            coordIndex [0 1 -1]
          }
        }
      ]
    }
    ''')

    trail_coord = sup.getFromDef("TRAIL_LINE").getField("coord").getSFNode()
    trail_point = trail_coord.getField("point")
    trail_index = sup.getFromDef("TRAIL_LINE").getField("coordIndex")
    
    plan_coord = sup.getFromDef("PLAN_LINE").getField("coord").getSFNode()
    plan_point = plan_coord.getField("point")
    plan_index = sup.getFromDef("PLAN_LINE").getField("coordIndex")

    last_trail_x, last_trail_y = active_robot.getField("translation").getSFVec3f()[:2]

    active_mission_target = None
    last_plan_update = -1e9

    def _ensure_mf_count(field, minimum_count, insert_value):
        while field.getCount() < minimum_count:
            insert_at = field.getCount()
            if isinstance(insert_value, int):
                field.insertMFInt32(insert_at, insert_value)
            else:
                field.insertMFVec3f(insert_at, insert_value)

    def clear_line(point_field, index_field, point=(0.0, 0.0)):
        _ensure_mf_count(point_field, 2, [point[0], point[1], 0.0])
        _ensure_mf_count(index_field, 3, -1)
        point_field.setMFVec3f(0, [point[0], point[1], 0.0])
        point_field.setMFVec3f(1, [point[0], point[1], 0.0])
        index_field.setMFInt32(0, 0)
        index_field.setMFInt32(1, 1)
        index_field.setMFInt32(2, -1)
        while index_field.getCount() > 3:
            index_field.removeMF(index_field.getCount() - 1)
        while point_field.getCount() > 2:
            point_field.removeMF(point_field.getCount() - 1)

    def set_line(point_field, index_field, points):
        if len(points) < 2:
            clear_line(point_field, index_field)
            return
        _ensure_mf_count(point_field, len(points), [points[0][0], points[0][1], 0.0])
        _ensure_mf_count(index_field, len(points) + 1, -1)
        for i, point in enumerate(points):
            point_field.setMFVec3f(i, [point[0], point[1], 0.0])
        for i in range(len(points)):
            index_field.setMFInt32(i, i)
        index_field.setMFInt32(len(points), -1)
        while index_field.getCount() > len(points) + 1:
            index_field.removeMF(index_field.getCount() - 1)
        while point_field.getCount() > len(points):
            point_field.removeMF(point_field.getCount() - 1)

    def append_line_point(point_field, index_field, point):
        idx = point_field.getCount()
        point_field.insertMFVec3f(idx, [point[0], point[1], 0.0])
        if index_field.getCount() > 0 and index_field.getMFInt32(index_field.getCount() - 1) == -1:
            index_field.setMFInt32(index_field.getCount() - 1, idx)
        else:
            index_field.insertMFInt32(index_field.getCount(), idx)
        index_field.insertMFInt32(index_field.getCount(), -1)

    clear_line(trail_point, trail_index, (last_trail_x, last_trail_y))
    clear_line(plan_point, plan_index)

    def trace_event(text):
        print(f"[supervisor] TRACE t={sup.getTime():.3f} {text}", flush=True)

    def send(message):
        trace_event(f"emitter_send payload={message}")
        emitter.send(json.dumps(message).encode())

    def write_booster_mission(kind, x, y, reason, target=None, model=None, zone=None):
        """Append a mission to the JSONL bridge for the ROS patrol node."""
        os.makedirs(os.path.dirname(mission_file), exist_ok=True)
        payload = {
            "time": sup.getTime(),
            "type": "DISPATCH",
            "kind": kind,
            "x": x,
            "y": y,
            "target": target,
            "model": model,
            "zone": zone,
            "reason": reason,
        }
        with open(mission_file, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, separators=(",", ":")) + "\n")
        trace_event(f"booster_mission_append path={mission_file} payload={payload}")

    def person_xy(name):
        x, y, _ = persons[name].getField("translation").getSFVec3f()
        return x, y

    def log_event(text, color=WHITE):
        now = sup.getTime()
        event_log.append((f"[{now:6.1f}s] {text}", color))
        del event_log[:-6]
        for i, (line, line_color) in enumerate(event_log):
            sup.setLabel(10 + i, line, 0.02, 0.1 + 0.035 * i, 0.07,
                         line_color, 0.0, "Lucida Console")
        print(f"[supervisor] {text}", flush=True)

    def set_status(text, color=WHITE):
        sup.setLabel(1, text, 0.02, 0.06, 0.08, color, 0.0, "Lucida Console")

    def open_door(door_def, by_robot=False):
        door = doors[door_def]
        door["position"].setSFFloat(DOOR_OPEN_POSITION)
        door["close_at"] = sup.getTime() + DOOR_OPEN_TIME
        door["robot_opened"] = by_robot
        trace_event(
            f"door_open door={door_def} by_robot={by_robot} "
            f"close_at={door['close_at']:.3f}"
        )

    def close_door(door_def):
        door = doors[door_def]
        door["position"].setSFFloat(0.0 if lockdown else door["default"])
        door["close_at"] = None
        door["robot_opened"] = False
        trace_event(
            f"door_close door={door_def} lockdown={lockdown} "
            f"default={door['default']:.3f}"
        )

    def start_lockdown(reason):
        nonlocal lockdown
        lockdown = True
        for door_def, door in doors.items():
            door["position"].setSFFloat(0.0)
            door["close_at"] = None
        send({"type": "LOCKDOWN", "reason": reason})
        set_status("LOCKDOWN ATIVO - todas as portas trancadas", RED)
        log_event(f"LOCKDOWN: {reason}", RED)

    def clear_lockdown():
        nonlocal lockdown, lockdown_clear_at
        lockdown = False
        lockdown_clear_at = None
        for door_def, door in doors.items():
            door["position"].setSFFloat(door["default"])
        send({"type": "LOCKDOWN_CLEAR"})
        set_status("Sistema normalizado", GREEN)
        log_event("Lockdown levantado: incidente contido", GREEN)

    def dispatch(kind, x, y, reason, target=None, model=None, zone=None):
        nonlocal active_mission_target
        trace_event(
            f"dispatch kind={kind} target={target} model={model} zone={zone} "
            f"xy=({x:.3f},{y:.3f}) reason={reason!r}"
        )
        send({"type": "DISPATCH", "kind": kind, "x": x, "y": y,
              "reason": reason, "target": target, "model": model, "zone": zone})
        write_booster_mission(kind, x, y, reason, target=target, model=model, zone=zone)
        log_event(f"Robo de patrulha despachado ({kind}): {reason}", ORANGE)
        active_mission_target = (x, y)

    def booster_yaw():
        # Yaw from the full orientation matrix, not the axis-angle Z component:
        # the walking biped tilts every gait step, and rz*angle collapses under
        # that tilt (worst near the corridor headings the robot operates in),
        # corrupting the closed-loop heading the patrol/PPO navigation drives.
        return yaw_from_orientation(active_robot.getOrientation())

    def write_booster_pose_file(now, x, y, z):
        os.makedirs(os.path.dirname(pose_file), exist_ok=True)
        tmp_path = f"{pose_file}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "time": now,
                    "x": x,
                    "y": y,
                    "z": z,
                    "theta": booster_yaw(),
                },
                fh,
                separators=(",", ":"),
            )
        os.replace(tmp_path, pose_file)

    def poll_booster_status():
        nonlocal pursuit_target, status_offset, lockdown_clear_at, active_mission_target
        if not os.path.exists(status_file):
            return
        with open(status_file, "r", encoding="utf-8") as fh:
            fh.seek(status_offset)
            read_count = 0
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except Exception as exc:
                    trace_event(f"booster_status_invalid line={line!r} error={exc}")
                    continue
                etype = evt.get("type")
                read_count += 1
                trace_event(f"booster_status_event type={etype} payload={evt}")
                if etype == "DETAINED":
                    pursuit_target = None
                    active_mission_target = (9.0, 0.0)
                    verified = evt.get("verified")
                    name = evt.get("name", "?")
                    log_event(
                        f"Intruso '{name}' DETIDO pelo robo "
                        f"(verificacao facial: "
                        f"{'OK' if verified else 'inconclusiva'})",
                        GREEN,
                    )
                    set_status("Intruso detido - operador notificado", ORANGE)
                elif etype == "REPORT":
                    active_mission_target = (9.0, 0.0)
                    zone = evt.get("zone", "?")
                    occupants = [
                        name
                        for name in persons
                        if zone_of(*person_xy(name)) == zone
                    ]
                    log_event(
                        f"Robo verificou '{zone}': "
                        f"presentes {occupants or 'ninguem'} - "
                        f"escalado para o operador",
                        ORANGE,
                    )
                    if lockdown:
                        lockdown_clear_at = sup.getTime() + LOCKDOWN_CLEAR_DELAY
                elif etype == "ASSIST_DONE":
                    active_mission_target = (9.0, 0.0)
                    log_event(
                        f"Assistencia a {evt.get('name', '?')} concluida",
                        GREEN,
                    )
            status_offset = fh.tell()
            if read_count:
                trace_event(f"booster_status_offset={status_offset}")

    def handle_access_request(name, gate):
        nonlocal pursuit_target
        face = last_face.get(gate)
        trace_event(f"access_request name={name} gate={gate} face={face}")
        if face is None or sup.getTime() - face[2] > FACE_VALIDITY:
            trace_event(f"access_request_waiting_for_face name={name} gate={gate}")
            return  # ainda sem observacao facial valida; pessoa volta a pedir
        identity, model, _ = face
        if lockdown:
            send({"type": "ACCESS_DENIED", "name": name, "gate": gate})
            trace_event(f"access_denied_lockdown name={name} gate={gate}")
            return
        authorized = (identity in EMPLOYEES if gate == "checkpoint"
                      else identity in DATACENTER_AUTHORIZED)
        trace_event(
            f"access_decision name={name} gate={gate} identity={identity} "
            f"authorized={authorized}"
        )
        if authorized:
            send({"type": "ACCESS_GRANTED", "name": name, "gate": gate})
            open_door(GATE_DOOR[gate])
            log_event(f"Acesso concedido a {identity} ({gate})", GREEN)
        else:
            send({"type": "ACCESS_DENIED", "name": name, "gate": gate})
            if identity == "UNKNOWN" and pursuit_target is None:
                pursuit_target = name
                x, y = person_xy(name)
                log_event(f"Cara DESCONHECIDA no gate '{gate}' - INTRUSAO", RED)
                set_status("ALERTA: intruso detetado", RED)
                dispatch("detain", x, y, "cara desconhecida no checkpoint",
                         target=name, model=model, zone=zone_of(x, y))
            else:
                log_event(f"Acesso NEGADO a {identity} ({gate})", ORANGE)

    sup.setLabel(0, "SentinelMAS - simulacao Webots (Challenge 4)",
                 0.02, 0.02, 0.09, WHITE, 0.0, "Lucida Console")
    set_status("Sistema nominal", GREEN)
    log_event("Supervisor de seguranca ativo")

    while sup.step(timestep) != -1:
        now = sup.getTime()

        while receiver.getQueueLength() > 0:
            try:
                msg = json.loads(receiver.getString())
            except Exception as exc:
                trace_event(f"receiver_invalid_json error={exc}")
                receiver.nextPacket()
                continue
            receiver.nextPacket()
            mtype = msg.get("type")
            trace_event(f"receiver_event type={mtype} payload={msg}")

            if mtype == "FACE":
                last_face[msg["gate"]] = (msg["identity"], msg["model"], now)
                trace_event(
                    f"face_observed gate={msg['gate']} identity={msg['identity']} "
                    f"model={msg['model']}"
                )

            elif mtype == "ACCESS_REQUEST":
                handle_access_request(msg["name"], msg["gate"])

            elif mtype == "MOTION":
                zone = msg.get("zone", "?")
                trace_event(f"motion_trigger zone={zone}")
                if now - last_motion_log.get(zone, -1e9) >= MOTION_LOG_COOLDOWN:
                    last_motion_log[zone] = now
                    log_event(f"PIR: movimento em '{zone}'")

            elif mtype == "CYBER_ALERT":
                log_event(f"CYBER: {msg['host']} executou comando malicioso "
                          f"[{msg['technique']}] {msg['description']}", RED)
                if not lockdown:
                    start_lockdown(f"comando malicioso em {msg['host']} "
                                   f"({msg['technique']})")
                    dispatch("investigate", 8.4, 2.2,
                             f"anomalia cibernetica em {msg['host']}",
                             zone="datacenter")

            elif mtype == "DETAINED":
                pursuit_target = None
                verified = msg.get("verified")
                log_event(f"Intruso '{msg['name']}' DETIDO pelo robo "
                          f"(verificacao facial: "
                          f"{'OK' if verified else 'inconclusiva'})", GREEN)
                set_status("Intruso detido - operador notificado", ORANGE)

            elif mtype == "REPORT":
                occupants = [name for name in persons
                             if zone_of(*person_xy(name)) == msg.get("zone")]
                log_event(f"Robo verificou '{msg.get('zone')}': "
                          f"presentes {occupants or 'ninguem'} - "
                          f"escalado para o operador", ORANGE)
                if lockdown:
                    lockdown_clear_at = now + LOCKDOWN_CLEAR_DELAY

            elif mtype == "STAFF_REQUEST":
                log_event(f"Pedido de assistencia de {msg['name']}", WHITE)
                dispatch("assist", float(msg["x"]), float(msg["y"]),
                         f"pedido de {msg['name']}", target=msg["name"])

            elif mtype == "ASSIST_DONE":
                log_event(f"Assistencia a {msg.get('name')} concluida", GREEN)

            else:
                trace_event(f"receiver_unhandled type={mtype} payload={msg}")

        poll_booster_status()

        # transmits target position during pursuit
        if pursuit_target and now - last_broadcast >= TARGET_BROADCAST_PERIOD:
            last_broadcast = now
            x, y = person_xy(pursuit_target)
            trace_event(
                f"target_broadcast target={pursuit_target} xy=({x:.3f},{y:.3f})"
            )
            send({"type": "TARGET_POS", "target": pursuit_target, "x": x, "y": y})
            # Also write to the JSONL bridge for the ROS patrol node
            os.makedirs(os.path.dirname(target_pos_file), exist_ok=True)
            with open(target_pos_file, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "time": now,
                    "type": "TARGET_POS",
                    "target": pursuit_target,
                    "x": x,
                    "y": y,
                }, separators=(",", ":")) + "\n")
            trace_event(f"target_pos_append path={target_pos_file}")

        # fecha portas com temporizador expirado
        for door_def, door in doors.items():
            if door["close_at"] is not None and now >= door["close_at"]:
                close_door(door_def)

        # robot mission doors
        rx, ry, rz = active_robot.getField("translation").getSFVec3f()
        
        # Trail update
        if math.hypot(rx - last_trail_x, ry - last_trail_y) > 0.1:
            append_line_point(trail_point, trail_index, (rx, ry))
            last_trail_x, last_trail_y = rx, ry

        # Planned path update
        if active_mission_target is not None:
            tx, ty = active_mission_target
            if pursuit_target:
                tx, ty = person_xy(pursuit_target)
                
            if active_mission_target == (9.0, 0.0) and math.hypot(rx - tx, ry - ty) < 0.5:
                active_mission_target = None
                clear_line(plan_point, plan_index)
            elif now - last_plan_update > 0.5:
                last_plan_update = now
                pts = [(rx, ry)] + route(rx, ry, tx, ty)
                set_line(plan_point, plan_index, pts)
                trace_event(
                    f"plan_update target=({tx:.3f},{ty:.3f}) points={len(pts)}"
                )

        if now - last_booster_pose_file >= BOOSTER_POSE_FILE_PERIOD:
            last_booster_pose_file = now
            write_booster_pose_file(now, rx, ry, rz)
        if now <= BOOSTER_POSE_LOG_UNTIL and now - last_booster_pose_log >= BOOSTER_POSE_LOG_PERIOD:
            last_booster_pose_log = now
            print(f"[supervisor] BOOSTER_POSE t={now:.2f} x={rx:.3f} y={ry:.3f} z={rz:.3f}")
        robot_active = math.hypot(rx - 9.0, ry - 0.0) > 0.5
        if robot_active:
            for door_def, (dx, dy) in DOORS.items():
                door = doors[door_def]
                near = math.hypot(rx - dx, ry - dy) <= ROBOT_DOOR_RADIUS
                if near and door["close_at"] is None:
                    open_door(door_def, by_robot=True)

        if lockdown_clear_at is not None and now >= lockdown_clear_at:
            clear_lockdown()


if __name__ == "__main__":
    main()
