"""Booster patrol ROS node — mission-driven waypoint follower.

Subscribes to /booster_t1/odom, reads missions from the JSONL bridge,
follows safe waypoint paths via /booster_rpc_service, and writes status
updates back through the bridge.

The heavy lifting is in PatrolStateMachine (pure Python, no ROS dependency)
so it can be unit-tested with a fake RPC client.
"""
from __future__ import annotations

from collections.abc import Callable
import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .navigation_manager import NavigationStatus
from .patrol_controller import (
    DEFAULT_ARRIVE_DISTANCE,
    FORWARD_SPEED,
    HEADING_TOLERANCE,
    MAX_WALK_YAW_RATE,
    MAX_YAW_RATE,
    command_towards,
)
from .patrol_map import DOCK, safe_route
from .patrol_mission_bridge import (
    append_status,
    read_new_missions,
    read_new_target_positions,
)
from .patrol_types import Mission, Pose2D, Waypoint

# Mission priority: lower number = higher priority
MISSION_PRIORITY = {"detain": 0, "investigate": 1, "assist": 2}

# Timing constants (seconds)
INVESTIGATE_TIME = 5.0
ASSIST_TIME = 5.0
GUARD_TIME = 10.0
DETAIN_DISTANCE = 0.95          # m — close enough to detain the target
PURSUIT_REPLAN_PERIOD = 1.0
MISSION_POLL_PERIOD = 1.0
PATROL_TICK_PERIOD = 0.1


