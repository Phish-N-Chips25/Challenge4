"""Booster patrol behavior static acceptance tests.

These tests verify the full patrol wiring without a live Webots simulation.
They check that all required files exist, are correctly connected, and that
the patrol map covers all zones in the building.
"""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
BOOSTER_PKG = (
    ROOT
    / "ros2_ws"
    / "src"
    / "booster_t1_webots_test"
    / "booster_t1_webots_test"
)


class PatrolFilesExistTest(unittest.TestCase):
    """All patrol source and test files must exist."""

    REQUIRED_SOURCES = [
        "patrol_types.py",
        "patrol_map.py",
        "patrol_controller.py",
        "patrol_mission_bridge.py",
        "booster_patrol_node.py",
    ]

    REQUIRED_TESTS = [
        "test_patrol_map.py",
        "test_patrol_controller.py",
        "test_patrol_mission_bridge.py",
        "test_booster_patrol_node.py",
    ]

    def test_all_patrol_source_files_exist(self):
        missing = [
            f for f in self.REQUIRED_SOURCES if not (BOOSTER_PKG / f).is_file()
        ]
        self.assertEqual([], missing, f"Missing patrol source files: {missing}")

    def test_all_patrol_test_files_exist(self):
        test_dir = BOOSTER_PKG.parent / "test"
        missing = [
            f for f in self.REQUIRED_TESTS if not (test_dir / f).is_file()
        ]
        self.assertEqual([], missing, f"Missing patrol test files: {missing}")


class PatrolSetupTest(unittest.TestCase):
    """The patrol node must be registered as a console script."""

    def test_setup_py_has_patrol_node_entry_point(self):
        setup = (BOOSTER_PKG.parent / "setup.py").read_text(encoding="utf-8")
        self.assertIn("booster_patrol_node", setup)
        self.assertIn(
            "booster_t1_webots_test.booster_patrol_node:main", setup
        )


