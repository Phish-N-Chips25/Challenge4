# 🍎 macOS Setup Guide

> Step-by-step instructions for setting up the Booster T1 simulation environment on macOS.

---

## 📋 Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| macOS | 12 Monterey+ | Apple Silicon (M1/M2/M3/M4) or Intel |
| Docker Desktop for Mac | 4.20+ | Required (Docker Engine is not available on macOS) |
| Webots | R2025a | Physics simulator |
| Git | Any recent | Comes with Xcode Command Line Tools |

> [!IMPORTANT]
> **No GPU passthrough is available on macOS.** The simulation runs CPU-only inside the Docker container. Webots on the host uses Metal for rendering, but the containerized ROS 2 stack has no GPU access.

---

## 1️⃣ Install Webots R2025a

1. Download the macOS `.dmg` from [cyberbotics.com](https://cyberbotics.com/doc/guide/installation-procedure#installation-on-macos).
2. Open the `.dmg` and drag **Webots** to `/Applications`.
3. On first launch, right-click → **Open** to bypass Gatekeeper.

### Verify Installation

```bash
/Applications/Webots.app/Contents/MacOS/webots --version
# Expected: Webots version: R2025a
```

> [!NOTE]
> The `webots` command is **not** on PATH by default on macOS. Always use the full path `/Applications/Webots.app/Contents/MacOS/webots`, or create an alias:
> ```bash
> alias webots='/Applications/Webots.app/Contents/MacOS/webots'
> ```

---

## 2️⃣ Install Docker Desktop for Mac

1. Download [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop/) (choose Apple Silicon or Intel based on your Mac).
2. Install and launch Docker Desktop.
3. Complete the setup wizard.

### Recommended Settings

Open Docker Desktop → **Settings** → **Resources**:

| Setting | Recommended Value | Reason |
|---|---|---|
| CPUs | 4+ | colcon parallel builds and simulation |
| Memory | **8 GB+** | ROS 2 build + Booster runner require significant memory |
| Disk | 20 GB+ | Docker images and build caches |
| File Sharing | VirtioFS | Significantly faster bind mounts |

> [!TIP]
> Enable **VirtioFS** under Settings → General → "Choose file sharing implementation". This dramatically improves colcon build times on bind-mounted workspaces.

### Verify Docker

```bash
docker --version
docker run hello-world
```

---

## 3️⃣ Networking Configuration

Docker Desktop on macOS runs containers inside a Linux VM. The container cannot use `--network host` to directly access host services.

### How to Reach Webots from the Container

Use `host.docker.internal` to resolve to the host machine's IP:

```bash
# From inside the container:
ping host.docker.internal
# Should resolve to the Docker Desktop gateway
```

When starting the Webots state bridge, set the host IP:

```bash
WEBOTS_HOST_IP=host.docker.internal ./containers/start_webots_state_bridge.sh
```

> [!WARNING]
> The default `WEBOTS_HOST_IP=127.0.0.1` in the scripts assumes Linux host networking. On macOS, you **must** override this to `host.docker.internal` or the actual host IP.

### Apple Container Networking Note

If using Apple Containers instead of Docker Desktop, note that `host.docker.internal` and `host.containers.internal` may **not** resolve. The container network uses a `192.168.64.0/24` range. Check:

```bash
ip route       # Inside container
hostname -I    # Inside container
```

You may need to use the gateway IP directly (e.g., `192.168.64.1`).

---

## 4️⃣ Apple Silicon Notes

On Apple Silicon Macs (M1/M2/M3/M4), the ROS 2 Docker image (`ros:humble-ros-base-jammy`) is an **amd64** image. Docker Desktop runs it under **Rosetta 2 emulation**.

Performance implications:

| Aspect | Impact |
|---|---|
| Container startup | Slightly slower due to emulation |
| colcon build | ~2-3x slower than native x86 |
| Runtime (ROS 2 nodes) | Minimal impact for I/O-bound nodes |
| Booster runner binary | x86 binary runs under Rosetta |

> [!NOTE]
> The simulation is fully functional on Apple Silicon. Build times are longer, but runtime performance is acceptable for development and testing.

---

## 5️⃣ Clone and Configure

```bash
git clone https://github.com/<your-org>/ISEP-Challenge-Robotics.git
cd ISEP-Challenge-Robotics
```

### Place Booster Runner Files

Download the official biped binaries and place them in `external/booster_runner/`:

```
external/booster_runner/
├── booster-runner-webots-full-0.0.11.run
├── webots_simulation.zip
└── webots_updated.zip
```

---

## 6️⃣ Build the Docker Container

```bash
./containers/build_ros_container.sh
```

> [!NOTE]
> On Apple Silicon, Docker will show a warning about `--platform linux/amd64`. This is expected — the container runs under emulation.

---

## 🚀 Quick Start

### Passive Mode (Recommended for macOS)

1. **Start Webots on the host**:
   ```bash
   /Applications/Webots.app/Contents/MacOS/webots --batch --stdout --stderr \
     --mode=fast --port=1234 --extern-urls \
     webots/worlds/T1_break_room.wbt
   ```

2. **Start the container**:
   ```bash
   ./containers/run_ros_container.sh
   ```

3. **Start the state bridge** (in a new terminal):
   ```bash
   WEBOTS_HOST_IP=host.docker.internal ./containers/start_webots_state_bridge.sh
   ```

4. **Monitor topics** (enter the container in another terminal):
   ```bash
   ./containers/enter_ros_container.sh
   source /opt/ros/humble/setup.bash
   ros2 topic echo /joint_states
   ```

### Active Mode

Active Mode follows the same pattern as Linux but requires the `WEBOTS_CONTROLLER_URL` to use `host.docker.internal`:

```bash
# The run_host_simulation.sh script may need modification for macOS.
# Specifically, change the Webots path and controller URL:
#   Webots path:  /Applications/Webots.app/Contents/MacOS/webots
#   Controller URL: tcp://host.docker.internal:1234/T1_release
```

---

## ⚠️ Known Limitations

| Limitation | Description |
|---|---|
| No GPU passthrough | Container runs CPU-only; no OpenGL/Vulkan acceleration |
| Rosetta emulation | x86 container on ARM Mac is slower than native |
| Host networking unavailable | Must use `host.docker.internal` for container→host communication |
| DNS resolution | `host.containers.internal` may not resolve with Apple Containers |
| X11 forwarding | No native X11; use XQuartz if GUI apps are needed inside container |
| Webots path | Not on PATH; must use full `/Applications/...` path |

---

## 🔗 Related Documentation

- [Architecture](ARCHITECTURE.md) — System design and network topology
- [Docker Reference](DOCKER_REFERENCE.md) — Container scripts and configuration
- [Debugging](DEBUGGING.md) — macOS-specific troubleshooting
- [Setup: Linux](SETUP_LINUX.md) | [Windows](SETUP_WINDOWS.md) — Other platforms
