import tempfile
import time
import unittest
from pathlib import Path

from booster_t1_webots_test.booster_patrol_node import (
    ASSIST_TIME,
    DETAIN_DISTANCE,
    GUARD_TIME,
    INVESTIGATE_TIME,
    PURSUIT_REPLAN_PERIOD,
    PatrolStateMachine,
)
from booster_t1_webots_test.navigation_manager import NavigationStatus
from booster_t1_webots_test.patrol_mission_bridge import (
    append_target_pos,
    read_new_statuses,
)
from booster_t1_webots_test.patrol_types import Mission, Pose2D


class FakeRpc:
    """Fake RPC client that records all movement commands."""

    def __init__(self):
        self.moves = []

    def move(self, vx, vy, vyaw):
        self.moves.append((vx, vy, vyaw))
        return True

    def stop(self):
        self.moves.append((0.0, 0.0, 0.0))
        return True


class FakeNavigationManager:
    def __init__(self, status):
        self.status = status
        self.targets = []

    def update_pose(self, pose, now):
        self.pose = pose

    def go_to(self, target, now, arrive_distance=None, forward_speed=None):
        self.targets.append((target, now, arrive_distance, forward_speed))
        return self.status


class PriorityQueueTest(unittest.TestCase):
    def test_priority_queue_starts_detain_before_investigate(self):
        with tempfile.TemporaryDirectory() as tmp:
            machine = PatrolStateMachine(
                rpc=FakeRpc(), status_path=Path(tmp) / "status.jsonl"
            )
            machine.enqueue(Mission(kind="assist", x=5.0, y=-3.0))
            machine.enqueue(
                Mission(kind="detain", x=-5.0, y=-1.0, target="Intruder")
            )
            machine.enqueue(
                Mission(kind="investigate", x=8.4, y=2.2, zone="datacenter")
            )
            self.assertEqual("detain", machine.pop_next_mission().kind)
            self.assertEqual("investigate", machine.pop_next_mission().kind)
            self.assertEqual("assist", machine.pop_next_mission().kind)

    def test_empty_queue_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            machine = PatrolStateMachine(
                rpc=FakeRpc(), status_path=Path(tmp) / "status.jsonl"
            )
            self.assertIsNone(machine.pop_next_mission())


class InvestigateRouteTest(unittest.TestCase):
    def test_investigate_route_starts_from_current_pose(self):
        with tempfile.TemporaryDirectory() as tmp:
            machine = PatrolStateMachine(
                rpc=FakeRpc(), status_path=Path(tmp) / "status.jsonl"
            )
            machine.update_pose(Pose2D(9.0, 0.0, 3.14159))
            machine.start_mission(
                Mission(kind="investigate", x=8.4, y=2.2, zone="datacenter")
            )
            # Route from corridor dock to datacenter should use precision door waypoints
            self.assertEqual((8.0, 0.2), machine.waypoints[-3].xy)
            self.assertEqual((8.0, 1.35), machine.waypoints[-2].xy)
            self.assertIsNotNone(machine.waypoints[-3].arrive_distance)
            self.assertIsNotNone(machine.waypoints[-3].forward_speed)
            self.assertEqual((8.4, 2.2), machine.waypoints[-1].xy)
            self.assertEqual("navigate", machine.state)


