"""ppo_patrol_node — the trained PPO policy drives the Booster T1.

Part 2 of the "SIMAGIA decides, PPO drives" integration:

  SIMAGIA (Contract Net auction)  --mission-->  .logs/booster_missions.jsonl
       |                                              |
       | (Part 1: booster_mission_bridge)             v
       |                                       THIS NODE
       |   reuses PatrolStateMachine (mission queue / states / status /
       |   return-to-dock) but swaps the lidar NavigationManager for a
       |   PPO-backed navigator that produces body-frame velocity from the
       |   trained policy and the robot's real odometry.
       v
  /booster_rpc_service  <--make_move_request(vx,vy,vyaw)--  PPONavAdapter

Why an adapter instead of a rewrite: the colleague's PatrolStateMachine is
ROS-free and drives waypoints through any object exposing a `go_to()` /
`update_pose()` interface (their lidar NavigationManager is one such object).
PPONavAdapter is another — it just computes velocity with PPONavigator instead
of a lidar planner. So the whole mission/state machinery is reused unchanged.

Scope: PPO handles the zone-targeted missions it was trained for
(`investigate`, `assist`). `detain` (chasing a *moving* target) needs dynamic
obstacle avoidance the PPO+A* layer doesn't have, so for detain the lidar
`booster_patrol_node` remains the better driver — run that node instead when
detain behaviour matters.

Requirements (see Containerfile + docker-compose RL mount):
  - torch / stable-baselines3 / gymnasium in the container
  - the RL nav code on PPO_RL_DIR (default /workspace/rl) with the trained
    model at PPO_MODEL_PATH (default /workspace/rl/data/models/nav_ppo_final)
  - SENTINEL_WBT_PATH pointing at the office world so the planner's wall
    geometry matches the simulated world

NOTE: this is structurally complete but UNTESTED end-to-end — it cannot run
until the vendor /opt/booster walk config lets the robot actually walk. The
PPO/odometry/RPC contract is the same one validated offline in policy_runner;
the parts that need on-robot tuning are flagged with `# TUNE:` below.
"""
from __future__ import annotations

import math
import os
import sys
import time
from pathlib import Path

from .booster_patrol_node import PatrolStateMachine
from .navigation_manager import NavigationStatus
from .patrol_types import Pose2D
from .precision_control import PrecisionLimits, shape_velocity

# Distance (m) at which a waypoint counts as reached. TUNE: on the real biped,
# a slightly larger radius avoids hovering/oscillating at the exact point.
PPO_ARRIVE_DISTANCE = 0.40


def _limits_from_env() -> PrecisionLimits:
    """Build the precision-layer envelope, overridable via BOOSTER_PPO_* env."""
    def f(name: str, default: float) -> float:
        try:
            return float(os.environ.get(name, "") or default)
        except ValueError:
            return default

    return PrecisionLimits(
        turn_in_place=f("BOOSTER_PPO_TURN_IN_PLACE", PrecisionLimits.turn_in_place),
        max_vx=f("BOOSTER_PPO_MAX_VX", PrecisionLimits.max_vx),
        max_vyaw=f("BOOSTER_PPO_MAX_VYAW", PrecisionLimits.max_vyaw),
        walk_yaw=f("BOOSTER_PPO_WALK_YAW", PrecisionLimits.walk_yaw),
        turn_kp=f("BOOSTER_PPO_TURN_KP", PrecisionLimits.turn_kp),
        slow_radius=f("BOOSTER_PPO_SLOW_RADIUS", PrecisionLimits.slow_radius),
    )


