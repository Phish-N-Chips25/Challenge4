import unittest

from booster_t1_webots_test.rpc_commands import API_CHANGE_MODE, API_MOVE
from booster_t1_webots_test.rpc_movement_client import build_arg_parser, run_command_sequence


class FakeRpcClient:
    def __init__(self):
        self.requests = []

    def call_api(self, api_id, body):
        self.requests.append((api_id, body))
        return True


class RpcMovementClientTest(unittest.TestCase):
    def test_parser_defaults_to_forward_for_one_second(self):
        args = build_arg_parser().parse_args([])

        self.assertEqual(args.command, "forward")
        self.assertEqual(args.duration, 1.0)
        self.assertEqual(args.service_name, "/booster_rpc_service")
        self.assertTrue(args.prepare)

    def test_parser_rejects_negative_duration(self):
        with self.assertRaises(SystemExit):
            build_arg_parser().parse_args(["--duration", "-1"])

    def test_sequence_prepares_walks_moves_and_stops(self):
        client = FakeRpcClient()

        run_command_sequence(client, command_name="forward", duration=0.0, prepare=True)

        self.assertEqual(len(client.requests), 4)
        self.assertEqual(client.requests[0][0], API_CHANGE_MODE)
        self.assertIn('"mode":1', client.requests[0][1])
        self.assertEqual(client.requests[1][0], API_CHANGE_MODE)
        self.assertIn('"mode":2', client.requests[1][1])
        self.assertEqual(client.requests[2][0], API_MOVE)
        self.assertIn('"vx":0.2', client.requests[2][1])
        self.assertEqual(client.requests[3][0], API_MOVE)
        self.assertIn('"vx":0.0', client.requests[3][1])

    def test_sequence_can_send_stop_without_prepare(self):
        client = FakeRpcClient()

        run_command_sequence(client, command_name="stop", duration=0.0, prepare=False)

        self.assertEqual(client.requests, [(API_MOVE, '{"vx":0.0,"vy":0.0,"vyaw":0.0}')])


if __name__ == "__main__":
    unittest.main()
