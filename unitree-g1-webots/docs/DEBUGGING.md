# Debugging Notes

## Apple Container networking

Observed inside a short-lived ROS container:

```txt
default via 192.168.64.1 dev eth0
192.168.64.0/24 dev eth0 proto kernel scope link src 192.168.64.7
nameserver 192.168.64.1
domain biscoito
hostname -I: 192.168.64.7
```

`host.containers.internal` and `host.docker.internal` did not resolve.

Do not assume Docker host networking. Prefer keeping ROS 2 nodes inside Apple Container and connect Webots deliberately through `webots_ros2` or a Webots external controller.

## Webots host process

Webots is installed at:

```bash
/Applications/Webots.app/Contents/MacOS/webots
```

Version:

```txt
Webots version: R2025a
```

The command `webots` is not on PATH.

## Webots extern controller connection

Batch load check:

```bash
/Applications/Webots.app/Contents/MacOS/webots --batch --mode=fast --stdout --stderr webots/worlds/break_room.wbt
```

Observed:

```txt
INFO: 'booster_t1' extern controller: Waiting for local or remote connection on port 1234 targeting robot named 'booster_t1'.
INFO: 'booster_t1' extern controller: disconnected.
```

This confirms Webots parses the world and starts the external controller wait path. The disconnect is expected when no external controller is attached during the batch smoke test.

## ROS 2 topic discovery

Without Webots ROS bridge data, the container saw:

```txt
/parameter_events
/rosout
```

Use these checks after starting Webots and any bridge/controller:

```bash
ros2 node list
ros2 topic list
ros2 topic list -t
ros2 topic list | grep -E "low_state|joint_ctrl|booster|t1|imu|joint" || true
```

## DDS/multicast issues

Apple Container uses a VM network in the `192.168.64.0/24` range. If ROS 2 discovery does not cross host/container boundaries, keep the ROS 2 graph inside the container and bridge through a Webots external controller or explicit ports rather than relying on multicast across the host boundary.

## Mesh/PROTO import issues

`BoosterT1.proto` uses relative mesh URLs like:

```txt
../assets/booster_assets/robots/T1/meshes/Trunk.STL
```

If Webots cannot load meshes, confirm this directory exists:

```bash
ls webots/assets/booster_assets/robots/T1/meshes
```

If assets are missing:

```bash
git clone https://github.com/BoosterRobotics/booster_assets.git webots/assets/booster_assets
./tools/import_booster_t1_proto.sh
```

## URDF conversion issues

Direct host `pip install --user urdf2webots` failed because Python is externally managed by Homebrew. The repo script creates `.venv` and installs `urdf2webots` there.

The successful conversion command was:

```bash
python -m urdf2webots.importer \
  --input webots/assets/booster_assets/robots/T1/T1_locomotion.urdf \
  --output webots/protos/BoosterT1.proto \
  --target R2025a
```

## Common errors and fixes

### Missing standard Webots PROTO declarations

Initial batch load failed until these lines were added to `break_room.wbt`:

```txt
EXTERNPROTO "https://raw.githubusercontent.com/cyberbotics/webots/R2025a/projects/objects/backgrounds/protos/TexturedBackground.proto"
EXTERNPROTO "https://raw.githubusercontent.com/cyberbotics/webots/R2025a/projects/objects/backgrounds/protos/TexturedBackgroundLight.proto"
EXTERNPROTO "https://raw.githubusercontent.com/cyberbotics/webots/R2025a/projects/objects/floors/protos/Floor.proto"
```

### ROS 2 scripts not found

`ros2 run booster_t1_webots_test topic_listener` initially returned `No executable found`. Adding `setup.cfg` fixed the install path:

```ini
[develop]
script_dir=$base/lib/booster_t1_webots_test

[install]
install_scripts=$base/lib/booster_t1_webots_test
```

## Platform-Specific Troubleshooting

### Linux
- **Host Networking**: If you cannot see ROS 2 topics from the host, ensure the container is running with `--network host` (using `.env.linux` overrides).
- **Permissions**: If Webots fails to start from the script, verify `/usr/local/webots/webots` is in your `$PATH` or the `$WEBOTS_PATH` env var points to the correct location.

### macOS
- **Performance**: Apple Silicon Macs run the amd64 ROS 2 image via Rosetta 2 emulation. This is normal but may cause higher CPU usage.
- **Networking**: `host.docker.internal` is required to reach Webots on the Mac host from the container. `--network host` does NOT work on Docker Desktop for Mac.

### Windows
- **WSL2 Integration**: Ensure Docker Desktop is set to use the WSL2 backend and integration is enabled for your specific Ubuntu distro in Docker Desktop settings.
- **Firewall**: Windows Defender Firewall may block traffic from the WSL2 subnet to the Webots executable on port `1234`. You may need to add an inbound rule allowing `webots.exe`.

## Docker Networking Issues

- **Container can't reach Webots**: Verify `WEBOTS_HOST_IP` in `.env.local` is correct for your platform (`127.0.0.1` for Linux, `host.docker.internal` for Mac/Windows).
- **Port Conflicts**: Ensure port `1234` is not in use by another application before starting Webots.

## Webots Connection Timeouts

If the Booster runner or state bridge fails to connect to Webots:
1.  Verify Webots is actually running and has the world `T1_break_room.wbt` loaded.
2.  Check the Webots console output. It should say: `INFO: 'T1_release' extern controller: Waiting for local or remote connection on port 1234`.
3.  Test TCP connectivity from inside the container:
    ```bash
    docker compose exec ros2 bash -c "nc -zv \$WEBOTS_HOST_IP 1234"
    ```

## GPU Verification

To verify GPU passthrough is working (Linux/WSL2 only):
1.  **NVIDIA SMI**: Run `docker compose exec ros2 nvidia-smi`. It should display your GPU details.
2.  **OpenGL Rendering**: Run `docker compose exec ros2 glxinfo -B`. Ensure the vendor string says "NVIDIA Corporation" and not "Mesa" or "llvmpipe".

## Log File Locations

-   **Host Webots Output**: `.logs/host-webots-break-room.log`
-   **Booster Runner Output**: `.logs/booster-webots-runner.log`
-   **ROS 2 Logs**: Inside the container at `~/.ros/log/` or `/workspace/project/ros2_ws/log/`

## Common Error Messages

| Error Message | Likely Cause | Solution |
|---|---|---|
| `Connection refused` (port 1234) | Webots is not running or blocked by firewall. | Start Webots first. Check Windows Firewall rules. Verify `WEBOTS_HOST_IP`. |
| `No executable found` (ROS 2 run) | Workspace not sourced or package not built. | Run `source install/setup.bash`. Ensure `colcon build` succeeded. |
| `Instant solver divergence` | `basicTimeStep` is > 1ms. | Revert any changes to `basicTimeStep` in the `.wbt` file back to `1`. |
| `cannot execute binary file: Exec format error` | Wrong architecture binary. | The Booster runner is Linux x86_64. Ensure it's running *inside* the container, not natively on Mac/Windows. |

## Quick Diagnostic Script

Run these commands inside your environment to check the health of the setup:

```bash
# 1. Check Docker container status
docker compose ps

# 2. Test TCP connection to Webots from container
docker compose exec ros2 bash -c 'echo > /dev/tcp/$WEBOTS_HOST_IP/1234 && echo "Webots Reachable" || echo "Webots UNREACHABLE"'

# 3. List active ROS 2 topics
docker compose exec ros2 bash -c 'source /opt/ros/humble/setup.bash && ros2 topic list'

# 4. Check Webots runner logs for errors
tail -n 20 .logs/booster-webots-runner.log
```
