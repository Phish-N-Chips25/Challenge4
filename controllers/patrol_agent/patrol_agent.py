"""PatrolAgent — robo de patrulha/resposta da empresa.

Fica na doca (corredor leste) e e despachado pelo supervisor de seguranca
sempre que ha algo suspeito:
  - DISPATCH kind=detain: persegue a pessoa alvo (posicao atualizada por
    mensagens TARGET_POS) e, ao alcanca-la, detem-na (DETAIN) e guarda-a;
  - DISPATCH kind=investigate: desloca-se a zona, verifica no local quem
    esta presente com a camara de reconhecimento e reporta (REPORT);
  - DISPATCH kind=assist: responde a um pedido de assistencia de um
    funcionario (StaffRequestAgent do artigo).

A navegacao usa as rotas pelo corredor definidas em zones.py; o movimento e
cinematico (proxy simples da pilha Nav2 + politica PPO descrita no artigo).
"""

import json
import math
import os
import sys

from controller import Supervisor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))
from zones import route, zone_of  # noqa: E402

DOCK = (9.0, 0.0)
SPEED = 2.5               # m/s
ARRIVE_DISTANCE = 0.25    # m para considerar um waypoint alcancado
DETAIN_DISTANCE = 0.95    # m para conseguir deter o alvo
GUARD_TIME = 15.0         # s a guardar a pessoa detida
INVESTIGATE_TIME = 6.0    # s de verificacao no local
ASSIST_TIME = 8.0         # s a prestar assistencia
REPLAN_PERIOD = 1.0       # s entre replaneamentos durante a perseguicao

PRIORITY = {"detain": 0, "investigate": 1, "assist": 2}


