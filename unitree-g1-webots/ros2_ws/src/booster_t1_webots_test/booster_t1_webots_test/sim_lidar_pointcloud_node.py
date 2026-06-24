"""Publish a simulated Booster point cloud from the Webots pose file."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import PointCloud2
from std_msgs.msg import Header

try:
    import sensor_msgs_py.point_cloud2 as point_cloud2
except ImportError as exc:  # pragma: no cover - ROS runtime dependency.
    point_cloud2 = None
    POINT_CLOUD_IMPORT_ERROR = exc
else:
    POINT_CLOUD_IMPORT_ERROR = None

from .office_lidar_sim import points_to_world, raycast_point_cloud
from .patrol_types import Pose2D
from .pose_file import read_pose_file


DEFAULT_POSE_FILE = "/workspace/project/.logs/booster_pose.json"
DEFAULT_POINTCLOUD_FILE = "/workspace/project/.logs/booster_pointcloud.json"


class SimLidarPointCloudNode(Node):
    """Raycast the static office map and publish `/booster_t1/points`."""

    def __init__(
        self,
        pose_file: str = DEFAULT_POSE_FILE,
        pointcloud_file: str = DEFAULT_POINTCLOUD_FILE,
        publish_period: float = 0.2,
        max_range: float = 8.0,
        rays: int = 181,
    ):
        super().__init__("sim_lidar_pointcloud_node")
        if point_cloud2 is None:
            raise RuntimeError(
                "sensor_msgs_py.point_cloud2 is unavailable"
            ) from POINT_CLOUD_IMPORT_ERROR
        self.pose_file = pose_file
        self.pointcloud_file = pointcloud_file
        self.max_range = max_range
        self.rays = rays
        self.publisher = self.create_publisher(PointCloud2, "/booster_t1/points", 10)
        self._last_missing_log_at = -1e9
        self._last_publish_log_at = -1e9
        self.create_timer(publish_period, self.publish_scan)
        self.get_logger().info(
            "Publishing simulated point cloud topic=/booster_t1/points "
            f"pose_file={self.pose_file} diagnostic_file={self.pointcloud_file} "
            f"rays={self.rays} max_range={self.max_range:.2f}"
        )

    def publish_scan(self) -> None:
        reading = read_pose_file(self.pose_file)
        now = time.time()
        if reading is None:
            if now - self._last_missing_log_at >= 2.0:
                self._last_missing_log_at = now
                self.get_logger().warn(f"pose file unavailable: {self.pose_file}")
            return

        pose = Pose2D(reading.x, reading.y, reading.theta)
        points = raycast_point_cloud(pose, rays=self.rays, max_range=self.max_range)
        header = Header()
        header.stamp = self.get_clock().now().to_msg()
        header.frame_id = "base_link"
        self.publisher.publish(point_cloud2.create_cloud_xyz32(header, points))
        self._write_diagnostics(reading.sim_time, pose, points)

        if now - self._last_publish_log_at >= 1.0:
            self._last_publish_log_at = now
            self.get_logger().info(
                f"POINTCLOUD published count={len(points)} "
                f"pose=({pose.x:.3f},{pose.y:.3f},{pose.theta:.3f})"
            )

    def _write_diagnostics(
        self,
        sim_time: float,
        pose: Pose2D,
        points: list[tuple[float, float, float]],
    ) -> None:
        path = Path(self.pointcloud_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        world_points = points_to_world(pose, points)
        payload = {
            "time": sim_time,
            "frame_id": "base_link",
            "pose": {"x": pose.x, "y": pose.y, "theta": pose.theta},
            "count": len(points),
            "robot_frame_points": points,
            "world_points": world_points,
        }
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(payload, separators=(",", ":")),
            encoding="utf-8",
        )
        tmp_path.replace(path)


def _env_float(name: str, default: float) -> float:
    raw_value = os.environ.get(name)
    if raw_value is None or raw_value == "":
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None or raw_value == "":
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def main(argv=None):
    rclpy.init(args=argv or [])
    node = SimLidarPointCloudNode(
        pose_file=os.environ.get("BOOSTER_POSE_FILE", DEFAULT_POSE_FILE),
        pointcloud_file=os.environ.get(
            "BOOSTER_POINTCLOUD_FILE", DEFAULT_POINTCLOUD_FILE
        ),
        publish_period=max(0.05, _env_float("BOOSTER_POINTCLOUD_PERIOD", 0.2)),
        max_range=max(0.5, _env_float("BOOSTER_POINTCLOUD_MAX_RANGE", 8.0)),
        rays=max(9, _env_int("BOOSTER_POINTCLOUD_RAYS", 181)),
    )
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
