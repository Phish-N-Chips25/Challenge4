from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    run_imu = LaunchConfiguration("run_imu")
    run_low_state = LaunchConfiguration("run_low_state")
    run_zero_cmd = LaunchConfiguration("run_zero_cmd")

    return LaunchDescription(
        [
            DeclareLaunchArgument("run_imu", default_value="true"),
            DeclareLaunchArgument("run_low_state", default_value="true"),
            DeclareLaunchArgument("run_zero_cmd", default_value="false"),
            Node(
                package="booster_t1_webots_test",
                executable="topic_listener",
                name="topic_listener",
                output="screen",
            ),
            Node(
                package="booster_t1_webots_test",
                executable="joint_state_listener",
                name="joint_state_listener",
                output="screen",
            ),
            Node(
                package="booster_t1_webots_test",
                executable="imu_listener",
                name="imu_listener",
                output="screen",
                condition=IfCondition(run_imu),
            ),
            Node(
                package="booster_t1_webots_test",
                executable="low_state_listener",
                name="low_state_listener",
                output="screen",
                condition=IfCondition(run_low_state),
            ),
            Node(
                package="booster_t1_webots_test",
                executable="simple_command_publisher",
                name="simple_command_publisher",
                output="screen",
                condition=IfCondition(run_zero_cmd),
            ),
        ]
    )
