"""Webots controller for FaceID cameras.

Captures raw BGRA frames from the Webots camera and sends them to the
MAS dashboard (/api/recognize_face) which runs InsightFace in the main
Python process. Returns identity + confidence to the MAS via emitter.

Only uses stdlib (urllib, json, struct) — no heavy ML dependencies needed
in the Webots Python environment.

Arguments (controllerArgs in the .wbt):
    --gate=GATE_NAME   e.g. --gate=checkpoint  --gate=work_room_1
"""

import json
import struct
import sys
import threading
import urllib.error
import urllib.request
from controller import Robot

TIME_STEP      = 256   # ms — must match WorldInfo.basicTimeStep
SCAN_COOLDOWN  = 40    # steps between recognition requests (~10 s)
DASHBOARD_URL  = "http://localhost:8081"

# Shared state for async recognition (background thread → main loop)
_pending  = False          # True while a request is in-flight
_result   = None           # latest result dict, or None
_lock     = threading.Lock()


def _recognize_bg(img_bytes: bytes, w: int, h: int) -> None:
    """Runs in a background thread — never blocks the Webots step."""
    global _pending, _result
    header  = w.to_bytes(4, "big") + h.to_bytes(4, "big")
    payload = header + img_bytes
    req = urllib.request.Request(
        DASHBOARD_URL + "/api/recognize_face",
        data=payload,
        headers={"Content-Type": "application/octet-stream"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            resultado = json.loads(resp.read())
    except Exception:
        resultado = {"reason": "service_unavailable"}
    with _lock:
        _result  = resultado
        _pending = False


def main():
    robot = Robot()

    gate = "checkpoint"
    for arg in sys.argv[1:]:
        if arg.startswith("--gate="):
            gate = arg.split("=", 1)[1]

    emitter = robot.getDevice("emitter")
    emitter.setChannel(1)

    receiver = robot.getDevice("receiver")
    receiver.setChannel(1)
    receiver.enable(TIME_STEP)

    camera = robot.getDevice("camera")
    camera.enable(TIME_STEP)

    global _pending, _result

    cooldown   = 0
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

        # ── Check if a background recognition result arrived ─────
        with _lock:
            resultado = _result
            _result   = None

        if resultado is not None:
            reason = resultado.get("reason", "ok")
            if reason not in ("sem_rosto", "imagem_invalida",
                              "base_vazia", "service_unavailable"):
                identity   = resultado.get("matched_name") if resultado.get("allowed") else "unknown"
                score      = resultado.get("score") or 0.0
                confidence = round(score if identity != "unknown" else 0.80, 2)
                emitter.send(json.dumps({
                    "type":           "sensor",
                    "event":          "face_detected",
                    "zone":           gate,
                    "identity":       identity,
                    "confidence":     confidence,
                    "liveness":       True,
                    "reverification": force_scan,
                }))
            force_scan = False
            cooldown = SCAN_COOLDOWN

        # ── Fire new recognition request (non-blocking) ──────────
        if cooldown > 0 and not force_scan:
            cooldown -= 1
            continue

        with _lock:
            already_pending = _pending

        if already_pending:
            continue  # previous request still in-flight

        img_bytes = camera.getImage()
        if not img_bytes:
            continue

        w = camera.getWidth()
        h = camera.getHeight()

        with _lock:
            _pending = True
        t = threading.Thread(
            target=_recognize_bg,
            args=(bytes(img_bytes), w, h),
            daemon=True,
        )
        t.start()


if __name__ == "__main__":
    main()
