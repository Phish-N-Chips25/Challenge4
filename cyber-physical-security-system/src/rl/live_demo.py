"""
Interactive live demo: click a zone button, watch the trained PPO policy +
path planner drive the (simulated) robot there in real time.

This exercises the exact same code path as production (PPONavigator's
policy queries and kinematics), just stepped synchronously frame-by-frame
instead of via asyncio — matplotlib's animation loop is a plain callback,
not asyncio-based, so DemoRobot re-implements move()'s control loop as
something steppable one tick at a time.

Clicking a new zone while the robot is mid-route re-plans from its CURRENT
position, mirroring how SIMAGIA preempts an active mission with a higher-
priority auction winner.

Usage:
    python live_demo.py
"""

from __future__ import annotations

import math

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation
from matplotlib.widgets import Button

from env import DEFAULT_ZONE_POS
from policy_runner import PPONavigator, _WAYPOINT_RADIUS
from visualize_paths import draw_map

START_POS = (9.0, 0.0)   # PATROL_ROBOT spawn in sentinelmas_office.wbt
TRAIL_LEN = 80            # how many past positions stay visible as a trail


class DemoRobot:
    """Steppable version of PPONavigator.move()'s control loop — identical
    physics and policy calls, driven one tick at a time by the caller
    instead of `await asyncio.sleep()`."""

    def __init__(self, navigator: PPONavigator, start_xy):
        self.nav = navigator
        self.pos = np.array(start_xy, dtype=np.float32)
        self.heading = 0.0
        self.prev_action = np.zeros(3, dtype=np.float32)
        self.waypoints: list = []
        self.leg_idx = 0
        self.min_dist_seen = math.inf
        self.goal_zone: str | None = None
        self._reset_heading = False
        self.history = [tuple(self.pos)]
        self.arrived = True

    def set_target(self, zone: str) -> None:
        """Re-plan from the CURRENT position."""
        self.goal_zone = zone
        self.waypoints = self.nav.get_waypoints(
            (float(self.pos[0]), float(self.pos[1])), zone
        )[1:]
        self.leg_idx = 0
        self.min_dist_seen = math.inf
        self._reset_heading = True
        self.arrived = False

    def step(self) -> None:
        if self.arrived or self.leg_idx >= len(self.waypoints):
            self.arrived = True
            return

        e = self.nav._env
        goal = np.array(self.waypoints[self.leg_idx], dtype=np.float32)
        if self._reset_heading:
            self.heading = math.atan2(*(goal - self.pos)[::-1])
            self.min_dist_seen = math.inf
            self._reset_heading = False

        norm = self.nav._predict_norm(
            (float(self.pos[0]), float(self.pos[1]), self.heading), goal, self.prev_action
        )
        self.prev_action = norm
        vx, vy, vyaw = e._rescale_action(norm)

        e._pos, e._heading = self.pos, self.heading
        e._integrate(vx, vy, vyaw)
        self.pos, self.heading = e._pos.copy(), e._heading
        self.history.append(tuple(self.pos))
        if len(self.history) > TRAIL_LEN:
            self.history.pop(0)

        is_final = self.leg_idx == len(self.waypoints) - 1
        radius = e.goal_radius if is_final else _WAYPOINT_RADIUS
        dist = float(np.linalg.norm(goal - self.pos))
        self.min_dist_seen = min(self.min_dist_seen, dist)
        # Advance on arrival, OR (for intermediate waypoints) when the robot
        # has passed through the waypoint's vicinity and is now moving away —
        # prevents the PPO from spiralling back to re-converge. Mirrors the
        # same logic in PPONavigator.move().
        passed_through = (not is_final
                          and self.min_dist_seen <= radius * 2.0
                          and dist > self.min_dist_seen + radius * 0.5)
        if dist <= radius or passed_through:
            self.leg_idx += 1
            self._reset_heading = True
            if self.leg_idx >= len(self.waypoints):
                self.arrived = True


def build_figure(robot: DemoRobot):
    fig, ax = plt.subplots(figsize=(12, 8))
    plt.subplots_adjust(right=0.8)
    draw_map(ax)
    ax.set_title("CyberPatrol live demo - click a zone to dispatch the robot")

    marker, = ax.plot([], [], "o", color="#1d4ed8", markersize=14, zorder=10)
    trail,  = ax.plot([], [], "-", color="#1d4ed8", linewidth=2, alpha=0.4, zorder=8)
    status = ax.text(0.02, 0.02, "", transform=ax.transAxes, fontsize=9,
                     va="bottom", family="monospace",
                     bbox=dict(boxstyle="round", facecolor="white", alpha=0.85))

    def make_handler(zone_name):
        def handler(_event):
            robot.set_target(zone_name)
        return handler

    buttons = []
    for i, zone in enumerate(DEFAULT_ZONE_POS):
        bax = fig.add_axes([0.83, 0.85 - i * 0.09, 0.14, 0.07])
        b = Button(bax, zone.replace("_", "\n"))
        b.on_clicked(make_handler(zone))
        buttons.append(b)  # keep references alive

    return fig, ax, marker, trail, status, buttons


def main():
    print("Loading PPO model...")
    nav = PPONavigator("data/models/nav_ppo_final")
    robot = DemoRobot(nav, START_POS)

    fig, ax, marker, trail, status, buttons = build_figure(robot)

    def update(_frame):
        if not robot.arrived:
            robot.step()
        xs, ys = zip(*robot.history)
        marker.set_data([robot.pos[0]], [robot.pos[1]])
        trail.set_data(xs, ys)
        target = robot.goal_zone or "(idle)"
        state = "ARRIVED" if robot.arrived else "en route"
        status.set_text(
            f"target: {target:<14} [{state}]\n"
            f"pos: ({robot.pos[0]:5.2f}, {robot.pos[1]:5.2f})"
        )
        return marker, trail, status

    anim = FuncAnimation(fig, update, interval=100, blit=False, cache_frame_data=False)
    plt.show()


if __name__ == "__main__":
    main()
