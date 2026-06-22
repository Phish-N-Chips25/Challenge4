import unittest

from booster_t1_webots_test.block_map import BlockMap
from booster_t1_webots_test.patrol_types import Pose2D


class BlockMapTest(unittest.TestCase):
    def test_lidar_points_mark_occupied_blocks(self):
        block_map = BlockMap(block_size=0.25)

        block_map.update_from_points(Pose2D(1.0, 2.0, 0.0), [(0.6, 0.1, 0.5)], now=10.0)

        self.assertTrue(block_map.is_occupied(1.6, 2.1))
        self.assertFalse(block_map.is_occupied(1.0, 2.0))

    def test_front_area_reports_obstacle_in_robot_frame(self):
        block_map = BlockMap(block_size=0.25)
        block_map.update_from_points(Pose2D(0.0, 0.0, 0.0), [(0.5, 0.0, 0.5)], now=10.0)

        self.assertTrue(
            block_map.has_obstacle_in_front(
                Pose2D(0.0, 0.0, 0.0),
                forward_distance=0.8,
                half_width=0.35,
                min_height=0.1,
                max_height=1.8,
            )
        )

    def test_route_segment_is_blocked_by_occupied_block(self):
        block_map = BlockMap(block_size=0.25)
        block_map.update_from_points(Pose2D(0.0, 0.0, 0.0), [(0.5, 0.0, 0.5)], now=10.0)

        self.assertFalse(block_map.route_segment_safe((0.0, 0.0), (1.0, 0.0)))
        self.assertTrue(block_map.route_segment_safe((0.0, 0.5), (1.0, 0.5)))


if __name__ == "__main__":
    unittest.main()
