# ROS 2 RPC Movement Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a safe ROS 2 command-line movement client that controls Booster T1 walking through the official `booster_interface/srv/RpcService` API.

**Architecture:** Keep Booster API message formatting in a pure Python module that is easy to unit test. Add a thin `rclpy` node that waits for `/booster_rpc_service`, sends `ChangeMode` and `Move` RPC requests, and always sends a zero-velocity stop command after timed movement. Expose the node through `ros2 run booster_t1_webots_test rpc_movement_client`.

**Tech Stack:** ROS 2 Humble, `rclpy`, official `booster_interface`, Python `unittest`, `colcon`.

---

## File Structure

- Create `ros2_ws/src/booster_t1_webots_test/booster_t1_webots_test/rpc_commands.py`
  - Pure helpers for Booster RPC API ids, mode ids, movement presets, JSON body generation, and command lookup.
  - No ROS imports.
- Create `ros2_ws/src/booster_t1_webots_test/booster_t1_webots_test/rpc_movement_client.py`
  - ROS 2 service client node for `/booster_rpc_service`.
  - Handles CLI args, mode switching, timed movement, stop-on-exit behavior, and service errors.
- Create `ros2_ws/src/booster_t1_webots_test/test/test_rpc_commands.py`
  - Unit tests for command presets and JSON payloads.
- Create `ros2_ws/src/booster_t1_webots_test/test/test_rpc_movement_client.py`
  - Unit tests for argument parsing and command sequencing using a fake client.
- Modify `ros2_ws/src/booster_t1_webots_test/setup.py`
  - Add the `rpc_movement_client` console script.
- Modify `docs/BOOSTER_T1_WEBOTS_ROS_SETUP.md`
  - Update the limitation about `booster_interface`.
  - Add build/source commands and safe movement examples.

## Task 1: Add Pure Booster RPC Command Formatting

**Files:**
- Create: `ros2_ws/src/booster_t1_webots_test/booster_t1_webots_test/rpc_commands.py`
- Create: `ros2_ws/src/booster_t1_webots_test/test/test_rpc_commands.py`

- [ ] **Step 1: Write failing command-formatting tests**

Create `ros2_ws/src/booster_t1_webots_test/test/test_rpc_commands.py`:

```python
import json
import unittest

from booster_t1_webots_test.rpc_commands import (
    API_CHANGE_MODE,
    API_MOVE,
    MODE_PREPARE,
    MODE_WALKING,
    MovementCommand,
    get_movement_command,
    make_change_mode_request,
    make_move_request,
)


class RpcCommandsTest(unittest.TestCase):
    def test_change_mode_request_uses_official_api_id_and_mode_body(self):
        request = make_change_mode_request(MODE_PREPARE)

        self.assertEqual(request.api_id, API_CHANGE_MODE)
        self.assertEqual(json.loads(request.body), {"mode": MODE_PREPARE})

    def test_move_request_uses_official_api_id_and_velocity_body(self):
        request = make_move_request(0.2, -0.1, 0.3)

        self.assertEqual(request.api_id, API_MOVE)
        self.assertEqual(json.loads(request.body), {"vx": 0.2, "vy": -0.1, "vyaw": 0.3})

    def test_named_command_presets_start_with_safe_low_speeds(self):
        self.assertEqual(get_movement_command("forward"), MovementCommand(0.2, 0.0, 0.0))
        self.assertEqual(get_movement_command("backward"), MovementCommand(-0.1, 0.0, 0.0))
        self.assertEqual(get_movement_command("left"), MovementCommand(0.0, 0.1, 0.0))
        self.assertEqual(get_movement_command("right"), MovementCommand(0.0, -0.1, 0.0))
        self.assertEqual(get_movement_command("turn_left"), MovementCommand(0.0, 0.0, 0.2))
        self.assertEqual(get_movement_command("turn_right"), MovementCommand(0.0, 0.0, -0.2))
        self.assertEqual(get_movement_command("stop"), MovementCommand(0.0, 0.0, 0.0))

    def test_unknown_command_lists_supported_names(self):
        with self.assertRaisesRegex(ValueError, "forward"):
            get_movement_command("jump")

    def test_walking_mode_constant_matches_booster_api(self):
        self.assertEqual(MODE_WALKING, 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new test to verify it fails**

Run inside the ROS container:

```bash
cd /workspace/project/ros2_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
python3 -m pytest src/booster_t1_webots_test/test/test_rpc_commands.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'booster_t1_webots_test.rpc_commands'`.

- [ ] **Step 3: Implement the pure command module**

Create `ros2_ws/src/booster_t1_webots_test/booster_t1_webots_test/rpc_commands.py`:

```python
import json
from dataclasses import dataclass


