"""Safe waypoint navigation manager for Booster patrol missions."""
from __future__ import annotations

from collections.abc import Callable
from enum import Enum

from .block_map import BlockMap
from .booster_lidar_adapter import LidarSensorAdapter
from .booster_localization_node import BoosterLocalization
from .obstacle_avoidance import ObstacleAvoidance
from .patrol_controller import (
    DEFAULT_ARRIVE_DISTANCE,
    FORWARD_SPEED,
    HEADING_TOLERANCE,
    MAX_WALK_YAW_RATE,
    MAX_YAW_RATE,
    command_towards,
)
from .patrol_types import Pose2D
from .route_corrector import RouteCorrector


class NavigationStatus(str, Enum):
    RUNNING = "RUNNING"
    ARRIVED = "ARRIVED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    UNSAFE = "UNSAFE"


class NavigationManager:
    """Connect localization, map, obstacle checks, route correction, and RPC."""

    def __init__(
        self,
        rpc,
        block_map: BlockMap | None = None,
        lidar_timeout: float = 0.5,
        require_fresh_lidar: bool = True,
        logger: Callable[[str], None] | None = None,
        forward_speed: float = FORWARD_SPEED,
        max_yaw_rate: float = MAX_YAW_RATE,
        heading_tolerance: float = HEADING_TOLERANCE,
        max_walk_yaw_rate: float = MAX_WALK_YAW_RATE,
        arrive_distance: float = DEFAULT_ARRIVE_DISTANCE,
    ):
        self.rpc = rpc
        self.block_map = block_map or BlockMap()
        self.localization = BoosterLocalization(lidar_timeout=lidar_timeout)
        self.lidar = LidarSensorAdapter(timeout=lidar_timeout)
        self.avoidance = ObstacleAvoidance(self.block_map)
        self.route_corrector = RouteCorrector(self.block_map)
        self.require_fresh_lidar = require_fresh_lidar
        self.logger = logger
        self.forward_speed = forward_speed
        self.max_yaw_rate = max_yaw_rate
        self.heading_tolerance = heading_tolerance
        self.max_walk_yaw_rate = max_walk_yaw_rate
        self.arrive_distance = arrive_distance
        self._last_pose_log_at = -1e9
        self._last_lidar_log_at = -1e9
        self._last_go_to_log_at = -1e9
        self._last_go_to_target: tuple[float, float] | None = None
        self._log(
            "config "
            f"require_fresh_lidar={self.require_fresh_lidar} "
            f"forward_speed={self.forward_speed:.3f} "
            f"max_yaw_rate={self.max_yaw_rate:.3f} "
            f"max_walk_yaw_rate={self.max_walk_yaw_rate:.3f} "
            f"heading_tolerance={self.heading_tolerance:.3f} "
            f"arrive_distance={self.arrive_distance:.3f}"
        )

    def update_pose(self, pose: Pose2D, now: float) -> None:
        self.localization.update_odometry(pose, now)
        if now - self._last_pose_log_at >= 1.0:
            self._last_pose_log_at = now
            self._log(
                f"pose_update x={pose.x:.3f} y={pose.y:.3f} theta={pose.theta:.3f}"
            )

    def update_lidar(self, points: list[tuple[float, float, float]], now: float) -> None:
        clean_points = self.lidar.sanitize_points(points)
        self.lidar.mark_update(now)
        estimate = self.localization.estimate(now)
        if estimate.pose is not None:
            self.block_map.update_from_points(estimate.pose, clean_points, now)
        self.localization.update_lidar(clean_points, now)
        if now - self._last_lidar_log_at >= 1.0:
            self._last_lidar_log_at = now
            self._log(
                f"lidar_update raw={len(points)} clean={len(clean_points)} "
                f"map_cells={len(self.block_map.occupied_centers())}"
            )

    def go_to(
        self,
        target: tuple[float, float],
        now: float,
        arrive_distance: float | None = None,
        forward_speed: float | None = None,
        ignore_route_blocks: bool = False,
    ) -> NavigationStatus:
        estimate = self.localization.estimate(now)
        log_decision = (
            now - self._last_go_to_log_at >= 1.0
            or self._last_go_to_target != target
        )
        if log_decision:
            self._last_go_to_log_at = now
            self._last_go_to_target = target
            self._log(
                f"go_to target=({target[0]:.3f},{target[1]:.3f}) "
                f"confident={estimate.confident} reason={estimate.reason}"
            )
        if estimate.pose is None:
            self._stop("odometry_missing")
            self._log("go_to stop reason=odometry_missing")
            return NavigationStatus.UNSAFE
        if (
            not estimate.confident
            and (self.require_fresh_lidar or estimate.reason != "lidar_stale")
        ):
            self._stop(estimate.reason)
            self._log(f"go_to stop reason={estimate.reason}")
            return NavigationStatus.UNSAFE

        pose = estimate.pose
        selected_arrive_distance = (
            self.arrive_distance if arrive_distance is None else arrive_distance
        )
        selected_forward_speed = (
            self.forward_speed if forward_speed is None else forward_speed
        )

        def make_decision(point: tuple[float, float]):
            return command_towards(
                pose,
                point,
                arrive_distance=selected_arrive_distance,
                forward_speed=selected_forward_speed,
                max_yaw_rate=self.max_yaw_rate,
                heading_tolerance=self.heading_tolerance,
                max_walk_yaw_rate=self.max_walk_yaw_rate,
            )

        decision = make_decision(target)
        if decision.arrived:
            if self._stop("arrived") is False:
                return NavigationStatus.FAILED
            self._log(f"go_to arrived distance={decision.distance:.3f}")
            return NavigationStatus.ARRIVED

        safety = self.avoidance.evaluate_motion(pose, decision.vx, decision.vy)
        if not safety.safe:
            self._stop(safety.reason)
            self._log(f"go_to stop reason={safety.reason}")
            return NavigationStatus.UNSAFE

        if (
            not ignore_route_blocks
            and not self.block_map.route_segment_safe((pose.x, pose.y), target)
        ):
            self._log(
                f"go_to route_blocked start=({pose.x:.3f},{pose.y:.3f}) "
                f"target=({target[0]:.3f},{target[1]:.3f})"
            )
            corrected = self.route_corrector.correct_route(pose, [(pose.x, pose.y), target])
            if corrected is None:
                self._stop("route_blocked")
                self._log("go_to blocked correction_failed")
                return NavigationStatus.BLOCKED
            target = corrected[1]
            self._log(f"go_to corrected_target=({target[0]:.3f},{target[1]:.3f})")
            decision = make_decision(target)
            if decision.arrived:
                if self._stop("arrived") is False:
                    return NavigationStatus.FAILED
                self._log(f"go_to arrived distance={decision.distance:.3f}")
                return NavigationStatus.ARRIVED
            safety = self.avoidance.evaluate_motion(pose, decision.vx, decision.vy)
            if not safety.safe:
                self._stop(safety.reason)
                self._log(f"go_to stop reason={safety.reason}")
                return NavigationStatus.UNSAFE

        if self.rpc.move(decision.vx, decision.vy, decision.vyaw) is False:
            self._log(
                f"go_to move_failed vx={decision.vx:.3f} vy={decision.vy:.3f} "
                f"vyaw={decision.vyaw:.3f}"
            )
            return NavigationStatus.FAILED
        if log_decision:
            self._log(
                f"go_to move vx={decision.vx:.3f} vy={decision.vy:.3f} "
                f"vyaw={decision.vyaw:.3f} distance={decision.distance:.3f}"
            )
        return NavigationStatus.RUNNING

    def _log(self, message: str) -> None:
        if self.logger is not None:
            try:
                self.logger(f"[navigation_manager] {message}")
            except Exception:
                print(f"[navigation_manager] {message}", flush=True)

    def _stop(self, reason: str) -> bool | None:
        result = self.rpc.stop()
        if result is False:
            self._log(f"stop_failed reason={reason}")
        return result
