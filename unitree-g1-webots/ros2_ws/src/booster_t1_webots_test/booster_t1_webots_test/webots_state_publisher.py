import time

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState

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
    "Left_Ankle_Pitch",
    "Left_Ankle_Roll",
    "Right_Hip_Pitch",
    "Right_Hip_Roll",
    "Right_Hip_Yaw",
    "Right_Knee_Pitch",
    "Right_Ankle_Pitch",
    "Right_Ankle_Roll",
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
        self._publishers = [
            self.create_publisher(JointState, "/joint_states", 10),
            self.create_publisher(JointState, "/booster_t1/joint_states", 10),
        ]
        self.get_logger().info(
            f"Publishing Webots joint states for {len(self.sensors)} joints"
        )

    def publish_joint_states(self):
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = JOINT_NAMES
        msg.position = [sensor.getValue() for sensor in self.sensors]
        for publisher in self._publishers:
            publisher.publish(msg)

    def run(self):
        while rclpy.ok() and self.robot.step(self.timestep) != -1:
            rclpy.spin_once(self, timeout_sec=0)
            self.publish_joint_states()
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
