# Docker Infrastructure Reference

This document explains the Docker and script infrastructure that allows the Booster T1 ROS 2 simulation environment to run consistently across Linux, macOS, and Windows.

---

## 🐳 Container Architecture

The `docker-compose.yml` defines the core environment. We use a multi-platform approach where the ROS 2 container connects to the host machine's Webots instance over TCP port 1234.

### Docker Compose Services

-   `ros2`: The default service. Uses bridge networking and is configured for macOS and Windows (and Linux setups not using `--network host`).
-   `ros2-linux`: Uses the `linux` profile. Configured with `--network host` and GPU passthrough for optimal performance on native Linux hosts.

### Volume Mounts

| Host Path | Container Path | Purpose |
|---|---|---|
| `./` (Project Root) | `/workspace/project` | Live code editing. Changes on host immediately reflect in container. |
| `/tmp/.X11-unix` | `/tmp/.X11-unix` | (Linux) X11 socket forwarding for GUI apps. |
| `${XAUTHORITY}` | `/tmp/.docker.xauth` | (Linux) X11 authentication forwarding. |

### Build Cache Management

To prevent redownloading Webots assets every time the container is destroyed, we map host directories into the container:
-   `.docker/home` -> Container's `$HOME`
-   `.docker/webots` -> Unzipped Webots controller libraries
-   `.docker/booster_runner` -> Unzipped Booster simulation assets
-   `.logs/` -> Holds `booster-webots-runner.log` and Webots logs

These are ignored by git via `.gitignore`.

---

## 🔧 Environment Variables

We use `.env` files to configure platform-specific behaviors.

### Default `.env` Variables
| Variable | Default Value | Description |
|---|---|---|
| `COMPOSE_PROJECT_NAME` | `booster-t1` | Docker Compose project prefix. |
| `WEBOTS_PORT` | `1234` | TCP port used by Webots external controller. |
| `ROBOT_NAME` | `T1_release` | The robot node name in the `.wbt` world. |
| `CONTAINER_NAME` | `booster-t1-ros` | Static container name for `docker exec` targeting. |
| `IMAGE_NAME` | `booster-t1-webots-ros:humble` | The built image tag. |

### Platform Overrides (`.env.linux`, `.env.macos`, `.env.windows`)
| Variable | Linux Value | macOS/Windows Value | Purpose |
|---|---|---|---|
| `WEBOTS_HOST_IP` | `127.0.0.1` | `host.docker.internal` | How the container reaches the host Webots. |
| `WEBOTS_PATH` | `/usr/local/webots/...` | `/Applications/...` or `C:\...` | Path to Webots executable on host. |
| `ENABLE_GPU` | `true` | `false` | Enables NVIDIA GPU passthrough. |
| `USE_HOST_NETWORK` | `true` | `false` | Disables bridge NAT for better DDS discovery. |

*To apply overrides, copy your platform's `.env` to `.env.local`.*

---

## 📜 Script Reference

The `containers/` directory holds helper scripts for managing the lifecycle.

### 1. `docker_common.sh`
The core library sourced by other scripts.
-   `ensure_docker_state_dirs()`: Creates `.docker/` cache folders.
-   `detect_platform()`: Returns `linux`, `macos`, or `windows` based on `uname`.
-   `append_runtime_args()`: Dynamically builds the `docker run` argument list based on platform (handles X11 forwarding, GPU flags, network modes).

### 2. `entrypoint.sh`
The smart container entrypoint defined in the `Containerfile`.
-   Sources `/opt/ros/humble/setup.bash`.
-   Sources the local workspace `install/setup.bash` if it exists.
-   Searches `/tmp` for `fastdds_profile.xml` and exports `FASTRTPS_DEFAULT_PROFILES_FILE` if found (required for cross-container DDS discovery).
-   Sets `WEBOTS_HOME`.

### 3. `build_ros_container.sh`
Builds the Docker image. It prefers `docker compose build` if the compose file is present, otherwise falls back to `docker build`.

### 4. `run_ros_container.sh`
Starts an interactive terminal session inside the container. It auto-detects your platform and loads the correct `.env` configuration.

### 5. `enter_ros_container.sh`
Use this to open a *second* terminal window inside an already running container. Equivalent to `docker compose exec ros2 bash`.

---

## 🛠️ Customizing the Container

### Adding Ubuntu Packages
If you need a new system dependency (e.g., `apt-get install htop`):
1.  Open `containers/Containerfile`.
2.  Add the package to the `RUN apt-get install -y \` list.
3.  Rebuild: `docker compose build`

### Adding ROS 2 Dependencies
If you need a new ROS 2 package (e.g., `ros-humble-rviz2`):
1.  Add it to the `Containerfile`.
2.  Add it as an `<exec_depend>` in the relevant `package.xml`.
3.  Rebuild: `docker compose build`

---

## 🐛 Debugging Docker Issues

**Container won't start?**
```bash
# Check container logs
docker compose logs ros2
```

**Webots controller connection refused?**
Ensure `WEBOTS_HOST_IP` is correct for your platform. If on Linux, ensure you are using `--network host` or the `linux` compose profile. If on Mac/Windows, ensure `host.docker.internal` is resolving.

**Missing Webots assets?**
Clear the `.docker` cache directory to force the scripts to re-extract the vendor ZIP files:
```bash
rm -rf .docker/booster_runner/webots_simulation
./tools/run_host_simulation.sh stop 1
```
