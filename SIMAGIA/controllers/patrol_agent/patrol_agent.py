"""Webots controller for the patrol robot.

Responsibilities:
  - Receives commands from the security_supervisor via Receiver (channel 1).
  - On "scan" command: activates the camera, scans for unknown persons,
    reports result back to the supervisor via Emitter.
  - On "idle" command: turns off the beacon LED.

Physical movement (teleportation between zones) is handled entirely by the
security_supervisor using the Supervisor API so that the SPADE MAS position
accounting stays in sync.  This controller only handles what happens once
the robot has arrived at its destination.
"""

import json
from controller import Robot

TIME_STEP = 256    # ms — must match WorldInfo.basicTimeStep
SCAN_STEPS   = 20   # ~2.5 s sim scanning window

# Webots model names that indicate an unauthorised person
UNKNOWN_MODELS = {"person_unknown"}


def main():
    robot = Robot()

    receiver = robot.getDevice("receiver")
    receiver.setChannel(1)
    receiver.enable(TIME_STEP)

    emitter = robot.getDevice("emitter")
    emitter.setChannel(1)

    camera = robot.getDevice("patrol_camera")
    camera.enable(TIME_STEP)
    # Recognition only enabled during active scan to save CPU

    beacon = robot.getDevice("beacon")

    scanning      = False
    scan_timer    = 0
    current_zone  = None

    while robot.step(TIME_STEP) != -1:
        # ── Incoming commands from supervisor ────────────────────
        while receiver.getQueueLength() > 0:
            try:
                data = json.loads(receiver.getString())
            except Exception:
                receiver.nextPacket()
                continue
            receiver.nextPacket()

            if data.get("to") != "patrol_robot":
                continue

            action = data.get("action")
            if action == "scan":
                scanning     = True
                scan_timer   = SCAN_STEPS
                current_zone = data.get("zone")
                camera.recognitionEnable(TIME_STEP)
                beacon.set(1)
            elif action == "idle":
                scanning = False
                beacon.set(0)

        # ── Scanning phase ───────────────────────────────────────
        if scanning:
            scan_timer -= 1
            if scan_timer <= 0:
                scanning = False
                beacon.set(0)

                objects  = camera.getRecognitionObjects()
                camera.recognitionDisable()
                models   = {obj.getModel() for obj in objects}
                intruder = bool(models & UNKNOWN_MODELS)

                result  = "intruder_confirmed" if intruder else "clear"
                payload = json.dumps({
                    "type":   "report",
                    "from":   "patrol_robot",
                    "event":  "patrol_scan_result",
                    "zone":   current_zone,
                    "result": result,
                })
                emitter.send(payload)


if __name__ == "__main__":
    main()
