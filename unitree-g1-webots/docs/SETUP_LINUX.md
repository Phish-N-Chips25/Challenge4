# 🐧 Linux Setup Guide

> Step-by-step instructions for setting up the Booster T1 simulation environment on Linux.

Tested on **Ubuntu 22.04 LTS** and **Ubuntu 24.04 LTS**.

---

## 📋 Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Ubuntu | 22.04 or 24.04 | Other distros may work but are untested |
| Docker Engine | 20.10+ | **Not** Docker Desktop — use Docker Engine |
| Webots | R2025a | Physics simulator |
| NVIDIA GPU + Drivers | Optional | Required for GPU-accelerated rendering |
| Git | Any recent | For cloning the repository |

---

## 1️⃣ Install Webots R2025a

### Option A: APT Package (Recommended)

```bash
sudo apt update
sudo apt install webots
```

### Option B: Manual Download

Download the `.deb` package from [cyberbotics.com](https://cyberbotics.com/doc/guide/installation-procedure#installation-on-linux):

```bash
wget https://github.com/cyberbotics/webots/releases/download/R2025a/webots_2025a_amd64.deb
sudo dpkg -i webots_2025a_amd64.deb
sudo apt-get install -f  # Fix any missing dependencies
```

### Verify Installation

```bash
/usr/local/webots/webots --version
# Expected: Webots version: R2025a
```

> [!NOTE]
> On Linux, Webots installs to `/usr/local/webots/webots`. The `run_host_simulation.sh` script references this path directly.

---

## 2️⃣ Install Docker Engine

Follow the [official Docker Engine installation guide for Ubuntu](https://docs.docker.com/engine/install/ubuntu/):

```bash
# Remove old versions
sudo apt-get remove docker docker-engine docker.io containerd runc

# Set up Docker's apt repository
sudo apt-get update
sudo apt-get install ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker Engine
sudo apt-get update
sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Add your user to the docker group (avoids needing sudo)
sudo usermod -aG docker $USER
newgrp docker
```

Verify Docker is working:

```bash
docker run hello-world
```

> [!WARNING]
> **Do not use Docker Desktop on Linux** for this project. The container scripts use `--network host` and `--privileged` flags that work best with Docker Engine. Docker Desktop on Linux runs inside a VM, which breaks host networking.

---

## 3️⃣ NVIDIA GPU Setup (Optional)

GPU passthrough enables accelerated rendering inside the container. This step is optional — the simulation works without a GPU.

### Install NVIDIA Container Toolkit

```bash
# Add the NVIDIA repository
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

# Install
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit

# Configure Docker to use NVIDIA runtime
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### Verify GPU Passthrough

```bash
docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi
```

You should see your GPU listed. If this works, the container scripts will automatically detect and use the GPU.

> [!TIP]
> The `docker_common.sh` script auto-detects GPU availability. If `nvidia-smi` is available on the host and the NVIDIA Docker runtime is configured, it automatically adds `--gpus all` to container arguments. No manual configuration needed.

---

## 4️⃣ Clone the Repository

```bash
git clone https://github.com/<your-org>/ISEP-Challenge-Robotics.git
cd ISEP-Challenge-Robotics
```

---

## 5️⃣ Place Booster Runner Files

Download the official biped binaries from the Booster Robotics manual and place them in `external/booster_runner/`:

```
external/booster_runner/
├── booster-runner-webots-full-0.0.11.run   # Official runner executable
├── webots_simulation.zip                    # Simulation world + assets
└── webots_updated.zip                       # Controller libraries
```

> [!IMPORTANT]
> These files are proprietary Booster Robotics binaries and are **not included** in the repository. Download them from the [Booster Robotics documentation portal](https://docs.boostrobotics.com/).

Verify the assets:

```bash
./tools/check_booster_runner_assets.sh
# Expected: "Booster runner assets are present and plausible."
```

---

## 6️⃣ Build the Docker Container

```bash
./containers/build_ros_container.sh
```

This builds a Docker image tagged `booster-t1-webots-ros:humble` from `containers/Containerfile`. The image is based on `ros:humble-ros-base-jammy` and includes all required ROS 2 packages and system dependencies.

Build time: ~5–10 minutes on first build (cached afterwards).

---

## 🚀 Quick Start

### Active Mode (Walking Simulation)

Run the all-in-one simulation script:

```bash
# Walk forward for 20 seconds
./tools/run_host_simulation.sh forward 20.0

# Turn left for 10 seconds
./tools/run_host_simulation.sh turn_left 10.0

# Available commands: forward, backward, left, right, turn_left, turn_right, stop
```

### Passive Mode (State Bridge)

1. Start Webots on the host:
   ```bash
   /usr/local/webots/webots --batch --stdout --stderr --mode=fast --port=1234 --extern-urls \
     webots/worlds/T1_break_room.wbt
   ```

2. Start the interactive container:
   ```bash
   ./containers/run_ros_container.sh
   ```

3. In another terminal, start the state bridge:
   ```bash
   ./containers/start_webots_state_bridge.sh
   ```

### Telemetry Monitoring

1. Start the container (if not already running):
   ```bash
   ./containers/run_ros_container.sh
   ```

2. Enter the running container in another terminal:
   ```bash
   ./containers/enter_ros_container.sh
   ```

3. Build and launch listener nodes:
   ```bash
   cd /workspace/project/ros2_ws
   source /opt/ros/humble/setup.bash
   colcon build --symlink-install
   source install/setup.bash
   ros2 launch booster_t1_webots_test booster_t1_break_room.launch.py
   ```

---

## ✅ First Run Walkthrough

After building the container and placing the runner files, here's what to expect:

1. **Run the simulation**:
   ```bash
   ./tools/run_host_simulation.sh forward 5.0
   ```

2. **Expected output**:
   ```
   Cleaning up old processes...
   Extracting webots_updated.zip for controller libraries...
   Extracting webots_simulation.zip for simulation assets...
   Syncing corrected world file to simulation path...
   Starting Webots on host with T1_break_room.wbt...
   Starting booster runner inside the container...
   Started Booster Webots runner with PID 12345
   Waiting for /booster_rpc_service to be ready...
   Sending movement command: forward for 5.0 seconds...
   RPC api_id=2000 status=0 body=
   RPC api_id=2000 status=0 body=
   RPC api_id=2001 status=0 body=
   RPC api_id=2001 status=0 body=
   Done!
   ```

3. **Verify topics** (from inside the container):
   ```bash
   # Set the FastDDS profile
   export FASTRTPS_DEFAULT_PROFILES_FILE=$(find /tmp -maxdepth 2 -name "fastdds_profile.xml" | head -n 1)

   ros2 topic list
   # Should show:
   # /booster_t1/joint_states
   # /booster_t1/imu
   # /booster_t1/low_state
   # /parameter_events
   # /rosout
   ```

---

## 🔗 Related Documentation

- [Architecture](ARCHITECTURE.md) — System design deep-dive
- [Docker Reference](DOCKER_REFERENCE.md) — Container infrastructure details
- [API Reference](API_REFERENCE.md) — ROS 2 topics, services, and messages
- [Debugging](DEBUGGING.md) — Troubleshooting guide
