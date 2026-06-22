"""
Goal-conditioned navigation environment for the patrol robot.

Role in the system
------------------
This env trains the *navigation* layer only — NOT zone selection.

  * Which zone to patrol  → decided by the SIMAGIA multi-agent system
    (Contract Net auction).  See SIMAGIA/sentinel_mas.
  * How to drive there    → THIS policy.  Given the dispatched target it
    produces body-frame velocity commands (vx, vy, vyaw) that match the
    Booster T1 walking interface (make_move_request in unitree-g1-webots).

The trained policy is a drop-in replacement for
sentinel_mas/agents/patrol.py::NavigationStub.move() — see
src/rl/policy_runner.py for the integration shim.

Coordinate frame
----------------
All positions are in Webots world metres, matching sentinelmas_office.wbt.
Arena: x in [-10, 10], y in [-6, 6] (external walls in the .wbt file).

The env is deliberately Webots-free so PPO can run millions of fast steps.
When the ROS2/Webots bridge is enabled, swap the kinematic _integrate()
step for a real publish_cmd_vel() + get_odometry() round-trip — the
observation/action contract stays identical.
"""

from __future__ import annotations

import math

import gymnasium as gym
import numpy as np
from gymnasium import spaces


# Webots world metres, from zone-mark Solid nodes in sentinelmas_office.wbt.
DEFAULT_ZONE_POS = {
    "lobby":       (-5.0, -3.5),
    "break_room":  ( 5.0, -3.5),
    "corridor":    ( 0.0,  0.0),
    "work_room_1": (-8.0,  3.5),
    "work_room_2": (-4.0,  3.5),
    "work_room_3": ( 0.0,  3.5),
    "work_room_4": ( 4.0,  3.5),
    "datacenter":  ( 8.0,  3.5),
}
DEFAULT_BASE_POS = (9.0, 0.0)   # PATROL_ROBOT translation in sentinelmas_office.wbt

# External wall positions in sentinelmas_office.wbt.
DEFAULT_ARENA = {"x": (-10.0, 10.0), "y": (-6.0, 6.0)}

# Booster T1 safe velocity envelope, from unitree-g1-webots rpc_commands.py.
# Asymmetric vx (fast forward, slow reverse) is a real property of the biped gait.
DEFAULT_VEL_LIMITS = {
    "vx":   (-0.1, 0.7),    # m/s  forward / reverse
    "vy":   (-0.1, 0.1),    # m/s  lateral strafe
    "vyaw": (-0.2, 0.2),    # rad/s  turn rate
}


