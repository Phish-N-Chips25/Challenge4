# 🏗️ Architecture

> Deep-dive into the Booster T1 Webots + ROS 2 simulation architecture.

---

## 📐 System Topology

The system is split between a **host-running Webots simulator** and a **Docker-containerized ROS 2 Humble stack**. Communication flows over TCP port 1234 using the Webots external controller protocol.

```mermaid
graph TD
    subgraph Host["🖥️ Host Machine"]
        Webots["Webots R2025a<br/>Physics Simulator"]
        World["T1_break_room.wbt<br/>basicTimeStep=1ms"]
        Webots <-->|"Simulates Physics"| World
    end

    subgraph Docker["🐳 Docker Container: booster-t1-ros"]
        direction TB
        Runner["Official Booster Runner<br/>mck executable"]
        ROS2["ROS 2 Humble<br/>Workspace"]
        StatePub["webots_state_publisher<br/>Passive Mode"]
        RPC["rpc_movement_client"]
        Listeners["Listener Nodes<br/>joint / imu / low_state"]

        Runner -->|"Publishes Topics"| ROS2
        Runner -->|"Exposes /booster_rpc_service"| ROS2
        RPC -->|"Calls RPC Service"| ROS2
        Listeners -->|"Subscribes to Topics"| ROS2
    end

    Runner <-->|"TCP:1234<br/>Active Mode"| Webots
    StatePub -.->|"TCP:1234<br/>Passive Mode"| Webots
```

> [!NOTE]
> Only one connection mode is active at a time. **Active Mode** uses the official Booster runner binary; **Passive Mode** uses a lightweight Python controller.

---

## 🔄 Data Flow Diagrams

### Active Mode (Booster Runner + RPC Service)

In Active Mode, the official Booster simulation runner (`mck` executable) connects to Webots over TCP:1234, runs its Whole-Body Controller (WBC), and exposes ROS 2 topics and services.

```mermaid
flowchart LR
    subgraph Webots["Webots Host"]
        SIM["Physics Engine<br/>T1_break_room.wbt"]
    end

    subgraph Container["Docker Container"]
        MCK["Booster Runner<br/>mck"]
        JOINTS["/booster_t1/joint_states"]
        IMU["/booster_t1/imu"]
        LOW["/booster_t1/low_state"]
        SRV["/booster_rpc_service"]
        CLIENT["rpc_movement_client"]
    end

    SIM <-->|"TCP:1234"| MCK
    MCK --> JOINTS
    MCK --> IMU
    MCK --> LOW
    MCK --> SRV
    CLIENT -->|"RpcService.srv"| SRV
```

### Passive Mode (Webots State Bridge)

In Passive Mode, a custom Python node connects directly to Webots using the `webots-controller` script, reads joint position sensors, and publishes to ROS 2.

```mermaid
flowchart LR
    subgraph Webots["Webots Host"]
        SIM["Physics Engine<br/>T1_break_room.wbt"]
    end

    subgraph Container["Docker Container"]
        WSP["webots_state_publisher"]
        JS1["/joint_states"]
        JS2["/booster_t1/joint_states"]
    end

    SIM <-->|"TCP:1234<br/>webots-controller"| WSP
    WSP --> JS1
    WSP --> JS2
```

---

## ⚙️ Physics Constraints

The biped Whole-Body Controller (WBC) requires high-frequency integration. Incorrect physics parameters cause immediate solver divergence and robot collapse.

| Parameter | Required Value | Consequence of Deviation |
|---|---|---|
| `basicTimeStep` | `1` (1 ms) | Higher values cause WBC solver divergence; the biped collapses instantly |
| `coulombFriction` | `0.4` | Incorrect values cause foot slipping or unrealistic ground contact |
| World file | `T1_break_room.wbt` | Must be the physics-corrected version from `webots/worlds/` |

> [!CAUTION]
> Never increase `basicTimeStep` above 1 ms. The Booster WBC control loop is tuned for 1 kHz integration frequency. Even `basicTimeStep 2` will cause the solver to diverge immediately.