class PPONavAdapter:
    """navigation_manager-compatible driver backed by the trained PPO policy.

    Implements the subset of the NavigationManager interface that
    PatrolStateMachine uses: update_pose(), update_lidar() (ignored), and
    go_to() returning a NavigationStatus. Velocity is produced closed-loop from
    the policy and the robot's *real* odometry heading (not a kinematic model),
    then sent over RPC.
    """

    def __init__(self, rpc, navigator, logger=None, arrive_distance=PPO_ARRIVE_DISTANCE,
                 limits: PrecisionLimits | None = None):
        self.rpc = rpc
        self.nav = navigator           # policy_runner.PPONavigator
        self.env = navigator._env      # OfficeNavEnv — obs encoding + action rescale
        self.logger = logger or (lambda _m: None)
        self.arrive_distance = arrive_distance
        # Deterministic precision layer applied on top of the PPO command so the
        # physics biped tracks the planned waypoints (stop-turn-go, no crabbing,
        # speed caps). See precision_control.shape_velocity.
        self.limits = limits or PrecisionLimits()
        self._was_turning: bool | None = None
        self.pose: Pose2D | None = None
        # previous *normalised* action — obs slots 7..9 (kept so the policy sees
        # the same action-history feature it was trained with).
        self._prev_norm = (0.0, 0.0, 0.0)

    # -- pose / sensor hooks --------------------------------------------------

    def update_pose(self, pose: Pose2D, now: float) -> None:
        self.pose = pose

    def update_lidar(self, points, now: float) -> None:
        # PPO + A* route around *static* walls only; lidar is unused here.
        # (detain / dynamic avoidance is the lidar booster_patrol_node's job.)
        return None

    # -- the one method PatrolStateMachine drives -----------------------------

    def go_to(self, target, now, arrive_distance=None, forward_speed=None) -> NavigationStatus:
        if self.pose is None:
            return NavigationStatus.RUNNING

        arrive = arrive_distance or self.arrive_distance
        dist = math.hypot(target[0] - self.pose.x, target[1] - self.pose.y)
        if dist <= arrive:
            self.rpc.stop()
            self._prev_norm = (0.0, 0.0, 0.0)
            return NavigationStatus.ARRIVED

        # Closed-loop policy query: observe (real pose+heading, goal, prev action)
        # -> normalised action -> real (vx, vy, vyaw). Same contract as
        # PPONavigator.velocity_command, but we keep the normalised action so the
        # obs history feature stays consistent across ticks.
        norm = self.nav._predict_norm(
            (float(self.pose.x), float(self.pose.y), float(self.pose.theta)),
            (float(target[0]), float(target[1])),
            self._prev_norm,
        )
        self._prev_norm = tuple(float(v) for v in norm)
        vx, vy, vyaw = (float(v) for v in self.env._rescale_action(norm))

        # Precision layer: shape the policy command into a stop-turn-go motion the
        # physics gait can track precisely (align before moving, no crabbing,
        # capped/slowed speeds) instead of arcing into walls.
        shaped = shape_velocity(self.pose, target, vx, vy, vyaw, self.limits)
        if shaped.turning_in_place != self._was_turning:
            self._was_turning = shaped.turning_in_place
            mode = "turn_in_place" if shaped.turning_in_place else "walk"
            self.logger(
                f"[ppo_precision] mode={mode} target=({target[0]:.2f},{target[1]:.2f}) "
                f"policy=({vx:.2f},{vy:.2f},{vyaw:.2f}) "
                f"shaped=({shaped.vx:.2f},{shaped.vy:.2f},{shaped.vyaw:.2f})"
            )
        self.rpc.move(shaped.vx, shaped.vy, shaped.vyaw)
        return NavigationStatus.RUNNING


# ── Minimal RPC adapter (mirrors booster_patrol_node's nested RpcAdapter) ─────

def _build_rpc_adapter(rclpy, rpc_node, client, log_info, log_warn, log_error):
    """Returns an object with .move(vx,vy,vyaw) and .stop(), de-duplicating
    identical commands with a keep-alive period (the RPC streams a velocity)."""
    from booster_interface.msg import BoosterApiReqMsg
    from booster_interface.srv import RpcService
    from .rpc_commands import make_move_request

    keepalive = float(os.environ.get("BOOSTER_RPC_KEEPALIVE_PERIOD", "0.5") or 0.5)

    class _Rpc:
        def __init__(self):
            self._last = None
            self._last_at = -1e9

        def _call(self, api_id, body):
            if not rclpy.ok():
                return False
            req = RpcService.Request()
            req.msg = BoosterApiReqMsg()
            req.msg.api_id = int(api_id)
            req.msg.body = body
            try:
                future = client.call_async(req)
                rclpy.spin_until_future_complete(rpc_node, future, timeout_sec=5.0)
                result = future.result()
            except Exception as exc:
                log_error(f"RPC exception api_id={api_id} error={exc}")
                return False
            if result is None:
                log_error(f"RPC failed api_id={api_id}")
                return False
            if result.msg.status != 0:
                log_warn(f"RPC api_id={api_id} status={result.msg.status} body={result.msg.body!r}")
            return result.msg.status == 0

        def move(self, vx, vy, vyaw):
            cmd = (round(float(vx), 3), round(float(vy), 3), round(float(vyaw), 3))
            now = time.time()
            if cmd == self._last and now - self._last_at < keepalive:
                return True
            req = make_move_request(vx, vy, vyaw)
            ok = self._call(req.api_id, req.body)
            if ok:
                self._last, self._last_at = cmd, now
            return ok

        def stop(self):
            return self.move(0.0, 0.0, 0.0)

    return _Rpc()


