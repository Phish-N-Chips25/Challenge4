"""WebotsBridge — thread-safe bridge between the Webots simulation loop
and the SPADE async MAS running in a background thread.

Webots side  (synchronous, runs every TIME_STEP ms):
    bridge.put_sensor_event(event_dict)   ← sensor controllers → supervisor
    bridge.get_patrol_command()           → supervisor reads patrol targets
    bridge.notify_arrived()              → supervisor signals patrol reached zone
    bridge.put_scan_result(result)        → supervisor signals scan finished

SPADE side (async, background thread):
    bridge.get_sensor_event(timeout)      ← WebotsSensorBehaviour polls this
    bridge.put_patrol_command(cmd)        ← WebotsNavigation sends targets
    bridge.wait_arrived()                 → WebotsNavigation awaits arrival
    bridge.wait_scan_result(timeout)      → WebotsNavigation awaits scan
"""

from __future__ import annotations
import queue
import threading

_instance: "WebotsBridge | None" = None


class WebotsBridge:
    def __init__(self):
        self._sensor_q: queue.Queue[dict] = queue.Queue()
        self._command_q: queue.Queue[dict] = queue.Queue()
        self._scan_q: queue.Queue[str] = queue.Queue()
        self._arrived = threading.Event()

        global _instance
        _instance = self

    # ── Webots → SPADE ───────────────────────────────────────────
    def put_sensor_event(self, event: dict) -> None:
        self._sensor_q.put(event)

    def get_sensor_event(self, timeout: float = 0.05) -> dict | None:
        try:
            return self._sensor_q.get(timeout=timeout)
        except queue.Empty:
            return None

    # ── SPADE → Webots ───────────────────────────────────────────
    def put_patrol_command(self, cmd: dict) -> None:
        self._command_q.put(cmd)

    def get_patrol_command(self) -> dict | None:
        try:
            return self._command_q.get_nowait()
        except queue.Empty:
            return None

    # ── Webots → SPADE: patrol navigation sync ───────────────────
    def notify_arrived(self) -> None:
        """Called by supervisor when patrol robot reaches its target."""
        self._arrived.set()

    async def wait_arrived(self, abort_event=None) -> bool:
        """Async poll until the supervisor signals arrival or abort fires.

        Returns True  → robot arrived at target.
        Returns False → mission was preempted before arrival.
        """
        import asyncio
        while not self._arrived.is_set():
            if abort_event and abort_event.is_set():
                return False
            await asyncio.sleep(0.05)
        self._arrived.clear()
        return True

    def put_scan_result(self, result: str) -> None:
        self._scan_q.put(result)

    async def wait_scan_result(self, abort_event=None) -> str:
        """Async poll until the supervisor delivers a scan result."""
        import asyncio
        while True:
            try:
                return self._scan_q.get_nowait()
            except queue.Empty:
                if abort_event and abort_event.is_set():
                    return "preempted"
                await asyncio.sleep(0.1)


def get_bridge() -> "WebotsBridge | None":
    return _instance
