# Windows Setup Guide

This guide explains how to set up and run the Booster T1 simulation environment on Windows using WSL2 and Docker Desktop.

## Prerequisites

1.  **Windows 10 Version 21H2+ or Windows 11**
2.  **WSL2 (Windows Subsystem for Linux)**
3.  **Docker Desktop for Windows** (with WSL2 backend enabled)
4.  **Webots R2025a**

---

## 1. Install WSL2 and Ubuntu

If you don't have WSL2 installed, open PowerShell as Administrator and run:

```powershell
wsl --install -d Ubuntu-22.04
```

Restart your computer if prompted. After restarting, complete the Ubuntu setup by creating a username and password.

## 2. Install Docker Desktop

1.  Download and install [Docker Desktop for Windows](https://docs.docker.com/desktop/install/windows-install/).
2.  During installation, ensure the **"Use WSL 2 instead of Hyper-V"** option is checked.
3.  Once installed, open Docker Desktop, go to **Settings > Resources > WSL Integration**, and ensure integration is enabled for your `Ubuntu-22.04` distribution.

## 3. Install Webots

1.  Download the **Webots R2025a MSI installer** from the [Cyberbotics website](https://cyberbotics.com/).
2.  Run the installer and complete the setup.
3.  The default installation path is usually `C:\Program Files\Webots\msys64\mingw64\bin\webots.exe`.

## 4. Setup GPU Support (Optional)

If you have an NVIDIA GPU and want to use it for the simulation, you can enable GPU passthrough in WSL2:

1.  Ensure you have the latest NVIDIA drivers installed on your Windows host.
2.  Install the NVIDIA Container Toolkit inside your WSL2 Ubuntu distribution (refer to NVIDIA's documentation).
3.  Docker Desktop should automatically support GPU access if your drivers are up to date.

---

## 🚀 Quick Start

All terminal commands should be run inside your WSL2 environment (e.g., open the Ubuntu terminal) or using Git Bash. Do not use standard PowerShell or CMD.

### 1. Clone the Repository

```bash
git clone <repo-url> && cd ISEP-Challenge-Robotics

# Clone Booster robot assets
git clone --depth 1 https://github.com/BoosterRobotics/booster_assets.git webots/assets/booster_assets
```

### 2. Prepare Environment

Copy the Windows-specific environment configuration:

```bash
cp .env.windows .env.local
```

### 3. Place Booster Runner Binaries

Download from the Booster T1 Manual and place them in `external/booster_runner/`:
-   `booster-runner-webots-full-0.0.11.run`
-   `webots_simulation.zip`

Verify the assets:

```bash
./tools/check_booster_runner_assets.sh
```

### 4. Start the Simulation

On Windows, Webots runs natively on the host, and the ROS 2 container connects to it via Docker's internal networking (`host.docker.internal`).

Start Webots on your Windows host manually or run this from your WSL2 terminal (adjust the path if necessary):

```bash
# This will launch the Webots GUI on Windows
"/mnt/c/Program Files/Webots/msys64/mingw64/bin/webots.exe" webots/worlds/T1_break_room.wbt
```

In another WSL2 terminal, bring up the container:

```bash
docker compose up -d
```

### 5. Run Commands

To send commands to the robot, execute them inside the running container:

```bash
docker compose exec ros2 ros2 run booster_t1_webots_test rpc_movement_client --command forward --duration 10.0
```

---

## ⚠️ Known Limitations

-   **Performance**: There might be slight performance overhead compared to native Linux due to the WSL2 virtualization layer.
-   **Networking**: The container communicates with Webots via `host.docker.internal`. Ensure Windows Defender Firewall allows traffic from WSL2/Docker to the Webots executable on port `1234`.
-   **GUI Forwarding**: Running GUI tools from within the container requires an X-server configured on Windows (like VcXsrv) and `$DISPLAY` properly set. This is not needed for just running the headless simulation backend.
