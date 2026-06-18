"""Webots controller for FaceID cameras (Camera + Recognition API).

Uses the Webots Recognition API to detect people in the camera's field of
view.  Maps the recognised object's model name to a MAS identity and sends
a face_detected event to the security_supervisor via Emitter.

Also listens for reverify commands from the supervisor (relayed from the
ZoneCoordinator) and triggers an immediate fresh scan.

Arguments (controllerArgs in the .wbt):
    --gate=GATE_NAME   e.g. --gate=checkpoint  --gate=work_room_1

Gate → MAS zone mapping lives in the supervisor; the camera just tags
events with the gate name and lets the supervisor translate.
"""

import json
import math
import sys
from controller import Robot

TIME_STEP = 256       # ms — must match WorldInfo.basicTimeStep
RECOGNITION_PERIOD = TIME_STEP * 4   # run recognition every 1024 ms
SCAN_COOLDOWN = 10   # steps between repeated face events (~2.5 s)
DEFAULT_MAX_DIST = 6.0  # metres — ignore people outside this range

# Webots model name → MAS identity string
IDENTITY_MAP: dict[str, str] = {
    "employee_alice": "alice",
    "employee_bruno": "bob",
    "employee_carla": "carla",
}


def main():
    robot = Robot()

    gate     = "checkpoint"
    max_dist = DEFAULT_MAX_DIST
    for arg in sys.argv[1:]:
        if arg.startswith("--gate="):
            gate = arg.split("=", 1)[1]
        elif arg.startswith("--max-dist="):
            max_dist = float(arg.split("=", 1)[1])

    emitter = robot.getDevice("emitter")
    emitter.setChannel(1)

    receiver = robot.getDevice("receiver")
    receiver.setChannel(1)
    receiver.enable(TIME_STEP)

    camera = robot.getDevice("camera")
    camera.enable(TIME_STEP)
    camera.recognitionEnable(RECOGNITION_PERIOD)

    cooldown = 0
    force_scan = False

    while robot.step(TIME_STEP) != -1:
        # Check for reverify commands from supervisor
        while receiver.getQueueLength() > 0:
            try:
                data = json.loads(receiver.getString())
                if data.get("to") == robot.getName() and data.get("action") == "reverify":
                    force_scan = True
                    cooldown = 0
            except Exception:
                pass
            finally:
                receiver.nextPacket()

        if cooldown > 0 and not force_scan:
            cooldown -= 1
            continue

        objects = camera.getRecognitionObjects()
        if not objects:
            force_scan = False
            continue

        for obj in objects:
            pos  = obj.getPosition()
            dist = math.sqrt(pos[0]**2 + pos[1]**2 + pos[2]**2)
            if dist > max_dist:
                continue   # too far — likely through a doorway into another room

            model = obj.getModel()
            identity = IDENTITY_MAP.get(model, "unknown")
            confidence = 0.95 if identity != "unknown" else 0.80

            payload = json.dumps({
                "type":       "sensor",
                "event":      "face_detected",
                "zone":       gate,       # supervisor translates to MAS zone
                "identity":   identity,
                "confidence": confidence,
                "liveness":   True,
                "reverification": force_scan,
            })
            emitter.send(payload)

        force_scan = False
        cooldown = SCAN_COOLDOWN


if __name__ == "__main__":
    main()
