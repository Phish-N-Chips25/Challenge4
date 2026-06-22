"""Route correction around occupied blocks."""
from __future__ import annotations

import math

from .block_map import BlockMap
from .patrol_types import Pose2D


class RouteCorrector:
    def __init__(self, block_map: BlockMap, detour_offset: float = 0.75):
        self.block_map = block_map
        self.detour_offset = detour_offset

    def correct_route(
        self,
        pose: Pose2D,
        route: list[tuple[float, float]],
    ) -> list[tuple[float, float]] | None:
        if len(route) < 2 or self.block_map.route_safe(route):
            return route

        start = (pose.x, pose.y)
        target = route[-1]
        for side in (1.0, -1.0):
            detour = self._side_detour(start, target, side)
            if self.block_map.route_safe(detour):
                return detour
        return self._simple_grid_route(start, target)

    def _side_detour(
        self,
        start: tuple[float, float],
        target: tuple[float, float],
        side: float,
    ) -> list[tuple[float, float]]:
        sx, sy = start
        tx, ty = target
        dx = tx - sx
        dy = ty - sy
        distance = math.hypot(dx, dy)
        if distance == 0.0:
            return [start, target]
        nx = -dy / distance
        ny = dx / distance
        mx = sx + dx * 0.5 + nx * self.detour_offset * side
        my = sy + dy * 0.5 + ny * self.detour_offset * side
        return [start, (mx, my), target]

    def _simple_grid_route(
        self,
        start: tuple[float, float],
        target: tuple[float, float],
    ) -> list[tuple[float, float]] | None:
        offsets = (1.0, -1.0, 1.5, -1.5)
        for offset in offsets:
            route = [(start[0], start[1]), (start[0], start[1] + offset), (target[0], target[1] + offset), target]
            if self.block_map.route_safe(route):
                return route
        return None
