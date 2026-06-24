from glob import glob

from setuptools import find_packages, setup


package_name = "booster_t1_webots_test"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", glob("launch/*.launch.py")),
        (f"share/{package_name}/config", glob("config/*.yaml")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="ISEP Challenge Robotics",
    maintainer_email="dev@example.com",
    description="Small ROS 2 listener package for Booster T1 Webots topic smoke tests.",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "topic_listener = booster_t1_webots_test.topic_listener:main",
            "joint_state_listener = booster_t1_webots_test.joint_state_listener:main",
            "imu_listener = booster_t1_webots_test.imu_listener:main",
            "low_state_listener = booster_t1_webots_test.low_state_listener:main",
            "simple_command_publisher = booster_t1_webots_test.simple_command_publisher:main",
            "webots_state_publisher = booster_t1_webots_test.webots_state_publisher:main",
            "pose_file_odometry_publisher = booster_t1_webots_test.pose_file_odometry_publisher:main",
            "sim_lidar_pointcloud_node = booster_t1_webots_test.sim_lidar_pointcloud_node:main",
            "rpc_movement_client = booster_t1_webots_test.rpc_movement_client:main",
            "booster_patrol_node = booster_t1_webots_test.booster_patrol_node:main",
            "ppo_patrol_node = booster_t1_webots_test.ppo_patrol_node:main",
            "booster_lidar_adapter = booster_t1_webots_test.booster_lidar_adapter:main",
            "booster_localization_node = booster_t1_webots_test.booster_localization_node:main",
        ],
    },
)