The `run_host_simulation.sh` script always copies the tracked, corrected world file to the runtime location to prevent accidentally running with bad physics parameters:

```bash
cp "${PROJECT_ROOT}/webots/worlds/T1_break_room.wbt" \
   "${PROJECT_ROOT}/.docker/booster_runner/webots_simulation/worlds/T1_break_room.wbt"
```

---

## 🌐 Network Architecture

### Linux (Host Networking)

On Linux with Docker Engine (not Docker Desktop), the container uses `--network host`, sharing the host's network namespace. Webots at `127.0.0.1:1234` is directly reachable from inside the container.

```mermaid
flowchart LR
    subgraph Host["Linux Host (shared network namespace)"]
        Webots["Webots<br/>:1234"]
        Container["Docker Container<br/>--network host"]
    end
    Container <-->|"127.0.0.1:1234"| Webots
```

### macOS / Windows (Docker Desktop NAT)

Docker Desktop runs containers inside a Linux VM. Host networking is not available. The container must reach Webots via `host.docker.internal` or the gateway IP `192.168.65.2`.

```mermaid
flowchart LR
    subgraph Host["macOS / Windows Host"]
        Webots["Webots<br/>:1234"]
    end
    subgraph VM["Docker Desktop VM"]
        Container["Docker Container"]
    end
    Container <-->|"host.docker.internal:1234<br/>or 192.168.65.2:1234"| Webots
```

| Platform | Network Mode | Webots Address from Container | Notes |
|---|---|---|---|
| Linux | `--network host` | `127.0.0.1:1234` | Shared network namespace |
| macOS | Docker Desktop NAT | `host.docker.internal:1234` | VM-based networking |
| Windows (WSL2) | Docker Desktop NAT | `host.docker.internal:1234` | WSL2 VM networking |

---

## 📡 DDS / FastDDS Profile Requirements

Standard ROS 2 discovery uses DDS multicast, which is isolated within the Docker container. To enable cross-process ROS 2 discovery (e.g., `ros2 topic list` from a `docker exec` shell), a FastDDS XML profile must be referenced.

The Booster runner generates a `fastdds_profile.xml` at runtime. Any additional shell that needs to interact with the ROS 2 graph must set:

```bash
export FASTRTPS_DEFAULT_PROFILES_FILE=$(find /tmp -maxdepth 2 -name "fastdds_profile.xml" | head -n 1)
```

> [!IMPORTANT]
> Without the FastDDS profile, `ros2 topic list` from a `docker exec` shell will only see `/parameter_events` and `/rosout`, even when the Booster runner is actively publishing topics.

---

## 📊 ROS 2 Topic Graph

### Published Topics

```mermaid
graph TD
    subgraph Publishers
        MCK["Booster Runner<br/>Active Mode"]
        WSP["webots_state_publisher<br/>Passive Mode"]
        SCP["simple_command_publisher"]
    end

    subgraph Topics
        BJS["/booster_t1/joint_states<br/>sensor_msgs/JointState"]
        BIMU["/booster_t1/imu<br/>sensor_msgs/Imu"]
        BLS["/booster_t1/low_state<br/>booster_interface/LowState"]
        JS["/joint_states<br/>sensor_msgs/JointState"]
        CV["/cmd_vel<br/>geometry_msgs/Twist"]
    end

    subgraph Subscribers
        JSL["joint_state_listener"]
        IL["imu_listener"]
        LSL["low_state_listener"]
    end

    MCK --> BJS
    MCK --> BIMU
    MCK --> BLS
    WSP --> JS
    WSP --> BJS
    SCP --> CV

    BJS --> JSL
    JS --> JSL
    BIMU --> IL
    BLS --> LSL
```

### Services

| Service | Type | Provider |
|---|---|---|
| `/booster_rpc_service` | `booster_interface/srv/RpcService` | Booster Runner (Active Mode) |

### All Nodes