def main():
    robot = Supervisor()
    timestep = int(robot.getBasicTimeStep())
    dt = timestep / 1000.0

    node = robot.getSelf()
    translation_field = node.getField("translation")
    rotation_field = node.getField("rotation")

    emitter = robot.getDevice("emitter")
    receiver = robot.getDevice("receiver")
    receiver.enable(timestep)
    beacon = robot.getDevice("beacon")
    camera = robot.getDevice("patrol_camera")
    camera.enable(timestep * 2)
    camera.recognitionEnable(timestep * 2)

    missions = []          # fila de missoes ordenada por prioridade
    mission = None         # missao ativa
    waypoints = []
    state = "idle"         # idle | navigate | pursue | guard | onsite | return
    state_timer = 0.0
    target_pos = None      # ultima posicao conhecida do alvo (perseguicao)
    last_replan = -1e9

    def send(message):
        emitter.send(json.dumps(message).encode())

    def position():
        x, y, _ = translation_field.getSFVec3f()
        return x, y

    def move_towards(tx, ty):
        """Avanca um passo em direcao a (tx, ty); devolve a distancia restante."""
        x, y = position()
        dx, dy = tx - x, ty - y
        distance = math.hypot(dx, dy)
        if distance < 1e-6:
            return 0.0
        step_len = min(SPEED * dt, distance)
        x += dx / distance * step_len
        y += dy / distance * step_len
        translation_field.setSFVec3f([x, y, 0])
        rotation_field.setSFRotation([0, 0, 1, math.atan2(dy, dx)])
        return distance - step_len

    def follow_waypoints():
        """Segue a lista de waypoints; devolve True quando ela termina."""
        while waypoints:
            tx, ty = waypoints[0]
            if move_towards(tx, ty) > ARRIVE_DISTANCE:
                return False
            waypoints.pop(0)
        return True

    def seen_models():
        return sorted({obj.getModel() for obj in camera.getRecognitionObjects()})

    def start_next_mission():
        nonlocal mission, waypoints, state, state_timer, target_pos, last_replan
        if not missions:
            return
        missions.sort(key=lambda m: PRIORITY.get(m["kind"], 9))
        mission = missions.pop(0)
        x, y = position()
        waypoints = route(x, y, mission["x"], mission["y"])
        target_pos = (mission["x"], mission["y"])
        last_replan = robot.getTime()
        state = "pursue" if mission["kind"] == "detain" else "navigate"
        state_timer = 0.0
        send({"type": "ROBOT_STATUS", "state": state, "mission": mission["kind"]})
        print(f"[patrol] missao '{mission['kind']}' iniciada -> "
              f"({mission['x']:.1f}, {mission['y']:.1f})")

    print("[patrol] PatrolAgent na doca, a aguardar despacho")

    while robot.step(timestep) != -1:
        now = robot.getTime()

        while receiver.getQueueLength() > 0:
            try:
                msg = json.loads(receiver.getString())
            except Exception:
                receiver.nextPacket()
                continue
            receiver.nextPacket()
            mtype = msg.get("type")
            if mtype == "DISPATCH":
                missions.append({
                    "kind": msg.get("kind", "investigate"),
                    "target": msg.get("target"),
                    "model": msg.get("model"),
                    "zone": msg.get("zone"),
                    "x": float(msg["x"]),
                    "y": float(msg["y"]),
                })
                print(f"[patrol] despacho recebido: {msg.get('kind')} "
                      f"({msg.get('reason', 'sem motivo')})")
            elif (mtype == "TARGET_POS" and mission
                  and mission["kind"] == "detain"
                  and msg.get("target") == mission["target"]):
                target_pos = (float(msg["x"]), float(msg["y"]))

        # beacon: fixo em guarda, a piscar em missao, apagado na doca
        if state == "guard":
            beacon.set(1)
        elif state == "idle":
            beacon.set(0)
        else:
            beacon.set(1 if int(now / 0.3) % 2 == 0 else 0)

        if state == "idle":
            if missions:
                start_next_mission()
            continue

        if state == "pursue":
            x, y = position()
            tx, ty = target_pos
            distance = math.hypot(tx - x, ty - y)
            if distance <= DETAIN_DISTANCE:
                send({"type": "DETAIN", "name": mission["target"]})
                verified = mission.get("model") in seen_models()
                send({
                    "type": "DETAINED",
                    "name": mission["target"],
                    "verified": verified,
                })
                print(f"[patrol] alvo '{mission['target']}' DETIDO "
                      f"(verificacao facial no local: "
                      f"{'confirmada' if verified else 'inconclusiva'})")
                state = "guard"
                state_timer = GUARD_TIME
                continue
            same_zone = zone_of(x, y) == zone_of(tx, ty)
            if same_zone:
                move_towards(tx, ty)
            else:
                if now - last_replan >= REPLAN_PERIOD:
                    last_replan = now
                    waypoints = route(x, y, tx, ty)
                follow_waypoints()
            continue

        if state == "navigate":
            if follow_waypoints():
                state = "onsite"
                state_timer = (INVESTIGATE_TIME if mission["kind"] == "investigate"
                               else ASSIST_TIME)
            continue

        if state == "onsite":
            state_timer -= dt
            if state_timer <= 0.0:
                if mission["kind"] == "investigate":
                    seen = seen_models()
                    send({"type": "REPORT", "zone": mission.get("zone"),
                          "seen": seen})
                    print(f"[patrol] investigacao concluida, presentes: {seen}")
                else:
                    send({"type": "ASSIST_DONE", "name": mission.get("target")})
                    print("[patrol] assistencia concluida")
                mission = None
                x, y = position()
                waypoints = route(x, y, *DOCK)
                state = "return"
            continue

        if state == "guard":
            state_timer -= dt
            if state_timer <= 0.0:
                print(f"[patrol] guarda de '{mission['target']}' terminada")
                mission = None
                if missions:
                    start_next_mission()
                else:
                    x, y = position()
                    waypoints = route(x, y, *DOCK)
                    state = "return"
            continue

        if state == "return":
            if missions:
                start_next_mission()
            elif follow_waypoints():
                state = "idle"
                send({"type": "ROBOT_STATUS", "state": "idle"})
                print("[patrol] de volta a doca")
            continue


if __name__ == "__main__":
    main()
