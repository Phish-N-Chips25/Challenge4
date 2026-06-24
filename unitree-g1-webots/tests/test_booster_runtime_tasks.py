"""Test that Booster robot follows the paths for the PATROL_ROBOT.md runtime tasks."""

import tempfile
import time
import unittest
from pathlib import Path

from booster_t1_webots_test.booster_patrol_node import (
    ASSIST_TIME,
    GUARD_TIME,
    INVESTIGATE_TIME,
    PatrolStateMachine,
)
from booster_t1_webots_test.patrol_map import DOCK
from booster_t1_webots_test.patrol_mission_bridge import read_new_statuses
from booster_t1_webots_test.patrol_types import Mission, Pose2D


class FakeRpc:
    """Fake RPC client that records all movement commands."""
    def __init__(self):
        self.moves = []
        self.stops = 0

    def move(self, vx, vy, vyaw):
        self.moves.append((vx, vy, vyaw))
        return True

    def stop(self):
        self.stops += 1
        return True


class RuntimeTasksCoverageTest(unittest.TestCase):
    """
    Checks if the booster robot goes all to the paths it should go described on
    the docs/PATROL_ROBOT.md runtime tasks.
    
    Tasks:
    1. detain (pursue target)
    2. investigate (move to datacenter, report, return)
    3. assist (move to staff request coords, wait, return)
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.status_path = Path(self.tmpdir.name) / "status.jsonl"
        self.rpc = FakeRpc()
        self.machine = PatrolStateMachine(rpc=self.rpc, status_path=self.status_path)
        # Start at dock
        self.machine.update_pose(Pose2D(DOCK[0], DOCK[1], 0.0))

    def tearDown(self):
        self.tmpdir.cleanup()

    def simulate_navigation(self, now):
        # Helper to fast-forward through all waypoints
        while self.machine.state == "navigate" and self.machine.waypoint_index < len(self.machine.waypoints):
            wp = self.machine.waypoints[self.machine.waypoint_index]
            self.machine.update_pose(Pose2D(wp.xy[0], wp.xy[1], 0.0))
            self.machine.tick(now)
            now += 0.1
        return now

    def test_investigate_runtime_task(self):
        # Move from the dock to the datacenter target (8.4, 2.2), report occupants, return to dock.
        datacenter_target = (8.4, 2.2)
        mission = Mission(kind="investigate", x=datacenter_target[0], y=datacenter_target[1], zone="datacenter", reason="Cyber alert")
        self.machine.enqueue(mission)
        
        now = time.time()
        self.machine.tick(now)
        self.assertEqual("navigate", self.machine.state)
        self.assertEqual(datacenter_target, self.machine.waypoints[-1].xy)
        
        # Walk through waypoints to datacenter
        now = self.simulate_navigation(now)
        
        # Wait investigate time
        self.assertEqual("onsite", self.machine.state)
        self.machine.tick(now + INVESTIGATE_TIME + 0.1)
        
        # Check report
        events, _ = read_new_statuses(self.status_path, 0)
        reports = [e for e in events if e["type"] == "REPORT"]
        self.assertEqual(1, len(reports))
        self.assertEqual("datacenter", reports[0]["zone"])
        
        # Should now be returning to dock
        self.assertEqual("return", self.machine.state)
        self.assertEqual(DOCK, self.machine.waypoints[-1].xy)
        
        # Walk through waypoints back to dock
        # `return` state logic uses the same waypoint logic
        while self.machine.state == "return" and self.machine.waypoint_index < len(self.machine.waypoints):
            wp = self.machine.waypoints[self.machine.waypoint_index]
            self.machine.update_pose(Pose2D(wp.xy[0], wp.xy[1], 0.0))
            self.machine.tick(now)
            now += 0.1
            
        self.assertEqual("idle", self.machine.state)

    def test_assist_runtime_task(self):
        # Move to the staff request coordinates, wait briefly, then return to dock.
        staff_coords = (-5.0, -3.5) # lobby
        mission = Mission(kind="assist", x=staff_coords[0], y=staff_coords[1], target="Staff123")
        self.machine.enqueue(mission)
        
        now = time.time()
        self.machine.tick(now)
        self.assertEqual("navigate", self.machine.state)
        self.assertEqual(staff_coords, self.machine.waypoints[-1].xy)
        
        now = self.simulate_navigation(now)
        
        self.assertEqual("onsite", self.machine.state)
        self.machine.tick(now + ASSIST_TIME + 0.1)
        
        events, _ = read_new_statuses(self.status_path, 0)
        assists = [e for e in events if e["type"] == "ASSIST_DONE"]
        self.assertEqual(1, len(assists))
        self.assertEqual("Staff123", assists[0]["name"])
        
        self.assertEqual("return", self.machine.state)
        self.assertEqual(DOCK, self.machine.waypoints[-1].xy)
        
        while self.machine.state == "return" and self.machine.waypoint_index < len(self.machine.waypoints):
            wp = self.machine.waypoints[self.machine.waypoint_index]
            self.machine.update_pose(Pose2D(wp.xy[0], wp.xy[1], 0.0))
            self.machine.tick(now)
            now += 0.1
            
        self.assertEqual("idle", self.machine.state)

    def test_detain_runtime_task(self):
        # Replan toward the intruder every second, using TARGET_POS updates.
        intruder_start = (-4.0, 3.0) # work_room_2
        mission = Mission(kind="detain", x=intruder_start[0], y=intruder_start[1], target="Intruder")
        self.machine.enqueue(mission)
        
        now = time.time()
        self.machine.tick(now)
        self.assertEqual("pursue", self.machine.state)
        self.assertEqual(intruder_start, self.machine.waypoints[-1].xy)
        
        # Let's say we walk a bit
        wp = self.machine.waypoints[self.machine.waypoint_index]
        self.machine.update_pose(Pose2D(wp.xy[0], wp.xy[1], 0.0))
        self.machine.tick(now + 0.1)
        
        # Update target pos
        intruder_moved = (-2.0, 3.0) # work_room_3
        self.machine.pursuit_target_xy = intruder_moved
        
        # Since it replans every 1s, let's advance time by 1s and tick to trigger replan
        now += 1.1
        self.machine.tick(now)
        self.assertEqual("pursue", self.machine.state)
        self.assertEqual(intruder_moved, self.machine.waypoints[-1].xy)
        
        # Now place the robot close to the intruder to trigger detain check
        self.machine.update_pose(Pose2D(intruder_moved[0], intruder_moved[1], 0.0))
        self.machine.tick(now + 0.1)
        
        self.assertEqual("guard", self.machine.state)
        
        events, _ = read_new_statuses(self.status_path, 0)
        detains = [e for e in events if e["type"] == "DETAINED"]
        self.assertEqual(1, len(detains))
        self.assertEqual("Intruder", detains[0]["name"])
        
        # Guard time
        self.machine.tick(now + GUARD_TIME + 0.2)
        self.assertEqual("return", self.machine.state)
        
        while self.machine.state == "return" and self.machine.waypoint_index < len(self.machine.waypoints):
            wp = self.machine.waypoints[self.machine.waypoint_index]
            self.machine.update_pose(Pose2D(wp.xy[0], wp.xy[1], 0.0))
            self.machine.tick(now)
            now += 0.1
            
        self.assertEqual("idle", self.machine.state)


if __name__ == "__main__":
    unittest.main()
