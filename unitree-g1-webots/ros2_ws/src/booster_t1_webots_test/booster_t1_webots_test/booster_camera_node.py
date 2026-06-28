import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image

try:
    from controller import Robot
except ImportError as exc:
    Robot = None
    CONTROLLER_IMPORT_ERROR = exc
else:
    CONTROLLER_IMPORT_ERROR = None


class BoosterCameraNode(Node):
    def __init__(self):
        super().__init__("booster_camera_node")
        if Robot is None:
            raise RuntimeError(
                "Webots controller Python module is unavailable. Start this node "
                "through webots-controller with WEBOTS_HOME set."
            ) from CONTROLLER_IMPORT_ERROR

        self.robot = Robot()
        self.timestep = int(self.robot.getBasicTimeStep())
        self.camera = self.robot.getDevice("booster_camera")
        if self.camera is None:
            raise RuntimeError("Device 'booster_camera' not found on the robot")
        self.camera.enable(self.timestep)

        self.publisher = self.create_publisher(
            Image, "/booster_t1/camera/image_raw", 10
        )
        self.get_logger().info(
            f"Publishing camera frames on /booster_t1/camera/image_raw "
            f"({self.camera.getWidth()}x{self.camera.getHeight()})"
        )

    def publish_frame(self):
        if self.camera is None:
            return
        width = self.camera.getWidth()
        height = self.camera.getHeight()
        image_data = self.camera.getImage()
        if image_data is None:
            return

        msg = Image()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "booster_camera"
        msg.height = height
        msg.width = width
        msg.encoding = "bgra8"
        msg.is_bigendian = False
        msg.step = width * 4
        msg.data = image_data
        self.publisher.publish(msg)

    def run(self):
        while rclpy.ok() and self.robot.step(self.timestep) != -1:
            rclpy.spin_once(self, timeout_sec=0)
            self.publish_frame()


def main(argv=None):
    rclpy.init(args=argv or [])
    node = BoosterCameraNode()
    try:
        node.run()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
