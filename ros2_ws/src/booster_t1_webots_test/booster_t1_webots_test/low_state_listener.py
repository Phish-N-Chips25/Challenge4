import subprocess

import rclpy
from rclpy.node import Node


class LowStateListener(Node):
    def __init__(self):
        super().__init__("low_state_listener")
        self.timer = self.create_timer(3.0, self.inspect_low_state_topics)
        self.get_logger().info(
            "Inspecting /low_state and /booster_t1/low_state. "
            "A typed subscriber is not created until the Booster message package is available."
        )

    def inspect_low_state_topics(self):
        for topic in ["/booster_t1/low_state", "/low_state"]:
            result = subprocess.run(
                ["ros2", "topic", "info", topic],
                text=True,
                capture_output=True,
                check=False,
            )
            if result.returncode == 0:
                self.get_logger().info(f"{topic}: {result.stdout.strip()}")
            else:
                self.get_logger().info(f"{topic}: not available yet")


def main():
    rclpy.init()
    node = LowStateListener()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