class RunnerStartsPatrolTest(unittest.TestCase):
    """The runner script must start the patrol node."""

    def test_runner_starts_booster_patrol_node(self):
        script = (ROOT / "tools" / "run_sentinelmas_booster.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("booster_patrol_node", script)
        self.assertIn("booster-patrol.log", script)
        self.assertIn("booster-patrol.pid", script)

    def test_runner_starts_pose_file_odometry_publisher(self):
        script = (ROOT / "tools" / "run_sentinelmas_booster.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("pose_file_odometry_publisher", script)

    def test_runner_cleans_up_patrol_node(self):
        script = (ROOT / "tools" / "run_sentinelmas_booster.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("pkill -f booster_patrol_node", script)


class SupervisorMissionBridgeTest(unittest.TestCase):
    """The supervisor must write missions to the JSONL bridge."""

    def test_supervisor_writes_booster_missions(self):
        supervisor = (
            ROOT
            / "controllers"
            / "security_supervisor"
            / "security_supervisor.py"
        ).read_text(encoding="utf-8")
        self.assertIn("booster_missions.jsonl", supervisor)
        self.assertIn("write_booster_mission", supervisor)

    def test_supervisor_polls_booster_status(self):
        supervisor = (
            ROOT
            / "controllers"
            / "security_supervisor"
            / "security_supervisor.py"
        ).read_text(encoding="utf-8")
        self.assertIn("booster_status.jsonl", supervisor)
        self.assertIn("poll_booster_status", supervisor)

    def test_supervisor_writes_target_pos_to_bridge(self):
        supervisor = (
            ROOT
            / "controllers"
            / "security_supervisor"
            / "security_supervisor.py"
        ).read_text(encoding="utf-8")
        self.assertIn("booster_target_pos.jsonl", supervisor)
        self.assertIn("TARGET_POS", supervisor)


class PatrolNodeTargetPosBridgeTest(unittest.TestCase):
    """The patrol node must consume TARGET_POS from the bridge."""

    def test_patrol_node_reads_target_pos_bridge(self):
        patrol_node = (
            BOOSTER_PKG / "booster_patrol_node.py"
        ).read_text(encoding="utf-8")
        self.assertIn("target_pos_path", patrol_node)
        self.assertIn("read_new_target_positions", patrol_node)
        self.assertIn("booster_target_pos.jsonl", patrol_node)

    def test_patrol_node_has_detain_distance(self):
        patrol_node = (
            BOOSTER_PKG / "booster_patrol_node.py"
        ).read_text(encoding="utf-8")
        self.assertIn("DETAIN_DISTANCE", patrol_node)

    def test_target_bridge_test_file_exists(self):
        test_dir = BOOSTER_PKG.parent / "test"
        self.assertTrue(
            (test_dir / "test_patrol_target_bridge.py").is_file(),
            "Missing test_patrol_target_bridge.py",
        )

class SafePathCoverageTest(unittest.TestCase):
    """All building zones must have safe paths from the dock."""

    def test_all_zones_reachable_from_dock(self):
        from booster_t1_webots_test.patrol_map import (
            DOCK,
            ZONES,
            safe_route,
        )

        zone_targets = {
            "lobby": (-5.0, -3.5),
            "break_room": (5.0, -3.5),
            "work_room_1": (-8.0, 3.0),
            "work_room_2": (-4.0, 3.0),
            "work_room_3": (0.0, 3.0),
            "work_room_4": (4.0, 3.0),
            "datacenter": (8.4, 2.2),
        }
        for zone, target in zone_targets.items():
            route = safe_route(DOCK, target)
            self.assertGreater(
                len(route),
                0,
                f"No route from dock to {zone} at {target}",
            )
            self.assertEqual(
                target, route[-1].xy,
                f"Route to {zone} doesn't end at target",
            )

    def test_all_zones_have_return_path_to_dock(self):
        from booster_t1_webots_test.patrol_map import (
            DOCK,
            safe_route,
        )

        zone_starts = [
            (-5.0, -3.5),  # lobby
            (5.0, -3.5),   # break_room
            (-8.0, 3.0),   # work_room_1
            (-4.0, 3.0),   # work_room_2
            (0.0, 3.0),    # work_room_3
            (4.0, 3.0),    # work_room_4
            (8.4, 2.2),    # datacenter
        ]
        for start in zone_starts:
            route = safe_route(start, DOCK)
            self.assertGreater(
                len(route), 0, f"No return route from {start} to dock"
            )
            self.assertEqual(
                DOCK, route[-1].xy,
                f"Return route from {start} doesn't end at dock",
            )


class PatrolControllerSafetyTest(unittest.TestCase):
    """Controller must keep patrol velocities inside the tested sim profile."""

    def test_forward_speed_is_fast_but_bounded(self):
        from booster_t1_webots_test.patrol_controller import FORWARD_SPEED

        self.assertGreaterEqual(
            FORWARD_SPEED, 0.70,
            "Forward speed should be high enough for visible patrol progress",
        )
        self.assertLessEqual(
            FORWARD_SPEED, 0.90,
            "Forward speed must stay inside the tested Webots patrol profile",
        )

    def test_yaw_rate_is_fast_but_bounded(self):
        from booster_t1_webots_test.patrol_controller import MAX_YAW_RATE

        self.assertLessEqual(
            MAX_YAW_RATE, 0.60,
            "Yaw rate must stay inside the tested Webots patrol profile",
        )

    def test_walk_yaw_correction_is_fast_but_bounded(self):
        from booster_t1_webots_test.patrol_controller import MAX_WALK_YAW_RATE

        self.assertLessEqual(
            MAX_WALK_YAW_RATE, 0.20,
            "Walk yaw correction must stay inside the tested Webots patrol profile",
        )


class DocumentationTest(unittest.TestCase):
    """Documentation must describe the full patrol wiring."""

    def test_patrol_doc_describes_booster_patrol_node(self):
        patrol_doc = (ROOT / "docs" / "PATROL_ROBOT.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("booster_patrol_node", patrol_doc)
        self.assertIn("PatrolStateMachine", patrol_doc)
        self.assertIn("safe_route", patrol_doc)

    def test_reference_doc_describes_patrol_topics(self):
        ref_doc = (ROOT / "docs" / "BOOSTER_T1_ROS2_REFERENCE.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("booster_patrol_node", ref_doc)
        self.assertIn("booster_missions.jsonl", ref_doc)
        self.assertIn("booster_status.jsonl", ref_doc)


if __name__ == "__main__":
    unittest.main()
