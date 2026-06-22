import math
import unittest

from booster_t1_webots_test.booster_lidar_adapter import LidarSensorAdapter
from booster_t1_webots_test.patrol_types import Pose2D


class LidarSensorAdapterTest(unittest.TestCase):
    def test_sanitizes_invalid_points_and_range(self):
        adapter = LidarSensorAdapter(min_range=0.05, max_range=2.0)

        points = adapter.sanitize_points(
            [
                (0.5, 0.0, 0.5),
                (math.nan, 0.0, 0.5),
                (3.0, 0.0, 0.5),
                (0.0, 0.0, 0.5),
            ]
        )

        self.assertEqual([(0.5, 0.0, 0.5)], points)

    def test_transforms_robot_frame_points_to_world(self):
        adapter = LidarSensorAdapter()

        world = adapter.transform_to_world(Pose2D(1.0, 2.0, math.pi / 2), [(1.0, 0.0, 0.5)])

        self.assertAlmostEqual(1.0, world[0][0], places=6)
        self.assertAlmostEqual(3.0, world[0][1], places=6)
        self.assertEqual(0.5, world[0][2])

    def test_marks_sensor_data_stale(self):
        adapter = LidarSensorAdapter(timeout=0.5)
        adapter.mark_update(now=10.0)

        self.assertFalse(adapter.is_stale(now=10.4))
        self.assertTrue(adapter.is_stale(now=10.6))


if __name__ == "__main__":
    unittest.main()
