"""Tests for TARGET_POS JSONL bridge functions."""
import tempfile
import unittest
from pathlib import Path

from booster_t1_webots_test.patrol_mission_bridge import (
    append_target_pos,
    read_new_target_positions,
)


class AppendAndReadTargetPosTest(unittest.TestCase):
    def test_read_nonexistent_file_returns_empty(self):
        events, offset = read_new_target_positions("/no/such/file.jsonl", 0)
        self.assertEqual([], events)
        self.assertEqual(0, offset)

    def test_append_and_read_single_target_pos(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "target_pos.jsonl"
            append_target_pos(path, "Intruder", -3.2, -1.5)
            events, offset = read_new_target_positions(path, 0)
            self.assertEqual(1, len(events))
            self.assertEqual("Intruder", events[0]["target"])
            self.assertAlmostEqual(-3.2, events[0]["x"])
            self.assertAlmostEqual(-1.5, events[0]["y"])
            self.assertGreater(offset, 0)

    def test_multiple_target_positions_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "target_pos.jsonl"
            append_target_pos(path, "Intruder", 1.0, 2.0)
            append_target_pos(path, "Intruder", 3.0, 4.0)
            append_target_pos(path, "Intruder", 5.0, 6.0)
            events, _ = read_new_target_positions(path, 0)
            self.assertEqual(3, len(events))
            self.assertAlmostEqual(1.0, events[0]["x"])
            self.assertAlmostEqual(5.0, events[2]["x"])

    def test_offset_skips_already_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "target_pos.jsonl"
            append_target_pos(path, "Intruder", 1.0, 2.0)
            _, offset = read_new_target_positions(path, 0)
            append_target_pos(path, "Intruder", 3.0, 4.0)
            events, new_offset = read_new_target_positions(path, offset)
            self.assertEqual(1, len(events))
            self.assertAlmostEqual(3.0, events[0]["x"])
            self.assertGreater(new_offset, offset)

    def test_ignores_non_target_pos_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "target_pos.jsonl"
            # Write a non-TARGET_POS line
            import json
            with path.open("a") as fh:
                fh.write(json.dumps({"type": "OTHER", "x": 1.0, "y": 2.0}) + "\n")
            append_target_pos(path, "Intruder", 5.0, 6.0)
            events, _ = read_new_target_positions(path, 0)
            self.assertEqual(1, len(events))
            self.assertEqual("Intruder", events[0]["target"])


if __name__ == "__main__":
    unittest.main()
