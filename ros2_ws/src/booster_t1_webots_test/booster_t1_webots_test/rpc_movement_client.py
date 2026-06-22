import argparse
import time

from booster_t1_webots_test.rpc_commands import (
    MODE_PREPARE,
    MODE_WALKING,
    SAFE_PATH_COMMANDS,
    SUPPORTED_COMMANDS,
    get_movement_command,
    get_safe_path_command,
    make_change_mode_request,
    make_move_request,
)


def _load_ros_dependencies():
    import rclpy
    from booster_interface.msg import BoosterApiReqMsg
    from booster_interface.srv import RpcService

    return rclpy, BoosterApiReqMsg, RpcService


def _client_log(client, message):
    node = getattr(client, "node", None)
    if node is not None:
        node.get_logger().info(f"[rpc_movement_client] {message}")
    else:
        print(f"[rpc_movement_client] {message}", flush=True)


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
        choices=SUPPORTED_COMMANDS,
        default="safe_dock_path",
    )
    parser.add_argument(
        "--duration",
        type=NonNegativeFloat(),
        default=1.0,
        help="Duration for simple movement commands. Safe path commands use fixed segment durations.",
    )
    parser.add_argument("--service-name", default="/booster_rpc_service")
    parser.add_argument(
        "--no-prepare",
        action="store_false",
        dest="prepare",
        help="Skip prepare and walking mode changes before the move command.",
    )
    parser.set_defaults(prepare=True)
    return parser


class BoosterRpcMovementClient:
    def __init__(self, service_name):
        self.rclpy, self.booster_api_request, self.rpc_service = _load_ros_dependencies()
        self.node = self.rclpy.create_node("rpc_movement_client")
        self.client = self.node.create_client(self.rpc_service, service_name)
        self.service_name = service_name

    def wait_for_service(self):
        while self.rclpy.ok() and not self.client.wait_for_service(timeout_sec=1.0):
            self.node.get_logger().info(f"waiting for {self.service_name}")
        return self.rclpy.ok()

    def call_api(self, api_id, body):
        self.node.get_logger().info(f"RPC request api_id={api_id} body={body}")
        request = self.rpc_service.Request()
        request.msg = self.booster_api_request()
        request.msg.api_id = int(api_id)
        request.msg.body = body

        future = self.client.call_async(request)
        self.rclpy.spin_until_future_complete(self.node, future)
        response = future.result()
        if response is None:
            self.node.get_logger().error(f"RPC call failed for api_id={api_id}")
            return False

        self.node.get_logger().info(
            f"RPC api_id={api_id} status={response.msg.status} body={response.msg.body}"
        )
        return response.msg.status == 0

    def destroy_node(self):
        self.node.destroy_node()


def _send_request(client, request):
    _client_log(client, f"send_request api_id={request.api_id} body={request.body}")
    ok = client.call_api(request.api_id, request.body)
    _client_log(client, f"send_request_done api_id={request.api_id} ok={ok}")
    return ok


def _send_stop(client):
    _client_log(client, "send_stop")
    return _send_request(client, make_move_request(0.0, 0.0, 0.0))


def _prepare_walking(client):
    _client_log(client, "prepare_walking start")
    if not _send_request(client, make_change_mode_request(MODE_PREPARE)):
        _client_log(client, "prepare_walking failed mode=prepare")
        return False
    time.sleep(3.5)
    if not _send_request(client, make_change_mode_request(MODE_WALKING)):
        _send_stop(client)
        _client_log(client, "prepare_walking failed mode=walking")
        return False
    time.sleep(1.0)
    _client_log(client, "prepare_walking ready")
    return True


def _send_named_movement(client, command_name):
    movement = get_movement_command(command_name)
    _client_log(
        client,
        f"send_named_movement command={command_name} "
        f"vx={movement.vx} vy={movement.vy} vyaw={movement.vyaw}",
    )
    return _send_request(
        client,
        make_move_request(movement.vx, movement.vy, movement.vyaw),
    )


def run_safe_path_sequence(client, path_name, prepare=True):
    _client_log(client, f"run_safe_path_sequence path={path_name} prepare={prepare}")
    if prepare:
        if not _prepare_walking(client):
            return False

    for step in get_safe_path_command(path_name):
        _client_log(
            client,
            f"safe_path_step command={step.command} duration={step.duration} "
            f"note={step.note!r}",
        )
        if not _send_named_movement(client, step.command):
            _send_stop(client)
            return False
        if step.duration > 0.0:
            time.sleep(step.duration)
        if step.command != "stop" and not _send_stop(client):
            return False
        time.sleep(0.25)

    return True


def run_movement_sequence(client, command_name, duration, prepare=True):
    _client_log(
        client,
        f"run_movement_sequence command={command_name} duration={duration} "
        f"prepare={prepare}",
    )
    if prepare and command_name != "stop":
        if not _send_request(client, make_change_mode_request(MODE_PREPARE)):
            return False
        time.sleep(3.5)
        if not _send_request(client, make_change_mode_request(MODE_WALKING)):
            _send_stop(client)
            return False
        time.sleep(1.0)

    if not _send_named_movement(client, command_name):
        _send_stop(client)
        return False

    if command_name != "stop":
        time.sleep(duration)
        return _send_stop(client)

    return True


def run_command_sequence(client, command_name, duration, prepare=True):
    if command_name in SAFE_PATH_COMMANDS:
        return run_safe_path_sequence(client, command_name, prepare=prepare)
    return run_movement_sequence(client, command_name, duration, prepare=prepare)


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    rclpy, _, _ = _load_ros_dependencies()

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
