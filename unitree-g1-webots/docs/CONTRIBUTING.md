# Contributing Guide

Welcome to the Booster T1 Webots ROS 2 project! This guide outlines how to set up your development environment, our code style conventions, and how to contribute new features.

## 🛠️ Development Environment

We strongly recommend developing directly inside the provided Docker container to ensure environment consistency.

1.  **Clone the repository**:
    ```bash
    git clone <repo-url>
    cd ISEP-Challenge-Robotics
    ```
2.  **Copy environment config**:
    Copy the appropriate `.env.<platform>` to `.env.local` to set your local overrides without committing them.
3.  **Start the container**:
    ```bash
    docker compose up -d
    ```
4.  **Enter the container**:
    ```bash
    docker compose exec ros2 bash
    ```

From here, you are inside the ROS 2 Humble workspace at `/workspace/project/ros2_ws`.

---

## 🔀 Git Workflow

1.  We use `main` as the stable branch.
2.  For new features, create a branch from `feat/booster-t1-webots-ros-test` (or the current active feature branch).
    ```bash
    git checkout -b feature/my-new-node
    ```
3.  Commit your changes using clear, descriptive commit messages.
4.  Open a Pull Request against the main integration branch.

---

## 📝 Code Style

### Python (ROS 2 Nodes)
*   We follow **PEP 8** style guidelines.
*   Use `rclpy` best practices (object-oriented node design).
*   Use type hints where appropriate.
*   Format code using `black` if possible.

### Bash Scripts
*   Always start bash scripts with:
    ```bash
    #!/usr/bin/env bash
    set -euo pipefail
    ```
*   Ensure scripts are `shellcheck` clean.
*   Do not hardcode absolute paths to user home directories. Use `$PROJECT_ROOT` relative logic.
*   Use variables for cross-platform differences (e.g., `$WEBOTS_HOST_IP`).

### C++ (If added later)
*   Follow ROS 2 C++ style guide (based on Google C++ Style Guide).
*   Format with `clang-format` (a `.clang-format` file is provided in `booster_ros2_interface`).

---

## ➕ Adding a New ROS 2 Node (Python)

To add a new Python node to `booster_t1_webots_test`:

1.  Create your Python file in `ros2_ws/src/booster_t1_webots_test/booster_t1_webots_test/my_new_node.py`.
2.  Ensure it has a `main()` function and calls `rclpy.init()`.
3.  Open `ros2_ws/src/booster_t1_webots_test/setup.py`.
4.  Add your node to the `console_scripts` entry points:
    ```python
    "console_scripts": [
        # ... existing nodes ...
        "my_new_node = booster_t1_webots_test.my_new_node:main",
    ],
    ```
5.  If it should run by default, add it to the launch file `ros2_ws/src/booster_t1_webots_test/launch/booster_t1_break_room.launch.py`.
6.  Rebuild the workspace:
    ```bash
    colcon build --symlink-install
    source install/setup.bash
    ```

---

## 📩 Adding New Message Types

If you need to define a new custom message or service for the `booster_interface` package:

1.  Create `MyNewMessage.msg` in `ros2_ws/src/booster_ros2_interface/msg/`.
2.  Open `ros2_ws/src/booster_ros2_interface/CMakeLists.txt`.
3.  Add the new message to the `rosidl_generate_interfaces` block:
    ```cmake
    rosidl_generate_interfaces(${PROJECT_NAME}
      # ... existing msgs ...
      "msg/MyNewMessage.msg"
    )
    ```
4.  Rebuild the interface package:
    ```bash
    colcon build --packages-select booster_interface
    ```

---

## 🌍 Modifying the Webots World

The Webots world file is located at `webots/worlds/T1_break_room.wbt`.

1.  Open the world in the native Webots GUI on your host machine.
2.  Make your modifications (adding obstacles, changing lighting).
3.  Save the world file.
4.  **Important**: Do NOT modify the `basicTimeStep 1` or `coulombFriction` values, as the biped walking controller will fail if these are changed.
5.  Check the diff before committing to ensure you aren't accidentally committing massive binary changes or absolute paths.

---

## 🧪 Testing

We use standard `pytest` for Python ROS 2 nodes.

To run the tests:
```bash
cd /workspace/project/ros2_ws
colcon test --packages-select booster_t1_webots_test
colcon test-result --all
```

## ✅ Pull Request Checklist

Before submitting a PR, ensure:
* [ ] Your code runs successfully on at least one platform (Linux, macOS, or Windows).
* [ ] You have not committed any `.env.local` files or vendor binaries.
* [ ] You have updated the documentation if your changes affect the API, Docker setup, or architecture.
* [ ] All bash scripts pass syntax checks (`bash -n`).
