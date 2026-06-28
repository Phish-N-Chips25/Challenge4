"""Robust heading extraction for the Booster T1 supervisor.

Shared, Webots-free helper (mirrors the pattern of zones.py). The supervisor
turns the robot's yaw into the closed-loop heading the patrol/PPO navigation
drives against (booster_pose.json -> /booster_t1/odom -> pose.theta).

A walking biped pitches and rolls on every gait step, so its Webots
`rotation` axis is almost never the world Z axis. Deriving yaw from the
axis-angle Z component (rz * angle) is only correct while perfectly upright
and degrades — or collapses to 0 once the tilt axis overtakes Z — exactly in
the corridor headings (yaw ~ 0 / +-pi) the robot operates in. That corrupts
the heading feedback and makes the controller weave and drift into walls.

Extracting yaw from the orientation matrix instead is invariant to pitch and
roll: the robot's forward (body +x) axis in world coordinates is column 0 of
the body->world matrix, and the heading of its projection onto the Z-up floor
is atan2(R[3], R[0]).
"""
from __future__ import annotations

import math


def yaw_from_orientation(orientation) -> float:
    """World yaw (rad) from a Webots 3x3 row-major orientation matrix.

    `orientation` is the nine-value, row-major, body->world rotation matrix
    returned by Webots `Node.getOrientation()`. Column 0 = (R[0], R[3], R[6])
    is the robot's forward axis in world coordinates; its floor projection has
    heading atan2(R[3], R[0]). Pitch and roll only tilt that axis out of the
    floor plane, leaving the projected angle equal to the true yaw.
    """
    return math.atan2(orientation[3], orientation[0])
