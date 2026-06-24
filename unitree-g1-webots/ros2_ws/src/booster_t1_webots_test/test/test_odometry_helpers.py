import math
import unittest

from booster_t1_webots_test.odometry_helpers import (
    OdometerReading,
    compare_odometry,
    normalize_angle,
    odometer_from_webots_pose,
)


class OdometryHelpersTest(unittest.TestCase):
    def test_normalize_angle_wraps_to_signed_pi_range(self):
        self.assertAlmostEqual(math.pi, normalize_angle(math.pi))
        self.assertAlmostEqual(-math.pi, normalize_angle(-math.pi))
        self.assertAlmostEqual(-math.pi + 0.1, normalize_angle(math.pi + 0.1))
        self.assertAlmostEqual(math.pi - 0.1, normalize_angle(-math.pi - 0.1))

    def test_odometer_from_webots_pose_uses_x_y_and_yaw(self):
        reading = odometer_from_webots_pose((8.75, 0.25, 0.66), (0.0, 0.0, -3.0))

        self.assertEqual(OdometerReading(x=8.75, y=0.25, theta=-3.0), reading)

    def test_compare_odometry_reports_vendor_drift(self):
        corrected = OdometerReading(x=8.8, y=0.1, theta=3.0)
        vendor = OdometerReading(x=0.0, y=0.0, theta=-3.0)

        comparison = compare_odometry(corrected, vendor)

        self.assertGreater(comparison.position_error, 8.0)
        self.assertAlmostEqual(0.28318530717958623, comparison.heading_error)
        self.assertIn("position_error=", comparison.summary)
        self.assertIn("heading_error=", comparison.summary)

    def test_compare_odometry_accepts_missing_vendor_reading(self):
        corrected = OdometerReading(x=8.8, y=0.1, theta=3.0)

        comparison = compare_odometry(corrected, None)

        self.assertIsNone(comparison.position_error)
        self.assertIsNone(comparison.heading_error)
        self.assertIn("vendor=unavailable", comparison.summary)


if __name__ == "__main__":
    unittest.main()