class StateTransitionTest(unittest.TestCase):
    def test_idle_picks_mission_on_tick(self):
        with tempfile.TemporaryDirectory() as tmp:
            rpc = FakeRpc()
            machine = PatrolStateMachine(
                rpc=rpc, status_path=Path(tmp) / "status.jsonl"
            )
            machine.enqueue(
                Mission(kind="investigate", x=8.4, y=2.2, zone="datacenter")
            )
            machine.tick(time.time())
            self.assertEqual("navigate", machine.state)

    def test_investigate_writes_report_after_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "status.jsonl"
            rpc = FakeRpc()
            machine = PatrolStateMachine(rpc=rpc, status_path=status_path)
            machine.update_pose(Pose2D(8.4, 2.2, 0.0))
            machine.start_mission(
                Mission(kind="investigate", x=8.4, y=2.2, zone="datacenter")
            )
            # Should arrive immediately since pose is at target
            now = time.time()
            machine.tick(now)
            # Should be onsite now
            self.assertEqual("onsite", machine.state)
            # After INVESTIGATE_TIME, should write REPORT
            machine.tick(now + INVESTIGATE_TIME + 1)
            events, _ = read_new_statuses(status_path, 0)
            report_events = [e for e in events if e["type"] == "REPORT"]
            self.assertEqual(1, len(report_events))
            self.assertEqual("datacenter", report_events[0]["zone"])
            self.assertEqual("return", machine.state)

    def test_assist_writes_assist_done_after_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "status.jsonl"
            rpc = FakeRpc()
            machine = PatrolStateMachine(rpc=rpc, status_path=status_path)
            machine.update_pose(Pose2D(5.0, -3.0, 0.0))
            machine.start_mission(
                Mission(kind="assist", x=5.0, y=-3.0, target="Alice")
            )
            now = time.time()
            machine.tick(now)  # arrive onsite
            self.assertEqual("onsite", machine.state)
            machine.tick(now + ASSIST_TIME + 1)
            events, _ = read_new_statuses(status_path, 0)
            assist_events = [e for e in events if e["type"] == "ASSIST_DONE"]
            self.assertEqual(1, len(assist_events))
            self.assertEqual("Alice", assist_events[0]["name"])
            self.assertEqual("return", machine.state)

    def test_detain_writes_detained_inconclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "status.jsonl"
            rpc = FakeRpc()
            machine = PatrolStateMachine(rpc=rpc, status_path=status_path)
            machine.update_pose(Pose2D(-5.0, -1.0, 0.0))
            machine.start_mission(
                Mission(kind="detain", x=-5.0, y=-1.0, target="Intruder")
            )
            now = time.time()
            # Detain starts in pursue; robot is at target so DETAIN_DISTANCE
            # fires immediately → guard.
            machine.tick(now)
            self.assertEqual("guard", machine.state)
            events, _ = read_new_statuses(status_path, 0)
            detained_events = [e for e in events if e["type"] == "DETAINED"]
            self.assertGreaterEqual(len(detained_events), 1)
            self.assertFalse(detained_events[0]["verified"])

    def test_return_to_dock_after_mission(self):
        with tempfile.TemporaryDirectory() as tmp:
            rpc = FakeRpc()
            machine = PatrolStateMachine(
                rpc=rpc, status_path=Path(tmp) / "status.jsonl"
            )
            # Simulate being already at dock
            machine.update_pose(Pose2D(9.0, 0.0, 0.0))
            machine.start_mission(
                Mission(kind="investigate", x=9.0, y=0.0, zone="corridor")
            )
            now = time.time()
            machine.tick(now)  # arrive immediately (same zone direct route)
            self.assertEqual("onsite", machine.state)
            machine.tick(now + INVESTIGATE_TIME + 1)
            self.assertEqual("return", machine.state)
            # Tick return — already at dock
            machine.tick(now + INVESTIGATE_TIME + 2)
            self.assertEqual("idle", machine.state)

    def test_handle_error_sends_stop_and_writes_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "status.jsonl"
            rpc = FakeRpc()
            machine = PatrolStateMachine(rpc=rpc, status_path=status_path)
            machine.handle_error("RPC timeout")
            self.assertTrue(
                any(m == (0.0, 0.0, 0.0) for m in rpc.moves),
                "should have sent stop",
            )
            events, _ = read_new_statuses(status_path, 0)
            error_events = [e for e in events if e.get("state") == "error"]
            self.assertEqual(1, len(error_events))
            self.assertEqual("RPC timeout", error_events[0]["error"])


class NavigationManagerIntegrationTest(unittest.TestCase):
    def test_navigate_uses_navigation_manager_and_stops_when_unsafe(self):
        with tempfile.TemporaryDirectory() as tmp:
            rpc = FakeRpc()
            nav = FakeNavigationManager(NavigationStatus.UNSAFE)
            machine = PatrolStateMachine(
                rpc=rpc,
                status_path=Path(tmp) / "status.jsonl",
                navigation_manager=nav,
            )
            machine.update_pose(Pose2D(9.0, 0.0, 0.0))
            machine.start_mission(
                Mission(kind="investigate", x=8.4, y=2.2, zone="datacenter")
            )

            machine.tick(time.time())

            self.assertEqual("navigate", machine.state)
            self.assertEqual((0.0, 0.0, 0.0), rpc.moves[-1])
            self.assertTrue(nav.targets)

    def test_navigate_advances_waypoint_when_navigation_manager_arrives(self):
        with tempfile.TemporaryDirectory() as tmp:
            rpc = FakeRpc()
            nav = FakeNavigationManager(NavigationStatus.ARRIVED)
            machine = PatrolStateMachine(
                rpc=rpc,
                status_path=Path(tmp) / "status.jsonl",
                navigation_manager=nav,
            )
            machine.update_pose(Pose2D(9.0, 0.0, 0.0))
            machine.start_mission(
                Mission(kind="investigate", x=8.4, y=2.2, zone="datacenter")
            )
            move_count_before_tick = len(rpc.moves)

            machine.tick(time.time())

            self.assertEqual(1, machine.waypoint_index)
            self.assertEqual(move_count_before_tick, len(rpc.moves))
            self.assertEqual(0.28, nav.targets[0][2])
            self.assertEqual(0.50, nav.targets[0][3])