class OfficeNavEnv(gym.Env):
    """Point-to-point navigation with a Booster-T1-faithful action space.

    Observation (Box, 10-d, all in [-1, 1]):
        0   x position            (normalised over arena x half-extent)
        1   y position            (normalised over arena y half-extent)
        2   sin(heading)
        3   cos(heading)
        4   goal error, forward   (body frame, normalised by arena diagonal)
        5   goal error, lateral   (body frame, normalised by arena diagonal)
        6   distance to goal      (normalised by arena diagonal)
        7   previous vx           (normalised to [-1, 1])
        8   previous vy           (normalised to [-1, 1])
        9   previous vyaw         (normalised to [-1, 1])

    Action (Box, 3-d, normalised [-1, 1]): rescaled internally to the robot's
        body-frame velocity envelope (vx, vy, vyaw).  A symmetric, normalised
        action space is what PPO's Gaussian policy expects; _rescale_action
        maps it onto the real (asymmetric) Booster T1 limits, which then feed
        make_move_request(vx, vy, vyaw) 1:1.

    Reward: potential-based progress toward the goal, a terminal bonus for
        arriving, a per-step efficiency cost, an action-smoothness penalty
        (biped stability), and an out-of-bounds penalty.
    """

    metadata = {"render_modes": ["human"]}

    def __init__(self, config: dict | None = None, render_mode=None):
        super().__init__()
        cfg = config or {}
        self.render_mode = render_mode

        # Arena bounds (Webots world metres, from external walls in .wbt)
        arena = cfg.get("arena", DEFAULT_ARENA)
        self._x_min, self._x_max = arena["x"]
        self._y_min, self._y_max = arena["y"]
        self._x_half = (self._x_max - self._x_min) / 2.0   # 10.0 m
        self._y_half = (self._y_max - self._y_min) / 2.0   # 6.0 m
        self._diag = math.sqrt(
            (self._x_max - self._x_min) ** 2 + (self._y_max - self._y_min) ** 2
        )  # ~23.3 m — used for distance normalisation

        # Zone positions (Webots world metres)
        zone_pos = cfg.get("zone_pos", DEFAULT_ZONE_POS)
        base_pos = cfg.get("base_pos", DEFAULT_BASE_POS)
        self.zones = list(zone_pos.keys())
        self.zone_pos = {z: np.array(p, dtype=np.float32) for z, p in zone_pos.items()}
        self.base_pos = np.array(base_pos, dtype=np.float32)

        # Robot velocity envelope
        vl = cfg.get("velocity_limits", DEFAULT_VEL_LIMITS)
        self._v_low  = np.array([vl["vx"][0], vl["vy"][0], vl["vyaw"][0]], dtype=np.float32)
        self._v_high = np.array([vl["vx"][1], vl["vy"][1], vl["vyaw"][1]], dtype=np.float32)

        # Episode dynamics
        self.dt          = cfg.get("control_dt", 0.1)
        self.goal_radius = cfg.get("goal_radius", 0.5)
        self._max_steps  = cfg.get("max_episode_steps", 400)

        # Reward weights
        r = cfg.get("reward", {})
        self.w_progress = r.get("progress", 1.0)
        self.r_goal     = r.get("goal_reached", 50.0)
        self.c_step     = r.get("step_penalty", 0.01)
        self.c_smooth   = r.get("action_smoothness_penalty", 0.02)
        self.r_bounds   = r.get("out_of_bounds_penalty", 1.0)

        # Spaces — normalised, symmetric action space (PPO best practice)
        self.action_space = spaces.Box(low=-1.0, high=1.0, shape=(3,), dtype=np.float32)
        self.observation_space = spaces.Box(low=-1.0, high=1.0, shape=(10,), dtype=np.float32)

        # Internal state
        self._pos         = np.zeros(2, dtype=np.float32)
        self._heading     = 0.0
        self._goal        = np.zeros(2, dtype=np.float32)
        self._prev_action = np.zeros(3, dtype=np.float32)
        self._prev_dist   = 0.0
        self._step_count  = 0

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _rescale_action(self, action) -> np.ndarray:
        """Normalised action in [-1, 1] → real (vx, vy, vyaw) in the envelope."""
        a = np.clip(np.asarray(action, dtype=np.float32), -1.0, 1.0)
        return self._v_low + (a + 1.0) * 0.5 * (self._v_high - self._v_low)

    def _observe(self) -> np.ndarray:
        to_goal = self._goal - self._pos
        dist = float(np.linalg.norm(to_goal))
        # Rotate goal vector into the robot's body frame (forward, lateral)
        c, s = math.cos(-self._heading), math.sin(-self._heading)
        fwd = c * to_goal[0] - s * to_goal[1]
        lat = s * to_goal[0] + c * to_goal[1]

        return np.array([
            self._pos[0] / self._x_half,                    # x in [-10,10] → [-1,1]
            self._pos[1] / self._y_half,                    # y in [-6,6]   → [-1,1]
            math.sin(self._heading),
            math.cos(self._heading),
            np.clip(fwd  / self._diag, -1.0, 1.0),
            np.clip(lat  / self._diag, -1.0, 1.0),
            np.clip(dist / self._diag,  0.0, 1.0),
            self._prev_action[0],                           # previous (normalised) action
            self._prev_action[1],
            self._prev_action[2],
        ], dtype=np.float32)

    def _integrate(self, vx: float, vy: float, vyaw: float) -> None:
        """Kinematic biped step: body-frame velocity → world pose.

        ROS2/Webots integration point: replace with
        bridge.publish_cmd_vel(vx, vy, vyaw) then bridge.get_odometry().
        """
        c, s = math.cos(self._heading), math.sin(self._heading)
        self._pos = self._pos + np.array(
            [(vx * c - vy * s) * self.dt, (vx * s + vy * c) * self.dt],
            dtype=np.float32,
        )
        self._heading = (self._heading + vyaw * self.dt + math.pi) % (2 * math.pi) - math.pi

    # ── Gymnasium API ─────────────────────────────────────────────────────────

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self._step_count = 0

        # Randomise start across the full arena so the policy generalises to all
        # (start, goal) combinations — fixes systematic failure on far zones.
        # Falls back to a fixed position when options["start"] is provided.
        if options and options.get("start") is not None:
            start = np.array(options["start"], dtype=np.float32)
            self._pos = np.clip(
                start + self.np_random.uniform(-0.3, 0.3, size=2).astype(np.float32),
                [self._x_min, self._y_min],
                [self._x_max, self._y_max],
            )
        else:
            margin = 0.5  # keep away from outer walls
            self._pos = np.array([
                self.np_random.uniform(self._x_min + margin, self._x_max - margin),
                self.np_random.uniform(self._y_min + margin, self._y_max - margin),
            ], dtype=np.float32)
        self._heading = float(self.np_random.uniform(-math.pi, math.pi))
        self._prev_action[:] = 0.0

        # Goal: a dispatched zone (as the MAS auction would provide) or random
        if options and options.get("goal_zone") in self.zone_pos:
            self._goal = self.zone_pos[options["goal_zone"]].copy()
        else:
            zone = self.zones[self.np_random.integers(len(self.zones))]
            self._goal = self.zone_pos[zone].copy()

        self._prev_dist = float(np.linalg.norm(self._goal - self._pos))
        return self._observe(), {}

    def step(self, action):
        self._step_count += 1
        action = np.clip(np.asarray(action, dtype=np.float32), -1.0, 1.0)
        vx, vy, vyaw = self._rescale_action(action)

        self._integrate(float(vx), float(vy), float(vyaw))

        dist = float(np.linalg.norm(self._goal - self._pos))
        reward  = self.w_progress * (self._prev_dist - dist)    # potential-based progress
        reward -= self.c_step                                    # efficiency cost
        reward -= self.c_smooth * float(np.linalg.norm(action - self._prev_action))

        terminated = False
        out_of_bounds = bool(
            self._pos[0] < self._x_min or self._pos[0] > self._x_max or
            self._pos[1] < self._y_min or self._pos[1] > self._y_max
        )
        if out_of_bounds:
            reward -= self.r_bounds
            self._pos = np.clip(
                self._pos,
                [self._x_min, self._y_min],
                [self._x_max, self._y_max],
            )

        arrived = dist <= self.goal_radius
        if arrived:
            reward += self.r_goal
            terminated = True

        self._prev_dist   = dist
        self._prev_action = action
        truncated = self._step_count >= self._max_steps
        info = {
            "distance":      dist,
            "arrived":       arrived,
            "is_success":    arrived,
            "out_of_bounds": out_of_bounds,
        }
        return self._observe(), reward, terminated, truncated, info

    def render(self):
        if self.render_mode == "human":
            print(
                f"step={self._step_count:4d} "
                f"pos=({self._pos[0]:5.2f},{self._pos[1]:5.2f}) "
                f"hdg={math.degrees(self._heading):6.1f}deg "
                f"dist={self._prev_dist:5.2f}m"
            )

    def close(self):
        # ROS2/Webots integration point: tear down the bridge connection.
        pass
