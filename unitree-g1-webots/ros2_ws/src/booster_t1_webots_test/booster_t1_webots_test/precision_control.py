"""Precision shaping layer for the PPO-driven Booster patrol.

The PPO policy proposes a body-frame velocity (vx, vy, vyaw) toward the current
waypoint, but it was trained on an idealised instant-response kinematic model.
On the real (physics) biped that makes it under-turn and arc into doorframes
instead of tracking the planned waypoints, and the faster it walks the larger
the drift.

This layer keeps the PPO policy in the loop but shapes its command into a
deterministic *stop-turn-go* motion that the physics gait can track precisely:

  * if the heading error to the waypoint is large -> turn in place (no forward
    motion) until aligned;
  * once aligned -> walk straight toward the waypoint with NO lateral crabbing
    (sideways steps are imprecise on the biped), keeping the policy's small yaw
    correction (clamped);
  * cap the forward speed and scale it down with heading error and with
    proximity to the waypoint, so approach and turns stay slow and precise.

Pure / Webots-free so it is unit-testable.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .odometry_helpers import normalize_angle
from .patrol_types import Pose2D


@dataclass(frozen=True)
class PrecisionLimits:
    """Tunable envelope for the precision shaper (all SI: m/s, rad, rad/s)."""
    turn_in_place: float = 0.35   # heading error above which we rotate in place
    max_vx: float = 0.45          # forward speed cap (lower than PPO for precision)
    max_vyaw: float = 0.30        # turn-in-place yaw-rate cap
    walk_yaw: float = 0.20        # walk-phase yaw-correction cap
    turn_kp: float = 0.9          # proportional gain for turn-in-place
    slow_radius: float = 1.0      # scale forward down within this distance


@dataclass(frozen=True)
class ShapedVelocity:
    vx: float
    vy: float
    vyaw: float
    turning_in_place: bool


def _clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def shape_velocity(
    pose: Pose2D,
    target: tuple[float, float],
    vx: float,
    vy: float,
    vyaw: float,
    limits: PrecisionLimits | None = None,
) -> ShapedVelocity:
    """Shape a raw policy command into a precise stop-turn-go command.

    *pose* is the robot pose (theta from the corrected odometry), *target* the
    current waypoint, and (vx, vy, vyaw) the PPO policy's proposed body-frame
    velocity. Returns the velocity actually sent to the vendor move RPC.
    """
    lim = limits or PrecisionLimits()
    tx, ty = target
    dx, dy = tx - pose.x, ty - pose.y
    dist = math.hypot(dx, dy)
    heading_error = normalize_angle(math.atan2(dy, dx) - pose.theta)

    # Misaligned -> rotate in place toward the waypoint, no translation. This is
    # what stops the robot arcing into the wall next to the door.
    if abs(heading_error) > lim.turn_in_place:
        turn = _clamp(lim.turn_kp * heading_error, lim.max_vyaw)
        return ShapedVelocity(0.0, 0.0, turn, True)

    # Aligned -> walk straight toward the waypoint. Keep the policy's forward
    # intent but cap it, trim it by how off-axis we still are, and slow down on
    # approach. No lateral crabbing (vy = 0) — the biped tracks a line cleanly
    # only by facing where it walks.
    forward = min(max(0.0, float(vx)), lim.max_vx)
    forward *= math.cos(heading_error)
    if dist < lim.slow_radius:
        forward *= max(dist / lim.slow_radius, 0.0)

    walk_yaw = _clamp(float(vyaw), lim.walk_yaw)
    return ShapedVelocity(forward, 0.0, walk_yaw, False)