| Node | Package | Purpose |
|---|---|---|
| `rpc_movement_client` | `booster_t1_webots_test` | Sends walk commands via RPC |
| `webots_state_publisher` | `booster_t1_webots_test` | Passive joint state bridge |
| `topic_listener` | `booster_t1_webots_test` | Enumerates visible ROS 2 topics |
| `joint_state_listener` | `booster_t1_webots_test` | Logs joint state messages |
| `imu_listener` | `booster_t1_webots_test` | Logs IMU messages |
| `low_state_listener` | `booster_t1_webots_test` | Inspects low state topics |
| `simple_command_publisher` | `booster_t1_webots_test` | Publishes zero `/cmd_vel` |

---

## 🔁 Sequence Diagrams

### Startup Sequence (Active Mode via `run_host_simulation.sh`)

```mermaid
sequenceDiagram
    participant User
    participant Script as run_host_simulation.sh
    participant Webots as Webots (Host)
    participant Container as Docker Container
    participant Runner as Booster Runner
    participant RPC as rpc_movement_client

    User->>Script: ./tools/run_host_simulation.sh forward 20.0
    Script->>Script: Kill existing Webots/mck processes
    Script->>Script: Extract vendor assets (if missing)
    Script->>Script: Copy corrected world file
    Script->>Webots: Launch with --port=1234 --extern-urls
    Note over Webots: Waiting for external controller on :1234
    Script->>Container: docker exec start_booster_webots_runner.sh
    Container->>Runner: Launch mck executable
    Runner->>Webots: Connect TCP:1234
    Note over Runner: WBC solver initializes
    Runner->>Container: Publish topics + expose RPC service
    Script->>Script: Wait for /booster_rpc_service
    Script->>Container: docker exec rpc_movement_client
    RPC->>Runner: Change Mode → kPrepare (api_id=2000)
    Note over Runner: Robot stands up (~3.5s)
    RPC->>Runner: Change Mode → kWalking (api_id=2000)
    Note over Runner: Robot enters walking mode (~1s)
    RPC->>Runner: Move forward (api_id=2001)
    Note over Runner: Robot walks for duration
    RPC->>Runner: Move stop (api_id=2001)
```

### RPC Walk Command Flow

```mermaid
sequenceDiagram
    participant Client as rpc_movement_client
    participant Service as /booster_rpc_service
    participant Runner as Booster Runner
    participant Webots as Webots Simulation

    Client->>Service: RpcService.Request(api_id=2000, body='{"mode":1}')
    Service->>Runner: Change to kPrepare mode
    Runner->>Webots: WBC standing sequence
    Service-->>Client: RpcService.Response(status=0)
    Note over Client: sleep 3.5s

    Client->>Service: RpcService.Request(api_id=2000, body='{"mode":2}')
    Service->>Runner: Change to kWalking mode
    Service-->>Client: RpcService.Response(status=0)
    Note over Client: sleep 1.0s

    Client->>Service: RpcService.Request(api_id=2001, body='{"vx":0.7,"vy":0.0,"vyaw":0.0}')
    Service->>Runner: Execute walk plan
    Runner->>Webots: Motor commands at 1kHz
    Service-->>Client: RpcService.Response(status=0)
    Note over Client: sleep duration

    Client->>Service: RpcService.Request(api_id=2001, body='{"vx":0.0,"vy":0.0,"vyaw":0.0}')
    Service->>Runner: Stop walking
    Service-->>Client: RpcService.Response(status=0)
```

### Passive State Bridge Flow

```mermaid
sequenceDiagram
    participant Script as start_webots_state_bridge.sh
    participant Container as Docker Container
    participant WSP as webots_state_publisher
    participant Webots as Webots (Host)
    participant Sub as joint_state_listener

    Script->>Container: docker exec (build + launch)
    Container->>WSP: webots-controller --protocol=tcp
    WSP->>Webots: Connect TCP:1234 as T1_release
    loop Every timestep (1ms)
        Webots->>WSP: Sensor data (12 joint positions)
        WSP->>WSP: Read position sensors
        WSP-->>Sub: Publish /joint_states
        WSP-->>Sub: Publish /booster_t1/joint_states
    end
```

---

## 📁 File / Directory Structure