def main(argv=None):
    import rclpy
    from rclpy.executors import ExternalShutdownException
    from nav_msgs.msg import Odometry

    from booster_interface.srv import RpcService
    from .rpc_commands import (
        MODE_PREPARE,
        MODE_WALKING,
        make_change_mode_request,
    )

    # ── Make the RL nav stack importable, and point its planner at the world ──
    rl_dir = os.environ.get("PPO_RL_DIR", "/workspace/rl")
    if rl_dir not in sys.path:
        sys.path.insert(0, rl_dir)
    os.environ.setdefault(
        "SENTINEL_WBT_PATH",
        "/workspace/project/worlds/sentinelmas_office.wbt",
    )
    model_path = os.environ.get("PPO_MODEL_PATH", os.path.join(rl_dir, "data", "models", "nav_ppo_final"))

    rclpy.init(args=argv or [])
    node = rclpy.create_node("ppo_patrol_node")

    def log_info(m): node.get_logger().info(m)
    def log_warn(m): node.get_logger().warn(m)
    def log_error(m): node.get_logger().error(m)

    # ── RPC service client ───────────────────────────────────────────────────
    rpc_node = rclpy.create_node("ppo_patrol_rpc_client")
    client = rpc_node.create_client(RpcService, "/booster_rpc_service")
    log_info("Waiting for /booster_rpc_service...")
    client.wait_for_service()
    log_info("/booster_rpc_service is ready.")
    rpc = _build_rpc_adapter(rclpy, rpc_node, client, log_info, log_warn, log_error)

    # ── Load the trained policy (heavy: torch + model) ───────────────────────
    log_info(f"Loading PPO navigator from {model_path} (RL dir {rl_dir})...")
    from policy_runner import PPONavigator   # noqa: E402 (sys.path set above)
    navigator = PPONavigator(model_path)
    limits = _limits_from_env()
    log_info(
        "PPO precision limits "
        f"turn_in_place={limits.turn_in_place:.2f} max_vx={limits.max_vx:.2f} "
        f"max_vyaw={limits.max_vyaw:.2f} walk_yaw={limits.walk_yaw:.2f} "
        f"turn_kp={limits.turn_kp:.2f} slow_radius={limits.slow_radius:.2f}"
    )
    adapter = PPONavAdapter(rpc, navigator, logger=log_info, limits=limits)
    log_info("PPO navigator ready.")

    # ── Stand up + enter walking mode (needs the vendor /opt/booster config) ──
    log_info("Preparing walking mode...")
    prep = make_change_mode_request(MODE_PREPARE)
    rpc._call(prep.api_id, prep.body)
    time.sleep(3.5)
    walk = make_change_mode_request(MODE_WALKING)
    rpc._call(walk.api_id, walk.body)
    time.sleep(1.0)
    log_info("Walking mode ready.")

    # ── Patrol state machine, driven by the PPO adapter ──────────────────────
    log_dir = Path(os.environ.get("PATROL_LOG_DIR", "/workspace/project/.logs"))
    machine = PatrolStateMachine(
        rpc=rpc,
        status_path=log_dir / "booster_status.jsonl",
        missions_path=log_dir / "booster_missions.jsonl",
        target_pos_path=log_dir / "booster_target_pos.jsonl",
        navigation_manager=adapter,
        logger=log_info,
    )

    # ── Odometry → pose (real heading drives the closed-loop policy) ──────────
    def odom_callback(msg: Odometry):
        p = msg.pose.pose.position
        q = msg.pose.pose.orientation
        siny = 2.0 * (q.w * q.z + q.x * q.y)
        cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        yaw = math.atan2(siny, cosy)
        machine.update_pose(Pose2D(p.x, p.y, yaw))

    node.create_subscription(Odometry, "/booster_t1/odom", odom_callback, 10)

    tick_period = max(0.05, float(os.environ.get("BOOSTER_PATROL_TICK_PERIOD", "0.1") or 0.1))

    def tick_callback():
        try:
            machine.tick(time.time())
        except Exception as exc:
            log_error(f"PPO patrol tick error: {exc}")
            try:
                machine.handle_error(str(exc))
            except Exception:
                pass

    node.create_timer(tick_period, tick_callback)
    log_info("PPO patrol node started.")

    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if rclpy.ok():
            try:
                rpc.stop()
            except Exception:
                pass
        for n in (node, rpc_node):
            try:
                n.destroy_node()
            except Exception:
                pass
        if rclpy.ok():
            try:
                rclpy.shutdown()
            except Exception:
                pass


if __name__ == "__main__":
    main()
