from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / "worlds" / "sentinelmas_office.wbt"


class BoosterIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world_text = WORLD.read_text(encoding="utf-8")

    def test_world_exposes_booster_t1_external_controller(self):
        self.assertIn("DEF BOOSTER_T1 Robot", self.world_text)
        self.assertNotIn("DEF PATROL_ROBOT Robot", self.world_text)
        self.assertIn("translation 9 0 0.6524744793109749", self.world_text)
        self.assertIn("rotation 0 0 1 3.14159", self.world_text)
        self.assertIn('name "T1_release"', self.world_text)
        self.assertIn('controller "<extern>"', self.world_text)
        self.assertIn("basicTimeStep 1", self.world_text)

    def test_all_t1_mesh_references_resolve_next_to_world(self):
        mesh_dir = ROOT / "worlds" / "T1_release_meshes"
        self.assertFalse(mesh_dir.is_symlink(), f"{mesh_dir} must be a real local directory")

        mesh_refs = sorted(set(re.findall(r'"\./T1_release_meshes/([^"]+\.STL)"', self.world_text)))

        self.assertGreater(len(mesh_refs), 30)
        missing = [
            str(mesh_dir / mesh_name)
            for mesh_name in mesh_refs
            if not (mesh_dir / mesh_name).is_file() or (mesh_dir / mesh_name).is_symlink()
        ]

        self.assertEqual([], missing)

    def test_ros2_booster_service_packages_are_local(self):
        required_paths = [
            ROOT / "ros2_ws" / "src" / "booster_ros2_interface" / "srv" / "RpcService.srv",
            ROOT / "ros2_ws" / "src" / "booster_ros2_interface" / "msg" / "BoosterApiReqMsg.msg",
            ROOT / "ros2_ws" / "src" / "booster_ros2_interface" / "msg" / "BoosterApiRespMsg.msg",
            ROOT / "ros2_ws" / "src" / "booster_t1_webots_test" / "booster_t1_webots_test" / "rpc_movement_client.py",
            ROOT / "ros2_ws" / "src" / "booster_t1_webots_test" / "booster_t1_webots_test" / "rpc_commands.py",
        ]

        missing = [str(path) for path in required_paths if not path.is_file()]
        self.assertEqual([], missing)

    def test_safe_booster_dock_path_is_documented_and_runnable(self):
        script = (ROOT / "tools" / "run_sentinelmas_booster.sh").read_text(encoding="utf-8")
        reference = (ROOT / "docs" / "BOOSTER_T1_ROS2_REFERENCE.md").read_text(encoding="utf-8")
        patrol_doc = (ROOT / "docs" / "PATROL_ROBOT.md").read_text(encoding="utf-8")
        supervisor = (ROOT / "controllers" / "security_supervisor" / "security_supervisor.py").read_text(encoding="utf-8")

        self.assertIn('COMMAND="${1:-safe_dock_path}"', script)
        self.assertIn("safe_dock_path", reference)
        self.assertIn("translation 9 0 0.6524744793109749", reference)
        self.assertIn("safe_dock_path", patrol_doc)
        self.assertIn('sup.getFromDef("BOOSTER_T1")', supervisor)
        self.assertIn("Do not move the robot by writing directly", reference)
        self.assertIn("/booster_rpc_service", patrol_doc)
        self.assertIn("legacy-only", patrol_doc)

    def test_runner_uses_local_dependencies_instead_of_worktree_paths(self):
        script = (ROOT / "tools" / "run_sentinelmas_booster.sh").read_text(encoding="utf-8")

        self.assertNotIn(".worktree", script)
        self.assertIn('source "${CHALLENGE_ROOT}/containers/docker_common.sh"', script)
        self.assertIn('WORLD_FILE="${CHALLENGE_ROOT}/worlds/sentinelmas_office.wbt"', script)
        self.assertIn('WEBOTS_MODE="${WEBOTS_MODE:-realtime}"', script)
        self.assertIn('"--mode=${WEBOTS_MODE}"', script)
        self.assertIn("--no-prepare", script)
        self.assertIn("Waiting for Booster patrol walking mode", script)
        self.assertIn("Walking mode ready.", script)
        self.assertIn("Waiting for Webots external controller connection", script)
        self.assertIn("extern controller: connected", script)
        self.assertIn('WEBOTS_BATCH="${WEBOTS_BATCH:-1}"', script)
        self.assertIn('WARNING: Webots process', script)
        self.assertIn("FASTDDS_DEFAULT_PROFILES_FILE", script)
        self.assertIn("Waiting for Booster FastDDS profile", script)
        self.assertIn('find /tmp -maxdepth 3 -name "fastdds_profile.xml"', script)
        self.assertIn("ros2 daemon stop", script)
        self.assertIn("assert_booster_runner_healthy", script)
        self.assertIn("copy_robot_config.sh: No such file or directory", script)
        self.assertIn("/opt/booster/configs/system_settings_config.yaml", script)
        self.assertIn("/opt/booster/configs/robot_config.yaml", script)
        self.assertIn("Load robot config file failed", script)

        required_paths = [
            ROOT / "containers" / "Containerfile",
            ROOT / "containers" / "docker_common.sh",
            ROOT / "containers" / "build_ros_container.sh",
            ROOT / "containers" / "run_ros_container.sh",
            ROOT / "tools" / "check_booster_runner_assets.sh",
            ROOT / "tools" / "start_booster_webots_runner.sh",
            ROOT / "docker-compose.yml",
            ROOT / "external" / "booster_runner" / "webots_simulation.zip",
            ROOT / "external" / "booster_runner" / "webots_updated.zip",
        ]

        missing = [str(path) for path in required_paths if not path.exists()]
        self.assertEqual([], missing)

    def test_docker_configuration_targets_booster_runner_runtime(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        docker_common = (ROOT / "containers" / "docker_common.sh").read_text(encoding="utf-8")
        build_script = (ROOT / "containers" / "build_ros_container.sh").read_text(encoding="utf-8")
        run_script = (ROOT / "containers" / "run_ros_container.sh").read_text(encoding="utf-8")

        for env_name in [".env", ".env.macos", ".env.linux", ".env.windows"]:
            self.assertTrue((ROOT / env_name).is_file(), f"missing {env_name}")

        self.assertIn("platform: ${DOCKER_PLATFORM:-linux/amd64}", compose)
        self.assertIn("WEBOTS_HOST_IP=${WEBOTS_HOST_IP:-host.docker.internal}", compose)
        self.assertIn("DOCKER_PLATFORM=linux/amd64", (ROOT / ".env").read_text(encoding="utf-8"))
        self.assertIn("WEBOTS_HOST_IP=host.docker.internal", (ROOT / ".env.macos").read_text(encoding="utf-8"))
        self.assertIn("--platform", docker_common)
        self.assertIn("load_project_env", docker_common)
        self.assertIn("load_project_env", build_script)
        self.assertIn("load_project_env", run_script)

    def test_supervisor_does_not_mutate_static_door_proto_can_be_open(self):
        supervisor = (
            ROOT / "controllers" / "security_supervisor" / "security_supervisor.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn('getField("canBeOpen")', supervisor)
        self.assertNotIn("setSFBool", supervisor)

    def test_default_open_doors_stay_within_door_proto_position_limit(self):
        supervisor = (
            ROOT / "controllers" / "security_supervisor" / "security_supervisor.py"
        ).read_text(encoding="utf-8")

        for door_def in ("DOOR_ENTRANCE", "DOOR_BREAK"):
            match = re.search(
                rf"DEF {door_def} Door \{{(?P<body>.*?)\n\}}",
                self.world_text,
                re.DOTALL,
            )
            self.assertIsNotNone(match, f"missing {door_def}")
            self.assertIn("position -1.0", match.group("body"))
            self.assertNotIn("position 1.5", match.group("body"))

        self.assertIn("DOOR_OPEN_POSITION = -1.0", supervisor)

    def test_supervisor_logs_booster_height_for_motion_diagnostics(self):
        supervisor = (
            ROOT / "controllers" / "security_supervisor" / "security_supervisor.py"
        ).read_text(encoding="utf-8")

        self.assertIn("rx, ry, rz", supervisor)
        self.assertIn('z={rz:.3f}', supervisor)

    def test_webots_state_bridge_publishes_corrected_odometry_and_diagnostics(self):
        publisher = (
            ROOT
            / "ros2_ws"
            / "src"
            / "booster_t1_webots_test"
            / "booster_t1_webots_test"
            / "webots_state_publisher.py"
        ).read_text(encoding="utf-8")
        topics = (
            ROOT
            / "ros2_ws"
            / "src"
            / "booster_t1_webots_test"
            / "config"
            / "topics.yaml"
        ).read_text(encoding="utf-8")
        reference = (ROOT / "docs" / "BOOSTER_T1_ROS2_REFERENCE.md").read_text(
            encoding="utf-8"
        )

        self.assertIn('robot.getDevice("torso gps")', publisher)
        self.assertIn('robot.getDevice("torso inertial unit")', publisher)
        self.assertIn('"/booster_t1/odom"', publisher)
        self.assertIn('"/booster_t1/odometer"', publisher)
        self.assertIn('"/booster_t1/odometry_diagnostics"', publisher)
        self.assertIn('"/odometer_state"', publisher)
        self.assertIn("/booster_t1/odom", topics)
        self.assertIn("/booster_t1/odometry_diagnostics", topics)
        self.assertIn("Webots-derived odometry", reference)

    def test_sentinelmas_runner_starts_pose_file_odometry_bridge(self):
        script = (ROOT / "tools" / "run_sentinelmas_booster.sh").read_text(
            encoding="utf-8"
        )
        supervisor = (
            ROOT / "controllers" / "security_supervisor" / "security_supervisor.py"
        ).read_text(encoding="utf-8")
        setup = (
            ROOT / "ros2_ws" / "src" / "booster_t1_webots_test" / "setup.py"
        ).read_text(encoding="utf-8")

        self.assertIn("pose_file_odometry_publisher", setup)
        self.assertIn("pose_file_odometry_publisher", script)
        self.assertIn("sim_lidar_pointcloud_node", setup)
        self.assertIn("sim_lidar_pointcloud_node", script)
        self.assertIn("BOOSTER_POSE_FILE=/workspace/project/.logs/booster_pose.json", script)
        self.assertIn("BOOSTER_POINTCLOUD_FILE=/workspace/project/.logs/booster_pointcloud.json", script)
        self.assertIn("booster_pose.json", supervisor)
        self.assertIn("write_booster_pose_file", supervisor)

    # ── Booster /opt config install glue (replacement for vendor copy_robot_config.sh) ──

    def test_booster_opt_installer_exists_and_is_actionable(self):
        installer = ROOT / "tools" / "install_booster_opt.sh"
        self.assertTrue(installer.is_file(), "missing tools/install_booster_opt.sh")
        self.assertTrue(os.access(installer, os.X_OK), "install_booster_opt.sh must be executable")

        text = installer.read_text(encoding="utf-8")
        # documents what it replaces and where the vendor data comes from
        self.assertIn("copy_robot_config.sh", text)
        self.assertIn("booster_config/booster_configs", text)
        self.assertIn("Booster_T1", text)
        self.assertIn("T1_2.3.4", text)
        # installs the exact hardcoded paths the runtime loads
        self.assertIn("/opt/booster/configs/robot_config.yaml", text)
        self.assertIn("/opt/booster/configs/system_settings_config.yaml", text)
        self.assertIn("robot_info.txt", text)
        # populates the container's root-owned /opt as root
        self.assertIn("docker exec", text)
        self.assertIn("-u 0", text)
        # documents the drop-in location for the vendor repo
        self.assertIn("external/booster_runner/booster_config", text)

    def test_booster_opt_installer_reports_missing_vendor_config(self):
        installer = ROOT / "tools" / "install_booster_opt.sh"
        self.assertTrue(installer.is_file(), "missing tools/install_booster_opt.sh")

        with tempfile.TemporaryDirectory() as empty:
            env = dict(os.environ, BOOSTER_OPT_SRC=empty)
            result = subprocess.run(
                ["bash", str(installer)],
                capture_output=True,
                text=True,
                env=env,
                cwd=str(ROOT),
            )

        self.assertNotEqual(result.returncode, 0, "installer must fail when vendor config is absent")
        combined = result.stdout + result.stderr
        self.assertIn("external/booster_runner/booster_config", combined)
        self.assertIn("robot_config.yaml", combined)
        self.assertIn("/opt/booster", combined)

    def test_booster_opt_installer_has_optional_simulation_mode(self):
        installer = ROOT / "tools" / "install_booster_opt.sh"
        self.assertTrue(installer.is_file(), "missing tools/install_booster_opt.sh")

        with tempfile.TemporaryDirectory() as empty:
            env = dict(os.environ, BOOSTER_OPT_SRC=empty, BOOSTER_OPT_OPTIONAL="1")
            result = subprocess.run(
                ["bash", str(installer)],
                capture_output=True,
                text=True,
                env=env,
                cwd=str(ROOT),
            )

        self.assertNotEqual(result.returncode, 0, "optional mode still signals missing config to caller")
        combined = result.stdout + result.stderr
        self.assertIn("NOTE: Booster vendor /opt config was not found", combined)
        self.assertNotIn("ERROR: Booster locomotion config not found", combined)

    def test_launcher_installs_booster_opt_before_runner(self):
        script = (ROOT / "tools" / "run_sentinelmas_booster.sh").read_text(encoding="utf-8")

        self.assertIn("install_booster_opt.sh", script)
        self.assertIn("BOOSTER_OPT_OPTIONAL=1", script)
        # absence of vendor data must NOT abort the Webots scenario launch
        self.assertIn("continuing without Booster locomotion config", script)
        # installer runs before the runner is started
        install_idx = script.index("install_booster_opt.sh")
        runner_idx = script.index("start_booster_webots_runner.sh")
        self.assertLess(install_idx, runner_idx)

    def test_patrol_doc_documents_opt_booster_install(self):
        patrol_doc = (ROOT / "docs" / "PATROL_ROBOT.md").read_text(encoding="utf-8")

        self.assertIn("install_booster_opt.sh", patrol_doc)
        self.assertIn("booster_config/booster_configs/Booster_T1/T1_2.3.4", patrol_doc)
        self.assertIn("/opt/booster/configs", patrol_doc)

    # ── 0.0.10 is the sim-capable runner; 0.0.11 regressed (hard /opt/booster dep) ──

    def test_runner_scripts_prefer_sim_capable_010_runner(self):
        for rel in (
            "tools/start_booster_webots_runner.sh",
            "tools/check_booster_runner_assets.sh",
        ):
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("booster-runner-webots-full-0.0.10.run", text, rel)
            # the explicit BOOSTER_RUNNER_PATH override must still win first
            path_idx = text.index("BOOSTER_RUNNER_PATH")
            pref_idx = text.index("booster-runner-webots-full-0.0.10.run")
            self.assertLess(path_idx, pref_idx, rel)

    def test_sim_capable_010_runner_is_present_locally(self):
        runner = ROOT / "external" / "booster_runner" / "booster-runner-webots-full-0.0.10.run"
        self.assertTrue(runner.is_file(), "0.0.10 sim runner must be present in external/booster_runner")
        self.assertFalse(runner.is_symlink())
        # ~88.5 MB; floor below the previous 90 MB check that this build trips
        self.assertGreater(runner.stat().st_size, 80_000_000)

    def test_asset_check_size_floor_admits_010_runner(self):
        check = (ROOT / "tools" / "check_booster_runner_assets.sh").read_text(encoding="utf-8")
        self.assertNotIn("require_min_size \"${RUNNER}\" 90000000", check)

    def test_patrol_doc_explains_runner_version_regression(self):
        patrol_doc = (ROOT / "docs" / "PATROL_ROBOT.md").read_text(encoding="utf-8")
        self.assertIn("0.0.10", patrol_doc)
        self.assertIn("0.0.11", patrol_doc)

    # ── Hybrid: 0.0.10 mck locomotion + 0.0.11 rpc_service_node bridge over shared DDS ──

    def test_runner_script_grafts_bridge_for_sim_capable_motion_runner(self):
        script = (ROOT / "tools" / "start_booster_webots_runner.sh").read_text(encoding="utf-8")
        # extracts the motion runner to a stable dir and grafts a bridge if absent
        self.assertIn("booster_ros2/install", script)
        self.assertIn("Grafting ROS bridge", script)
        self.assertIn("resolve_bridge_runner", script)
        self.assertIn("booster-simulate-webots-run.sh", script)
        self.assertIn("COLCON_CURRENT_PREFIX", script)
        # the bridge donor must exclude the bridge-less 0.0.10 runner
        self.assertIn("! -name '*0.0.10*'", script)

    def test_bridge_script_exists_and_is_actionable(self):
        bridge = ROOT / "tools" / "start_booster_bridge.sh"
        self.assertTrue(bridge.is_file(), "missing tools/start_booster_bridge.sh")
        self.assertTrue(os.access(bridge, os.X_OK), "start_booster_bridge.sh must be executable")
        text = bridge.read_text(encoding="utf-8")
        self.assertIn("rpc_service_node", text)
        self.assertIn("COLCON_CURRENT_PREFIX", text)
        # bridge donor excludes the bridge-less 0.0.10 runner
        self.assertIn("! -name '*0.0.10*'", text)
        # must share mck's FastDDS profile (the grafted motion profile)
        self.assertIn("fastdds_profile.xml", text)

    def test_launcher_starts_bridge_between_profile_and_service(self):
        script = (ROOT / "tools" / "run_sentinelmas_booster.sh").read_text(encoding="utf-8")
        self.assertIn("start_booster_bridge.sh", script)
        # stale bridge is cleaned up alongside mck
        self.assertIn("pkill -9 -f rpc_service_node", script)
        # bridge starts after the FastDDS profile exists, before the service wait
        profile_idx = script.index("Waiting for Booster FastDDS profile")
        bridge_idx = script.index("start_booster_bridge.sh")
        service_idx = script.index("Waiting for /booster_rpc_service")
        self.assertLess(profile_idx, bridge_idx)
        self.assertLess(bridge_idx, service_idx)


if __name__ == "__main__":
    unittest.main()
