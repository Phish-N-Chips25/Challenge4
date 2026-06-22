import math
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Quaternion
from nav_msgs.msg import Odometry
from sensor_msgs.msg import JointState
from std_msgs.msg import String

from booster_interface.msg import Odometer

from .odometry_helpers import (
    OdometerReading,
    compare_odometry,
    odometer_from_webots_pose,
)

try:
    from controller import Robot
except ImportError as exc:  # pragma: no cover - only available through Webots.
    Robot = None
    CONTROLLER_IMPORT_ERROR = exc
else:
    CONTROLLER_IMPORT_ERROR = None


JOINT_NAMES = [
    "Left_Hip_Pitch",
    "Left_Hip_Roll",
    "Left_Hip_Yaw",
    "Left_Knee_Pitch",
    "Crank_Down_Left",
    "Crank_Up_Left",
    "Right_Hip_Pitch",
    "Right_Hip_Roll",
    "Right_Hip_Yaw",
    "Right_Knee_Pitch",
    "Crank_Down_Right",
    "Crank_Up_Right",
]


class WebotsStatePublisher(Node):
    def __init__(self, robot):
        super().__init__("webots_state_publisher")
        self.robot = robot
        self.timestep = int(robot.getBasicTimeStep())
        self.sensors = []
        for joint_name in JOINT_NAMES:
            sensor = robot.getDevice(f"{joint_name}_sensor")
            sensor.enable(self.timestep)
            self.sensors.append(sensor)
        self.gps = robot.getDevice("torso gps")
        self.gps.enable(self.timestep)
        self.inertial_unit = robot.getDevice("torso inertial unit")
        self.inertial_unit.enable(self.timestep)
        self.vendor_odometer = None
        self._joint_publishers = [
            self.create_publisher(JointState, "/joint_states", 10),
            self.create_publisher(JointState, "/booster_t1/joint_states", 10),
        ]
        self._nav_odom_publishers = [
            self.create_publisher(Odometry, "/odom", 10),
            self.create_publisher(Odometry, "/booster_t1/odom", 10),
        ]
        self._booster_odom_publishers = [
            self.create_publisher(Odometer, "/booster_t1/odometer", 10),
        ]
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
        self.get_logger().info(
            "Publishing Webots joint states and corrected odometry "
            f"for {len(self.sensors)} joints"
        )

    def publish_joint_states(self):
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = JOINT_NAMES
        msg.position = [sensor.getValue() for sensor in self.sensors]
        for publisher in self._joint_publishers:
            publisher.publish(msg)

    def _update_vendor_odometer(self, msg):
        self.vendor_odometer = OdometerReading(
            x=float(msg.x),
            y=float(msg.y),
            theta=float(msg.theta),
        )

    def _current_odometer(self):
        return odometer_from_webots_pose(
            self.gps.getValues(),
            self.inertial_unit.getRollPitchYaw(),
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

    def publish_odometry(self):
        reading = self._current_odometer()
        nav_msg = self._to_nav_odometry_msg(reading)
        booster_msg = self._to_booster_odometer_msg(reading)
        for publisher in self._nav_odom_publishers:
            publisher.publish(nav_msg)
        for publisher in self._booster_odom_publishers:
            publisher.publish(booster_msg)

        comparison = compare_odometry(reading, self.vendor_odometer)
        diagnostics = String()
        diagnostics.data = comparison.summary
        self._diagnostics_publisher.publish(diagnostics)

    def run(self):
        while rclpy.ok() and self.robot.step(self.timestep) != -1:
            rclpy.spin_once(self, timeout_sec=0)
            self.publish_joint_states()
            self.publish_odometry()
            time.sleep(0)


def main():
    if Robot is None:
        raise RuntimeError(
            "Webots controller Python module is unavailable. Start this node "
            "through webots-controller with WEBOTS_HOME set."
        ) from CONTROLLER_IMPORT_ERROR

    rclpy.init()
    robot = Robot()
    node = WebotsStatePublisher(robot)
    try:
        node.run()
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
