"""
Goal-conditioned navigation environment for the patrol robot.

Role in the system
------------------
This env trains the *navigation* layer only — NOT zone selection.

  * Which zone to patrol  → decided by the SIMAGIA multi-agent system
    (Contract Net auction: ZoneCoordinator bids threat level, PatrolAgent
    awards the robot to the highest bidder).  See SIMAGIA/sentinel_mas.
  * How to drive there    → THIS policy.  Given the dispatched target it
    produces body-frame velocity commands (vx, vy, vyaw) that match the
    Booster T1 walking interface (`make_move_request` in unitree-g1-webots).

The trained policy is a drop-in replacement for
`sentinel_mas/agents/patrol.py::NavigationStub.move()` — see
`src/rl/policy_runner.py` for the integration shim.

Coordinate frame
----------------
Training happens in the robot's metric frame (metres, m/s) so the learned
velocities stay inside the real walking envelope.  SIMAGIA's dashboard uses a
0..100 grid; `map_scale` converts between the two (default: 100 grid units =
20 m).  The integration shim handles the conversion at run time.

The env is deliberately Webots-free so PPO can run millions of fast steps.
When the ROS2/Webots bridge is enabled, swap the kinematic `_integrate()`
step for a real `publish_cmd_vel()` + `get_odometry()` round-trip — the
observation/action contract stays identical.
"""

from __future__ import annotations

import math

import gymnasium as gym
import numpy as np
from gymnasium import spaces


# ── Defaults mirroring SIMAGIA (sentinel_mas/config/settings.py) ──────────────
# ZONE_POS / PATROL_BASE_POS are on SIMAGIA's 0..100 grid; they are scaled to
# metres by `map_scale` at reset.  Keep these in sync with settings.py.
DEFAULT_ZONE_POS = {
    "exterior":    (50.0, 13.0),
    "server_room": (22.0, 35.0),
    "lab":         (78.0, 35.0),
    "corridor":    (50.0, 57.0),
    "lobby":       (50.0, 83.0),
}
DEFAULT_BASE_POS = (50.0, 70.0)

# Booster T1 safe velocity envelope, from unitree-g1-webots
# (booster_t1_webots_test/rpc_commands.py::MOVEMENT_COMMANDS).  Asymmetric vx
# (fast forward, slow reverse) is a real property of the biped gait.
DEFAULT_VEL_LIMITS = {
    "vx":   (-0.1, 0.7),    # m/s  forward / reverse
    "vy":   (-0.1, 0.1),    # m/s  lateral strafe
    "vyaw": (-0.2, 0.2),    # rad/s  turn rate
}