API_CHANGE_MODE = 2000
API_MOVE = 2001

MODE_DAMPING = 0
MODE_PREPARE = 1
MODE_WALKING = 2
MODE_CUSTOM = 3


@dataclass(frozen=True)
class BoosterRpcRequest:
    api_id: int
    body: str


@dataclass(frozen=True)
class MovementCommand:
    vx: float
    vy: float
    vyaw: float


MOVEMENT_COMMANDS = {
    "forward": MovementCommand(0.2, 0.0, 0.0),
    "backward": MovementCommand(-0.1, 0.0, 0.0),
    "left": MovementCommand(0.0, 0.1, 0.0),
    "right": MovementCommand(0.0, -0.1, 0.0),
    "turn_left": MovementCommand(0.0, 0.0, 0.2),
    "turn_right": MovementCommand(0.0, 0.0, -0.2),
    "stop": MovementCommand(0.0, 0.0, 0.0),
}


def _json_body(values):
    return json.dumps(values, separators=(",", ":"), sort_keys=True)


def make_change_mode_request(mode):
    return BoosterRpcRequest(API_CHANGE_MODE, _json_body({"mode": int(mode)}))


def make_move_request(vx, vy, vyaw):
    return BoosterRpcRequest(
        API_MOVE,
        _json_body({"vx": float(vx), "vy": float(vy), "vyaw": float(vyaw)}),
    )


def get_movement_command(name):
    try:
        return MOVEMENT_COMMANDS[name]
    except KeyError as exc:
        supported = ", ".join(sorted(MOVEMENT_COMMANDS))
        raise ValueError(f"unknown movement command '{name}'. Supported commands: {supported}") from exc
```

- [ ] **Step 4: Run the command-formatting tests**

Run:

```bash
cd /workspace/project/ros2_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
python3 -m pytest src/booster_t1_webots_test/test/test_rpc_commands.py -v
```

Expected: PASS, 5 tests passed.

- [ ] **Step 5: Commit Task 1**

Run:

```bash
git add ros2_ws/src/booster_t1_webots_test/booster_t1_webots_test/rpc_commands.py \
  ros2_ws/src/booster_t1_webots_test/test/test_rpc_commands.py
git commit -m "feat(ros2): add Booster RPC movement command helpers"
```

## Task 2: Add ROS 2 RPC Movement Client Node

**Files:**
- Create: `ros2_ws/src/booster_t1_webots_test/booster_t1_webots_test/rpc_movement_client.py`
- Create: `ros2_ws/src/booster_t1_webots_test/test/test_rpc_movement_client.py`

- [ ] **Step 1: Write failing tests for argument parsing and command sequence**

Create `ros2_ws/src/booster_t1_webots_test/test/test_rpc_movement_client.py`:

```python
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
```

- [ ] **Step 2: Run the new test to verify it fails**

Run:

```bash
cd /workspace/project/ros2_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
python3 -m pytest src/booster_t1_webots_test/test/test_rpc_movement_client.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'booster_t1_webots_test.rpc_movement_client'`.

- [ ] **Step 3: Implement the ROS 2 RPC movement client**

Create `ros2_ws/src/booster_t1_webots_test/booster_t1_webots_test/rpc_movement_client.py`:

```python
import argparse
import time

import rclpy
from rclpy.node import Node

from booster_interface.msg import BoosterApiReqMsg
from booster_interface.srv import RpcService

from booster_t1_webots_test.rpc_commands import (
    MODE_PREPARE,
    MODE_WALKING,
    get_movement_command,
    make_change_mode_request,
    make_move_request,
)


