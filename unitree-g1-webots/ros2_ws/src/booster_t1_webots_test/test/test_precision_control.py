import math
import unittest

from booster_t1_webots_test.patrol_types import Pose2D
from booster_t1_webots_test.precision_control import (
    PrecisionLimits,
    shape_velocity,
)


LIM = PrecisionLimits()


class PrecisionControlTest(unittest.TestCase):
    def test_large_heading_error_turns_in_place(self):
        # Facing +x, target straight behind/left -> must rotate in place, no walk.
        pose = Pose2D(0.0, 0.0, 0.0)
        out = shape_velocity(pose, (-1.0, 0.5), 0.7, 0.0, 0.0, LIM)
        self.assertTrue(out.turning_in_place)
        self.assertEqual(0.0, out.vx)
        self.assertEqual(0.0, out.vy)
        self.assertGreater(abs(out.vyaw), 0.0)
        self.assertLessEqual(abs(out.vyaw), LIM.max_vyaw)

    def test_turn_direction_matches_error_sign(self):
        pose = Pose2D(0.0, 0.0, 0.0)
        left = shape_velocity(pose, (0.0, 1.0), 0.5, 0.0, 0.0, LIM)   # target to the left
        right = shape_velocity(pose, (0.0, -1.0), 0.5, 0.0, 0.0, LIM)  # target to the right
        self.assertGreater(left.vyaw, 0.0)   # CCW toward +y
        self.assertLess(right.vyaw, 0.0)     # CW toward -y

    def test_aligned_walks_forward_without_crabbing(self):
        pose = Pose2D(0.0, 0.0, 0.0)
        out = shape_velocity(pose, (5.0, 0.0), 0.7, 0.3, 0.0, LIM)  # dead ahead
        self.assertFalse(out.turning_in_place)
        self.assertEqual(0.0, out.vy)            # never crabs
        self.assertGreater(out.vx, 0.0)

    def test_forward_speed_is_capped(self):
        pose = Pose2D(0.0, 0.0, 0.0)
        out = shape_velocity(pose, (5.0, 0.0), 0.7, 0.0, 0.0, LIM)  # PPO asks 0.7
        self.assertLessEqual(out.vx, LIM.max_vx + 1e-9)

    def test_reverse_command_is_not_allowed(self):
        pose = Pose2D(0.0, 0.0, 0.0)
        out = shape_velocity(pose, (5.0, 0.0), -0.3, 0.0, 0.0, LIM)
        self.assertGreaterEqual(out.vx, 0.0)

    def test_slows_down_near_target(self):
        pose = Pose2D(0.0, 0.0, 0.0)
        far = shape_velocity(pose, (5.0, 0.0), 0.45, 0.0, 0.0, LIM)
        near = shape_velocity(pose, (0.3, 0.0), 0.45, 0.0, 0.0, LIM)  # within slow_radius
        self.assertLess(near.vx, far.vx)

    def test_walk_yaw_correction_is_clamped(self):
        pose = Pose2D(0.0, 0.0, 0.05)  # tiny error -> walk phase
        out = shape_velocity(pose, (5.0, 0.0), 0.4, 0.0, 5.0, LIM)  # PPO yaw huge
        self.assertLessEqual(abs(out.vyaw), LIM.walk_yaw + 1e-9)

    def test_threshold_boundary_is_walk(self):
        # Just inside the turn-in-place threshold -> walk, not rotate.
        err = LIM.turn_in_place - 0.01
        pose = Pose2D(0.0, 0.0, 0.0)
        out = shape_velocity(pose, (math.cos(err), math.sin(err)), 0.4, 0.0, 0.0, LIM)
        self.assertFalse(out.turning_in_place)


if __name__ == "__main__":
    unittest.main()
