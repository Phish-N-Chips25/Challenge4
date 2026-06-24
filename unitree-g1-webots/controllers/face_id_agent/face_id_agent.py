"""FaceIDAgent — camara fixa de controlo de acesso por reconhecimento facial.

Usa o no Recognition da camara do Webots como proxy do pipeline ArcFace /
InsightFace descrito no artigo: cada pessoa tem um campo `model` que faz o
papel do embedding facial. A "galeria" de funcionarios enrolados mapeia
embeddings para identidades; qualquer cara fora da galeria e classificada
como UNKNOWN (reconhecimento open-set).

A camara publica mensagens FACE no canal partilhado; a decisao de conceder
ou negar o acesso pertence ao supervisor de seguranca (ZoneCoordinator).
"""

import json
import sys

from controller import Robot

# "embedding" (campo model do no) -> identidade enrolada
GALLERY = {
    "employee_alice": "Alice",
    "employee_bruno": "Bruno",
    "employee_carla": "Carla",
}

# modelos que correspondem a pessoas (tudo o resto, ex. patrol_robot, e ignorado)
PERSON_PREFIXES = ("employee_", "person_")

MAX_FACE_DISTANCE = 4.5   # m: alem disto a cara nao e fiavel
REPORT_COOLDOWN = 2.5     # s entre relatorios para o mesmo modelo


def main():
    robot = Robot()
    timestep = int(robot.getBasicTimeStep())

    gate = "unknown"
    for arg in sys.argv[1:]:
        if arg.startswith("--gate="):
            gate = arg.split("=", 1)[1]

    camera = robot.getDevice("camera")
    camera.enable(timestep * 2)
    camera.recognitionEnable(timestep * 2)
    emitter = robot.getDevice("emitter")

    last_report = {}  # model -> instante do ultimo relatorio

    print(f"[face_id] camara do gate '{gate}' ativa "
          f"(galeria: {sorted(GALLERY.values())})")

    while robot.step(timestep) != -1:
        now = robot.getTime()
        for obj in camera.getRecognitionObjects():
            model = obj.getModel()
            if not model.startswith(PERSON_PREFIXES):
                continue
            position = obj.getPosition()  # relativo a camara, x = frente
            if position[0] > MAX_FACE_DISTANCE:
                continue
            if now - last_report.get(model, -1e9) < REPORT_COOLDOWN:
                continue
            last_report[model] = now
            identity = GALLERY.get(model, "UNKNOWN")
            emitter.send(json.dumps({
                "type": "FACE",
                "gate": gate,
                "identity": identity,
                "model": model,
            }).encode())
            if identity == "UNKNOWN":
                print(f"[face_id] {gate}: cara DESCONHECIDA detetada (open-set reject)")


if __name__ == "__main__":
    main()
