import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORLD_FILES = [
    ROOT / "unitree-g1-webots" / "worlds" / "sentinelmas_office.wbt",
    ROOT / "SIMAGIA" / "worlds" / "sentinelmas_office.wbt",
    ROOT / "cyber-physical-security-system" / "src" / "world" / "sentinelmas_office.wbt",
]
PERSON_DEFS = ("PERSON_ALICE", "PERSON_BRUNO", "PERSON_CARLA", "PERSON_INTRUDER")


def robot_block(text, def_name):
    match = re.search(rf"DEF {def_name} Robot \{{", text)
    if not match:
        raise AssertionError(f"missing {def_name}")
    depth = 0
    for index in range(match.start(), len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[match.start() : index + 1]
    raise AssertionError(f"unterminated {def_name}")


class WebotsPersonCollisionTests(unittest.TestCase):
    def test_people_are_visual_only(self):
        for world_file in WORLD_FILES:
            text = world_file.read_text(encoding="utf-8")
            with self.subTest(world=world_file):
                for def_name in PERSON_DEFS:
                    block = robot_block(text, def_name)
                    self.assertIn("boundingObject NULL", block, def_name)
                    self.assertNotIn("Cylinder { height 1.8 radius 0.25 }", block, def_name)


if __name__ == "__main__":
    unittest.main()
