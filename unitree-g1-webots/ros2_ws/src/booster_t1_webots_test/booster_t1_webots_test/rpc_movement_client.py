import argparse
import time

import rclpy
from booster_interface.msg import BoosterApiReqMsg
from booster_interface.srv import RpcService
from rclpy.node import Node

from booster_t1_webots_test.rpc_commands import (
    MODE_PREPARE,
    MODE_WALKING,
    MOVEMENT_COMMANDS,
    get_movement_command,
    make_change_mode_request,
    make_move_request,
)


class NonNegativeFloat:
    def __call__(self, value):
        parsed = float(value)
        if parsed < 0.0:
            raise argparse.ArgumentTypeError(
                "duration must be greater than or equal to 0"
            )
        return parsed


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Send safe Booster T1 movement commands through booster_rpc_service."
    )
    parser.add_argument(
        "--command",
        choices=sorted(MOVEMENT_COMMANDS),
        default="forward",
    )
    parser.add_argument("--duration", type=NonNegativeFloat(), default=1.0)
    parser.add_argument("--service-name", default="/booster_rpc_service")
    parser.add_argument(
        "--no-prepare",
        action="store_false",
        dest="prepare",
        help="Skip prepare and walking mode changes before the move command.",
    )
    parser.set_defaults(prepare=True)
    return parser


class BoosterRpcMovementClient(Node):
    def __init__(self, service_name):
        super().__init__("rpc_movement_client")
        self.client = self.create_client(RpcService, service_name)
        self.service_name = service_name

    def wait_for_service(self):
        while rclpy.ok() and not self.client.wait_for_service(timeout_sec=1.0):
            self.get_logger().info(f"waiting for {self.service_name}")
        return rclpy.ok()

    def call_api(self, api_id, body):
        request = RpcService.Request()
        request.msg = BoosterApiReqMsg()
        request.msg.api_id = int(api_id)
        request.msg.body = body

        future = self.client.call_async(request)
        rclpy.spin_until_future_complete(self, future)
        response = future.result()
        if response is None:
            self.get_logger().error(f"RPC call failed for api_id={api_id}")
            return False

        self.get_logger().info(
            f"RPC api_id={api_id} status={response.msg.status} body={response.msg.body}"
        )
        return response.msg.status == 0


def _send_request(client, request):
    return client.call_api(request.api_id, request.body)


def run_command_sequence(client, command_name, duration, prepare=True):
    movement = get_movement_command(command_name)

    if prepare and command_name != "stop":
        if not _send_request(client, make_change_mode_request(MODE_PREPARE)):
            return False
        time.sleep(3.5)
        if not _send_request(client, make_change_mode_request(MODE_WALKING)):
            _send_request(client, make_move_request(0.0, 0.0, 0.0))
            return False
        time.sleep(1.0)

    if not _send_request(
        client, make_move_request(movement.vx, movement.vy, movement.vyaw)
    ):
        _send_request(client, make_move_request(0.0, 0.0, 0.0))
        return False

    if command_name != "stop":
        time.sleep(duration)
        return _send_request(client, make_move_request(0.0, 0.0, 0.0))

    return True


def main(argv=None):
    args = build_arg_parser().parse_args(argv)

    rclpy.init(args=[])
    node = BoosterRpcMovementClient(args.service_name)
    try:
        if not node.wait_for_service():
            return 1
        ok = run_command_sequence(
            node,
            command_name=args.command,
            duration=args.duration,
            prepare=args.prepare,
        )
        return 0 if ok else 2
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
