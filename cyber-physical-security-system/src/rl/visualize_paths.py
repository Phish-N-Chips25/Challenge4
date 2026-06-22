"""
Visualise and validate the global path planner against the real wall layout.

Draws every wall segment from office_map.py and the planned route between
zones, then asserts every leg of every route is actually wall-free — this
is a real correctness check, not just a picture.

Usage:
    python visualize_paths.py                          # all 56 zone pairs, validation only
    python visualize_paths.py --from lobby --to datacenter   # draw one route
"""

import argparse
import itertools

import matplotlib.pyplot as plt
import numpy as np

from env import DEFAULT_ZONE_POS
from office_map import DOORS, WALLS, line_of_sight
from path_planner import plan_path


def draw_map(ax):
    for x1, y1, x2, y2 in WALLS:
        ax.plot([x1, x2], [y1, y2], color="black", linewidth=3, zorder=4)
    for name, (x, y) in DOORS.items():
        ax.scatter(x, y, color="white", edgecolor="black", s=50, zorder=6, marker="s")
    for name, (x, y) in DEFAULT_ZONE_POS.items():
        ax.scatter(x, y, color="#4e9af1", s=110, zorder=5)
        ax.annotate(name, (x, y), xytext=(x, y + 0.5),
                    ha="center", fontsize=7, fontweight="bold")
    ax.set_xlim(-11, 11)
    ax.set_ylim(-7, 7)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.2)


def assert_path_is_clear(path: list[tuple[float, float]]) -> None:
    for a, b in zip(path[:-1], path[1:]):
        if not line_of_sight(a, b):
            raise AssertionError(f"Planned leg {a} -> {b} crosses a wall!")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="start_zone", default=None)
    parser.add_argument("--to",   dest="goal_zone",   default=None)
    args = parser.parse_args()

    fig, ax = plt.subplots(figsize=(11, 8))
    ax.set_title("Path planner validation — every leg must avoid walls")
    draw_map(ax)

    single_route = args.start_zone and args.goal_zone
    pairs = ([(args.start_zone, args.goal_zone)] if single_route
             else list(itertools.permutations(DEFAULT_ZONE_POS, 2)))

    failures = []
    for start, goal in pairs:
        start_xy = DEFAULT_ZONE_POS[start]
        try:
            path = plan_path(start_xy, goal)
            assert_path_is_clear(path)
        except Exception as e:
            failures.append((start, goal, str(e)))
            continue
        xs, ys = zip(*path)
        if single_route:
            ax.plot(xs, ys, color="red", linewidth=2.5, marker="o",
                    markersize=6, zorder=7, label=f"{start} -> {goal}")
            ax.legend(loc="upper left")
        else:
            # Overview mode: draw all 56 routes translucently so the overall
            # routing pattern is visible without one route obscuring another.
            ax.plot(xs, ys, color="red", linewidth=1.0, alpha=0.12, zorder=7)

    print(f"Checked {len(pairs)} zone-to-zone routes for wall crossings.")
    if failures:
        print(f"  {len(failures)} FAILED:")
        for s, g, err in failures:
            print(f"    {s} -> {g}: {err}")
    else:
        print("  All routes are wall-free. OK")

    out = "data/path_validation.png"
    plt.tight_layout()
    plt.savefig(out, dpi=150)
    print(f"Saved {out}")
    plt.show()


if __name__ == "__main__":
    main()
