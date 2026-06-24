import math
import unittest

from booster_t1_webots_test.office_lidar_sim import (
    WALL_SEGMENTS,
    points_to_world,
    raycast_point_cloud,
)
from booster_t1_webots_test.patrol_types import Pose2D


class OfficeLidarSimTest(unittest.TestCase):
    def test_raycast_returns_robot_frame_wall_hits(self):
        pose = Pose2D(9.0, 0.0, math.pi)

        points = raycast_point_cloud(pose, fov=math.radians(90), rays=31)

        self.assertGreater(len(points), 0)
        self.assertTrue(all(x >= 0.0 for x, _, _ in points))
        self.assertTrue(any(abs(y) > 0.1 for _, y, _ in points))

    def test_datacenter_door_gap_has_no_wall_segment_across_center(self):
        # The datacenter doorway is centered at x=8, y=1 and must stay open
        # for the Booster's precision door route.
        crossing_segments = [
            segment
            for segment in WALL_SEGMENTS
            if min(segment.x1, segment.x2) <= 8.0 <= max(segment.x1, segment.x2)
            and min(segment.y1, segment.y2) <= 1.0 <= max(segment.y1, segment.y2)
        ]

        self.assertEqual([], crossing_segments)

    def test_points_to_world_uses_pose_yaw(self):
        pose = Pose2D(1.0, 2.0, math.pi / 2.0)

        points = points_to_world(pose, [(1.0, 0.0, 0.4)])

        self.assertAlmostEqual(1.0, points[0][0])
        self.assertAlmostEqual(3.0, points[0][1])
        self.assertEqual(0.4, points[0][2])


if __name__ == "__main__":
    unittest.main()
