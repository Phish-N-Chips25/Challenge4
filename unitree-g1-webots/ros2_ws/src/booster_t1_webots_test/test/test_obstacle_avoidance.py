import unittest

from booster_t1_webots_test.block_map import BlockMap
from booster_t1_webots_test.obstacle_avoidance import ObstacleAvoidance
from booster_t1_webots_test.patrol_types import Pose2D


class ObstacleAvoidanceTest(unittest.TestCase):
    def test_obstacle_in_safety_area_is_unsafe(self):
        block_map = BlockMap(block_size=0.25)
        block_map.update_from_points(Pose2D(0.0, 0.0, 0.0), [(0.45, 0.0, 0.5)], now=1.0)
        avoidance = ObstacleAvoidance(block_map)

        decision = avoidance.evaluate(Pose2D(0.0, 0.0, 0.0))

        self.assertFalse(decision.safe)
        self.assertEqual("obstacle_ahead", decision.reason)

    def test_clear_safety_area_is_safe(self):
        block_map = BlockMap(block_size=0.25)
        block_map.update_from_points(Pose2D(0.0, 0.0, 0.0), [(0.45, 1.0, 0.5)], now=1.0)
        avoidance = ObstacleAvoidance(block_map)

        decision = avoidance.evaluate(Pose2D(0.0, 0.0, 0.0))

        self.assertTrue(decision.safe)
        self.assertEqual("clear", decision.reason)

    def test_motion_check_uses_command_direction(self):
        block_map = BlockMap(block_size=0.25)
        block_map.update_from_points(Pose2D(0.0, 0.0, 0.0), [(0.45, 0.0, 0.5)], now=1.0)
        avoidance = ObstacleAvoidance(block_map)

        forward = avoidance.evaluate_motion(Pose2D(0.0, 0.0, 0.0), 0.5, 0.0)
        sidestep = avoidance.evaluate_motion(Pose2D(0.0, 0.0, 0.0), 0.0, 0.5)

        self.assertFalse(forward.safe)
        self.assertEqual("obstacle_in_motion_path", forward.reason)
        self.assertTrue(sidestep.safe)

    def test_motion_check_blocks_lateral_obstacle(self):
        block_map = BlockMap(block_size=0.25)
        block_map.update_from_points(Pose2D(0.0, 0.0, 0.0), [(0.0, 0.45, 0.5)], now=1.0)
        avoidance = ObstacleAvoidance(block_map)

        decision = avoidance.evaluate_motion(Pose2D(0.0, 0.0, 0.0), 0.0, 0.5)

        self.assertFalse(decision.safe)
        self.assertEqual("obstacle_in_motion_path", decision.reason)


if __name__ == "__main__":
    unittest.main()
