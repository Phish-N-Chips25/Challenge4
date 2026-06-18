"""Webots controller for PIR motion sensors (DistanceSensor × 3).

Simulates a passive infrared sensor: only fires motion_detected when an
object ENTERS the detection range (transition from absent → present).
Each sensor beam is tracked independently so a rack blocking one beam
doesn't suppress detection on the other beams.

Arguments (controllerArgs in the .wbt):
    --zone=ZONE_NAME   e.g. --zone=lobby
"""

import json
import sys
from controller import Robot

TIME_STEP = 256    # ms — must match WorldInfo.basicTimeStep
# Ceiling-mounted at 3.0m, pointing straight down.
# Person (1.7m, bounding cylinder top ~1.17m) → sensor reads ~1.83m → triggers.
# Furniture/floor (≤0.75m) → 2.25m → not < 1.9m → no trigger.
# Server rack (2m, reads 1.0m) → triggers BUT tracked independently per beam.
THRESHOLD      = 1.9   # metres
DEBOUNCE_STEPS = 10    # cooldown after firing
STARTUP_STEPS  = 3     # steps to absorb static background (keep short so people aren't missed)


def main():
    robot = Robot()

    zone = "lobby"
    for arg in sys.argv[1:]:
        if arg.startswith("--zone="):
            zone = arg.split("=", 1)[1]

    emitter = robot.getDevice("emitter")
    emitter.setChannel(1)

    sensors = [
        robot.getDevice("ds_center"),
        robot.getDevice("ds_left"),
        robot.getDevice("ds_right"),
    ]
    for ds in sensors:
        ds.enable(TIME_STEP)

    try:
        led = robot.getDevice("led")
    except Exception:
        led = None

    # Per-beam state: True = something already present (don't re-fire)
    was = [False, False, False]
    startup  = STARTUP_STEPS
    debounce = 0

    while robot.step(TIME_STEP) != -1:

        det = [s.getValue() < THRESHOLD for s in sensors]

        if startup > 0:
            startup -= 1
            # Absorb current state per beam as static background
            for i in range(3):
                was[i] = det[i]
            continue

        if debounce > 0:
            debounce -= 1
            if led and debounce == 0:
                led.set(0)
            # Still update was[] so re-arm logic is correct after debounce
            for i in range(3):
                if not det[i]:
                    was[i] = False
            continue

        # New entry: any beam that was clear and now detects something
        new_entry = any(det[i] and not was[i] for i in range(3))

        for i in range(3):
            was[i] = det[i]   # update state: clear when not detecting

        if new_entry:
            emitter.send(json.dumps({
                "type":  "sensor",
                "event": "motion_detected",
                "zone":  zone,
            }))
            if led:
                led.set(1)
            debounce = DEBOUNCE_STEPS


if __name__ == "__main__":
    main()
