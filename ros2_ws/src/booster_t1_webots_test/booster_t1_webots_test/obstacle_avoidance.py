"""Obstacle safety checks for Booster patrol movement."""
from __future__ import annotations

from dataclasses import dataclass

from .block_map import BlockMap
from .patrol_types import Pose2D


@dataclass(frozen=True)
class ObstacleAvoidanceConfig:
    forward_distance: float = 0.8
    half_width: float = 0.35
    min_height: float = 0.1
    max_height: float = 1.8


@dataclass(frozen=True)
class SafetyDecision:
    safe: bool
    reason: str


class ObstacleAvoidance:
    def __init__(
        self,
        block_map: BlockMap,
        config: ObstacleAvoidanceConfig | None = None,
    ):
        self.block_map = block_map
        self.config = config or ObstacleAvoidanceConfig()

    def evaluate(self, pose: Pose2D) -> SafetyDecision:
        cfg = self.config
        blocked = self.block_map.has_obstacle_in_front(
            pose,
            forward_distance=cfg.forward_distance,
            half_width=cfg.half_width,
            min_height=cfg.min_height,
            max_height=cfg.max_height,
        )
        if blocked:
            return SafetyDecision(False, "obstacle_ahead")
        return SafetyDecision(True, "clear")

    def evaluate_motion(self, pose: Pose2D, vx: float, vy: float) -> SafetyDecision:
        cfg = self.config
        blocked = self.block_map.has_obstacle_along_body_motion(
            pose,
            vx,
            vy,
            forward_distance=cfg.forward_distance,
            half_width=cfg.half_width,
            min_height=cfg.min_height,
            max_height=cfg.max_height,
        )
        if blocked:
            return SafetyDecision(False, "obstacle_in_motion_path")
        return SafetyDecision(True, "clear")
