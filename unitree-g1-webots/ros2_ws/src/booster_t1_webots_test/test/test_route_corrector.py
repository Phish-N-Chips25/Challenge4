import unittest

from booster_t1_webots_test.block_map import BlockMap
from booster_t1_webots_test.patrol_types import Pose2D
from booster_t1_webots_test.route_corrector import RouteCorrector


class RouteCorrectorTest(unittest.TestCase):
    def test_uses_original_route_when_clear(self):
        block_map = BlockMap(block_size=0.25)
        route = [(0.0, 0.0), (1.0, 0.0)]

        corrected = RouteCorrector(block_map).correct_route(Pose2D(0.0, 0.0, 0.0), route)

        self.assertEqual(route, corrected)

    def test_creates_detour_when_original_segment_blocked(self):
        block_map = BlockMap(block_size=0.25)
        block_map.update_from_points(Pose2D(0.0, 0.0, 0.0), [(0.5, 0.0, 0.5)], now=1.0)

        corrected = RouteCorrector(block_map).correct_route(
            Pose2D(0.0, 0.0, 0.0),
            [(0.0, 0.0), (1.0, 0.0)],
        )

        self.assertIsNotNone(corrected)
        self.assertNotEqual([(0.0, 0.0), (1.0, 0.0)], corrected)
        self.assertEqual((1.0, 0.0), corrected[-1])


if __name__ == "__main__":
    unittest.main()
