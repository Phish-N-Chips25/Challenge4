import unittest

from booster_t1_webots_test.rpc_commands import (
    API_CHANGE_MODE,
    API_MOVE,
    MODE_PREPARE,
    MODE_WALKING,
    MOVEMENT_COMMANDS,
    MovementCommand,
    get_movement_command,
    make_change_mode_request,
    make_move_request,
)


class RpcCommandsTest(unittest.TestCase):
    def test_change_mode_request_uses_api_id_and_mode_body(self):
        request = make_change_mode_request(MODE_PREPARE)

        self.assertEqual(API_CHANGE_MODE, request.api_id)
        self.assertEqual('{"mode":1}', request.body)

    def test_move_request_uses_api_id_and_velocity_body(self):
        request = make_move_request(0.2, 0.1, -0.2)

        self.assertEqual(API_MOVE, request.api_id)
        self.assertEqual('{"vx":0.2,"vy":0.1,"vyaw":-0.2}', request.body)

    def test_all_named_presets_match_safe_low_speeds(self):
        expected_commands = {
            "forward": MovementCommand(0.2, 0.0, 0.0),
            "backward": MovementCommand(-0.1, 0.0, 0.0),
            "left": MovementCommand(0.0, 0.1, 0.0),
            "right": MovementCommand(0.0, -0.1, 0.0),
            "turn_left": MovementCommand(0.0, 0.0, 0.2),
            "turn_right": MovementCommand(0.0, 0.0, -0.2),
            "stop": MovementCommand(0.0, 0.0, 0.0),
        }

        self.assertEqual(expected_commands, MOVEMENT_COMMANDS)
        self.assertEqual(expected_commands["forward"], get_movement_command("forward"))
        stop = MOVEMENT_COMMANDS["stop"]
        self.assertEqual(
            '{"vx":0.0,"vy":0.0,"vyaw":0.0}',
            make_move_request(stop.vx, stop.vy, stop.vyaw).body,
        )

    def test_unknown_command_error_lists_supported_commands(self):
        with self.assertRaises(ValueError) as context:
            get_movement_command("jump")

        self.assertIn("forward", str(context.exception))

    def test_walking_mode_id_is_two(self):
        self.assertEqual(2, MODE_WALKING)


if __name__ == "__main__":
    unittest.main()
