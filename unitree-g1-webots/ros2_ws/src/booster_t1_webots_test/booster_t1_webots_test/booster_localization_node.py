"""Odometry-primary localization status for the Booster patrol node."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass

from .patrol_types import Pose2D


@dataclass(frozen=True)
class LocalizationEstimate:
    pose: Pose2D | None
    confident: bool
    confidence: float
    timestamp: float
    reason: str = "ok"


class BoosterLocalization:
    """Conservative localization fusion shell.

    Odometry remains the primary pose source. LiDAR freshness gates confidence
    and leaves room for scan-matching correction without destabilizing patrol.
    """

    def __init__(self, lidar_timeout: float = 0.5, odom_timeout: float = 2.0):
        self.lidar_timeout = lidar_timeout
        self.odom_timeout = odom_timeout
        self._odom_pose: Pose2D | None = None
        self._odom_time: float | None = None
        self._lidar_time: float | None = None
        self._lidar_points: list[tuple[float, float, float]] = []

    def update_odometry(self, pose: Pose2D, now: float) -> None:
        self._odom_pose = pose
        self._odom_time = now

    def update_lidar(self, points: list[tuple[float, float, float]], now: float) -> None:
        self._lidar_points = points
        self._lidar_time = now

    def estimate(self, now: float) -> LocalizationEstimate:
        if self._odom_pose is None or self._odom_time is None:
            return LocalizationEstimate(None, False, 0.0, now, "odometry_missing")
        if now - self._odom_time > self.odom_timeout:
            return LocalizationEstimate(self._odom_pose, False, 0.0, now, "odometry_stale")
        if self._lidar_time is None or now - self._lidar_time > self.lidar_timeout:
            return LocalizationEstimate(self._odom_pose, False, 0.25, now, "lidar_stale")
        return LocalizationEstimate(self._odom_pose, True, 0.9, now, "ok")


def main(argv=None):
    import rclpy
    from geometry_msgs.msg import Pose2D as Pose2DMsg
    from nav_msgs.msg import Odometry
    from sensor_msgs.msg import PointCloud2
    from std_msgs.msg import String

    rclpy.init(args=argv or [])
    node = rclpy.create_node("booster_localization_node")
    localization = BoosterLocalization()
    pose_pub = node.create_publisher(Pose2DMsg, "/booster_t1/local_pose", 10)
    status_pub = node.create_publisher(String, "/booster_t1/localization_status", 10)

    try:
        import sensor_msgs_py.point_cloud2 as point_cloud2
    except ImportError:
        point_cloud2 = None
        node.get_logger().warn("sensor_msgs_py is unavailable; LiDAR freshness will stay low")

    def publish_status():
        estimate = localization.estimate(node.get_clock().now().nanoseconds / 1e9)
        status_msg = String()
        status_msg.data = json.dumps(
            {
                "confident": estimate.confident,
                "confidence": estimate.confidence,
                "reason": estimate.reason,
                "timestamp": estimate.timestamp,
            },
            sort_keys=True,
        )
        status_pub.publish(status_msg)
        if estimate.pose is not None:
            pose_msg = Pose2DMsg()
            pose_msg.x = estimate.pose.x
            pose_msg.y = estimate.pose.y
            pose_msg.theta = estimate.pose.theta
            pose_pub.publish(pose_msg)

    def odom_callback(msg: Odometry):
        pos = msg.pose.pose.position
        q = msg.pose.pose.orientation
        siny = 2.0 * (q.w * q.z + q.x * q.y)
        cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        yaw = math.atan2(siny, cosy)
        localization.update_odometry(
            Pose2D(pos.x, pos.y, yaw),
            node.get_clock().now().nanoseconds / 1e9,
        )

    def points_callback(msg: PointCloud2):
        if point_cloud2 is None:
            return
        points = [
            (float(x), float(y), float(z))
            for x, y, z in point_cloud2.read_points(
                msg, field_names=("x", "y", "z"), skip_nans=True
            )
        ]
        localization.update_lidar(points, node.get_clock().now().nanoseconds / 1e9)

    node.create_subscription(Odometry, "/booster_t1/odom", odom_callback, 10)
    node.create_subscription(PointCloud2, "/booster_t1/points", points_callback, 10)
    node.create_timer(0.2, publish_status)

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
