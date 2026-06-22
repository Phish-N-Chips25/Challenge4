"""Safe zone definitions and conservative room-to-room route generation.

Mirrored from controllers/common/zones.py with Booster-specific clearance.
The building has a central corridor (y between -1 and 1) that connects all
zones; each zone has a single door waypoint pair (corridor side, room side).
"""
from __future__ import annotations

from .patrol_types import Waypoint

# Booster T1 dock / home position (corridor, near east wall)
DOCK = (9.0, 0.0)

# Zone bounding boxes: name -> (xmin, xmax, ymin, ymax)
ZONES = {
    "lobby": (-10, 0, -6, -1),
    "break_room": (0, 10, -6, -1),
    "corridor": (-10, 10, -1, 1),
    "work_room_1": (-10, -6, 1, 6),
    "work_room_2": (-6, -2, 1, 6),
    "work_room_3": (-2, 2, 1, 6),
    "work_room_4": (2, 6, 1, 6),
    "datacenter": (6, 10, 1, 6),
}

# Each door has two waypoints: (corridor-side clearance, room-side clearance).
# The Booster walks corridor -> corridor_wp -> inside_wp -> target, ensuring
# it passes through the door opening without clipping walls.
DOOR_WAYPOINTS = {
    "lobby": ((-5, -0.35), (-5, -1.7)),
    "break_room": ((5, -0.35), (5, -1.7)),
    "work_room_1": ((-8, 0.35), (-8, 1.7)),
    "work_room_2": ((-4, 0.35), (-4, 1.7)),
    "work_room_3": ((0, 0.35), (0, 1.7)),
    "work_room_4": ((4, 0.35), (4, 1.7)),
    # Keep the datacenter route on the door centerline. The door opening spans
    # x=7.5..8.5; precision arrival prevents diagonal clipping at the frame.
    "datacenter": ((8.0, 0.2), (8.0, 1.35)),
}

DOOR_ARRIVE_DISTANCE = 0.28
DOOR_FORWARD_SPEED = 0.50


def zone_of(x, y):
    """Return the zone name containing point (x, y), or None if outside."""
    for name, (xmin, xmax, ymin, ymax) in ZONES.items():
        if xmin <= x <= xmax and ymin <= y <= ymax:
            return name
    return None


def safe_route(start, target):
    """Build a conservative waypoint list from *start* to *target*.

    Routes always pass through the central corridor and the relevant door
    waypoints. When start and target are in the same zone, we still route
    directly.
    """
    sx, sy = start
    tx, ty = target
    src = zone_of(sx, sy)
    dst = zone_of(tx, ty)

    if src == dst and src is not None:
        return [Waypoint(tx, ty, f"direct to target in {src}")]

    points: list[Waypoint] = []

    # Exit source zone through its door
    if src not in (None, "corridor"):
        corridor_wp, inside_wp = DOOR_WAYPOINTS[src]
        points.extend([
            _door_waypoint(inside_wp, f"exit {src} inside"),
            _door_waypoint(corridor_wp, f"exit {src} corridor"),
        ])

    # Enter destination zone through its door
    if dst not in (None, "corridor"):
        corridor_wp, inside_wp = DOOR_WAYPOINTS[dst]
        points.extend([
            _door_waypoint(corridor_wp, f"enter {dst} corridor"),
            _door_waypoint(inside_wp, f"enter {dst} inside"),
        ])

    # Final target
    points.append(Waypoint(tx, ty, "safe route"))

    return points


def _door_waypoint(point: tuple[float, float], note: str) -> Waypoint:
    return Waypoint(
        point[0],
        point[1],
        note,
        arrive_distance=DOOR_ARRIVE_DISTANCE,
        forward_speed=DOOR_FORWARD_SPEED,
        ignore_route_blocks=True,
    )
