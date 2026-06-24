"""Pure movement math for the Booster patrol behavior.

Computes heading error, distance to target, and velocity command selection
for closed-loop walking toward waypoints. The defaults are tuned for visible
Webots patrol missions, where the Booster gait needs assertive commands to
make clear progress across the map.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .odometry_helpers import normalize_angle
from .patrol_types import Pose2D

# Faster simulation patrol limits. Keep walk yaw lower than turn-in-place yaw,
# but allow enough correction that the robot does not stall on shallow diagonal
# doorway approaches.
FORWARD_SPEED = 0.75       # m/s
MAX_YAW_RATE = 0.55        # rad/s
MAX_WALK_YAW_RATE = 0.20   # rad/s
MAX_LATERAL_SPEED = 0.45   # m/s
HEADING_TOLERANCE = 1.40   # rad — turn-in-place threshold
DEFAULT_ARRIVE_DISTANCE = 0.35  # m — waypoint arrival threshold


@dataclass(frozen=True)
class MotionDecision:
    """The velocity command the controller wants to send this tick."""
    vx: float
    vy: float
    vyaw: float
    distance: float
    arrived: bool


def command_towards(
    pose: Pose2D,
    target: tuple[float, float],
    arrive_distance: float = DEFAULT_ARRIVE_DISTANCE,
    forward_speed: float = FORWARD_SPEED,
    max_yaw_rate: float = MAX_YAW_RATE,
    heading_tolerance: float = HEADING_TOLERANCE,
    max_walk_yaw_rate: float = MAX_WALK_YAW_RATE,
    max_lateral_speed: float = MAX_LATERAL_SPEED,
) -> MotionDecision:
    """Compute a single-tick velocity command to walk *pose* toward *target*.

    The controller follows a turn-or-walk strategy:
    1. If the heading error exceeds HEADING_TOLERANCE, turn in place.
    2. Once the target is in the front-side walking envelope, use forward and
       lateral velocity with a small yaw correction.
    3. Stop when within *arrive_distance* of the target.
    """
    tx, ty = target
    dx = tx - pose.x
    dy = ty - pose.y
    distance = math.hypot(dx, dy)

    if distance <= arrive_distance:
        return MotionDecision(0.0, 0.0, 0.0, distance, True)

    desired = math.atan2(dy, dx)
    heading_error = normalize_angle(desired - pose.theta)

    if abs(heading_error) > heading_tolerance:
        # Turn in place: clamp yaw rate
        vyaw = max(-max_yaw_rate, min(max_yaw_rate, heading_error))
        return MotionDecision(0.0, 0.0, vyaw, distance, False)

    # Walk in the robot frame. This keeps doorway approaches from stalling when
    # the target is off to the side but still inside the stable walking envelope.
    vx = max(0.0, forward_speed * math.cos(heading_error))
    vy = max(-max_lateral_speed, min(max_lateral_speed, forward_speed * math.sin(heading_error)))
    correction = max(-max_walk_yaw_rate, min(max_walk_yaw_rate, heading_error * 0.3))
    return MotionDecision(vx, vy, correction, distance, False)
