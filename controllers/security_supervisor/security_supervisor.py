"""Supervisor de seguranca — coordenacao das zonas e dos alertas.

Implementa, de forma centralizada para efeitos de simulacao, os papeis dos
ZoneCoordinatorAgents e do AlertAgent do artigo (no sistema real este
raciocinio BDI corre descentralizado em SPADE/FIPA-ACL):

  - decide os pedidos de acesso dos gates de reconhecimento facial
    (checkpoint do lobby e porta do datacenter) e abre/fecha as portas;
  - funde os eventos MOTION dos PIR com a ocupacao das zonas;
  - ao detetar uma cara desconhecida, despacha o robo de patrulha para
    deter o intruso e transmite a posicao do alvo durante a perseguicao;
  - ao receber um CYBER_ALERT de um servidor, decreta LOCKDOWN: tranca
    TODAS as portas (canBeOpen=FALSE) e envia o robo investigar o
    datacenter; apos o relatorio do robo, escala para o operador e
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
from zones import DOORS, GATE_DOOR, zone_of  # noqa: E402

EMPLOYEES = {"Alice", "Bruno", "Carla"}
DATACENTER_AUTHORIZED = {"Bruno"}

PERSON_DEFS = {
    "Alice": "PERSON_ALICE",
    "Bruno": "PERSON_BRUNO",
    "Carla": "PERSON_CARLA",
    "Intruder": "PERSON_INTRUDER",
}

DOOR_OPEN_POSITION = 1.5
DOOR_OPEN_TIME = 5.0          # s que uma porta fica aberta apos acesso concedido
FACE_VALIDITY = 4.0           # s de validade de uma observacao FACE
ROBOT_DOOR_RADIUS = 1.3       # m: o robo em missao abre a porta mais proxima
TARGET_BROADCAST_PERIOD = 0.5
LOCKDOWN_CLEAR_DELAY = 10.0   # s entre o relatorio do robo e a normalizacao
MOTION_LOG_COOLDOWN = 6.0     # s entre registos de movimento da mesma zona

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
            "can_be_open": node.getField("canBeOpen"),
            "default": DOOR_OPEN_POSITION if door_def in ("DOOR_ENTRANCE",
                                                          "DOOR_BREAK") else 0.0,
            "close_at": None,
            "robot_opened": False,
        }
    patrol = sup.getFromDef("PATROL_ROBOT")

    last_face = {}           # gate -> (identity, model, instante)
    lockdown = False
    lockdown_clear_at = None
    pursuit_target = None    # nome da pessoa a ser perseguida
    last_broadcast = -1e9
    last_motion_log = {}     # zona -> instante
    event_log = []

    def send(message):
        emitter.send(json.dumps(message).encode())

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
        print(f"[supervisor] {text}")

    def set_status(text, color=WHITE):
        sup.setLabel(1, text, 0.02, 0.06, 0.08, color, 0.0, "Lucida Console")

    def open_door(door_def, by_robot=False):
        door = doors[door_def]
        door["position"].setSFFloat(DOOR_OPEN_POSITION)
        door["close_at"] = sup.getTime() + DOOR_OPEN_TIME
        door["robot_opened"] = by_robot

    def close_door(door_def):
        door = doors[door_def]
        door["position"].setSFFloat(0.0 if lockdown else door["default"])
        door["close_at"] = None
        door["robot_opened"] = False

    def start_lockdown(reason):
        nonlocal lockdown
        lockdown = True
        for door_def, door in doors.items():
            door["can_be_open"].setSFBool(False)
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
            door["can_be_open"].setSFBool(True)
            door["position"].setSFFloat(door["default"])
        send({"type": "LOCKDOWN_CLEAR"})
        set_status("Sistema normalizado", GREEN)
        log_event("Lockdown levantado: incidente contido", GREEN)

    def dispatch(kind, x, y, reason, target=None, model=None, zone=None):
        send({"type": "DISPATCH", "kind": kind, "x": x, "y": y,
              "reason": reason, "target": target, "model": model, "zone": zone})
        log_event(f"Robo de patrulha despachado ({kind}): {reason}", ORANGE)

    def handle_access_request(name, gate):
        nonlocal pursuit_target
        face = last_face.get(gate)
        if face is None or sup.getTime() - face[2] > FACE_VALIDITY:
            return  # ainda sem observacao facial valida; pessoa volta a pedir
        identity, model, _ = face
        if lockdown:
            send({"type": "ACCESS_DENIED", "name": name, "gate": gate})
            return
        authorized = (identity in EMPLOYEES if gate == "checkpoint"
                      else identity in DATACENTER_AUTHORIZED)
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
            except Exception:
                receiver.nextPacket()
                continue
            receiver.nextPacket()
            mtype = msg.get("type")

            if mtype == "FACE":
                last_face[msg["gate"]] = (msg["identity"], msg["model"], now)

            elif mtype == "ACCESS_REQUEST":
                handle_access_request(msg["name"], msg["gate"])

            elif mtype == "MOTION":
                zone = msg.get("zone", "?")
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

        # transmite a posicao do alvo durante a perseguicao
        if pursuit_target and now - last_broadcast >= TARGET_BROADCAST_PERIOD:
            last_broadcast = now
            x, y = person_xy(pursuit_target)
            send({"type": "TARGET_POS", "target": pursuit_target, "x": x, "y": y})

        # fecha portas com temporizador expirado
        for door_def, door in doors.items():
            if door["close_at"] is not None and now >= door["close_at"]:
                close_door(door_def)

        # o robo em missao abre a porta de que se aproxima (mesmo em lockdown)
        rx, ry, _ = patrol.getField("translation").getSFVec3f()
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
