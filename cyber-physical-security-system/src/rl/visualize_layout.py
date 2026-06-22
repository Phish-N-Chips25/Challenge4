"""
Visualise the patrol zone layout from ppo.yaml against the office floor plan.

Positions match sentinelmas_office.wbt exactly (Webots world metres).

Usage:
    python src/rl/visualize_layout.py
    python src/rl/visualize_layout.py --config configs/ppo.yaml
"""

import argparse
from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import yaml


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/ppo.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)["env"]
    zone_pos = cfg["zone_pos"]
    base_pos = cfg["base_pos"]
    goal_r   = cfg.get("goal_radius", 0.5)
    x_min, x_max = cfg["arena"]["x"]
    y_min, y_max = cfg["arena"]["y"]

    zones = {z: np.array(p) for z, p in zone_pos.items()}
    base  = np.array(base_pos)

    fig, ax = plt.subplots(figsize=(10, 7))
    ax.set_xlim(x_min - 1, x_max + 1)
    ax.set_ylim(y_min - 1, y_max + 1)
    ax.set_aspect("equal")
    ax.set_xlabel("X (metres — Webots world frame)")
    ax.set_ylabel("Y (metres — Webots world frame)")
    ax.set_title("SentinelMAS Office — Patrol Zone Layout\n"
                 "(from sentinelmas_office.wbt + configs/ppo.yaml)")
    ax.grid(True, alpha=0.3)

    # Office floor outline
    floor = mpatches.FancyBboxPatch(
        (x_min, y_min), x_max - x_min, y_max - y_min,
        boxstyle="square,pad=0", linewidth=2,
        edgecolor="black", facecolor="#f5f5f5",
    )
    ax.add_patch(floor)

    # Approximate room dividers (mirrors sentinelmas_office.wbt wall layout)
    # Corridor strip y in [-1, 1]
    ax.axhline(-1, color="#aaaaaa", lw=1, ls="--")
    ax.axhline( 1, color="#aaaaaa", lw=1, ls="--")
    # Lobby / break room divider at x=0 (south half)
    ax.plot([0, 0], [y_min, -1], color="#aaaaaa", lw=1, ls="--")
    # Work room / datacenter dividers (north half, every 4 m)
    for xd in [-6, -2, 2, 6]:
        ax.plot([xd, xd], [1, y_max], color="#aaaaaa", lw=1, ls="--")

    # Zone colours
    colours = {
        "lobby":       "#4e9af1",
        "break_room":  "#e0a85c",
        "corridor":    "#aaaaaa",
        "work_room_1": "#7ac47a",
        "work_room_2": "#7ac47a",
        "work_room_3": "#7ac47a",
        "work_room_4": "#7ac47a",
        "datacenter":  "#e05c5c",
    }

    for name, pos in zones.items():
        colour = colours.get(name, "#cccccc")
        circle = plt.Circle(pos, goal_r, color=colour, alpha=0.30, zorder=3)
        ax.add_patch(circle)
        ax.scatter(*pos, s=120, color=colour, zorder=5)
        label = name.replace("_", "\n")
        ax.annotate(label, xy=pos, xytext=(pos[0], pos[1] + 0.7),
                    ha="center", va="bottom", fontsize=8, fontweight="bold",
                    color=colour)
        ax.annotate(f"({pos[0]:.0f}, {pos[1]:.0f})",
                    xy=pos, xytext=(pos[0], pos[1] - 0.7),
                    ha="center", va="top", fontsize=7, color="#666666")

    # Patrol dock
    ax.scatter(*base, s=220, marker="D", color="#222222", zorder=6)
    ax.annotate("patrol\ndock", xy=base, xytext=(base[0] - 1.2, base[1]),
                fontsize=8, color="#222222", va="center", ha="right")

    # Example trajectory from base to datacenter
    if "datacenter" in zones:
        tgt = zones["datacenter"]
        ax.annotate("", xy=tgt, xytext=base,
                    arrowprops=dict(arrowstyle="->", color="#999999",
                                    lw=1.2, linestyle="dashed"))

    # Velocity envelope info
    vl   = cfg.get("velocity_limits", {})
    info = (
        f"Booster T1 velocity envelope\n"
        f"  vx:   {vl.get('vx', '?')} m/s\n"
        f"  vy:   {vl.get('vy', '?')} m/s\n"
        f"  vyaw: {vl.get('vyaw', '?')} rad/s\n"
        f"Goal radius: {goal_r} m\n"
        f"Arena: {x_max-x_min:.0f} x {y_max-y_min:.0f} m"
    )
    ax.text(0.02, 0.98, info, transform=ax.transAxes,
            fontsize=8, va="top", family="monospace",
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.85))

    # Legend
    seen = {}
    patches = []
    for name, c in colours.items():
        label = "work rooms" if name.startswith("work_room") else name.replace("_", " ").title()
        if label not in seen:
            seen[label] = True
            patches.append(mpatches.Patch(color=c, label=label))
    patches.append(mpatches.Patch(color="#222222", label="Patrol dock"))
    ax.legend(handles=patches, loc="lower right", fontsize=8)

    out = Path("data/layout.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(out, dpi=150)
    print(f"Layout saved to {out.resolve()}")
    plt.show()


if __name__ == "__main__":
    main()
