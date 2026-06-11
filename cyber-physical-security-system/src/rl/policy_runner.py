"""
Integration shim: trained PPO navigation policy → SIMAGIA / ROS2.

This is the concrete replacement for
`sentinel_mas/agents/patrol.py::NavigationStub` that the SIMAGIA design calls
for ("substituir por política PPO a publicar Twist em /cmd_vel").

Two consumers, one policy:

  * SIMAGIA PatrolAgent — `await navigator.move(agent, target)` glides
    `agent.pos` (SIMAGIA's 0..100 grid) to the target, identical signature to
    NavigationStub, so it drops in with no other agent changes.

  * ROS2 bridge — `navigator.velocity_command(pose, goal)` returns the raw
    (vx, vy, vyaw) to feed straight into make_move_request() / publish_cmd_vel().

The policy is queried closed-loop: observe → predict → actuate → repeat, so it
reacts to wherever the robot actually is (drift, disturbances), unlike the
open-loop stub.
"""

from __future__ import annotations

import asyncio
import math

import numpy as np
from stable_baselines3 import PPO

from env import OfficeNavEnv


class PPONavigator:
    """Closed-loop navigation driven by a trained PPO policy."""

    def __init__(self, model_path: str, config: dict | None = None,
                 deterministic: bool = True):
        self.model = PPO.load(model_path)
        # The env is reused purely as the single source of truth for the
        # observation encoding and the kinematic model — guarantees the obs we
        # feed the policy is byte-identical to what it trained on.
        self._env = OfficeNavEnv(config=config or {})
        self.deterministic = deterministic

    # ── Prediction: normalised action for a given pose+goal ──────────────
    def _predict_norm(self, pose: tuple, goal_m: tuple, prev_norm) -> np.ndarray:
        """Query the policy; returns the normalised action in [-1, 1].
        `prev_norm` is the previous *normalised* action (obs slots 7-9)."""
        e = self._env
        e._pos = np.array(pose[:2], dtype=np.float32)
        e._heading = float(pose[2])
        e._goal = np.array(goal_m, dtype=np.float32)
        e._prev_action = np.asarray(prev_norm, dtype=np.float32)
        obs = e._observe()
        action, _ = self.model.predict(obs, deterministic=self.deterministic)
        return np.clip(action, -1.0, 1.0).astype(np.float32)

    # ── Low-level: one velocity command for a given pose+goal ────────────
    def velocity_command(self, pose: tuple, goal_m: tuple,
                         prev_norm=(0.0, 0.0, 0.0)) -> tuple:
        """Return real (vx, vy, vyaw) for a robot at `pose`=(x_m, y_m,
        heading_rad) aiming for `goal_m`=(x_m, y_m), to feed straight into
        make_move_request() / publish_cmd_vel().  Metric frame throughout."""
        norm = self._predict_norm(pose, goal_m, prev_norm)
        vx, vy, vyaw = self._env._rescale_action(norm)
        return float(vx), float(vy), float(vyaw)

    # ── High-level: drop-in for NavigationStub.move() ────────────────────
    async def move(self, agent, target: tuple) -> None:
        """Drive `agent.pos` (SIMAGIA 0..100 grid) to `target` (grid) by rolling
        the policy closed-loop.  Matches NavigationStub.move()'s signature."""
        e = self._env
        pos = e._to_m(agent.pos)                       # grid → metres
        goal = e._to_m(target)
        heading = math.atan2(*(goal - pos)[::-1])      # face the goal initially
        prev = np.zeros(3, dtype=np.float32)

        max_ticks = e._max_steps
        for _ in range(max_ticks):
            norm = self._predict_norm(
                (float(pos[0]), float(pos[1]), heading), goal, prev
            )
            prev = norm                                # feed normalised action back
            vx, vy, vyaw = e._rescale_action(norm)

            # --- ACTUATE ---
            # ROS2 mode: bridge.publish_cmd_vel(vx, vy, vyaw); pose ← odometry.
            # Sim/dashboard mode: integrate the same kinematic model the policy
            # trained on, then mirror the pose onto agent.pos for the UI.
            e._pos = pos
            e._heading = heading
            e._integrate(vx, vy, vyaw)
            pos, heading = e._pos, e._heading

            agent.pos = (float(pos[0]) / e.map_scale, float(pos[1]) / e.map_scale)
            await asyncio.sleep(e.dt)

            if float(np.linalg.norm(goal - pos)) <= e.goal_radius:
                break

        agent.pos = target

    async def scan_zone(self, zone: str, scan_seconds: float = 5.0) -> str:
        """Kept for interface parity with NavigationStub.  Scanning is a
        perception concern (FaceID/Motion agents), not navigation — left as a
        timed no-op so PatrolMission keeps working unchanged."""
        await asyncio.sleep(scan_seconds)
        return "clear"
