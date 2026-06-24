"""MotionAgent — sensor de movimento (PIR) de uma zona.

Tal como no artigo, o PIR e aproximado por DistanceSensors do Webots: tres
feixes em leque apontados para a zona. Apos uma fase de calibracao (cena
vazia), qualquer desvio significativo numa das leituras e interpretado como
movimento e publicado como evento MOTION no canal partilhado.
"""

import json
import sys

from controller import Robot

CALIBRATION_STEPS = 40    # amostras usadas para fixar a linha de base
TRIGGER_DELTA = 0.6       # m de desvio face a linha de base para disparar
EVENT_COOLDOWN = 2.0      # s minimos entre eventos MOTION
LED_FLASH_TIME = 0.6      # s com o LED aceso apos detecao


def main():
    robot = Robot()
    timestep = int(robot.getBasicTimeStep())

    zone = "unknown"
    for arg in sys.argv[1:]:
        if arg.startswith("--zone="):
            zone = arg.split("=", 1)[1]

    sensors = []
    for sensor_name in ("ds_center", "ds_left", "ds_right"):
        sensor = robot.getDevice(sensor_name)
        sensor.enable(timestep)
        sensors.append(sensor)
    led = robot.getDevice("led")
    emitter = robot.getDevice("emitter")

    baselines = None
    samples = []
    last_event = -1e9
    led_until = -1e9

    print(f"[motion] PIR da zona '{zone}' a calibrar...")

    while robot.step(timestep) != -1:
        now = robot.getTime()
        values = [sensor.getValue() for sensor in sensors]

        if baselines is None:
            samples.append(values)
            if len(samples) >= CALIBRATION_STEPS:
                baselines = [
                    sum(sample[i] for sample in samples) / len(samples)
                    for i in range(len(sensors))
                ]
                print(f"[motion] PIR '{zone}' calibrado: "
                      f"{[round(b, 2) for b in baselines]}")
            continue

        moved = any(
            abs(value - baseline) > TRIGGER_DELTA
            for value, baseline in zip(values, baselines)
        )
        if moved and now - last_event >= EVENT_COOLDOWN:
            last_event = now
            led_until = now + LED_FLASH_TIME
            emitter.send(json.dumps({"type": "MOTION", "zone": zone}).encode())

        led.set(1 if now < led_until else 0)


if __name__ == "__main__":
    main()
