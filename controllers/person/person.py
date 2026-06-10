"""Controlador das pessoas (funcionarios e intruso).

Cada pessoa e um robo cinematico (move-se definindo a propria translation via
API de Supervisor) que segue um guiao de acoes:
  ("wait", segundos)        - espera parada
  ("goto", x, y)            - caminha em linha reta ate ao ponto
  ("gate", nome)            - para em frente a camara de reconhecimento facial
                              e pede acesso; avanca quando ACCESS_GRANTED
  ("announce", tipo)        - envia um pedido (ex.: STAFF_REQUEST)
  ("idle",)                 - fica parada para sempre

Comportamentos especiais:
  - O intruso, ao receber ACCESS_DENIED, espera uns segundos e forca a
    passagem na mesma (tailgating / arrombamento).
  - Qualquer pessoa que receba DETAIN com o seu nome fica imobilizada
    (detida pelo robo de patrulha).
  - Durante um LOCKDOWN os funcionarios ficam parados (shelter in place)
    ate receberem LOCKDOWN_CLEAR.
"""

import json
import math
import os
import sys

from controller import Supervisor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))

WALK_SPEED = 1.2          # m/s
INTRUDER_SPEED = 1.35     # m/s
GATE_RETRY_PERIOD = 2.0   # s entre pedidos de acesso
FORCE_ENTRY_DELAY = 6.0   # s que o intruso espera antes de forcar a porta

SCHEDULES = {
    "Alice": [
        ("wait", 2),
        ("goto", -5, -5),
        ("goto", -5, -2.1),
        ("gate", "checkpoint"),
        ("goto", -5, 0),
        ("goto", -4, 0),
        ("goto", -4, 1.7),
        ("goto", -4.9, 3.4),
        ("idle",),
    ],
    "Bruno": [
        ("wait", 10),
        ("goto", -5, -5),
        ("goto", -5, -2.1),
        ("gate", "checkpoint"),
        ("goto", -5, 0),
        ("goto", 8, 0),
        ("gate", "datacenter"),
        ("goto", 8, 1.7),
        ("goto", 7.8, 2.4),
        ("idle",),
    ],
    "Carla": [
        ("wait", 20),
        ("goto", -5, -5),
        ("goto", -5, -2.1),
        ("gate", "checkpoint"),
        ("goto", -5, 0),
        ("goto", 5, 0),
        ("goto", 5, -1.7),
        ("goto", 5, -3),
        ("wait", 150),
        ("announce", "staff_request"),
        ("idle",),
    ],
    "Intruder": [
        ("wait", 45),
        ("goto", -5, -5),
        ("goto", -5, -2.1),
        ("gate", "checkpoint"),
        ("goto", -5, 0),
        ("goto", 0, 0),
        ("goto", 8, 0),
        ("goto", 8, 1.7),
        ("goto", 7.5, 2.6),
        ("idle",),
    ],
}


def main():
    robot = Supervisor()
    timestep = int(robot.getBasicTimeStep())
    dt = timestep / 1000.0
    name = robot.getName()
    is_intruder = name == "Intruder"
    speed = INTRUDER_SPEED if is_intruder else WALK_SPEED

    node = robot.getSelf()
    translation_field = node.getField("translation")
    rotation_field = node.getField("rotation")

    emitter = robot.getDevice("emitter")
    receiver = robot.getDevice("receiver")
    receiver.enable(timestep)

    schedule = list(SCHEDULES.get(name, [("idle",)]))
    action_index = 0
    wait_left = 0.0
    gate_timer = 0.0
    gate_state = None      # None | "waiting" | "granted" | "denied"
    force_timer = 0.0
    detained = False
    lockdown = False

    def send(message):
        emitter.send(json.dumps(message).encode())

    def read_messages():
        messages = []
        while receiver.getQueueLength() > 0:
            try:
                messages.append(json.loads(receiver.getString()))
            except Exception:
                pass
            receiver.nextPacket()
        return messages

    print(f"[person] {name} pronto ({'INTRUSO' if is_intruder else 'funcionario'})")

    while robot.step(timestep) != -1:
        for msg in read_messages():
            mtype = msg.get("type")
            if mtype == "DETAIN" and msg.get("name") == name and not detained:
                detained = True
                print(f"[person] {name} foi DETIDO pelo robo de patrulha")
            elif mtype == "ACCESS_GRANTED" and msg.get("name") == name:
                gate_state = "granted"
            elif mtype == "ACCESS_DENIED" and msg.get("name") == name:
                if gate_state == "waiting":
                    gate_state = "denied"
                    force_timer = FORCE_ENTRY_DELAY
            elif mtype == "LOCKDOWN":
                lockdown = True
            elif mtype == "LOCKDOWN_CLEAR":
                lockdown = False

        if detained:
            continue
        if lockdown and not is_intruder:
            continue  # funcionarios abrigam-se no lugar durante o lockdown
        if action_index >= len(schedule):
            continue

        action = schedule[action_index]
        kind = action[0]

        if kind == "idle":
            continue

        if kind == "wait":
            if wait_left <= 0.0:
                wait_left = float(action[1])
            wait_left -= dt
            if wait_left <= 0.0:
                action_index += 1
            continue

        if kind == "announce":
            x, y, _ = translation_field.getSFVec3f()
            send({"type": "STAFF_REQUEST", "name": name, "x": x, "y": y})
            print(f"[person] {name} pediu assistencia ao robo de patrulha")
            action_index += 1
            continue

        if kind == "gate":
            gate = action[1]
            if gate_state is None:
                gate_state = "waiting"
                gate_timer = 0.0
                send({"type": "ACCESS_REQUEST", "name": name, "gate": gate})
            elif gate_state == "waiting":
                gate_timer += dt
                if gate_timer >= GATE_RETRY_PERIOD:
                    gate_timer = 0.0
                    send({"type": "ACCESS_REQUEST", "name": name, "gate": gate})
            elif gate_state == "granted":
                gate_state = None
                action_index += 1
            elif gate_state == "denied":
                force_timer -= dt
                if force_timer <= 0.0:
                    print(f"[person] {name} FORCOU a passagem no gate '{gate}'")
                    gate_state = None
                    action_index += 1
            continue

        if kind == "goto":
            tx, ty = float(action[1]), float(action[2])
            x, y, z = translation_field.getSFVec3f()
            dx, dy = tx - x, ty - y
            distance = math.hypot(dx, dy)
            if distance < 0.06:
                action_index += 1
                continue
            step_len = min(speed * dt, distance)
            x += dx / distance * step_len
            y += dy / distance * step_len
            translation_field.setSFVec3f([x, y, 0])
            rotation_field.setSFRotation([0, 0, 1, math.atan2(dy, dx)])
            continue

        action_index += 1  # acao desconhecida: ignora


if __name__ == "__main__":
    main()
