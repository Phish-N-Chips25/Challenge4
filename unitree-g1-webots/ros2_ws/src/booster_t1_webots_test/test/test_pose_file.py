import json
import math
import tempfile
import unittest
from pathlib import Path

from booster_t1_webots_test.pose_file import read_pose_file


class PoseFileTest(unittest.TestCase):
    def test_read_pose_file_returns_odometer_reading(self):
        with tempfile.TemporaryDirectory() as tmp:
            pose_file = Path(tmp) / "booster_pose.json"
            pose_file.write_text(
                json.dumps({
                    "time": 12.5,
                    "x": 8.5,
                    "y": 0.25,
                    "z": 0.66,
                    "theta": math.pi,
                }),
                encoding="utf-8",
            )

            reading = read_pose_file(pose_file)

        self.assertEqual(8.5, reading.x)
        self.assertEqual(0.25, reading.y)
        self.assertEqual(math.pi, reading.theta)
        self.assertEqual(12.5, reading.sim_time)

    def test_read_pose_file_returns_none_for_missing_or_partial_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.json"
            partial = Path(tmp) / "partial.json"
            partial.write_text('{"x": 8.5', encoding="utf-8")

            self.assertIsNone(read_pose_file(missing))
            self.assertIsNone(read_pose_file(partial))


if __name__ == "__main__":
    unittest.main()
