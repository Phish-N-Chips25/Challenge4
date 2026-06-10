import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node


class SimpleCommandPublisher(Node):
    def __init__(self):
        super().__init__("simple_command_publisher")
        self.publisher = self.create_publisher(Twist, "/cmd_vel", 10)
        self.timer = self.create_timer(1.0, self.publish_zero_twist)
        self.count = 0
        self.get_logger().info("Publishing zero Twist messages on /cmd_vel only")

    def publish_zero_twist(self):
        msg = Twist()
        self.publisher.publish(msg)
        self.count += 1
        self.get_logger().info(f"published zero /cmd_vel message #{self.count}")


def main():
    rclpy.init()
    node = SimpleCommandPublisher()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
