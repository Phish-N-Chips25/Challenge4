import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Imu

from .listener_base import MultiTopicCounter, create_subscriptions
from .message_formatters import format_imu


class ImuListener(Node):
    def __init__(self):
        super().__init__("imu_listener")
        self.counter = MultiTopicCounter()
        self._subscriptions = create_subscriptions(
            self,
            Imu,
            "imu",
            self._callback_for,
        )
        self.get_logger().info("Waiting for IMU messages")

    def _callback_for(self, topic):
        def callback(msg):
            count = self.counter.next_count(topic)
            if count == 1 or count % 20 == 0:
                self.get_logger().info(f"{topic}: {format_imu(msg, count)}")

        return callback


def main():
    rclpy.init()
    node = ImuListener()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
