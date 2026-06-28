import unittest

from booster_t1_webots_test.patrol_map import (
    DOCK,
    ZONES,
    DOOR_ARRIVE_DISTANCE,
    DOOR_FORWARD_SPEED,
    DOOR_WAYPOINTS,
    ZONE_ARRIVE_DISTANCE,
    zone_of,
    safe_route,
)
from booster_t1_webots_test.patrol_types import Waypoint


class ZoneOfTest(unittest.TestCase):
    def test_dock_is_in_corridor(self):
        self.assertEqual("corridor", zone_of(9.0, 0.0))

    def test_datacenter_center(self):
        self.assertEqual("datacenter", zone_of(8.4, 2.2))

    def test_lobby_center(self):
        self.assertEqual("lobby", zone_of(-5.0, -3.5))

    def test_break_room_center(self):
        self.assertEqual("break_room", zone_of(5.0, -3.5))

    def test_outside_returns_none(self):
        self.assertIsNone(zone_of(20.0, 20.0))


class SafeRouteTest(unittest.TestCase):
    def test_datacenter_route_enters_through_door_waypoints(self):
        route = safe_route(DOCK, (8.4, 2.2))
        # Route from corridor dock to datacenter: precision corridor_wp, inside_wp, target
        self.assertEqual((8.0, 0.2), route[-3].xy)
        self.assertEqual((8.0, 1.35), route[-2].xy)
        self.assertEqual(DOOR_ARRIVE_DISTANCE, route[-3].arrive_distance)
        self.assertEqual(DOOR_FORWARD_SPEED, route[-3].forward_speed)
        self.assertEqual((8.4, 2.2), route[-1].xy)

    def test_break_room_route_uses_south_door_clearance(self):
        route = safe_route(DOCK, (5.0, -3.5))
        self.assertIn((5.0, -0.35), [wp.xy for wp in route])
        self.assertIn((5.0, -1.7), [wp.xy for wp in route])

    def test_lobby_route(self):
        route = safe_route(DOCK, (-5.0, -3.5))
        self.assertIn((-5.0, -0.35), [wp.xy for wp in route])
        self.assertIn((-5.0, -1.7), [wp.xy for wp in route])

    def test_work_room_1_route(self):
        route = safe_route(DOCK, (-8.0, 3.0))
        self.assertIn((-8.0, 0.35), [wp.xy for wp in route])
        self.assertIn((-8.0, 1.7), [wp.xy for wp in route])

    def test_same_zone_goes_direct(self):
        route = safe_route((8.0, 2.0), (8.4, 2.2))
        self.assertEqual(1, len(route))
        self.assertEqual((8.4, 2.2), route[0].xy)

    def test_corridor_to_corridor_goes_direct(self):
        route = safe_route(DOCK, (0.0, 0.0))
        self.assertEqual(1, len(route))
        self.assertEqual((0.0, 0.0), route[0].xy)

    def test_room_to_room_goes_through_corridor(self):
        # break_room to datacenter: exit break_room, enter datacenter
        route = safe_route((5.0, -3.5), (8.4, 2.2))
        xys = [wp.xy for wp in route]
        # Exit break_room
        self.assertIn((5.0, -1.7), xys)
        self.assertIn((5.0, -0.35), xys)
        # Enter datacenter
        self.assertIn((8.0, 0.2), xys)
        self.assertIn((8.0, 1.35), xys)

    def test_all_zones_have_door_waypoints(self):
        for zone_name in ZONES:
            if zone_name == "corridor":
                continue
            self.assertIn(zone_name, DOOR_WAYPOINTS, f"missing door for {zone_name}")


class ZoneArrivalToleranceTest(unittest.TestCase):
    """The robot should stop a bit inside the room, not on the exact point."""

    def test_room_target_uses_loose_arrival(self):
        # Loose enough to not chase the exact coordinate, but well inside a room.
        self.assertGreater(ZONE_ARRIVE_DISTANCE, DOOR_ARRIVE_DISTANCE)

    def test_final_room_waypoint_is_loose(self):
        route = safe_route(DOCK, (5.0, -3.5))  # break_room centre
        final = route[-1]
        self.assertEqual((5.0, -3.5), final.xy)
        self.assertEqual(ZONE_ARRIVE_DISTANCE, final.arrive_distance)

    def test_door_threading_stays_precise(self):
        # The room-side door waypoint must keep its tight tolerance so the
        # robot threads the opening before the loose final arrival can trigger.
        route = safe_route(DOCK, (5.0, -3.5))
        inside = next(wp for wp in route if wp.xy == (5.0, -1.7))
        self.assertEqual(DOOR_ARRIVE_DISTANCE, inside.arrive_distance)

    def test_same_room_target_is_loose(self):
        route = safe_route((5.0, -2.0), (5.0, -3.5))
        self.assertEqual(1, len(route))
        self.assertEqual(ZONE_ARRIVE_DISTANCE, route[0].arrive_distance)

    def test_corridor_target_keeps_default_arrival(self):
        route = safe_route(DOCK, (0.0, 0.0))
        self.assertIsNone(route[-1].arrive_distance)


if __name__ == "__main__":
    unittest.main()
