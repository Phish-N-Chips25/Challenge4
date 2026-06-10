"""
Gymnasium environment wrapper for the Webots office patrol simulation.

This bridges the Webots supervisor API with Stable-Baselines3.
"""

import gymnasium as gym
import numpy as np
from gymnasium import spaces


class OfficePatrolEnv(gym.Env):
    """
    Observation space:
        - robot_room:          int    (which room the robot is in, 0..N-1)
        - motion_alerts:       binary vector (1 = motion detected in room i)
        - camera_detections:   categorical per camera (0=none, 1=known, 2=unknown)
        - time_since_patrol:   float vector (seconds since robot last visited room i)

    Action space:
        - Discrete(N): move toward room i

    Reward:
        - See configs/ppo.yaml for reward structure
    """

    metadata = {"render_modes": ["human"]}

    def __init__(self, config: dict | None = None, render_mode=None):
        super().__init__()
        self.config = config or {}
        self.num_rooms = self.config.get("num_rooms", 5)
        self.render_mode = render_mode

        # ── Spaces ───────────────────────────────────────────────────────
        obs_size = (
            1                    # robot room index (normalized)
            + self.num_rooms     # motion sensor alerts
            + self.num_rooms     # camera detection codes (normalized)
            + self.num_rooms     # time since last patrol (normalized)
        )
        self.observation_space = spaces.Box(
            low=0.0, high=1.0, shape=(obs_size,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(self.num_rooms)

        # ── Internal state ───────────────────────────────────────────────
        self._step_count = 0
        self._max_steps = self.config.get("max_episode_steps", 2000)
        self._webots_supervisor = None  # set during _connect_webots()

    # TODO: implement these methods ──────────────────────────────────────
    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self._step_count = 0
        # TODO: reset Webots simulation, re-randomize intruder spawn
        obs = np.zeros(self.observation_space.shape, dtype=np.float32)
        info = {}
        return obs, info

    def step(self, action):
        self._step_count += 1
        # TODO:
        # 1. Send navigation command to robot in Webots
        # 2. Step the Webots simulation
        # 3. Read sensor values (motion sensors, cameras)
        # 4. Compute reward based on config
        # 5. Check termination conditions
        obs = np.zeros(self.observation_space.shape, dtype=np.float32)
        reward = 0.0
        terminated = False
        truncated = self._step_count >= self._max_steps
        info = {}
        return obs, reward, terminated, truncated, info

    def close(self):
        # TODO: clean up Webots connection
        pass
