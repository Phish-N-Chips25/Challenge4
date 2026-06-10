#!/usr/bin/env bash
set -e

# ── Webots Python controller path ────────────────────────────────────────────
WEBOTS_PYTHON="${WEBOTS_HOME}/lib/controller/python"
if [ -d "$WEBOTS_PYTHON" ]; then
    export PYTHONPATH="${WEBOTS_PYTHON}:${PYTHONPATH}"
    echo "[entrypoint] Added Webots Python controller to PYTHONPATH"
fi

# ── Virtual display (always start – needed even for headless Webots) ─────────
Xvfb :99 -screen 0 1920x1080x24 &
sleep 1

if [ "${WEBOTS_HEADLESS}" = "true" ]; then
    echo "[entrypoint] Running in HEADLESS mode"
else
    echo "[entrypoint] Starting GUI stack (VNC + noVNC on :6080)"
    fluxbox &
    x11vnc -display :99 -forever -nopw -shared -rfbport 5900 &
    websockify --web /usr/share/novnc 6080 localhost:5900 &
    sleep 1
    echo "============================================="
    echo "  noVNC ready → http://localhost:6080"
    echo "============================================="
fi

# ── Hand off to CMD ──────────────────────────────────────────────────────────
exec "$@"
