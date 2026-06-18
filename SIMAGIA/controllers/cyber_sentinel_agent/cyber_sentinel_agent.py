"""Webots controller for server racks (CyberSentinel — passive mode).

Anomalies are injected manually via the dashboard, not generated here.
The rack LED starts green and turns red when the supervisor relays an
active anomaly event (via Receiver channel 1).
"""

import json
from controller import Robot

TIME_STEP = 256   # ms — must match WorldInfo.basicTimeStep


def main():
    robot = Robot()

    receiver = robot.getDevice("receiver")
    receiver.setChannel(1)
    receiver.enable(TIME_STEP)

    led = robot.getDevice("status_led")
    led.set(0)   # green — normal

    alert_steps = 0   # steps remaining for red LED

    while robot.step(TIME_STEP) != -1:
        # Listen for anomaly alerts relayed from the supervisor
        while receiver.getQueueLength() > 0:
            try:
                data = json.loads(receiver.getString())
                if data.get("event") == "cyber_anomaly" and data.get("zone") == "datacenter":
                    led.set(1)        # red — anomaly active
                    alert_steps = 150  # ~10 s
            except Exception:
                pass
            finally:
                receiver.nextPacket()

        if alert_steps > 0:
            alert_steps -= 1
            if alert_steps == 0:
                led.set(0)   # green — back to normal


if __name__ == "__main__":
    main()
