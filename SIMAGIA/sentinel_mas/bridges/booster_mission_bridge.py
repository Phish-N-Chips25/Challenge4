"""Bridge: SIMAGIA dispatches → Booster T1 patrol (via the JSONL seam).

Integration mode "SIMAGIA decides, PPO drives":
  * SIMAGIA's Contract Net auction decides WHICH zone to patrol (unchanged).
  * Instead of simulating movement in Python (PPONavigator/NavigationStub),
    this navigator writes a DISPATCH mission to the file seam the colleague's
    Booster stack already consumes, and the on-robot node drives the Booster
    T1 there. The PPO policy drives the robot inside that node (ppo_patrol_node,
    Part 2) — SIMAGIA stays the brain, the robot stays the body.

File seam (matches ros2_ws .../patrol_mission_bridge.py exactly, append-only
JSONL under a shared .logs/ dir):
  * booster_missions.jsonl — we WRITE  {type:DISPATCH, kind,x,y,target,model,zone,reason}
  * booster_status.jsonl   — we READ   {type:REPORT|ASSIST_DONE|DETAINED|..., zone,...}
  * booster_pose.json      — we READ   {x,y,theta,time}  (robot ground-truth pose)

Mission kinds (their schema): 'investigate' | 'assist' | 'detain'.
SIMAGIA only emits 'investigate' (routine/threat patrol of a zone) and
'assist' (staff request). 'detain' chases a MOVING target and needs the
supervisor's ground-truth target position + lidar avoidance, so it stays on
their navigation stack — SIMAGIA never emits it.

Soft by design: if USE_BOOSTER_BRIDGE is off this module isn't used at all;
the patrol agent keeps PPONavigator/NavigationStub.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from pathlib import Path
from typing import Any

# Terminal status events that mean "this SIMAGIA mission is finished" — the
# robot arrived and completed the on-site action. Keyed by mission kind.
_DONE_STATUS = {
    "investigate": "REPORT",
    "assist": "ASSIST_DONE",
}
_POLL_SECONDS = 0.2          # how often we poll status/pose while en route


# ── Low-level JSONL helpers (self-contained — no ROS dependency) ─────────────

def append_mission(path: Path, *, kind: str, x: float, y: float,
                   zone: str | None, reason: str = "",
                   target: str | None = None, model: str | None = None) -> None:
    """Append a DISPATCH mission — byte-identical to the schema the Booster
    patrol node's read_new_missions() expects."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "time": time.time(), "type": "DISPATCH", "kind": kind,
        "x": float(x), "y": float(y), "target": target, "model": model,
        "zone": zone, "reason": reason,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, separators=(",", ":")) + "\n")


def read_new_statuses(path: Path, offset: int) -> tuple[list[dict], int]:
    """Read status events appended after `offset` bytes. Returns (events, new_offset)."""
    if not path.exists():
        return [], offset
    events: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        fh.seek(offset)
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return events, fh.tell()


def read_pose(path: Path) -> tuple[float, float] | None:
    """Latest robot (x, y) in Webots metres, or None if unavailable."""
    try:
        p = json.loads(path.read_text(encoding="utf-8"))
        return float(p["x"]), float(p["y"])
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


# ── Navigator: drop-in replacement for PPONavigator in patrol.py ─────────────

class BoosterBridgeNavigator:
    """Delegates navigation to the Booster T1 over the JSONL file seam.

    Same async interface as PPONavigator (move / scan_zone), so patrol.py
    swaps it in with no behavioural changes. The robot's on-board node drives
    (PPO for investigate/assist); we just dispatch and await completion,
    mirroring agent.pos from the robot's real pose so the dashboard tracks it.
    """

    def __init__(self, log_dir: str | Path, zone_pos: dict[str, tuple[float, float]]):
        self.log_dir = Path(log_dir)
        self.missions_path = self.log_dir / "booster_missions.jsonl"
        self.status_path = self.log_dir / "booster_status.jsonl"
        self.pose_path = self.log_dir / "booster_pose.json"
        # zone name -> (x, y) for resolving raw-tuple targets back to a zone label
        self._zone_pos = {z: (float(p[0]), float(p[1])) for z, p in zone_pos.items()}

    # -- helpers -------------------------------------------------------------

    def _resolve(self, target) -> tuple[str | None, float, float]:
        """Return (zone_name, x, y). target is a zone name OR an (x, y) tuple;
        a tuple is reverse-matched to the nearest known zone for the label."""
        if isinstance(target, str):
            x, y = self._zone_pos.get(target, (0.0, 0.0))
            return target, x, y
        x, y = float(target[0]), float(target[1])
        zone = min(self._zone_pos,
                   key=lambda z: math.dist(self._zone_pos[z], (x, y)),
                   default=None)
        return zone, x, y

    @staticmethod
    def _kind_for(_zone: str | None) -> str:
        # SIMAGIA routine/threat patrol of a zone == 'investigate'. 'detain'
        # (moving target) is deliberately left to the supervisor + lidar nav.
        return "investigate"

    # -- NavigationStub / PPONavigator interface -----------------------------

    async def move(self, agent, target, abort_event: asyncio.Event = None,
                   realtime: bool = True) -> bool:
        """Dispatch a mission and await the robot's completion status.

        Returns True when the robot reports done (REPORT/ASSIST_DONE) for this
        zone, False if abort_event fires (auction preemption) first.
        """
        zone, gx, gy = self._resolve(target)
        kind = self._kind_for(zone)
        append_mission(self.missions_path, kind=kind, x=gx, y=gy, zone=zone,
                       reason=f"SIMAGIA dispatch to {zone}")

        # Offline (tests/eval): there is no live robot to answer — record the
        # dispatch, snap agent.pos to the goal, and return.
        if not realtime:
            agent.pos = (gx, gy)
            return True

        done_type = _DONE_STATUS.get(kind, "REPORT")
        _, offset = read_new_statuses(self.status_path, 0)   # ignore history
        while True:
            if abort_event and abort_event.is_set():
                return False
            pose = read_pose(self.pose_path)
            if pose is not None:
                agent.pos = pose
            events, offset = read_new_statuses(self.status_path, offset)
            for ev in events:
                if ev.get("type") == done_type and (ev.get("zone") in (zone, None)):
                    agent.pos = (gx, gy)
                    return True
                if ev.get("type") in ("FAILED", "NAVIGATION_FAILED"):
                    return False
            await asyncio.sleep(_POLL_SECONDS)

    async def scan_zone(self, zone: str, abort_event: asyncio.Event = None,
                        scan_seconds: float = 5.0, realtime: bool = True) -> str:
        """The Booster's on-site INVESTIGATE already covers scanning, so this is
        a short interruptible no-op kept for interface parity."""
        elapsed, interval = 0.0, 0.1
        while elapsed < scan_seconds:
            if abort_event and abort_event.is_set():
                return "preempted"
            await asyncio.sleep(interval if realtime else 0)
            elapsed += interval
        return "clear"
