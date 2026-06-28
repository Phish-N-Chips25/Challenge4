"""Heading extraction for the Booster T1 supervisor.

The supervisor feeds the robot's yaw into the closed-loop patrol/PPO
navigation (booster_pose.json -> /booster_t1/odom -> pose.theta). A walking
biped pitches and rolls every gait step, so the Webots `rotation` axis is
almost never the world Z axis. Deriving yaw from the axis-angle Z component
(rz * angle) is only valid while perfectly upright and collapses under tilt,
which corrupts the heading the controller turns against.

These tests pin the matrix-based extraction (yaw_from_orientation), which is
invariant to pitch and roll, and document the failure mode of the legacy
axis-angle shortcut.
"""
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "unitree-g1-webots" / "controllers" / "common"
sys.path.insert(0, str(COMMON))

from heading import yaw_from_orientation  # noqa: E402


def _rot_z(yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    return [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]


def _rot_y(pitch):
    c, s = math.cos(pitch), math.sin(pitch)
    return [[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]]


def _rot_x(roll):
    c, s = math.cos(roll), math.sin(roll)
    return [[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]]


def _matmul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _flat(m):
    """Row-major 9-vector, matching Webots Node.getOrientation()."""
    return [m[i][j] for i in range(3) for j in range(3)]


def _orientation(yaw, pitch=0.0, roll=0.0):
    # Body tilt applied in the body frame after yaw: R = Rz * Ry * Rx.
    return _flat(_matmul(_matmul(_rot_z(yaw), _rot_y(pitch)), _rot_x(roll)))


class BoosterHeadingTests(unittest.TestCase):
    def test_upright_matches_yaw(self):
        for yaw in (-math.pi + 1e-3, -1.0, 0.0, 1.0, math.pi / 2, math.pi - 1e-3):
            with self.subTest(yaw=yaw):
                got = yaw_from_orientation(_orientation(yaw))
                self.assertAlmostEqual(
                    math.atan2(math.sin(got - yaw), math.cos(got - yaw)), 0.0, places=6
                )

    def test_spawn_pose_is_pi(self):
        # BOOSTER_T1 spawns `rotation 0 0 1 3.14159`.
        self.assertAlmostEqual(abs(yaw_from_orientation(_orientation(math.pi))), math.pi, places=4)

    def test_invariant_to_gait_tilt(self):
        # A leaning biped (up to ~30 deg pitch/roll) must still report true yaw —
        # this is exactly where the legacy rz*angle extraction failed, worst of
        # all near the corridor headings (yaw ~ 0 / +-pi) the robot operates in.
        for yaw in (0.0, math.pi / 2, math.pi - 1e-3, -math.pi / 2, 2.5):
            for pitch in (-0.5, -0.25, 0.25, 0.5):
                for roll in (-0.4, 0.0, 0.4):
                    with self.subTest(yaw=yaw, pitch=pitch, roll=roll):
                        got = yaw_from_orientation(_orientation(yaw, pitch, roll))
                        err = math.atan2(math.sin(got - yaw), math.cos(got - yaw))
                        self.assertLess(abs(err), 1e-6)


if __name__ == "__main__":
    unittest.main()