class NonNegativeFloat:
    def __call__(self, value):
        parsed = float(value)
        if parsed < 0.0:
            raise argparse.ArgumentTypeError("duration must be greater than or equal to 0")
        return parsed


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Send safe Booster T1 movement commands through booster_rpc_service."
    )
    parser.add_argument(
        "--command",
        choices=[
            "forward",
            "backward",
            "left",
            "right",
            "turn_left",
            "turn_right",
            "stop",
        ],
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
        if not _send_request(client, make_change_mode_request(MODE_WALKING)):
            _send_request(client, make_move_request(0.0, 0.0, 0.0))
            return False

    if not _send_request(client, make_move_request(movement.vx, movement.vy, movement.vyaw)):
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
```

- [ ] **Step 4: Run node tests**

Run:

```bash
cd /workspace/project/ros2_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
python3 -m pytest src/booster_t1_webots_test/test/test_rpc_movement_client.py -v
```

Expected: PASS, 4 tests passed.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add ros2_ws/src/booster_t1_webots_test/booster_t1_webots_test/rpc_movement_client.py \
  ros2_ws/src/booster_t1_webots_test/test/test_rpc_movement_client.py
git commit -m "feat(ros2): add Booster RPC movement client"
```

## Task 3: Register Console Script and Build the Workspace

**Files:**
- Modify: `ros2_ws/src/booster_t1_webots_test/setup.py`

- [ ] **Step 1: Write failing package entry-point check**

Run before editing:

```bash
cd /workspace/project/ros2_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 run booster_t1_webots_test rpc_movement_client --help
```

Expected: FAIL with `No executable found`.

- [ ] **Step 2: Add the console script**

Modify the `entry_points["console_scripts"]` list in `ros2_ws/src/booster_t1_webots_test/setup.py` so it contains this exact additional entry:

```python
            "rpc_movement_client = booster_t1_webots_test.rpc_movement_client:main",
```

The final console scripts block should be:

```python
        "console_scripts": [
            "topic_listener = booster_t1_webots_test.topic_listener:main",
            "joint_state_listener = booster_t1_webots_test.joint_state_listener:main",
            "imu_listener = booster_t1_webots_test.imu_listener:main",
            "low_state_listener = booster_t1_webots_test.low_state_listener:main",
            "simple_command_publisher = booster_t1_webots_test.simple_command_publisher:main",
            "webots_state_publisher = booster_t1_webots_test.webots_state_publisher:main",
            "rpc_movement_client = booster_t1_webots_test.rpc_movement_client:main",
        ],
```

- [ ] **Step 3: Rebuild and source the workspace**

Run:

```bash
cd /workspace/project/ros2_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash
```

Expected: `booster_interface` and `booster_t1_webots_test` finish successfully.

- [ ] **Step 4: Verify CLI help works**

Run:

```bash
ros2 run booster_t1_webots_test rpc_movement_client --help
```

Expected: output includes `--command`, `--duration`, `--service-name`, and `--no-prepare`.

- [ ] **Step 5: Run all Python tests**

Run:

```bash
cd /workspace/project/ros2_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
python3 -m pytest src/booster_t1_webots_test/test -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit Task 3**

Run:

```bash
git add ros2_ws/src/booster_t1_webots_test/setup.py
git commit -m "chore(ros2): expose Booster RPC movement CLI"
```

## Task 4: Document Safe ROS 2 RPC Movement Usage

**Files:**
- Modify: `docs/BOOSTER_T1_WEBOTS_ROS_SETUP.md`

- [ ] **Step 1: Update the setup doc**

In `docs/BOOSTER_T1_WEBOTS_ROS_SETUP.md`, change the "What this setup does" section from:

```markdown
It does not implement walking, balance control, reinforcement learning, or Booster joint command control.
```

to:

```markdown
It includes passive topic listeners plus a safe high-level Booster RPC movement client. It does not implement balance control, reinforcement learning, or raw Booster joint command control.
```

In the "Safe command publisher" section, replace the final sentence:

```markdown
It does not publish to `joint_ctrl` because the exact Booster ROS 2 message type is not available in this package.
```

with:

```markdown
Raw `joint_ctrl` control is intentionally not used for walking. The project vendors the official `booster_interface` package and uses the high-level `booster_rpc_service` movement API instead.
```

Add this new section after "Safe command publisher":

````markdown
## ROS 2 RPC movement client

The official Booster high-level movement API is exposed through `booster_interface/srv/RpcService`.
Build and source the workspace before running movement commands:

```bash
cd /workspace/project/ros2_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash
```

Verify the interface is available:

```bash
ros2 interface show booster_interface/srv/RpcService
```

Safe timed movement examples:

```bash
ros2 run booster_t1_webots_test rpc_movement_client --command forward --duration 1.0
ros2 run booster_t1_webots_test rpc_movement_client --command backward --duration 1.0
ros2 run booster_t1_webots_test rpc_movement_client --command left --duration 1.0
ros2 run booster_t1_webots_test rpc_movement_client --command right --duration 1.0
ros2 run booster_t1_webots_test rpc_movement_client --command turn_left --duration 1.0
ros2 run booster_t1_webots_test rpc_movement_client --command turn_right --duration 1.0
ros2 run booster_t1_webots_test rpc_movement_client --command stop --no-prepare
```

The client switches to `kPrepare`, then `kWalking`, sends the requested `Move(vx, vy, vyaw)` command, waits for the requested duration, and sends `Move(0, 0, 0)` unless the command is `stop`.
Use `--no-prepare` only when the robot is already in a valid walking mode or when sending `stop`.
````

- [ ] **Step 2: Verify Markdown includes the movement commands**

Run:

```bash
rg -n "ROS 2 RPC movement client|rpc_movement_client|booster_rpc_service|--command forward" docs/BOOSTER_T1_WEBOTS_ROS_SETUP.md
```

Expected: one or more matches for each searched phrase.

- [ ] **Step 3: Commit Task 4**

Run:

```bash
git add docs/BOOSTER_T1_WEBOTS_ROS_SETUP.md
git commit -m "docs(ros2): document Booster RPC movement client"
```

## Task 5: End-to-End Verification Without a Live Robot

**Files:**
- No source edits.

- [ ] **Step 1: Build the full workspace**

Run:

```bash
cd /workspace/project/ros2_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash
```

Expected:

```text
Summary: 2 packages finished
```

- [ ] **Step 2: Verify the official RPC service type exists**

Run:

```bash
ros2 interface show booster_interface/srv/RpcService
```

Expected:

```text
booster_interface/BoosterApiReqMsg msg
	int64 api_id
	string body
---
booster_interface/BoosterApiRespMsg msg
	int64 status
	string body
```

- [ ] **Step 3: Run all package tests**

Run:

```bash
python3 -m pytest src/booster_t1_webots_test/test -v
```

Expected: all tests pass.

- [ ] **Step 4: Verify CLI argument handling**

Run:

```bash
ros2 run booster_t1_webots_test rpc_movement_client --help
```

Expected: help text lists all commands and options.

- [ ] **Step 5: Verify missing service behavior is non-destructive**

Run in a shell where no `/booster_rpc_service` is running:

```bash
timeout 3 ros2 run booster_t1_webots_test rpc_movement_client --command forward --duration 0.1
```

Expected: repeated log output containing `waiting for /booster_rpc_service`, then the `timeout` command exits. The node must not publish `joint_ctrl` commands or raw motor commands.

- [ ] **Step 6: Commit verification-only changes if any files changed**

Run:

```bash
git status --short
```

Expected: no uncommitted source changes from verification. If generated files appear under `ros2_ws/build`, `ros2_ws/install`, or `ros2_ws/log`, leave them unstaged.

## Task 6: Live-Service Smoke Test When Booster RPC Is Available

**Files:**
- No source edits.

- [ ] **Step 1: Confirm the service is available**

Run:

```bash
cd /workspace/project/ros2_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 service list | rg 'booster_rpc_service'
```

Expected:

```text
/booster_rpc_service
```

- [ ] **Step 2: Send a stop command first**

Run:

```bash
ros2 run booster_t1_webots_test rpc_movement_client --command stop --no-prepare
```

Expected: the node logs an RPC result for API id `2001` with status `0`.

- [ ] **Step 3: Send the smallest timed forward command**

Run:

```bash
ros2 run booster_t1_webots_test rpc_movement_client --command forward --duration 0.5
```

Expected: the node logs API id `2000` for prepare, API id `2000` for walking, API id `2001` for forward movement, and API id `2001` for stop. The robot should stop after 0.5 seconds.

- [ ] **Step 4: Send the explicit stop command again**

Run:

```bash
ros2 run booster_t1_webots_test rpc_movement_client --command stop --no-prepare
```

Expected: the node logs a successful API id `2001` stop request.

- [ ] **Step 5: Record live-test result in the final response**

Report whether `/booster_rpc_service` existed and whether each RPC returned status `0`. Include any non-zero status and the response body text.

## Self-Review Notes

- Spec coverage: The plan implements official ROS 2 RPC walking through `booster_interface/srv/RpcService`, safe named movements, automatic stop, CLI entry point, tests, and documentation.
- Placeholder scan: The plan has no incomplete sections or unnamed files.
- Type consistency: `BoosterRpcRequest`, `MovementCommand`, `call_api(api_id, body)`, and `run_command_sequence(client, command_name, duration, prepare=True)` are used consistently across tests and implementation.