```
ISEP-Challenge-Robotics/
├── containers/                     # Docker infrastructure
│   ├── Containerfile               # Docker image definition (ROS 2 Humble)
│   ├── docker_common.sh            # Shared Docker helper functions
│   ├── build_ros_container.sh      # Build the Docker image
│   ├── run_ros_container.sh        # Start interactive container
│   ├── enter_ros_container.sh      # Exec into running container
│   └── start_webots_state_bridge.sh  # Launch Passive Mode
│
├── tools/                          # Host-side automation scripts
│   ├── run_host_simulation.sh      # All-in-one Active Mode launcher
│   ├── start_booster_webots_runner.sh  # Start Booster runner inside container
│   └── check_booster_runner_assets.sh  # Validate vendor binaries
│
├── ros2_ws/                        # ROS 2 workspace
│   └── src/
│       ├── booster_ros2_interface/ # Custom message/service package (ament_cmake)
│       │   ├── msg/               # 20 message definitions
│       │   ├── srv/               # 2 service definitions
│       │   ├── CMakeLists.txt
│       │   └── package.xml
│       └── booster_t1_webots_test/ # Python node package (ament_python)
│           ├── booster_t1_webots_test/
│           │   ├── rpc_movement_client.py    # Walk command client
│           │   ├── rpc_commands.py           # RPC command definitions
│           │   ├── webots_state_publisher.py  # Passive state bridge
│           │   ├── joint_state_listener.py   # Joint state subscriber
│           │   ├── imu_listener.py           # IMU subscriber
│           │   ├── low_state_listener.py     # Low state inspector
│           │   ├── topic_listener.py         # Topic enumerator
│           │   ├── simple_command_publisher.py  # Zero cmd_vel publisher
│           │   ├── listener_base.py          # Subscription helper
│           │   └── message_formatters.py     # Log formatting utilities
│           ├── launch/
│           │   └── booster_t1_break_room.launch.py
│           ├── config/
│           ├── setup.py
│           └── package.xml
│
├── webots/                         # Webots simulation files
│   ├── worlds/
│   │   └── T1_break_room.wbt      # Physics-corrected world file
│   └── assets/                    # Booster robot meshes (gitignored)
│
├── external/                       # Vendor binaries (gitignored)
│   └── booster_runner/            # Official Booster runner files
│       ├── booster-runner-webots-full-*.run
│       ├── webots_simulation.zip
│       └── webots_updated.zip
│
├── .docker/                        # Runtime cache (gitignored)
│   ├── home/                      # Container home directory
│   ├── webots/                    # Extracted controller libraries
│   ├── booster_runner/            # Extracted simulation assets
│   ├── ros2_build/                # colcon build cache
│   └── ros2_install/              # colcon install cache
│
├── .logs/                          # Runtime logs (gitignored)
│   ├── host-webots-break-room.log
│   ├── host-webots-break-room.pid
│   ├── booster-webots-runner.log
│   └── booster-webots-runner.pid
│
├── docs/                           # Documentation
│   ├── ARCHITECTURE.md            # This file
│   ├── SETUP_LINUX.md
│   ├── SETUP_MACOS.md
│   ├── SETUP_WINDOWS.md
│   ├── API_REFERENCE.md
│   ├── CONTRIBUTING.md
│   ├── DOCKER_REFERENCE.md
│   ├── DEBUGGING.md
│   └── FINAL_REPORT.md
│
├── README.md
├── .gitignore
└── .dockerignore
```

---

## 🔗 Related Documentation

- [README](../README.md) — Quick start and overview
- [API Reference](API_REFERENCE.md) — Complete ROS 2 message, service, and topic reference
- [Docker Reference](DOCKER_REFERENCE.md) — Container infrastructure details
- [Setup: Linux](SETUP_LINUX.md) | [macOS](SETUP_MACOS.md) | [Windows](SETUP_WINDOWS.md) — Platform-specific installation guides
- [Debugging](DEBUGGING.md) — Troubleshooting guide
- [Contributing](CONTRIBUTING.md) — Development workflow
