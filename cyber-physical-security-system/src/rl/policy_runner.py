"""
Integration shim: trained PPO navigation policy → SIMAGIA / ROS2.

This is the concrete replacement for
sentinel_mas/agents/patrol.py::NavigationStub that the SIMAGIA design calls
for ("substituir por politica PPO a publicar Twist em /cmd_vel").

Two-layer architecture
----------------------
  GLOBAL  path_planner.plan_path()   — knows the wall layout (office_map.py),
                                        returns a sequence of wall-free
                                        waypoints through doorways.
  LOCAL   PPO policy (this module)   — drives between two consecutive
                                        waypoints, knows nothing about walls.

The PPO policy was trained purely on open-space point-to-point navigation.
It does not need retraining to handle the real (walled) office — the path
planner guarantees every individual leg it's asked to fly is obstacle-free,
which is exactly the assumption it was trained under.

Two consumers, one policy:

  * SIMAGIA PatrolAgent — await navigator.move(agent, zone_name) plans a
    route and drives through it, updating agent.pos with the real Webots
    metre position.  Minimal change required in patrol.py: pass self.zone
    (a string) instead of settings.ZONE_POS[self.zone] (a grid tuple).

  * ROS2 bridge — navigator.velocity_command(pose, goal_m) returns the raw
    (vx, vy, vyaw) for a single waypoint leg; navigator.get_waypoints(...)
    exposes the planned route so the ROS2 node can step through it itself.

The policy is queried closed-loop: observe -> predict -> actuate -> repeat,
so it reacts to wherever the robot actually is (drift, disturbances), unlike
an open-loop stub.

Zone names recognised by this shim (must match sentinelmas_office.wbt and
the zone_pos block in configs/ppo.yaml):
    lobby, break_room, corridor, work_room_1..4, datacenter
"""

from __future__ import annotations

import asyncio
import math
import random

import numpy as np
from stable_baselines3 import PPO

from env import OfficeNavEnv
from path_planner import plan_path

# Intermediate waypoints only need to be approached closely enough to clear
# a doorway, not hit the same precision as the final zone goal — but must
# stay tighter than (door half-width - robot radius) or the robot can still
# clip a doorway edge even though the planned line threads it safely.
_WAYPOINT_RADIUS = 0.15


