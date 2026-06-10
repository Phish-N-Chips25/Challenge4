import rclpy
from rclpy.node import Node


class TopicListener(Node):
    def __init__(self):
        super().__init__("topic_listener")
        self.timer = self.create_timer(2.0, self.print_topics)

    def print_topics(self):
        topics = self.get_topic_names_and_types()
        self.get_logger().info("Visible topics:")
        for name, types in topics:
            self.get_logger().info(f"  {name}: {types}")


def main():
    rclpy.init()
    node = TopicListener()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