class OfficeNavEnv(gym.Env):
    """Point-to-point navigation with a Booster-T1-faithful action space.

    Observation (Box, 10-d, all roughly in [-1, 1]):
        0   x position            (normalised by arena size)
        1   y position            (normalised by arena size)
        2   sin(heading)
        3   cos(heading)
        4   goal error, forward   (body frame, normalised)
        5   goal error, lateral   (body frame, normalised)
        6   distance to goal      (normalised)
        7   previous vx           (normalised by its limit)
        8   previous vy           (normalised by its limit)
        9   previous vyaw         (normalised by its limit)

    Action (Box, 3-d, normalised [-1, 1]): rescaled internally to the robot's
        body-frame velocity envelope (vx, vy, vyaw).  A symmetric, normalised
        action space is what PPO's Gaussian policy expects; `_rescale_action`
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

        # ── Map / geometry ───────────────────────────────────────────────
        self.map_scale = cfg.get("map_scale", 0.2)            # metres per grid unit
        self.arena_m = 100.0 * self.map_scale                 # arena side length (m)
        zone_pos_grid = cfg.get("zone_pos", DEFAULT_ZONE_POS)
        base_grid = cfg.get("base_pos", DEFAULT_BASE_POS)
        self.zones = list(zone_pos_grid.keys())
        self.zone_pos = {z: self._to_m(p) for z, p in zone_pos_grid.items()}
        self.base_pos = self._to_m(base_grid)

        # ── Robot velocity envelope ──────────────────────────────────────
        vl = cfg.get("velocity_limits", DEFAULT_VEL_LIMITS)
        self._v_low = np.array([vl["vx"][0], vl["vy"][0], vl["vyaw"][0]], dtype=np.float32)
        self._v_high = np.array([vl["vx"][1], vl["vy"][1], vl["vyaw"][1]], dtype=np.float32)

        # ── Episode dynamics ─────────────────────────────────────────────
        self.dt = cfg.get("control_dt", 0.1)                  # s per control step (~10 Hz)
        self.goal_radius = cfg.get("goal_radius", 0.5)        # m, "arrived" threshold
        self._max_steps = cfg.get("max_episode_steps", 400)

        # ── Reward weights ───────────────────────────────────────────────
        r = cfg.get("reward", {})
        self.w_progress = r.get("progress", 1.0)
        self.r_goal = r.get("goal_reached", 50.0)
        self.c_step = r.get("step_penalty", 0.01)
        self.c_smooth = r.get("action_smoothness_penalty", 0.02)
        self.r_bounds = r.get("out_of_bounds_penalty", 1.0)

        # ── Spaces ───────────────────────────────────────────────────────
        # Normalised, symmetric action space (PPO best practice); rescaled to
        # the real velocity envelope in `_rescale_action`.
        self.action_space = spaces.Box(
            low=-1.0, high=1.0, shape=(3,), dtype=np.float32
        )
        self.observation_space = spaces.Box(
            low=-1.0, high=1.0, shape=(10,), dtype=np.float32
        )

        # ── Internal state ───────────────────────────────────────────────
        self._pos = np.zeros(2, dtype=np.float32)
        self._heading = 0.0
        self._goal = np.zeros(2, dtype=np.float32)
        self._prev_action = np.zeros(3, dtype=np.float32)
        self._prev_dist = 0.0
        self._step_count = 0

    # ── Helpers ──────────────────────────────────────────────────────────
    def _to_m(self, grid_xy) -> np.ndarray:
        """SIMAGIA 0..100 grid → metric frame."""
        return np.array(grid_xy, dtype=np.float32) * self.map_scale

    def _rescale_action(self, action) -> np.ndarray:
        """Normalised action in [-1, 1] → real (vx, vy, vyaw) in the envelope."""
        a = np.clip(np.asarray(action, dtype=np.float32), -1.0, 1.0)
        return self._v_low + (a + 1.0) * 0.5 * (self._v_high - self._v_low)

    def _observe(self) -> np.ndarray:
        to_goal = self._goal - self._pos
        dist = float(np.linalg.norm(to_goal))
        # Rotate goal vector into the robot's body frame (forward, lateral).
        c, s = math.cos(-self._heading), math.sin(-self._heading)
        fwd = c * to_goal[0] - s * to_goal[1]
        lat = s * to_goal[0] + c * to_goal[1]

        diag = self.arena_m * math.sqrt(2.0)
        obs = np.array([
            2.0 * self._pos[0] / self.arena_m - 1.0,
            2.0 * self._pos[1] / self.arena_m - 1.0,
            math.sin(self._heading),
            math.cos(self._heading),
            np.clip(fwd / self.arena_m, -1.0, 1.0),
            np.clip(lat / self.arena_m, -1.0, 1.0),
            np.clip(dist / diag, 0.0, 1.0),
            self._prev_action[0],          # previous (normalised) action,
            self._prev_action[1],          # already in [-1, 1]
            self._prev_action[2],
        ], dtype=np.float32)
        return obs

    def _integrate(self, vx: float, vy: float, vyaw: float) -> None:
        """Kinematic biped step: body-frame velocity → world pose.

        ROS2/Webots integration point: replace this with
        bridge.publish_cmd_vel(...) followed by reading bridge.get_odometry().
        """
        c, s = math.cos(self._heading), math.sin(self._heading)
        world_dx = (vx * c - vy * s) * self.dt
        world_dy = (vx * s + vy * c) * self.dt
        self._pos = self._pos + np.array([world_dx, world_dy], dtype=np.float32)
        self._heading = (self._heading + vyaw * self.dt + math.pi) % (2 * math.pi) - math.pi

    # ── Gymnasium API ────────────────────────────────────────────────────
    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self._step_count = 0

        # Start at the patrol dock (optionally jittered for robustness).
        start = self.base_pos.copy()
        if options and options.get("start") is not None:
            start = self._to_m(options["start"])
        self._pos = start + self.np_random.uniform(-0.3, 0.3, size=2).astype(np.float32)
        self._heading = float(self.np_random.uniform(-math.pi, math.pi))
        self._prev_action[:] = 0.0

        # Goal: a dispatched zone (as the MAS auction would provide) or random.
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

        # ── Reward ───────────────────────────────────────────────────────
        dist = float(np.linalg.norm(self._goal - self._pos))
        reward = self.w_progress * (self._prev_dist - dist)     # potential-based progress
        reward -= self.c_step                                    # efficiency cost
        reward -= self.c_smooth * float(np.linalg.norm(action - self._prev_action))

        terminated = False
        out_of_bounds = bool(
            np.any(self._pos < 0.0) or np.any(self._pos > self.arena_m)
        )
        if out_of_bounds:
            reward -= self.r_bounds
            self._pos = np.clip(self._pos, 0.0, self.arena_m)

        arrived = dist <= self.goal_radius
        if arrived:
            reward += self.r_goal
            terminated = True

        self._prev_dist = dist
        self._prev_action = action
        truncated = self._step_count >= self._max_steps
        info = {
            "distance": dist,
            "arrived": arrived,
            "is_success": arrived,
            "out_of_bounds": out_of_bounds,
        }
        return self._observe(), reward, terminated, truncated, info

    def render(self):
        if self.render_mode == "human":
            print(
                f"step={self._step_count:4d} "
                f"pos=({self._pos[0]:5.2f},{self._pos[1]:5.2f}) "
                f"hdg={math.degrees(self._heading):6.1f}° "
                f"dist={self._prev_dist:5.2f}m"
            )

    def close(self):
        # ROS2/Webots integration point: tear down the bridge connection.
        pass
