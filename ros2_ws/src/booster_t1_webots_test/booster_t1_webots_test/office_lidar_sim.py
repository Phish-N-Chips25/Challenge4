"""Static office raycast model for simulated Booster point clouds."""
from __future__ import annotations

import math
from dataclasses import dataclass

from .patrol_types import Pose2D


@dataclass(frozen=True)
class Segment:
    """A 2-D occupied wall segment in world coordinates."""
    x1: float
    y1: float
    x2: float
    y2: float
    name: str = ""


WALL_SEGMENTS: tuple[Segment, ...] = (
    Segment(-10.0, -6.0, -5.5, -6.0, "wall south west"),
    Segment(-4.5, -6.0, 10.0, -6.0, "wall south east"),
    Segment(-10.0, 6.0, 10.0, 6.0, "wall north"),
    Segment(-10.0, -6.0, -10.0, 6.0, "wall west"),
    Segment(10.0, -6.0, 10.0, 6.0, "wall east"),
    Segment(-10.0, -1.0, -5.5, -1.0, "wall corridor south 1"),
    Segment(-4.5, -1.0, 4.5, -1.0, "wall corridor south 2"),
    Segment(5.5, -1.0, 10.0, -1.0, "wall corridor south 3"),
    Segment(-10.0, 1.0, -8.5, 1.0, "wall corridor north 1"),
    Segment(-7.5, 1.0, -4.5, 1.0, "wall corridor north 2"),
    Segment(-3.5, 1.0, -0.5, 1.0, "wall corridor north 3"),
    Segment(0.5, 1.0, 3.5, 1.0, "wall corridor north 4"),
    Segment(4.5, 1.0, 7.5, 1.0, "wall corridor north 5"),
    Segment(8.5, 1.0, 10.0, 1.0, "wall corridor north 6"),
    Segment(0.0, -6.0, 0.0, -1.0, "wall lobby break divider"),
    Segment(-6.0, 1.0, -6.0, 6.0, "wall divider wr1 wr2"),
    Segment(-2.0, 1.0, -2.0, 6.0, "wall divider wr2 wr3"),
    Segment(2.0, 1.0, 2.0, 6.0, "wall divider wr3 wr4"),
    Segment(6.0, 1.0, 6.0, 6.0, "wall divider wr4 datacenter"),
)


def raycast_point_cloud(
    pose: Pose2D,
    fov: float = math.radians(270.0),
    rays: int = 181,
    max_range: float = 8.0,
    hit_height: float = 0.45,
    segments: tuple[Segment, ...] = WALL_SEGMENTS,
) -> list[tuple[float, float, float]]:
    """Return robot-frame hit points for a planar simulated LiDAR scan."""
    if rays <= 1:
        raise ValueError("rays must be greater than 1")
    if max_range <= 0.0:
        raise ValueError("max_range must be positive")

    points: list[tuple[float, float, float]] = []
    start_angle = -0.5 * fov
    step = fov / (rays - 1)
    for index in range(rays):
        local_angle = start_angle + step * index
        world_angle = pose.theta + local_angle
        distance = _nearest_intersection_distance(
            pose.x,
            pose.y,
            math.cos(world_angle),
            math.sin(world_angle),
            max_range,
            segments,
        )
        if distance is None:
            continue
        points.append(
            (
                distance * math.cos(local_angle),
                distance * math.sin(local_angle),
                hit_height,
            )
        )
    return points


def points_to_world(
    pose: Pose2D,
    points: list[tuple[float, float, float]],
) -> list[tuple[float, float, float]]:
    """Transform robot-frame points into world coordinates for diagnostics."""
    cos_yaw = math.cos(pose.theta)
    sin_yaw = math.sin(pose.theta)
    return [
        (
            pose.x + x * cos_yaw - y * sin_yaw,
            pose.y + x * sin_yaw + y * cos_yaw,
            z,
        )
        for x, y, z in points
    ]


def _nearest_intersection_distance(
    ox: float,
    oy: float,
    dx: float,
    dy: float,
    max_range: float,
    segments: tuple[Segment, ...],
) -> float | None:
    nearest: float | None = None
    for segment in segments:
        distance = _ray_segment_intersection(ox, oy, dx, dy, segment)
        if distance is None or distance > max_range:
            continue
        if nearest is None or distance < nearest:
            nearest = distance
    return nearest


def _ray_segment_intersection(
    ox: float,
    oy: float,
    dx: float,
    dy: float,
    segment: Segment,
) -> float | None:
    sx = segment.x2 - segment.x1
    sy = segment.y2 - segment.y1
    denominator = _cross(dx, dy, sx, sy)
    if abs(denominator) < 1e-9:
        return None

    qpx = segment.x1 - ox
    qpy = segment.y1 - oy
    t = _cross(qpx, qpy, sx, sy) / denominator
    u = _cross(qpx, qpy, dx, dy) / denominator
    if t >= 0.0 and 0.0 <= u <= 1.0:
        return t
    return None


def _cross(ax: float, ay: float, bx: float, by: float) -> float:
    return ax * by - ay * bx