@dataclass
class PatrolStateMachine:
    """Pure Python patrol state machine.

    Manages mission queue, waypoint following, and state transitions.
    No ROS dependency — testable with a fake RPC client.
    """
    rpc: Any                      # object with .move(vx, vy, vyaw) and .stop()
    status_path: Path             # path to booster_status.jsonl
    missions_path: Path | None = None
    target_pos_path: Path | None = None  # path to booster_target_pos.jsonl
    navigation_manager: Any | None = None
    logger: Callable[[str], None] | None = None

    # ── Internal state ───────────────────────────────────────────────
    state: str = "idle"
    pose: Pose2D = field(default_factory=lambda: Pose2D(9.0, 0.0, 3.14159))
    queue: list[Mission] = field(default_factory=list)
    current_mission: Mission | None = None
    waypoints: list[Waypoint] = field(default_factory=list)
    waypoint_index: int = 0
    state_entered_at: float = 0.0
    last_mission_poll: float = 0.0
    mission_file_offset: int = 0
    target_pos_file_offset: int = 0
    last_pursuit_replan: float = 0.0
    pursuit_target_xy: tuple[float, float] | None = None
    last_pose_log_at: float = -1e9
    last_logged_move: tuple[float, float, float] | None = None
    last_logged_stop_reason: str | None = None
    last_logged_nav_status: NavigationStatus | None = None

    # ── Mission queue management ─────────────────────────────────────

    def enqueue(self, mission: Mission) -> None:
        """Add a mission to the priority queue."""
        self.queue.append(mission)
        self.queue.sort(key=lambda m: MISSION_PRIORITY.get(m.kind, 99))
        self._log(
            f"ENQUEUE {self._mission_summary(mission)} queue_len={len(self.queue)}"
        )

    def pop_next_mission(self) -> Mission | None:
        """Pop the highest-priority mission from the queue."""
        if not self.queue:
            return None
        mission = self.queue.pop(0)
        self._log(
            f"DEQUEUE {self._mission_summary(mission)} queue_len={len(self.queue)}"
        )
        return mission

    # ── Pose update ──────────────────────────────────────────────────

    def update_pose(self, pose: Pose2D) -> None:
        """Update the robot's current pose from odometry."""
        now = time.time()
        self.pose = pose
        if self.navigation_manager is not None:
            self.navigation_manager.update_pose(pose, now)
        if now - self.last_pose_log_at >= 1.0:
            self.last_pose_log_at = now
            self._log(
                f"POSE x={pose.x:.3f} y={pose.y:.3f} theta={pose.theta:.3f}"
            )

    # ── Mission start ────────────────────────────────────────────────

    def start_mission(self, mission: Mission) -> None:
        """Begin executing a mission by building a safe route."""
        self.current_mission = mission
        start = (self.pose.x, self.pose.y)
        target = (mission.x, mission.y)
        self.waypoints = safe_route(start, target)
        self.waypoint_index = 0
        self.state_entered_at = time.time()
        self._stop("start_mission")

        if mission.kind == "detain":
            # Detain missions start immediately in pursue state so the
            # robot replans toward the live TARGET_POS updates.
            self._enter_state("pursue", self.state_entered_at)
            self.pursuit_target_xy = target
            self.last_pursuit_replan = time.time()
        else:
            self._enter_state("navigate", self.state_entered_at)

        self._log(
            f"START {self._mission_summary(mission)} "
            f"route_len={len(self.waypoints)} waypoints={self._waypoint_summary()}"
        )

    # ── State machine tick ───────────────────────────────────────────

    def tick(self, now: float) -> None:
        """Advance the state machine by one tick."""
        # Poll for new missions periodically
        if self.missions_path and now - self.last_mission_poll >= MISSION_POLL_PERIOD:
            self.last_mission_poll = now
            self._poll_missions()

        if self.state == "idle":
            self._tick_idle(now)
        elif self.state == "navigate":
            self._tick_navigate(now)
        elif self.state == "pursue":
            self._tick_pursue(now)
        elif self.state == "onsite":
            self._tick_onsite(now)
        elif self.state == "guard":
            self._tick_guard(now)
        elif self.state == "return":
            self._tick_return(now)

    def _tick_idle(self, now: float) -> None:
        mission = self.pop_next_mission()
        if mission is not None:
            self.start_mission(mission)

    def _tick_navigate(self, now: float) -> None:
        if self.waypoint_index >= len(self.waypoints):
            self._arrive_onsite(now)
            return

        wp = self.waypoints[self.waypoint_index]
        if self._use_navigation_manager(wp, now):
            return

        decision = command_towards(
            self.pose,
            wp.xy,
            arrive_distance=wp.arrive_distance or DEFAULT_ARRIVE_DISTANCE,
            forward_speed=wp.forward_speed or FORWARD_SPEED,
        )

        if decision.arrived:
            self._stop("waypoint_arrived")
            self.waypoint_index += 1
            self._log(f"WAYPOINT {self.waypoint_index}/{len(self.waypoints)}")
            if self.waypoint_index >= len(self.waypoints):
                self._arrive_onsite(now)
            return

        self._move(
            decision.vx,
            decision.vy,
            decision.vyaw,
            f"navigate waypoint={self.waypoint_index + 1}/{len(self.waypoints)} "
            f"distance={decision.distance:.3f}",
        )

    def _tick_pursue(self, now: float) -> None:
        if self.pursuit_target_xy is None:
            self._tick_navigate(now)
            return

        # Check if we are close enough to detain the target
        tx, ty = self.pursuit_target_xy
        distance = math.hypot(tx - self.pose.x, ty - self.pose.y)
        if distance <= DETAIN_DISTANCE:
            self._stop("detain_distance")
            mission = self.current_mission
            # Write DETAINED status (no real vision — inconclusive)
            append_status(
                self.status_path,
                "DETAINED",
                name=mission.target if mission else "",
                verified=False,
                reason="inconclusive — no camera/perception source",
            )
            self._log(f"DETAINED '{mission.target if mission else '?'}' "
                      f"(distance={distance:.2f}m)")
            self._enter_state("guard", now)
            return

        # Replan route toward latest target position
        if now - self.last_pursuit_replan >= PURSUIT_REPLAN_PERIOD:
            self.last_pursuit_replan = now
            start = (self.pose.x, self.pose.y)
            self.waypoints = safe_route(start, self.pursuit_target_xy)
            self.waypoint_index = 0
            self._log(
                f"REPLAN pursuit target=({self.pursuit_target_xy[0]:.3f},"
                f"{self.pursuit_target_xy[1]:.3f}) route_len={len(self.waypoints)} "
                f"waypoints={self._waypoint_summary()}"
            )

        self._tick_navigate(now)

    def _tick_onsite(self, now: float) -> None:
        elapsed = now - self.state_entered_at
        mission = self.current_mission
        if mission is None:
            self._transition_return(now)
            return

        if mission.kind == "investigate":
            if elapsed >= INVESTIGATE_TIME:
                append_status(
                    self.status_path,
                    "REPORT",
                    zone=mission.zone or "",
                    reason=mission.reason,
                )
                self._log("REPORT sent")
                self._transition_return(now)
        elif mission.kind == "assist":
            if elapsed >= ASSIST_TIME:
                append_status(
                    self.status_path,
                    "ASSIST_DONE",
                    name=mission.target or "",
                    reason=mission.reason,
                )
                self._log("ASSIST_DONE sent")
                self._transition_return(now)
        elif mission.kind == "detain":
            # No real vision: always inconclusive
            append_status(
                self.status_path,
                "DETAINED",
                name=mission.target or "",
                verified=False,
                reason="inconclusive — no camera/perception source",
            )
            self._log("DETAINED sent (inconclusive)")
            self._enter_state("guard", now)

    def _tick_guard(self, now: float) -> None:
        if now - self.state_entered_at >= GUARD_TIME:
            self._transition_return(now)

    def _tick_return(self, now: float) -> None:
        if self.waypoint_index >= len(self.waypoints):
            self._stop("return_complete")
            self.current_mission = None
            self._enter_state("idle", now)
            self._log("RETURNED to dock")
            return

        wp = self.waypoints[self.waypoint_index]
        if self._use_navigation_manager(wp, now):
            if self.waypoint_index >= len(self.waypoints):
                self._stop("return_complete")
                self.current_mission = None
                self._enter_state("idle", now)
                self._log("RETURNED to dock")
            return

        decision = command_towards(
            self.pose,
            wp.xy,
            arrive_distance=wp.arrive_distance or DEFAULT_ARRIVE_DISTANCE,
            forward_speed=wp.forward_speed or FORWARD_SPEED,
        )

        if decision.arrived:
            self._stop("return_waypoint_arrived")
            self.waypoint_index += 1
            if self.waypoint_index >= len(self.waypoints):
                self._stop("return_complete")
                self.current_mission = None
                self._enter_state("idle", now)
                self._log("RETURNED to dock")
            return

        self._move(
            decision.vx,
            decision.vy,
            decision.vyaw,
            f"return waypoint={self.waypoint_index + 1}/{len(self.waypoints)} "
            f"distance={decision.distance:.3f}",
        )

    # ── Helpers ──────────────────────────────────────────────────────

    def _arrive_onsite(self, now: float) -> None:
        self._stop("arrive_onsite")
        self._enter_state("onsite", now)
        self._log(f"ONSITE state={self.state}")

    def _transition_return(self, now: float) -> None:
        self._stop("transition_return")
        start = (self.pose.x, self.pose.y)
        self.waypoints = safe_route(start, DOCK)
        self.waypoint_index = 0
        self._enter_state("return", now)
        self._log(f"RETURNING to dock route_len={len(self.waypoints)}")

    def _enter_state(self, state: str, now: float) -> None:
        old_state = self.state
        self.state = state
        self.state_entered_at = now
        if old_state != state:
            self._log(f"STATE {old_state} -> {state}")

    def _use_navigation_manager(self, waypoint: Waypoint, now: float) -> bool:
        if self.navigation_manager is None:
            return False

        target = waypoint.xy
        status = self.navigation_manager.go_to(
            target,
            now,
            arrive_distance=waypoint.arrive_distance,
            forward_speed=waypoint.forward_speed,
        )
        if status != self.last_logged_nav_status:
            self.last_logged_nav_status = status
            self._log(
                f"NAVIGATION status={status.value} "
                f"target=({target[0]:.3f},{target[1]:.3f})"
            )
        if status == NavigationStatus.RUNNING:
            return True
        if status == NavigationStatus.ARRIVED:
            self.waypoint_index += 1
            self._log(f"WAYPOINT {self.waypoint_index}/{len(self.waypoints)}")
            if self.state == "navigate" and self.waypoint_index >= len(self.waypoints):
                self._arrive_onsite(now)
            return True

        self._stop(f"navigation_{status.value.lower()}")
        if status == NavigationStatus.FAILED:
            self.handle_error("navigation_failed")
        elif status == NavigationStatus.BLOCKED:
            append_status(
                self.status_path,
                "ROBOT_STATUS",
                state="blocked",
                error=f"navigation_{status.value.lower()}",
            )
            self._log(f"NAVIGATION {status.value}")
        return True

    def _poll_missions(self) -> None:
        if self.missions_path is None:
            return
        missions, offset = read_new_missions(
            self.missions_path, self.mission_file_offset
        )
        old_offset = self.mission_file_offset
        self.mission_file_offset = offset
        if missions:
            self._log(
                f"POLL missions count={len(missions)} "
                f"offset={old_offset}->{offset}"
            )
        for m in missions:
            self.enqueue(m)

        # Poll live TARGET_POS updates for active pursuit
        self._poll_target_positions()

    def _poll_target_positions(self) -> None:
        if self.target_pos_path is None:
            return
        events, offset = read_new_target_positions(
            self.target_pos_path, self.target_pos_file_offset
        )
        old_offset = self.target_pos_file_offset
        self.target_pos_file_offset = offset
        if not events:
            return
        self._log(
            f"POLL target_pos count={len(events)} offset={old_offset}->{offset}"
        )
        # Only apply if we have an active detain mission
        mission = self.current_mission
        if mission is None or mission.kind != "detain":
            self._log("TARGET_POS ignored reason=no_active_detain_mission")
            return
        # Use the latest matching target position
        for evt in reversed(events):
            if evt["target"] == mission.target or mission.target is None:
                self.pursuit_target_xy = (evt["x"], evt["y"])
                self._log(
                    f"TARGET_POS applied target={evt['target']} "
                    f"xy=({evt['x']:.3f},{evt['y']:.3f})"
                )
                break

    def _log(self, msg: str) -> None:
        line = f"[booster_patrol] state={self.state} {msg}"
        if self.logger is not None:
            try:
                self.logger(line)
            except Exception:
                print(line, flush=True)
        else:
            print(line, flush=True)

    def _mission_summary(self, mission: Mission) -> str:
        return (
            f"kind={mission.kind} target={mission.target} zone={mission.zone} "
            f"xy=({mission.x:.3f},{mission.y:.3f}) reason={mission.reason!r}"
        )

    def _waypoint_summary(self) -> str:
        return "[" + ", ".join(
            f"({wp.xy[0]:.2f},{wp.xy[1]:.2f})" for wp in self.waypoints
        ) + "]"

    def _move(self, vx: float, vy: float, vyaw: float, reason: str) -> bool | None:
        command = (round(vx, 3), round(vy, 3), round(vyaw, 3))
        if command != self.last_logged_move:
            self.last_logged_move = command
            self._log(
                f"MOVE reason={reason} vx={vx:.3f} vy={vy:.3f} vyaw={vyaw:.3f}"
            )
        result = self.rpc.move(vx, vy, vyaw)
        if result is False:
            self._log(f"MOVE failed reason={reason}")
        return result

    def _stop(self, reason: str) -> bool | None:
        if reason != self.last_logged_stop_reason:
            self.last_logged_stop_reason = reason
            self._log(f"STOP reason={reason}")
        self.last_logged_move = (0.0, 0.0, 0.0)
        result = self.rpc.stop()
        if result is False:
            self._log(f"STOP failed reason={reason}")
        return result

    # ── Error handling ───────────────────────────────────────────────

    def handle_error(self, error: str) -> None:
        """Handle an RPC or navigation error."""
        self._stop("handle_error")
        self._enter_state("error", time.time())
        append_status(
            self.status_path,
            "ROBOT_STATUS",
            state="error",
            error=error,
        )
        self._log(f"ERROR: {error}")


