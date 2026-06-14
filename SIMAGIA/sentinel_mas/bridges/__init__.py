"""Bridge stubs — to be implemented when integrating Webots + ROS2.

Design contract:
  * Agents NEVER import rclpy directly; everything goes through
    these bridge classes so SPADE stays ROS-agnostic.
  * Each bridge runs its ROS2 executor in a background thread and
    exposes asyncio-friendly methods to the agents.
"""

from __future__ import annotations


class ROS2Bridge:
    """Future: rclpy node wrapping pub/sub for the patrol robot.

    Planned interface:
        publish_cmd_vel(linear, angular)
        get_odometry() -> dict
        get_lidar_scan() -> list[float]
        subscribe_camera(callback)
    """

    def __init__(self):
        raise NotImplementedError("Enable when ROS2 integration begins")


class WebotsBridge:
    """Future: Webots supervisor/controller adapter.

    Planned interface:
        spawn_robot(model: str, zone: str)
        get_zone_camera_frame(zone: str) -> np.ndarray
        teleport_intruder(zone: str)   # scenario scripting
    """

    def __init__(self):
        raise NotImplementedError("Enable when Webots integration begins")