class PPONavigator:
    """Closed-loop navigation driven by a trained PPO policy, with a global
    path planner handling the wall layout."""

    def __init__(self, model_path: str, config: dict | None = None,
                 deterministic: bool = True):
        self.model = PPO.load(model_path)
        # Env reused as the single source of truth for observation encoding —
        # guarantees the obs fed to the policy is identical to training.
        self._env = OfficeNavEnv(config=config or {})
        self.deterministic = deterministic

    # ── Prediction: normalised action for a given pose+goal ──────────────────

    def _predict_norm(self, pose: tuple, goal_m: tuple, prev_norm) -> np.ndarray:
        """Query the policy; returns the normalised action in [-1, 1].
        prev_norm is the previous *normalised* action (obs slots 7-9)."""
        e = self._env
        e._pos         = np.array(pose[:2], dtype=np.float32)
        e._heading     = float(pose[2])
        e._goal        = np.array(goal_m, dtype=np.float32)
        e._prev_action = np.asarray(prev_norm, dtype=np.float32)
        obs = e._observe()
        action, _ = self.model.predict(obs, deterministic=self.deterministic)
        return np.clip(action, -1.0, 1.0).astype(np.float32)

    # ── Low-level: one velocity command for a given pose+goal ────────────────

    def velocity_command(self, pose: tuple, goal_m: tuple,
                         prev_norm=(0.0, 0.0, 0.0)) -> tuple:
        """Return real (vx, vy, vyaw) for a robot at pose=(x_m, y_m, heading_rad)
        aiming for goal_m=(x_m, y_m) — ONE leg, not a full route.  Feeds
        straight into make_move_request() or publish_cmd_vel().

        For a full cross-room trip, call get_waypoints() first and step
        through the returned legs yourself (the ROS2 node owns its own
        control loop, unlike move() below which owns the loop for SIMAGIA)."""
        norm = self._predict_norm(pose, goal_m, prev_norm)
        vx, vy, vyaw = self._env._rescale_action(norm)
        return float(vx), float(vy), float(vyaw)

    # ── Path planning helper, exposed for both consumers ──────────────────────

    def get_waypoints(self, start_xy: tuple, goal_zone: str) -> list[tuple]:
        """Plan a wall-free route from start_xy to goal_zone's centre.
        Returns [start_xy, ...intermediate doors..., zone_centre]."""
        return plan_path(start_xy, goal_zone)

    # ── High-level: drop-in for NavigationStub.move() ────────────────────────

    async def move(self, agent, target: str | tuple,
                   abort_event: asyncio.Event = None, realtime: bool = True) -> bool:
        """Drive the robot to `target`, planning around walls, and update
        agent.pos every tick.

        target: zone name string (e.g. "lobby") OR (x, y) in Webots metres
                (a raw tuple skips planning — used for sub-waypoint calls).
        agent.pos is updated to the real metre position each step so SIMAGIA's
        dashboard can track the robot (metres, not the 0..100 grid).
        realtime: if False, skip the per-tick sleep (dynamics are identical,
                it just doesn't wait control_dt seconds between ticks) — for
                fast offline testing/evaluation. Always True in production.

        Returns True when arrived, False when abort_event fires mid-flight
        (preempted by a higher-priority auction winner).

        Minimal change needed in sentinel_mas/agents/patrol.py:
            await agent.nav.move(agent, self.zone, agent.abort_event)
        instead of:
            await agent.nav.move(agent, settings.ZONE_POS[self.zone], ...)
        """
        e = self._env
        start_xy = (float(agent.pos[0]), float(agent.pos[1]))

        # Plan a wall-free route whether the target is a zone name OR a raw
        # (x, y) point (e.g. the patrol base). Routing BOTH through plan_path
        # means the return-to-base leg avoids walls exactly like a zone route,
        # rather than driving a naive straight line that could clip a wall.
        waypoints = plan_path(start_xy, target)[1:]   # drop the start itself

        pos  = np.array(start_xy, dtype=np.float32)
        prev = np.zeros(3, dtype=np.float32)
        goal = pos  # in case waypoints is somehow empty (already at target)

        for leg_idx, wp in enumerate(waypoints):
            goal = np.array(wp, dtype=np.float32)
            is_final = (leg_idx == len(waypoints) - 1)
            radius = e.goal_radius if is_final else _WAYPOINT_RADIUS
            heading = math.atan2(*(goal - pos)[::-1])  # face this leg's target
            min_dist_seen = math.inf

            for _ in range(e._max_steps):
                if abort_event and abort_event.is_set():
                    agent.pos = (float(pos[0]), float(pos[1]))
                    return False

                norm = self._predict_norm(
                    (float(pos[0]), float(pos[1]), heading), goal, prev
                )
                prev = norm
                vx, vy, vyaw = e._rescale_action(norm)

                # ACTUATE
                # ROS2 mode: bridge.publish_cmd_vel(vx, vy, vyaw); pose <- odometry.
                # Dashboard mode: integrate kinematic model, mirror to agent.pos.
                e._pos     = pos
                e._heading = heading
                e._integrate(vx, vy, vyaw)
                pos, heading = e._pos.copy(), e._heading

                agent.pos = (float(pos[0]), float(pos[1]))
                await asyncio.sleep(e.dt if realtime else 0)

                dist = float(np.linalg.norm(goal - pos))
                min_dist_seen = min(min_dist_seen, dist)
                if dist <= radius:
                    break  # this leg done, advance to next waypoint
                # Pass-through: robot got close but is now moving away — don't
                # let it spiral back. Only for intermediate waypoints; the final
                # goal always requires full convergence.
                if (not is_final
                        and min_dist_seen <= radius * 2.0
                        and dist > min_dist_seen + radius * 0.5):
                    break

        agent.pos = (float(goal[0]), float(goal[1]))
        return True

    async def scan_zone(self, zone: str, abort_event: asyncio.Event = None,
                        scan_seconds: float = 5.0, realtime: bool = True) -> str:
        """Inspect a zone — drop-in for NavigationStub.scan_zone.

        Matches the stub's interface exactly: positional (zone, abort_event),
        returns "preempted" if the auction aborts the mission mid-scan, else a
        scan result. Scanning is a perception concern (Motion/FaceID agents),
        so this stays a timed, interruptible placeholder — real detection
        should flow in from those agents, not the navigation layer."""
        elapsed, interval = 0.0, 0.1
        while elapsed < scan_seconds:
            if abort_event and abort_event.is_set():
                return "preempted"
            await asyncio.sleep(interval if realtime else 0)
            elapsed += interval
        return random.choice(["clear", "clear", "clear", "intruder_confirmed"])
