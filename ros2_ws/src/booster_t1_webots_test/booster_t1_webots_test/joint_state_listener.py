import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState

from .listener_base import MultiTopicCounter, create_subscriptions
from .message_formatters import format_joint_state


class JointStateListener(Node):
    def __init__(self):
        super().__init__("joint_state_listener")
        self.counter = MultiTopicCounter()
        self._subscriptions = create_subscriptions(
            self,
            JointState,
            "joint_states",
            self._callback_for,
        )
        self.get_logger().info("Waiting for joint state messages")

    def _callback_for(self, topic):
        def callback(msg):
            count = self.counter.next_count(topic)
            if count == 1 or count % 20 == 0:
                self.get_logger().info(f"{topic}: {format_joint_state(msg, count)}")

        return callback


def main():
    rclpy.init()
    node = JointStateListener()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