class DetainStartsInPursueTest(unittest.TestCase):
    """Detain missions must immediately enter pursue state."""

    def test_detain_starts_in_pursue_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            rpc = FakeRpc()
            machine = PatrolStateMachine(
                rpc=rpc, status_path=Path(tmp) / "status.jsonl"
            )
            machine.update_pose(Pose2D(9.0, 0.0, 3.14159))
            machine.start_mission(
                Mission(kind="detain", x=-5.0, y=-1.0, target="Intruder")
            )
            self.assertEqual("pursue", machine.state)
            self.assertEqual((-5.0, -1.0), machine.pursuit_target_xy)

    def test_investigate_starts_in_navigate_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            rpc = FakeRpc()
            machine = PatrolStateMachine(
                rpc=rpc, status_path=Path(tmp) / "status.jsonl"
            )
            machine.start_mission(
                Mission(kind="investigate", x=8.4, y=2.2, zone="datacenter")
            )
            self.assertEqual("navigate", machine.state)


class DetainDistanceTest(unittest.TestCase):
    """When the robot is within DETAIN_DISTANCE, it must detain."""

    def test_detain_within_distance_sends_detained(self):
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "status.jsonl"
            rpc = FakeRpc()
            machine = PatrolStateMachine(rpc=rpc, status_path=status_path)
            # Place robot very close to target
            machine.update_pose(Pose2D(-5.0, -1.0, 0.0))
            machine.start_mission(
                Mission(kind="detain", x=-5.0, y=-1.0, target="Intruder")
            )
            # State should be pursue, and pursuit_target_xy set
            self.assertEqual("pursue", machine.state)
            # Tick — robot is at target position so within DETAIN_DISTANCE
            now = time.time()
            machine.tick(now)
            # Should have transitioned to guard and written DETAINED
            self.assertEqual("guard", machine.state)
            events, _ = read_new_statuses(status_path, 0)
            detained = [e for e in events if e["type"] == "DETAINED"]
            self.assertGreaterEqual(len(detained), 1)
            self.assertEqual("Intruder", detained[0]["name"])

    def test_detain_outside_distance_continues_pursuing(self):
        with tempfile.TemporaryDirectory() as tmp:
            rpc = FakeRpc()
            machine = PatrolStateMachine(
                rpc=rpc, status_path=Path(tmp) / "status.jsonl"
            )
            # Place robot far from target
            machine.update_pose(Pose2D(9.0, 0.0, 3.14159))
            machine.start_mission(
                Mission(kind="detain", x=-5.0, y=-1.0, target="Intruder")
            )
            now = time.time()
            machine.tick(now)
            # Should still be in pursue (not guard)
            self.assertIn(machine.state, ("pursue", "navigate"))


