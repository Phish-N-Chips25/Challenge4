"""Small occupancy block map built from robot-frame obstacle points."""
from __future__ import annotations

import math
from dataclasses import dataclass

from .odometry_helpers import normalize_angle
from .patrol_types import Pose2D


@dataclass
class BlockCell:
    state: str
    last_seen_time: float
    confidence: float
    min_height: float
    max_height: float


class BlockMap:
    """Grid occupancy map with conservative block-sized cells."""

    def __init__(self, block_size: float = 0.25):
        if block_size <= 0.0:
            raise ValueError("block_size must be positive")
        self.block_size = block_size
        self._cells: dict[tuple[int, int], BlockCell] = {}

    def update_from_points(
        self,
        pose: Pose2D,
        points: list[tuple[float, float, float]],
        now: float,
    ) -> None:
        """Mark sanitized robot-frame LiDAR points as occupied world blocks."""
        cos_yaw = math.cos(pose.theta)
        sin_yaw = math.sin(pose.theta)
        for x, y, z in points:
            if not all(math.isfinite(v) for v in (x, y, z)):
                continue
            wx = pose.x + x * cos_yaw - y * sin_yaw
            wy = pose.y + x * sin_yaw + y * cos_yaw
            key = self._key(wx, wy)
            existing = self._cells.get(key)
            if existing is None:
                self._cells[key] = BlockCell("occupied", now, 1.0, z, z)
            else:
                existing.state = "occupied"
                existing.last_seen_time = now
                existing.confidence = min(1.0, existing.confidence + 0.2)
                existing.min_height = min(existing.min_height, z)
                existing.max_height = max(existing.max_height, z)

    def is_occupied(self, x: float, y: float) -> bool:
        cell = self._cells.get(self._key(x, y))
        return cell is not None and cell.state == "occupied"

    def has_obstacle_in_front(
        self,
        pose: Pose2D,
        forward_distance: float,
        half_width: float,
        min_height: float,
        max_height: float,
    ) -> bool:
        """Return true when an occupied block intersects the forward safety box."""
        for (ix, iy), cell in self._cells.items():
            if cell.state != "occupied":
                continue
            if cell.max_height < min_height or cell.min_height > max_height:
                continue
            wx, wy = self._center(ix, iy)
            dx = wx - pose.x
            dy = wy - pose.y
            distance = math.hypot(dx, dy)
            bearing = normalize_angle(math.atan2(dy, dx) - pose.theta)
            rx = distance * math.cos(bearing)
            ry = distance * math.sin(bearing)
            if 0.0 <= rx <= forward_distance and abs(ry) <= half_width:
                return True
        return False

    def has_obstacle_along_body_motion(
        self,
        pose: Pose2D,
        vx: float,
        vy: float,
        forward_distance: float,
        half_width: float,
        min_height: float,
        max_height: float,
    ) -> bool:
        """Return true when an occupied block intersects the commanded motion box."""
        speed = math.hypot(vx, vy)
        if speed <= 1e-6:
            return False

        ux = vx / speed
        uy = vy / speed
        cos_yaw = math.cos(pose.theta)
        sin_yaw = math.sin(pose.theta)
        for (ix, iy), cell in self._cells.items():
            if cell.state != "occupied":
                continue
            if cell.max_height < min_height or cell.min_height > max_height:
                continue
            wx, wy = self._center(ix, iy)
            dx = wx - pose.x
            dy = wy - pose.y
            # World -> robot body frame.
            rx = dx * cos_yaw + dy * sin_yaw
            ry = -dx * sin_yaw + dy * cos_yaw
            along = rx * ux + ry * uy
            side = -rx * uy + ry * ux
            if 0.0 <= along <= forward_distance and abs(side) <= half_width:
                return True
        return False

    def route_segment_safe(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        inflation_radius: float = 0.25,
    ) -> bool:
        """Sample a line segment and reject it near occupied cells."""
        sx, sy = start
        ex, ey = end
        distance = math.hypot(ex - sx, ey - sy)
        steps = max(1, int(math.ceil(distance / (self.block_size * 0.5))))
        for step in range(steps + 1):
            t = step / steps
            x = sx + (ex - sx) * t
            y = sy + (ey - sy) * t
            if self._occupied_near(x, y, inflation_radius):
                return False
        return True

    def route_safe(
        self,
        route: list[tuple[float, float]],
        inflation_radius: float = 0.25,
    ) -> bool:
        return all(
            self.route_segment_safe(a, b, inflation_radius=inflation_radius)
            for a, b in zip(route, route[1:])
        )

    def occupied_centers(self) -> list[tuple[float, float]]:
        return [self._center(ix, iy) for ix, iy in self._cells]

    def _occupied_near(self, x: float, y: float, radius: float) -> bool:
        radius_blocks = max(0, int(math.ceil(radius / self.block_size)))
        ix, iy = self._key(x, y)
        for nx in range(ix - radius_blocks, ix + radius_blocks + 1):
            for ny in range(iy - radius_blocks, iy + radius_blocks + 1):
                cell = self._cells.get((nx, ny))
                if cell is None or cell.state != "occupied":
                    continue
                cx, cy = self._center(nx, ny)
                if math.hypot(cx - x, cy - y) <= radius + self.block_size * 0.5:
                    return True
        return False

    def _key(self, x: float, y: float) -> tuple[int, int]:
        return (math.floor(x / self.block_size), math.floor(y / self.block_size))

    def _center(self, ix: int, iy: int) -> tuple[float, float]:
        return ((ix + 0.5) * self.block_size, (iy + 0.5) * self.block_size)
