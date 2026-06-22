"""
End-to-end safety check: does the PPO controller's REAL trajectory (not
just the planner's straight-line legs) ever get dangerously close to a wall?

plan_path() guarantees each leg's straight line is wall-free, but the PPO
policy doesn't fly perfectly straight — it can drift, which matters most in
the 2m-wide corridor. This drives the actual PPONavigator logic (instantly,
no real-time wait) for every zone pair and records the minimum distance to
any wall along the real (possibly curved) path the robot took.

Usage:
    python validate_trajectories.py                       # all 56 pairs
    python validate_trajectories.py --from lobby --to datacenter --plot
"""

import argparse
import asyncio
import itertools

from office_map import WALLS, distance_to_nearest_wall
from env import DEFAULT_ZONE_POS
from policy_runner import PPONavigator

ROBOT_RADIUS = 0.3   # PATROL_ROBOT boundingObject Cylinder radius (sentinelmas_office.wbt)


async def run_route(nav: PPONavigator, start_xy, goal_zone) -> dict:
    """Drive one route via the real PPONavigator.move() and record every
    intermediate position it visits (not just the planned waypoints)."""
    # move() assigns agent.pos every tick — a property-backed agent lets us
    # record every intermediate position without touching policy_runner.py.
    trace = []

    class TracingAgent:
        def __init__(self, pos):
            self._pos = pos
            trace.append(pos)

        @property
        def pos(self):
            return self._pos

        @pos.setter
        def pos(self, value):
            self._pos = value
            trace.append(value)

    tracing_agent = TracingAgent(start_xy)
    reached = await nav.move(tracing_agent, goal_zone, realtime=False)

    min_clearance = min(distance_to_nearest_wall(p) for p in trace)
    return {
        "reached": reached,
        "steps": len(trace),
        "min_clearance": min_clearance,
        "trace": trace,
    }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="start_zone", default=None)
    parser.add_argument("--to",   dest="goal_zone",   default=None)
    parser.add_argument("--model", default="data/models/nav_ppo_final")
    parser.add_argument("--plot", action="store_true")
    parser.add_argument("--unsafe-threshold", type=float, default=ROBOT_RADIUS,
                        help=f"flag trajectories with clearance below this (default: robot radius {ROBOT_RADIUS}m)")
    args = parser.parse_args()

    nav = PPONavigator(args.model)
    pairs = ([(args.start_zone, args.goal_zone)] if (args.start_zone and args.goal_zone)
             else list(itertools.permutations(DEFAULT_ZONE_POS, 2)))

    results = []
    for start, goal in pairs:
        res = await run_route(nav, DEFAULT_ZONE_POS[start], goal)
        results.append((start, goal, res))
        flag = "UNSAFE" if res["min_clearance"] < args.unsafe_threshold else "ok"
        arrived = "arrived" if res["reached"] else "TIMED OUT"
        print(f"  {start:<14} -> {goal:<14}  {arrived:<10}  "
              f"min clearance {res['min_clearance']:.2f}m  [{flag}]")

    unsafe = [(s, g, r) for s, g, r in results if r["min_clearance"] < args.unsafe_threshold]
    failed = [(s, g, r) for s, g, r in results if not r["reached"]]

    print(f"\nChecked {len(results)} routes.")
    print(f"  {len(failed)} failed to arrive.")
    print(f"  {len(unsafe)} came within the robot's radius ({args.unsafe_threshold}m) of a wall.")
    if not failed and not unsafe:
        print("  All routes arrived safely. OK")

    if args.plot:
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(11, 8))
        for x1, y1, x2, y2 in WALLS:
            ax.plot([x1, x2], [y1, y2], color="black", linewidth=3, zorder=4)
        for name, (x, y) in DEFAULT_ZONE_POS.items():
            ax.scatter(x, y, color="#4e9af1", s=100, zorder=5)
            ax.annotate(name, (x, y), xytext=(x, y + 0.5), ha="center", fontsize=7)
        for start, goal, res in results:
            xs, ys = zip(*res["trace"])
            ax.plot(xs, ys, linewidth=1.5, alpha=0.8, zorder=6)
        ax.set_aspect("equal")
        ax.set_title("Actual PPO-driven trajectories (not just planned legs)")
        plt.tight_layout()
        plt.savefig("data/trajectory_validation.png", dpi=150)
        print("Saved data/trajectory_validation.png")
        plt.show()


if __name__ == "__main__":
    asyncio.run(main())
