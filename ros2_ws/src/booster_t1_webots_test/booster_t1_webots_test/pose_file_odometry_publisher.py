from __future__ import annotations

import math
import os
from pathlib import Path

import rclpy
from geometry_msgs.msg import Quaternion
from nav_msgs.msg import Odometry
from rclpy.node import Node
from std_msgs.msg import String

from booster_interface.msg import Odometer

from .odometry_helpers import OdometerReading, compare_odometry
from .pose_file import read_pose_file


DEFAULT_POSE_FILE = "/workspace/project/.logs/booster_pose.json"


class PoseFileOdometryPublisher(Node):
    def __init__(self, pose_file=DEFAULT_POSE_FILE, stale_timeout: float = 2.0):
        super().__init__("pose_file_odometry_publisher")
        self.pose_file = pose_file
        self.stale_timeout = float(stale_timeout)
        self.vendor_odometer = None
        self._nav_odom_publishers = [
            self.create_publisher(Odometry, "/odom", 10),
            self.create_publisher(Odometry, "/booster_t1/odom", 10),
        ]
        self._booster_odom_publisher = self.create_publisher(
            Odometer,
            "/booster_t1/odometer",
            10,
        )
        self._diagnostics_publisher = self.create_publisher(
            String,
            "/booster_t1/odometry_diagnostics",
            10,
        )
        self._vendor_subscriptions = [
            self.create_subscription(
                Odometer,
                "/odometer_state",
                self._update_vendor_odometer,
                10,
            ),
            self.create_subscription(
                Odometer,
                "/booster_t1/odometer_state",
                self._update_vendor_odometer,
                10,
            ),
        ]
        self._last_pose_log_time = -1e9
        self._last_stale_log_time = -1e9
        self.create_timer(0.1, self.publish_latest_pose)
        self.get_logger().info(
            f"Publishing corrected odometry from {self.pose_file} "
            f"stale_timeout={self.stale_timeout:.1f}s"
        )

    def _update_vendor_odometer(self, msg):
        self.vendor_odometer = OdometerReading(
            x=float(msg.x),
            y=float(msg.y),
            theta=float(msg.theta),
        )
        self.get_logger().info(
            "vendor_odometer_update "
            f"x={self.vendor_odometer.x:.3f} y={self.vendor_odometer.y:.3f} "
            f"theta={self.vendor_odometer.theta:.3f}"
        )

    def _to_booster_odometer_msg(self, reading):
        msg = Odometer()
        msg.x = float(reading.x)
        msg.y = float(reading.y)
        msg.theta = float(reading.theta)
        return msg

    def _to_nav_odometry_msg(self, reading):
        msg = Odometry()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "map"
        msg.child_frame_id = "base_link"
        msg.pose.pose.position.x = float(reading.x)
        msg.pose.pose.position.y = float(reading.y)
        msg.pose.pose.position.z = 0.0
        half_yaw = float(reading.theta) / 2.0
        msg.pose.pose.orientation = Quaternion(
            x=0.0,
            y=0.0,
            z=math.sin(half_yaw),
            w=math.cos(half_yaw),
        )
        return msg

    def publish_latest_pose(self):
        reading = read_pose_file(self.pose_file)
        if reading is None:
            return
        now = self.get_clock().now().nanoseconds / 1e9
        try:
            file_age = max(0.0, Path(self.pose_file).stat().st_mtime_ns / 1e9)
            file_age = now - file_age
        except OSError:
            return
        if file_age > self.stale_timeout:
            if now - self._last_stale_log_time >= 1.0:
                self._last_stale_log_time = now
                self.get_logger().warn(
                    f"pose_file_stale age={file_age:.3f}s "
                    f"sim_time={reading.sim_time} path={self.pose_file}"
                )
                diagnostics = String()
                diagnostics.data = (
                    f"pose_file_stale age={file_age:.3f}s "
                    f"sim_time={reading.sim_time}"
                )
                self._diagnostics_publisher.publish(diagnostics)
            return

        nav_msg = self._to_nav_odometry_msg(reading)
        for publisher in self._nav_odom_publishers:
            publisher.publish(nav_msg)
        self._booster_odom_publisher.publish(self._to_booster_odometer_msg(reading))

        diagnostics = String()
        diagnostics.data = compare_odometry(reading, self.vendor_odometer).summary
        self._diagnostics_publisher.publish(diagnostics)
        if now - self._last_pose_log_time >= 1.0:
            self._last_pose_log_time = now
            self.get_logger().info(
                f"pose_file_publish x={reading.x:.3f} y={reading.y:.3f} "
                f"theta={reading.theta:.3f} sim_time={reading.sim_time} "
                f"age={file_age:.3f}s diagnostics={diagnostics.data!r}"
            )


def main(argv=None):
    rclpy.init(args=argv)
    node = PoseFileOdometryPublisher(
        pose_file=os.environ.get("BOOSTER_POSE_FILE", DEFAULT_POSE_FILE),
        stale_timeout=float(os.environ.get("BOOSTER_POSE_STALE_TIMEOUT", "2.0")),
    )
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
