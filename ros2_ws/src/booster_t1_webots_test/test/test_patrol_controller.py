import math
import unittest

from booster_t1_webots_test.patrol_controller import (
    DEFAULT_ARRIVE_DISTANCE,
    FORWARD_SPEED,
    HEADING_TOLERANCE,
    MAX_LATERAL_SPEED,
    MAX_WALK_YAW_RATE,
    command_towards,
)
from booster_t1_webots_test.patrol_types import Pose2D


class CommandTowardsTest(unittest.TestCase):
    """Unit tests for the closed-loop walking controller."""

    def test_turns_before_walking_when_heading_error_is_large(self):
        # Robot at dock facing east (theta=0), target is directly west.
        # Heading error is pi, so robot should turn in place.
        command = command_towards(Pose2D(9.0, 0.0, 0.0), (8.0, 0.0))
        self.assertEqual(0.0, command.vx)
        # Target is at angle pi from east-facing, so heading error is ~pi.
        # normalize_angle(pi - 0) = pi, |pi| > HEADING_TOLERANCE => turn
        # direction depends on sign of normalized angle
        self.assertNotEqual(0.0, command.vyaw)
        self.assertFalse(command.arrived)

    def test_walks_forward_when_aligned(self):
        # Robot facing west (theta=pi), target is directly west.
        command = command_towards(Pose2D(9.0, 0.0, math.pi), (8.0, 0.0))
        self.assertGreater(command.vx, 0.0)
        self.assertAlmostEqual(0.0, command.vyaw, delta=0.08)
        self.assertFalse(command.arrived)

    def test_stops_when_arrived(self):
        # Robot very close to target
        command = command_towards(Pose2D(8.02, 0.02, math.pi), (8.0, 0.0))
        self.assertEqual(0.0, command.vx)
        self.assertEqual(0.0, command.vyaw)
        self.assertTrue(command.arrived)

    def test_walks_north(self):
        # Robot facing north (theta=pi/2), target is directly north.
        command = command_towards(Pose2D(0.0, 0.0, math.pi / 2), (0.0, 5.0))
        self.assertGreater(command.vx, 0.0)
        self.assertFalse(command.arrived)

    def test_turns_to_face_north_from_east(self):
        # Robot facing east (theta=0), target is north.
        command = command_towards(Pose2D(0.0, 0.0, 0.0), (0.0, 5.0))
        self.assertEqual(0.0, command.vx)
        self.assertGreater(command.vyaw, 0.0)  # turn left (positive yaw)
        self.assertFalse(command.arrived)

    def test_at_exact_arrive_distance_is_arrived(self):
        # Distance exactly at threshold
        command = command_towards(
            Pose2D(0.0, 0.0, 0.0), (DEFAULT_ARRIVE_DISTANCE, 0.0)
        )
        self.assertTrue(command.arrived)

    def test_just_outside_arrive_distance_is_not_arrived(self):
        command = command_towards(
            Pose2D(0.0, 0.0, 0.0), (DEFAULT_ARRIVE_DISTANCE + 0.01, 0.0)
        )
        self.assertFalse(command.arrived)

    def test_yaw_correction_is_small_when_aligned(self):
        # Nearly aligned, should get small proportional correction
        command = command_towards(Pose2D(0.0, 0.0, 0.1), (5.0, 0.0))
        self.assertGreater(command.vx, 0.0)
        # Small heading error should produce small correction
        self.assertLessEqual(abs(command.vyaw), MAX_WALK_YAW_RATE)

    def test_uses_lateral_velocity_for_side_doorway_approach(self):
        command = command_towards(
            Pose2D(7.94, -0.01, 2.59),
            (8.0, 1.35),
            arrive_distance=0.16,
            forward_speed=0.50,
        )

        self.assertGreater(command.vx, 0.0)
        self.assertLess(abs(command.vy), MAX_LATERAL_SPEED + 0.001)
        self.assertNotEqual(0.0, command.vy)
        self.assertFalse(command.arrived)

    def test_custom_limits_are_applied(self):
        command = command_towards(
            Pose2D(0.0, 0.0, 0.0),
            (5.0, 0.0),
            forward_speed=0.04,
            max_walk_yaw_rate=0.01,
        )

        self.assertEqual(0.04, command.vx)
        self.assertGreaterEqual(command.vyaw, -0.01)
        self.assertLessEqual(command.vyaw, 0.01)

    def test_custom_turn_rate_is_applied(self):
        command = command_towards(
            Pose2D(0.0, 0.0, 0.0),
            (0.0, 5.0),
            max_yaw_rate=0.05,
        )

        self.assertEqual(0.0, command.vx)
        self.assertAlmostEqual(0.05, command.vyaw)


if __name__ == "__main__":
    unittest.main()
