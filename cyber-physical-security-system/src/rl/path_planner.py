"""
Global path planner — occupancy-grid A* over arbitrary 2D wall geometry.

Works for ANY floor plan: rectangular rooms, curved corridors, scattered
obstacles, clutter — anything expressible as a set of wall line segments.
Unlike a hand-built room/door graph, this makes no assumption about the
layout's logical structure — it doesn't need "doors" identified at all; an
opening is simply wherever there's no wall. Re-deploying to a different
building only requires a different WALLS list (see office_map.py /
wbt_parser.py); this module never changes.

Role in the system
-------------------
  SIMAGIA dispatches a zone name
        -> path_planner finds a sequence of waypoints around any obstacles
        -> PPONavigator (already trained, knows nothing about walls)
           drives between consecutive waypoints

Standard two-layer mobile-robotics architecture: a global grid planner plus
a local learned controller — the same split ROS's navigation stack uses
(global_planner + a local trajectory controller).
"""

from __future__ import annotations

import heapq
import math

from env import DEFAULT_ARENA, DEFAULT_ZONE_POS
from office_map import WALLS, _point_to_segment_distance, line_of_sight

GRID_RESOLUTION = 0.1   # metres/cell — fine enough to resolve a ~1m doorway

# Clearance kept from every wall when PLANNING — must cover the robot's
# physical footprint (PATROL_ROBOT boundingObject Cylinder radius = 0.3m in
# sentinelmas_office.wbt), not just floating-point robustness. Without this,
# the shortest path through a doorway hugs the opening's corner exactly,
# which is mathematically wall-free but physically clips the robot's body.
# This is intentionally different from line_of_sight()'s small 0.05m margin
# in office_map.py, which serves a different purpose (rejecting/accepting
# string-pulling shortcuts, not robot clearance).
ROBOT_RADIUS = 0.3
WALL_MARGIN  = ROBOT_RADIUS + 0.05

# Extra slack used ONLY when deciding whether a string-pulling shortcut is
# safe — the PPO controller doesn't track a straight line exactly, it
# drifts, so a shortcut that is mathematically clear at exactly
# robot-radius distance can still be clipped in practice.
TRACKING_MARGIN = WALL_MARGIN + 0.3


class OccupancyGrid:
    """Rasterised obstacle map built from a list of wall segments. Works
    for any layout — only depends on which (x1,y1,x2,y2) segments are
    passed in, never on what they represent (no rooms/doors concept)."""

    def __init__(self, walls=None, arena=None,
                 resolution: float = GRID_RESOLUTION, wall_margin: float = WALL_MARGIN):
        self.walls = walls if walls is not None else WALLS
        arena = arena or DEFAULT_ARENA
        self.x_min, self.x_max = arena["x"]
        self.y_min, self.y_max = arena["y"]
        self.res    = resolution
        self.margin = wall_margin
        self.cols = int((self.x_max - self.x_min) / resolution) + 1
        self.rows = int((self.y_max - self.y_min) / resolution) + 1
        self._blocked = self._rasterise()

    def _rasterise(self) -> list[list[bool]]:
        blocked = [[False] * self.cols for _ in range(self.rows)]
        half_cell = self.res / 2.0
        for row in range(self.rows):
            y = self.y_min + row * self.res
            for col in range(self.cols):
                x = self.x_min + col * self.res
                for (x1, y1, x2, y2) in self.walls:
                    if _point_to_segment_distance(x, y, x1, y1, x2, y2) <= self.margin + half_cell:
                        blocked[row][col] = True
                        break
        return blocked

    def to_cell(self, xy: tuple[float, float]) -> tuple[int, int]:
        x, y = xy
        col = int(round((x - self.x_min) / self.res))
        row = int(round((y - self.y_min) / self.res))
        return max(0, min(self.rows - 1, row)), max(0, min(self.cols - 1, col))

    def to_xy(self, rc: tuple[int, int]) -> tuple[float, float]:
        row, col = rc
        return (self.x_min + col * self.res, self.y_min + row * self.res)

    def is_free(self, rc: tuple[int, int]) -> bool:
        row, col = rc
        if not (0 <= row < self.rows and 0 <= col < self.cols):
            return False
        return not self._blocked[row][col]


