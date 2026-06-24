import tempfile
import unittest
from pathlib import Path

from booster_t1_webots_test.patrol_mission_bridge import (
    append_mission,
    append_status,
    read_new_missions,
    read_new_statuses,
)
from booster_t1_webots_test.patrol_types import Mission


class AppendAndReadMissionTest(unittest.TestCase):
    def test_append_and_read_single_mission(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missions.jsonl"
            append_mission(
                path,
                Mission(
                    kind="investigate",
                    x=8.4,
                    y=2.2,
                    zone="datacenter",
                ),
            )
            missions, offset = read_new_missions(path, 0)
        self.assertEqual(1, len(missions))
        self.assertEqual("investigate", missions[0].kind)
        self.assertEqual(8.4, missions[0].x)
        self.assertEqual(2.2, missions[0].y)
        self.assertEqual("datacenter", missions[0].zone)
        self.assertGreater(offset, 0)

    def test_offset_skips_already_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missions.jsonl"
            append_mission(path, Mission(kind="investigate", x=1.0, y=2.0))
            _, offset1 = read_new_missions(path, 0)
            append_mission(path, Mission(kind="detain", x=3.0, y=4.0, target="Intruder"))
            missions, offset2 = read_new_missions(path, offset1)
        self.assertEqual(1, len(missions))
        self.assertEqual("detain", missions[0].kind)
        self.assertGreater(offset2, offset1)

    def test_read_nonexistent_file_returns_empty(self):
        missions, offset = read_new_missions("/nonexistent/path.jsonl", 0)
        self.assertEqual([], missions)
        self.assertEqual(0, offset)

    def test_multiple_missions_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missions.jsonl"
            append_mission(path, Mission(kind="investigate", x=1.0, y=1.0))
            append_mission(path, Mission(kind="detain", x=2.0, y=2.0, target="X"))
            append_mission(path, Mission(kind="assist", x=3.0, y=3.0))
            missions, _ = read_new_missions(path, 0)
        self.assertEqual(3, len(missions))
        self.assertEqual(["investigate", "detain", "assist"],
                         [m.kind for m in missions])


class AppendAndReadStatusTest(unittest.TestCase):
    def test_append_and_read_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.jsonl"
            append_status(path, "REPORT", zone="datacenter", occupants=[])
            events, offset = read_new_statuses(path, 0)
        self.assertEqual(1, len(events))
        self.assertEqual("REPORT", events[0]["type"])
        self.assertEqual("datacenter", events[0]["zone"])
        self.assertGreater(offset, 0)

    def test_offset_works_for_statuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.jsonl"
            append_status(path, "REPORT", zone="datacenter")
            _, offset1 = read_new_statuses(path, 0)
            append_status(path, "DETAINED", name="Intruder", verified=False)
            events, offset2 = read_new_statuses(path, offset1)
        self.assertEqual(1, len(events))
        self.assertEqual("DETAINED", events[0]["type"])
        self.assertGreater(offset2, offset1)

    def test_read_nonexistent_status_file(self):
        events, offset = read_new_statuses("/nonexistent/status.jsonl", 0)
        self.assertEqual([], events)
        self.assertEqual(0, offset)


if __name__ == "__main__":
    unittest.main()