class PursuitTargetUpdateTest(unittest.TestCase):
    """TARGET_POS updates must refresh pursuit_target_xy."""

    def test_pursuit_updates_target_from_bridge(self):
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "status.jsonl"
            target_pos_path = Path(tmp) / "target_pos.jsonl"
            missions_path = Path(tmp) / "missions.jsonl"
            rpc = FakeRpc()
            machine = PatrolStateMachine(
                rpc=rpc,
                status_path=status_path,
                missions_path=missions_path,
                target_pos_path=target_pos_path,
            )
            # Place robot far from the target so DETAIN_DISTANCE doesn't fire
            machine.update_pose(Pose2D(9.0, 0.0, 3.14159))
            machine.start_mission(
                Mission(kind="detain", x=-5.0, y=-1.0, target="Intruder")
            )
            self.assertEqual((-5.0, -1.0), machine.pursuit_target_xy)

            # Write a new TARGET_POS event
            append_target_pos(target_pos_path, "Intruder", -3.0, -2.0)

            # Tick to poll (need to advance past MISSION_POLL_PERIOD)
            now = time.time()
            machine.last_mission_poll = now - 2.0  # force poll
            machine.tick(now)

            # Should have updated pursuit_target_xy
            self.assertEqual((-3.0, -2.0), machine.pursuit_target_xy)

    def test_pursuit_ignores_target_for_different_mission(self):
        with tempfile.TemporaryDirectory() as tmp:
            target_pos_path = Path(tmp) / "target_pos.jsonl"
            rpc = FakeRpc()
            machine = PatrolStateMachine(
                rpc=rpc,
                status_path=Path(tmp) / "status.jsonl",
                target_pos_path=target_pos_path,
            )
            machine.update_pose(Pose2D(9.0, 0.0, 3.14159))
            machine.start_mission(
                Mission(kind="detain", x=-5.0, y=-1.0, target="Intruder")
            )
            # Write TARGET_POS for a DIFFERENT target
            append_target_pos(target_pos_path, "OtherPerson", 1.0, 1.0)

            now = time.time()
            machine.last_mission_poll = now - 2.0
            machine.tick(now)

            # pursuit_target_xy should NOT be updated
            self.assertEqual((-5.0, -1.0), machine.pursuit_target_xy)

    def test_no_target_pos_for_investigate_mission(self):
        with tempfile.TemporaryDirectory() as tmp:
            target_pos_path = Path(tmp) / "target_pos.jsonl"
            rpc = FakeRpc()
            machine = PatrolStateMachine(
                rpc=rpc,
                status_path=Path(tmp) / "status.jsonl",
                target_pos_path=target_pos_path,
            )
            machine.update_pose(Pose2D(9.0, 0.0, 0.0))
            machine.start_mission(
                Mission(kind="investigate", x=8.4, y=2.2, zone="datacenter")
            )
            # Write TARGET_POS
            append_target_pos(target_pos_path, "Intruder", 1.0, 1.0)

            now = time.time()
            machine.last_mission_poll = now - 2.0
            machine.tick(now)

            # pursuit_target_xy should remain None
            self.assertIsNone(machine.pursuit_target_xy)


class PursueReplanTest(unittest.TestCase):
    """Pursuit replanning must not throw away waypoint progress at a doorway.

    Regression: in pursue state the route was rebuilt every PURSUIT_REPLAN_PERIOD
    with waypoint_index hard-reset to 0. At a door the index-0 waypoint is the
    corridor-side approach point *behind* the robot, so each replan yanked the
    robot back out of the doorway — it could never cross into the room (e.g. the
    datacenter) and ping-ponged on the threshold forever.
    """

    def _pursue_machine(self, tmp):
        machine = PatrolStateMachine(
            rpc=FakeRpc(), status_path=Path(tmp) / "status.jsonl"
        )
        # Start from the corridor dock, chase an intruder inside the datacenter.
        machine.update_pose(Pose2D(9.0, 0.0, 3.14159))
        machine.start_mission(
            Mission(kind="detain", x=7.53, y=2.55, target="Intruder")
        )
        self.assertEqual("pursue", machine.state)
        # safe_route through the datacenter door: approach (8,0.2) then cross
        # (8,1.35) then the target.
        self.assertEqual((8.0, 0.2), machine.waypoints[0].xy)
        self.assertEqual((8.0, 1.35), machine.waypoints[1].xy)
        # The robot has already cleared the corridor approach wp and is on the
        # threshold heading for the door-cross wp.
        machine.waypoint_index = 1
        machine.update_pose(Pose2D(8.0, 0.7, 1.5708))
        return machine

    def test_static_target_does_not_reset_waypoint_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            machine = self._pursue_machine(tmp)
            door_wp = machine.waypoints[1].xy
            # A full replan period elapses with the intruder position unchanged.
            machine.tick(machine.last_pursuit_replan + PURSUIT_REPLAN_PERIOD + 0.1)
            # Progress preserved: still heading for the door-cross wp, not
            # rewound to the corridor approach wp.
            self.assertEqual(1, machine.waypoint_index)
            self.assertEqual(door_wp, machine.waypoints[machine.waypoint_index].xy)

    def test_moved_target_replans_but_keeps_cleared_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            machine = self._pursue_machine(tmp)
            # Intruder moves deeper into the datacenter — a real replan is needed
            # (the final target waypoint changes), but the shared leading door
            # waypoints must not send the robot back to the corridor.
            machine.pursuit_target_xy = (6.8, 4.0)
            machine.tick(machine.last_pursuit_replan + PURSUIT_REPLAN_PERIOD + 0.1)
            self.assertGreaterEqual(machine.waypoint_index, 1)
            self.assertNotEqual(
                (8.0, 0.2), machine.waypoints[machine.waypoint_index].xy
            )


if __name__ == "__main__":
    unittest.main()