# (row delta, col delta, step cost) — 8-connected grid
_NEIGHBOURS_8 = [
    (-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
    (-1, -1, math.sqrt(2)), (-1, 1, math.sqrt(2)),
    ( 1, -1, math.sqrt(2)), ( 1, 1, math.sqrt(2)),
]


def _astar(grid: OccupancyGrid, start_rc, goal_rc) -> list[tuple[int, int]]:
    def h(rc):
        return math.dist(rc, goal_rc)

    open_set: list[tuple[float, float, tuple[int, int]]] = [(h(start_rc), 0.0, start_rc)]
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    g_score = {start_rc: 0.0}
    visited: set[tuple[int, int]] = set()

    while open_set:
        _, g, current = heapq.heappop(open_set)
        if current in visited:
            continue
        visited.add(current)
        if current == goal_rc:
            path = [current]
            while path[-1] in came_from:
                path.append(came_from[path[-1]])
            return list(reversed(path))

        for dr, dc, cost in _NEIGHBOURS_8:
            nb = (current[0] + dr, current[1] + dc)
            if not grid.is_free(nb):
                continue
            # Don't let the path cut through the corner of two blocked
            # orthogonal cells (a diagonal move that would clip a wall edge).
            if dr != 0 and dc != 0:
                if not grid.is_free((current[0] + dr, current[1])) or \
                   not grid.is_free((current[0], current[1] + dc)):
                    continue
            ng = g + cost
            if ng < g_score.get(nb, math.inf):
                g_score[nb] = ng
                came_from[nb] = current
                heapq.heappush(open_set, (ng + h(nb), ng, nb))

    raise RuntimeError("No path found — goal is unreachable on the occupancy grid")


# Built once at import time from whatever office_map.WALLS currently holds.
_GRID = OccupancyGrid()


def plan_path(start_xy: tuple[float, float], goal,
              grid: OccupancyGrid | None = None) -> list[tuple[float, float]]:
    """Return an ordered list of (x, y) waypoints from start_xy to the goal,
    routed around every wall in the occupancy grid.

    goal: a zone name (str) resolved via DEFAULT_ZONE_POS, OR an (x, y)
    coordinate in metres. Accepting raw coordinates lets callers route to
    arbitrary points (e.g. the patrol base) with the SAME wall-avoidance the
    named-zone routes get, instead of a naive straight line.

    Works for any layout expressible as wall segments — no rooms/doors
    structure required. The raw grid path is string-pulled against the
    *continuous* wall geometry (not the discretised grid), so the final
    route is smooth and near-optimal rather than a blocky staircase.
    """
    g = grid or _GRID
    if isinstance(goal, str):
        if goal not in DEFAULT_ZONE_POS:
            raise ValueError(f"Unknown zone '{goal}'. Known: {list(DEFAULT_ZONE_POS)}")
        goal_xy = DEFAULT_ZONE_POS[goal]
    else:
        goal_xy = (float(goal[0]), float(goal[1]))

    start_rc, goal_rc = g.to_cell(start_xy), g.to_cell(goal_xy)
    if not g.is_free(start_rc):
        raise RuntimeError(f"Start position {start_xy} falls inside a wall margin")
    if not g.is_free(goal_rc):
        raise RuntimeError(f"Goal '{goal_zone}' at {goal_xy} falls inside a wall margin")

    cell_path = _astar(g, start_rc, goal_rc)
    raw_waypoints = [start_xy] + [g.to_xy(rc) for rc in cell_path[1:-1]] + [goal_xy]

    # String-pulling: skip ahead to the furthest waypoint still in direct
    # line-of-sight at the same robot-radius-aware margin as the grid
    # search, removing discretisation staircasing and unnecessary hops.
    simplified = [raw_waypoints[0]]
    i = 0
    while i < len(raw_waypoints) - 1:
        j = len(raw_waypoints) - 1
        while j > i + 1 and not line_of_sight(raw_waypoints[i], raw_waypoints[j], margin=TRACKING_MARGIN):
            j -= 1
        simplified.append(raw_waypoints[j])
        i = j
    return [(round(x, 3), round(y, 3)) for x, y in simplified]
