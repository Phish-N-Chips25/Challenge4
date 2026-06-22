"""
2D floor-plan geometry for the navigation graph.

Walls and doors are read directly from a Webots .wbt file via wbt_parser.py
— this is what makes the planner deployable to a different building: point
WBT_PATH at a new world file and the geometry below updates automatically,
no code changes. The fallback constants are the sentinelmas_office.wbt
layout, hand-verified earlier in this project, kept only as a safety net if
the .wbt file isn't reachable (e.g. running tests outside the repo).

Used by path_planner.py to build a navigation graph: walls block
line-of-sight between waypoints, doors are the only gaps connecting rooms.
"""

from __future__ import annotations

import os
import warnings
from pathlib import Path

from wbt_parser import parse_walls_and_doors

Segment = tuple[float, float, float, float]  # (x1, y1, x2, y2)

# Override with an env var to point this whole stack at a different building
# without touching any code: SENTINEL_WBT_PATH=C:\path\to\other_office.wbt
WBT_PATH = Path(os.environ.get(
    "SENTINEL_WBT_PATH",
    Path(__file__).resolve().parent.parent / "world" / "sentinelmas_office.wbt",
))

# ── Fallback geometry — used only if WBT_PATH can't be parsed ──────────────
_FALLBACK_WALLS: list[Segment] = [
    (-10.0, -6.0,  -5.5, -6.0), ( -4.5, -6.0,  10.0, -6.0),
    (-10.0,  6.2,  10.0,  6.2), (-10.0, -6.2, -10.0,  6.2),
    ( 10.0, -6.2,  10.0,  6.2),
    (-10.0, -1.0,  -5.5, -1.0), ( -4.5, -1.0,   4.5, -1.0), (  5.5, -1.0,  10.0, -1.0),
    (-10.0,  1.0,  -8.5,  1.0), ( -7.5,  1.0,  -4.5,  1.0), ( -3.5,  1.0,  -0.5,  1.0),
    (  0.5,  1.0,   3.5,  1.0), (  4.5,  1.0,   7.5,  1.0), (  8.5,  1.0,  10.0,  1.0),
    ( 0.0, -6.0,  0.0, -1.0), (-6.0,  1.0, -6.0,  6.0), (-2.0,  1.0, -2.0,  6.0),
    ( 2.0,  1.0,  2.0,  6.0), ( 6.0,  1.0,  6.0,  6.0),
]
_FALLBACK_DOORS: dict[str, tuple[float, float]] = {
    "door_checkpoint": (-5.0, -1.0), "door_break_room": (5.0, -1.0),
    "door_wr1": (-8.0, 1.0), "door_wr2": (-4.0, 1.0), "door_wr3": (0.0, 1.0),
    "door_wr4": (4.0, 1.0), "door_datacenter": (8.0, 1.0),
}


def _load_geometry() -> tuple[list[Segment], dict[str, tuple[float, float]]]:
    try:
        walls, doors = parse_walls_and_doors(WBT_PATH)
        if not walls:
            raise ValueError("parsed 0 walls — file likely doesn't match expected format")
        return walls, doors
    except Exception as e:
        warnings.warn(
            f"Could not parse wall layout from {WBT_PATH} ({e}). "
            f"Falling back to the hardcoded sentinelmas_office.wbt geometry."
        )
        return _FALLBACK_WALLS, _FALLBACK_DOORS


WALLS, DOORS = _load_geometry()


def _segments_intersect(p1, p2, p3, p4) -> bool:
    """General segment-intersection test (orientation + on-segment checks)."""
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    d1, d2 = cross(p3, p4, p1), cross(p3, p4, p2)
    d3, d4 = cross(p1, p2, p3), cross(p1, p2, p4)

    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and \
       d1 != 0 and d2 != 0 and d3 != 0 and d4 != 0:
        return True

    def on_segment(p, q, r):
        return (min(p[0], r[0]) <= q[0] <= max(p[0], r[0]) and
                min(p[1], r[1]) <= q[1] <= max(p[1], r[1]))

    if d1 == 0 and on_segment(p3, p1, p4): return True
    if d2 == 0 and on_segment(p3, p2, p4): return True
    if d3 == 0 and on_segment(p1, p3, p2): return True
    if d4 == 0 and on_segment(p1, p4, p2): return True
    return False


def _point_to_segment_distance(px, py, x1, y1, x2, y2) -> float:
    dx, dy = x2 - x1, y2 - y1
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length_sq))
    cx, cy = x1 + t * dx, y1 + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def distance_to_nearest_wall(xy: tuple[float, float]) -> float:
    """Shortest distance from a point to any wall segment. Used to check
    the robot's *actual* trajectory (not just planned straight lines) never
    gets dangerously close to a wall — see validate_trajectories.py."""
    x, y = xy
    return min(_point_to_segment_distance(x, y, x1, y1, x2, y2)
               for (x1, y1, x2, y2) in WALLS)


def _segment_to_segment_distance(p1, p2, p3, p4) -> float:
    """Minimum distance between segment p1-p2 and segment p3-p4. Zero if
    they intersect; otherwise the minimum of all four endpoint-to-opposite-
    segment distances (the standard, complete way to compute this — unlike
    an intersection test alone, it also catches a segment that *ends* close
    to the other without ever crossing all the way through it)."""
    if _segments_intersect(p1, p2, p3, p4):
        return 0.0
    return min(
        _point_to_segment_distance(p1[0], p1[1], p3[0], p3[1], p4[0], p4[1]),
        _point_to_segment_distance(p2[0], p2[1], p3[0], p3[1], p4[0], p4[1]),
        _point_to_segment_distance(p3[0], p3[1], p1[0], p1[1], p2[0], p2[1]),
        _point_to_segment_distance(p4[0], p4[1], p1[0], p1[1], p2[0], p2[1]),
    )


def line_of_sight(a: tuple[float, float], b: tuple[float, float],
                   margin: float = 0.05) -> bool:
    """True if the straight segment a-b stays at least `margin` away from
    every wall (zero margin = merely "doesn't cross").

    Earlier version of this function inflated each wall by `margin` and
    tested for intersection — that only catches a candidate segment that
    crosses all the way through the safety buffer. It misses a segment that
    *ends* inside the buffer without crossing out the other side, which is
    exactly what happens when a waypoint is deliberately placed close to a
    doorway. Computing the true segment-to-segment distance handles both
    cases correctly."""
    for (x1, y1, x2, y2) in WALLS:
        if _segment_to_segment_distance(a, b, (x1, y1), (x2, y2)) < margin:
            return False
    return True