# ── ROS node wrapper (thin) ─────────────────────────────────────────

def main(argv=None):
    """ROS 2 entry point for the patrol node."""
    import rclpy
    from rclpy.executors import ExternalShutdownException
    from nav_msgs.msg import OccupancyGrid, Odometry
    from sensor_msgs.msg import PointCloud2

    from .navigation_manager import NavigationManager
    from .rpc_commands import (
        MODE_PREPARE,
        MODE_WALKING,
        make_change_mode_request,
        make_move_request,
    )

    rclpy.init(args=argv or [])
    node = rclpy.create_node("booster_patrol_node")

    def log_node(level: str, message: str) -> None:
        try:
            getattr(node.get_logger(), level)(message)
        except Exception:
            print(f"[booster_patrol_node] {level.upper()} {message}", flush=True)

    def log_info(message: str) -> None:
        log_node("info", message)

    def log_warn(message: str) -> None:
        log_node("warn", message)

    def log_error(message: str) -> None:
        log_node("error", message)

    # Lazily load ROS service client
    from booster_interface.srv import RpcService

    rpc_node = rclpy.create_node("booster_patrol_rpc_client")
    client = rpc_node.create_client(RpcService, "/booster_rpc_service")
    log_info("Waiting for /booster_rpc_service...")
    client.wait_for_service()
    log_info("/booster_rpc_service is ready.")

    # Thin RPC adapter
    class RpcAdapter:
        def __init__(self):
            self._last_move_command: tuple[float, float, float] | None = None
            self._last_move_sent_at = -1e9
            self._move_keepalive_period = self._read_keepalive_period()

        def _read_keepalive_period(self) -> float:
            raw_value = os.environ.get("BOOSTER_RPC_KEEPALIVE_PERIOD", "0.5")
            try:
                value = float(raw_value)
            except ValueError:
                log_warn(
                    f"Ignoring invalid BOOSTER_RPC_KEEPALIVE_PERIOD={raw_value!r}; "
                    "using 0.500"
                )
                return 0.5
            return max(0.1, value)

        def _call(self, api_id, body):
            from booster_interface.msg import BoosterApiReqMsg

            started_at = time.time()
            if not rclpy.ok():
                log_warn(f"RPC skipped api_id={api_id} reason=rclpy_shutdown")
                return False

            log_info(f"RPC request api_id={api_id} body={body}")
            req = RpcService.Request()
            req.msg = BoosterApiReqMsg()
            req.msg.api_id = int(api_id)
            req.msg.body = body
            try:
                future = client.call_async(req)
                rclpy.spin_until_future_complete(rpc_node, future, timeout_sec=5.0)
                result = future.result()
            except Exception as exc:
                log_error(
                    f"RPC exception api_id={api_id} "
                    f"elapsed={time.time() - started_at:.3f}s error={exc}"
                )
                return False
            if result is None:
                log_error(
                    f"RPC failed api_id={api_id} elapsed={time.time() - started_at:.3f}s"
                )
                return False
            elapsed = time.time() - started_at
            message = (
                f"RPC response api_id={api_id} status={result.msg.status} "
                f"body={result.msg.body!r} elapsed={elapsed:.3f}s"
            )
            if result.msg.status == 0:
                log_info(message)
            else:
                log_warn(message)
            return result.msg.status == 0

        def move(self, vx, vy, vyaw):
            command = (round(float(vx), 3), round(float(vy), 3), round(float(vyaw), 3))
            now_s = time.time()
            if (
                self._last_move_command == command
                and now_s - self._last_move_sent_at < self._move_keepalive_period
            ):
                return True
            req = make_move_request(vx, vy, vyaw)
            result = self._call(req.api_id, req.body)
            if result:
                self._last_move_command = command
                self._last_move_sent_at = now_s
            return result

        def stop(self):
            return self.move(0.0, 0.0, 0.0)

    rpc = RpcAdapter()

    def env_float(name: str, default: float) -> float:
        raw_value = os.environ.get(name)
        if raw_value is None or raw_value == "":
            return default
        try:
            value = float(raw_value)
        except ValueError:
            log_warn(f"Ignoring invalid {name}={raw_value!r}; using {default:.3f}")
            return default
        if value < 0.0:
            log_warn(f"Ignoring negative {name}={raw_value!r}; using {default:.3f}")
            return default
        return value

    patrol_forward_speed = env_float("BOOSTER_PATROL_FORWARD_SPEED", FORWARD_SPEED)
    patrol_max_yaw_rate = env_float("BOOSTER_PATROL_MAX_YAW_RATE", MAX_YAW_RATE)
    patrol_heading_tolerance = env_float(
        "BOOSTER_PATROL_HEADING_TOLERANCE", HEADING_TOLERANCE
    )
    patrol_max_walk_yaw_rate = env_float(
        "BOOSTER_PATROL_MAX_WALK_YAW_RATE", MAX_WALK_YAW_RATE
    )
    patrol_tick_period = max(
        0.05, env_float("BOOSTER_PATROL_TICK_PERIOD", PATROL_TICK_PERIOD)
    )
    log_info(
        "Patrol motion limits "
        f"forward_speed={patrol_forward_speed:.3f} "
        f"max_yaw_rate={patrol_max_yaw_rate:.3f} "
        f"max_walk_yaw_rate={patrol_max_walk_yaw_rate:.3f} "
        f"heading_tolerance={patrol_heading_tolerance:.3f} "
        f"tick_period={patrol_tick_period:.3f} "
        f"rpc_keepalive={rpc._move_keepalive_period:.3f}"
    )
    navigation_manager = NavigationManager(
        rpc=rpc,
        require_fresh_lidar=False,
        logger=log_info,
        forward_speed=patrol_forward_speed,
        max_yaw_rate=patrol_max_yaw_rate,
        heading_tolerance=patrol_heading_tolerance,
        max_walk_yaw_rate=patrol_max_walk_yaw_rate,
    )

    # Prepare walking mode
    log_info("Preparing walking mode...")
    prep = make_change_mode_request(MODE_PREPARE)
    rpc._call(prep.api_id, prep.body)
    import time as _time
    _time.sleep(3.5)
    walk = make_change_mode_request(MODE_WALKING)
    rpc._call(walk.api_id, walk.body)
    _time.sleep(1.0)
    log_info("Walking mode ready.")

    log_dir = Path(os.environ.get("PATROL_LOG_DIR", "/workspace/project/.logs"))
    machine = PatrolStateMachine(
        rpc=rpc,
        status_path=log_dir / "booster_status.jsonl",
        missions_path=log_dir / "booster_missions.jsonl",
        target_pos_path=log_dir / "booster_target_pos.jsonl",
        navigation_manager=navigation_manager,
        logger=log_info,
    )
    internal_map_pub = node.create_publisher(
        OccupancyGrid,
        "/booster_t1/internal_map",
        10,
    )
    internal_map_path = log_dir / "booster_internal_map.json"
    last_internal_map_log_at = -1e9

    def publish_internal_map():
        nonlocal last_internal_map_log_at
        resolution = navigation_manager.block_map.block_size
        origin_x = -10.5
        origin_y = -6.5
        width = int(round(21.0 / resolution))
        height = int(round(13.0 / resolution))
        centers = navigation_manager.block_map.occupied_centers()

        msg = OccupancyGrid()
        msg.header.stamp = node.get_clock().now().to_msg()
        msg.header.frame_id = "map"
        msg.info.resolution = float(resolution)
        msg.info.width = width
        msg.info.height = height
        msg.info.origin.position.x = origin_x
        msg.info.origin.position.y = origin_y
        msg.info.origin.position.z = 0.0
        data = [0] * (width * height)
        for x, y in centers:
            ix = int(math.floor((x - origin_x) / resolution))
            iy = int(math.floor((y - origin_y) / resolution))
            if 0 <= ix < width and 0 <= iy < height:
                data[iy * width + ix] = 100
        msg.data = data
        internal_map_pub.publish(msg)

        payload = {
            "frame_id": "map",
            "resolution": resolution,
            "origin": {"x": origin_x, "y": origin_y},
            "width": width,
            "height": height,
            "occupied_count": len(centers),
            "occupied_centers": centers,
        }
        tmp_path = internal_map_path.with_suffix(internal_map_path.suffix + ".tmp")
        try:
            tmp_path.write_text(
                json.dumps(payload, separators=(",", ":")),
                encoding="utf-8",
            )
            tmp_path.replace(internal_map_path)
        except OSError as exc:
            log_warn(f"internal_map_write_failed path={internal_map_path} error={exc}")

        now_s = time.time()
        if now_s - last_internal_map_log_at >= 1.0:
            last_internal_map_log_at = now_s
            log_info(
                f"INTERNAL_MAP published occupied_cells={len(centers)} "
                f"topic=/booster_t1/internal_map"
            )

    # Odometry callback
    import math
    last_odom_log_at = -1e9

    def odom_callback(msg: Odometry):
        nonlocal last_odom_log_at
        pos = msg.pose.pose.position
        q = msg.pose.pose.orientation
        # Convert quaternion to yaw
        siny = 2.0 * (q.w * q.z + q.x * q.y)
        cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        yaw = math.atan2(siny, cosy)
        now_s = time.time()
        machine.update_pose(Pose2D(pos.x, pos.y, yaw))
        if now_s - last_odom_log_at >= 1.0:
            last_odom_log_at = now_s
            log_info(
                f"ODOM received x={pos.x:.3f} y={pos.y:.3f} yaw={yaw:.3f}"
            )

    node.create_subscription(Odometry, "/booster_t1/odom", odom_callback, 10)

    try:
        import sensor_msgs_py.point_cloud2 as point_cloud2
    except ImportError:
        point_cloud2 = None
        log_warn(
            "sensor_msgs_py is unavailable; /booster_t1/points will not feed navigation"
        )

    last_points_log_at = -1e9

    def points_callback(msg: PointCloud2):
        nonlocal last_points_log_at
        if point_cloud2 is None:
            return
        now_s = time.time()
        points = [
            (float(x), float(y), float(z))
            for x, y, z in point_cloud2.read_points(
                msg, field_names=("x", "y", "z"), skip_nans=True
            )
        ]
        navigation_manager.update_lidar(points, now_s)
        if now_s - last_points_log_at >= 1.0:
            last_points_log_at = now_s
            log_info(f"POINTS received count={len(points)}")

    node.create_subscription(PointCloud2, "/booster_t1/points", points_callback, 10)

    # Timer for state machine ticks.
    def tick_callback():
        try:
            machine.tick(time.time())
        except Exception as exc:
            log_error(f"Patrol tick error: {exc}")
            try:
                machine.handle_error(str(exc))
            except Exception as handle_exc:
                log_error(f"Patrol error handler failed: {handle_exc}")

    node.create_timer(patrol_tick_period, tick_callback)
    node.create_timer(1.0, publish_internal_map)

    log_info("Booster patrol node started.")
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if rclpy.ok():
            try:
                rpc.stop()
            except Exception as exc:
                print(f"[booster_patrol_node] WARN stop during shutdown failed: {exc}", flush=True)
        for shutdown_node in (node, rpc_node):
            try:
                shutdown_node.destroy_node()
            except Exception as exc:
                print(f"[booster_patrol_node] WARN destroy_node failed: {exc}", flush=True)
        if rclpy.ok():
            try:
                rclpy.shutdown()
            except Exception as exc:
                print(f"[booster_patrol_node] WARN rclpy shutdown failed: {exc}", flush=True)
