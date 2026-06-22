"""Helpers for adapting simulated LiDAR-like points into patrol obstacle data."""
from __future__ import annotations

import math

from .patrol_types import Pose2D


class LidarSensorAdapter:
    """Sanitize and transform simulated obstacle points."""

    def __init__(
        self,
        min_range: float = 0.05,
        max_range: float = 10.0,
        timeout: float = 0.5,
    ):
        self.min_range = min_range
        self.max_range = max_range
        self.timeout = timeout
        self.last_update_time: float | None = None

    def sanitize_points(
        self,
        points: list[tuple[float, float, float]],
    ) -> list[tuple[float, float, float]]:
        clean = []
        for x, y, z in points:
            if not all(math.isfinite(v) for v in (x, y, z)):
                continue
            distance = math.hypot(x, y)
            if self.min_range <= distance <= self.max_range:
                clean.append((x, y, z))
        return clean

    def transform_to_world(
        self,
        pose: Pose2D,
        points: list[tuple[float, float, float]],
    ) -> list[tuple[float, float, float]]:
        cos_yaw = math.cos(pose.theta)
        sin_yaw = math.sin(pose.theta)
        transformed = []
        for x, y, z in points:
            transformed.append((
                pose.x + x * cos_yaw - y * sin_yaw,
                pose.y + x * sin_yaw + y * cos_yaw,
                z,
            ))
        return transformed

    def mark_update(self, now: float) -> None:
        self.last_update_time = now

    def is_stale(self, now: float) -> bool:
        return self.last_update_time is None or now - self.last_update_time > self.timeout


def main(argv=None):
    raise SystemExit(
        "booster_lidar_adapter provides pure adapter helpers; configure a Webots "
        "sensor bridge to publish sanitized points on /booster_t1/points."
    )
