import unittest

from booster_t1_webots_test.block_map import BlockMap
from booster_t1_webots_test.navigation_manager import NavigationManager, NavigationStatus
from booster_t1_webots_test.patrol_types import Pose2D


class FakeRpc:
    def __init__(self):
        self.moves = []

    def move(self, vx, vy, vyaw):
        self.moves.append((vx, vy, vyaw))
        return True

    def stop(self):
        self.moves.append((0.0, 0.0, 0.0))
        return True


class NavigationManagerTest(unittest.TestCase):
    def test_go_to_stops_when_odometry_missing(self):
        rpc = FakeRpc()
        manager = NavigationManager(rpc=rpc)

        status = manager.go_to((1.0, 0.0), now=10.0)

        self.assertEqual(NavigationStatus.UNSAFE, status)
        self.assertEqual((0.0, 0.0, 0.0), rpc.moves[-1])

    def test_go_to_stops_when_lidar_stale(self):
        rpc = FakeRpc()
        manager = NavigationManager(rpc=rpc, lidar_timeout=0.5)
        manager.update_pose(Pose2D(0.0, 0.0, 0.0), now=10.0)
        manager.update_lidar([(1.5, 0.0, 0.5)], now=10.0)

        status = manager.go_to((1.0, 0.0), now=10.6)

        self.assertEqual(NavigationStatus.UNSAFE, status)
        self.assertEqual((0.0, 0.0, 0.0), rpc.moves[-1])

    def test_go_to_can_use_odometry_when_fresh_lidar_is_optional(self):
        rpc = FakeRpc()
        manager = NavigationManager(
            rpc=rpc,
            lidar_timeout=0.5,
            require_fresh_lidar=False,
        )
        manager.update_pose(Pose2D(0.0, 0.0, 0.0), now=10.0)

        status = manager.go_to((1.0, 0.0), now=10.6)

        self.assertEqual(NavigationStatus.RUNNING, status)
        self.assertGreater(rpc.moves[-1][0], 0.0)

    def test_go_to_stops_when_obstacle_is_ahead(self):
        rpc = FakeRpc()
        block_map = BlockMap(block_size=0.25)
        manager = NavigationManager(rpc=rpc, block_map=block_map, lidar_timeout=0.5)
        manager.update_pose(Pose2D(0.0, 0.0, 0.0), now=10.0)
        manager.update_lidar([(0.45, 0.0, 0.5)], now=10.0)

        status = manager.go_to((1.0, 0.0), now=10.1)

        self.assertEqual(NavigationStatus.UNSAFE, status)
        self.assertEqual((0.0, 0.0, 0.0), rpc.moves[-1])

    def test_go_to_uses_rpc_move_when_safe(self):
        rpc = FakeRpc()
        manager = NavigationManager(rpc=rpc, lidar_timeout=0.5)
        manager.update_pose(Pose2D(0.0, 0.0, 0.0), now=10.0)
        manager.update_lidar([(1.5, 1.5, 0.5)], now=10.0)

        status = manager.go_to((1.0, 0.0), now=10.1)

        self.assertEqual(NavigationStatus.RUNNING, status)
        self.assertGreater(rpc.moves[-1][0], 0.0)

    def test_go_to_applies_configured_forward_speed(self):
        rpc = FakeRpc()
        manager = NavigationManager(
            rpc=rpc,
            lidar_timeout=0.5,
            require_fresh_lidar=False,
            forward_speed=0.04,
        )
        manager.update_pose(Pose2D(0.0, 0.0, 0.0), now=10.0)

        status = manager.go_to((1.0, 0.0), now=10.1)

        self.assertEqual(NavigationStatus.RUNNING, status)
        self.assertEqual(0.04, rpc.moves[-1][0])

    def test_go_to_applies_configured_turn_rate(self):
        rpc = FakeRpc()
        manager = NavigationManager(
            rpc=rpc,
            lidar_timeout=0.5,
            require_fresh_lidar=False,
            max_yaw_rate=0.05,
        )
        manager.update_pose(Pose2D(0.0, 0.0, 0.0), now=10.0)

        status = manager.go_to((0.0, 1.0), now=10.1)

        self.assertEqual(NavigationStatus.RUNNING, status)
        self.assertEqual((0.0, 0.0, 0.05), rpc.moves[-1])

    def test_go_to_reports_arrived_and_stops(self):
        rpc = FakeRpc()
        manager = NavigationManager(rpc=rpc, lidar_timeout=0.5)
        manager.update_pose(Pose2D(1.0, 0.0, 0.0), now=10.0)
        manager.update_lidar([(1.5, 1.5, 0.5)], now=10.0)

        status = manager.go_to((1.0, 0.0), now=10.1)

        self.assertEqual(NavigationStatus.ARRIVED, status)
        self.assertEqual((0.0, 0.0, 0.0), rpc.moves[-1])


if __name__ == "__main__":
    unittest.main()
