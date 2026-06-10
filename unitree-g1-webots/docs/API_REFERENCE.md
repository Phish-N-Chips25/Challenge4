# ROS 2 API Reference

This document provides a comprehensive reference for the custom ROS 2 messages, services, and RPC commands used in the Booster T1 simulation environment.

## Custom Messages (`booster_interface/msg`)

The `booster_interface` package defines the following 20 custom message types used for telemetry and control.

### API & Core Control
*   **BoosterApiReqMsg**: `int64 api_id`, `string body` - Encapsulates an RPC request payload.
*   **BoosterApiRespMsg**: `int64 status`, `string body` - Encapsulates an RPC response payload.
*   **RawBytesMsg**: `char[] msg` - A simple raw byte array wrapper.

### Telemetry & State
*   **ImuState**: Contains IMU readings.
    *   `float32[3] rpy` (Roll, Pitch, Yaw)
    *   `float32[3] gyro` (Angular velocity)
    *   `float32[3] acc` (Linear acceleration)
*   **LowState**: Raw hardware state encapsulation.
    *   `ImuState imu_state`
    *   `MotorState[] motor_state_parallel`
    *   `MotorState[] motor_state_serial`
*   **RobotStatesMsg**: Current high-level robot mode.
    *   `int32 current_mode`
    *   `int32 current_body_control`
    *   `int32[] current_actions`
*   **FallDownState**: Fall detection and recovery tracking.
    *   `uint32 fall_down_state` (0=IS_READY, 1=IS_FALLING, 2=HAS_FALLEN, 3=IS_GETTING_UP)
    *   `bool is_recovery_available`
*   **Odometer**: Odometry tracking.
    *   `float32 x`, `float32 y`, `float32 theta`

### Motor & Joint Control
*   **MotorState**: Low-level state for a single motor.
    *   `int8 mode`, `float32 q` (position), `float32 dq` (velocity), `float32 ddq` (acceleration)
    *   `float32 tau_est` (estimated torque), `int8 temperature`
    *   `uint32 lost`, `uint32[2] reserve`
*   **MotorCmd**: Low-level command for a single motor.
    *   `int8 mode`, `float32 q`, `float32 dq`, `float32 tau`
    *   `float32 kp`, `float32 kd`, `float32 weight`
*   **LowCmd**: Array of motor commands.
    *   `int8 cmd_type` (0=CMD_TYPE_PARALLEL, 1=CMD_TYPE_SERIAL)
    *   `MotorCmd[] motor_cmd`

### Hands & Accessories
*   **HandActionStatus**: `uint32 hand_action`
*   **HandParam**: `int32 angle`, `int32 force`, `int32 speed`, `int32 seq`
*   **HandCommand**: `HandParam[] hand_param`, `int32 force_mode`, `int32 hand_index`, `int32 hand_type`
*   **HandDdsMsg**: `HandCommand[] hands_vec`

### UI & Remote Control
*   **ButtonEventMsg**: `int8 event`, `int32 button` (Constants for press, click, long press, etc.)
*   **RemoteControllerState**: Maps a standard gamepad.
    *   `uint32 event`, `float32 lx/ly/rx/ry`, `bool a/b/x/y/lb/rb/lt/rt/ls/rs/back/start`
    *   Hat switches: `bool hat_c/u/d/l/r/lu/ld/ru/rd`, `uint8 hat_pos`
*   **Subtitle**: Text data for UI/speech tracking.
    *   `string magic_number`, `string text`, `string language`, `string user_id`
    *   `int32 seq`, `bool definite`, `bool paragraph`, `int32 round_id`
*   **ProneBodyControlStatus**: `int32 posture`
*   **RobotReplayTrajID**: `string id`

---

## Custom Services (`booster_interface/srv`)

### 1. `RpcService.srv`
The primary interface for high-level walk planning and mode switching.
*   **Request**: `booster_interface/BoosterApiReqMsg msg`
*   **Response**: `booster_interface/BoosterApiRespMsg msg`

### 2. `AgentService.srv`
Used for generic string-based agent commands.
*   **Request**: `string body`
*   **Response**: `string body`

---

## RPC Commands Reference

The `rpc_movement_client` uses `RpcService` with specific `api_id` integer values and JSON-encoded `body` payloads.

### API ID `2000`: Change Mode
Changes the high-level controller state machine.
*   **Payload Schema**: `{"mode": <int>}`
*   **Valid Modes**:
    *   `0` = Damping (relax joints)
    *   `1` = Prepare (stand up)
    *   `2` = Walking (ready for move commands)
    *   `3` = Custom

### API ID `2001`: Move
Issues a velocity command to the walk planner. The robot MUST be in `Walking` mode (2) to accept these.
*   **Payload Schema**: `{"vx": <float>, "vy": <float>, "vyaw": <float>}`
*   **Parameters**:
    *   `vx`: Forward/backward velocity (m/s)
    *   `vy`: Left/right strafing velocity (m/s)
    *   `vyaw`: Rotational velocity (rad/s)

### Standard Movement Speeds
| Command | `vx` | `vy` | `vyaw` |
|---|---|---|---|
| `forward` | `0.7` | `0.0` | `0.0` |
| `backward` | `-0.1` | `0.0` | `0.0` |
| `left` | `0.0` | `0.1` | `0.0` |
| `right` | `0.0` | `-0.1` | `0.0` |
| `turn_left` | `0.0` | `0.0` | `0.2` |
| `turn_right` | `0.0` | `0.0` | `-0.2` |
| `stop` | `0.0` | `0.0` | `0.0` |

---

## Published Topics

| Topic | Message Type | Mode Available |
|---|---|---|
| `/booster_t1/joint_states` | `sensor_msgs/JointState` | Active / Passive |
| `/joint_states` | `sensor_msgs/JointState` | Active / Passive |
| `/booster_t1/imu` | `sensor_msgs/Imu` | Active Only |
| `/booster_t1/low_state` | `booster_interface/LowState` | Active Only |
| `/cmd_vel` | `geometry_msgs/Twist` | N/A (Standardized fallback) |

### Joint Names
The Booster T1 has 12 leg joints, tracked in this order:
1.  `Left_Hip_Pitch`
2.  `Left_Hip_Roll`
3.  `Left_Hip_Yaw`
4.  `Left_Knee_Pitch`
5.  `Left_Ankle_Pitch`
6.  `Left_Ankle_Roll`
7.  `Right_Hip_Pitch`
8.  `Right_Hip_Roll`
9.  `Right_Hip_Yaw`
10. `Right_Knee_Pitch`
11. `Right_Ankle_Pitch`
12. `Right_Ankle_Roll`
