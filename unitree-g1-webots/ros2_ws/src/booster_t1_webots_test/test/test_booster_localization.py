import unittest

from booster_t1_webots_test.booster_localization_node import BoosterLocalization
from booster_t1_webots_test.patrol_types import Pose2D


class BoosterLocalizationTest(unittest.TestCase):
    def test_odometry_is_primary_pose_source(self):
        localization = BoosterLocalization(lidar_timeout=0.5)

        localization.update_odometry(Pose2D(1.0, 2.0, 0.5), now=10.0)
        localization.update_lidar([(0.4, 0.0, 0.5)], now=10.0)
        status = localization.estimate(now=10.1)

        self.assertTrue(status.confident)
        self.assertEqual(Pose2D(1.0, 2.0, 0.5), status.pose)

    def test_lidar_staleness_reduces_confidence(self):
        localization = BoosterLocalization(lidar_timeout=0.5)

        localization.update_odometry(Pose2D(1.0, 2.0, 0.5), now=10.0)
        localization.update_lidar([(0.4, 0.0, 0.5)], now=10.0)
        status = localization.estimate(now=11.0)

        self.assertFalse(status.confident)
        self.assertEqual("lidar_stale", status.reason)

    def test_odometry_staleness_is_not_confident(self):
        localization = BoosterLocalization(lidar_timeout=0.5, odom_timeout=1.0)

        localization.update_odometry(Pose2D(1.0, 2.0, 0.5), now=10.0)
        localization.update_lidar([(0.4, 0.0, 0.5)], now=10.0)
        status = localization.estimate(now=11.5)

        self.assertFalse(status.confident)
        self.assertEqual("odometry_stale", status.reason)

    def test_missing_odometry_is_not_confident(self):
        localization = BoosterLocalization(lidar_timeout=0.5)
        localization.update_lidar([(0.4, 0.0, 0.5)], now=10.0)

        status = localization.estimate(now=10.1)

        self.assertFalse(status.confident)
        self.assertEqual("odometry_missing", status.reason)


if __name__ == "__main__":
    unittest.main()
