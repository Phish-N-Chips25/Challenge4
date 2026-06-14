"""
Visualise the patrol zone layout from ppo.yaml.

Usage:
    python src/rl/visualize_layout.py
    python src/rl/visualize_layout.py --config configs/ppo.yaml
"""

import argparse
import math
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
    scale = cfg["map_scale"]
    zone_grid = cfg["zone_pos"]
    base_grid = cfg["base_pos"]
    goal_r = cfg.get("goal_radius", 0.5)

    # Convert grid (0..100) to metres
    zones = {z: (np.array(p) * scale) for z, p in zone_grid.items()}
    base = np.array(base_grid) * scale
    arena = 100.0 * scale

    fig, ax = plt.subplots(figsize=(8, 8))
    ax.set_xlim(-1, arena + 1)
    ax.set_ylim(-1, arena + 1)
    ax.set_aspect("equal")
    ax.set_xlabel("X (metres)")
    ax.set_ylabel("Y (metres)")
    ax.set_title("Patrol Zone Layout\n(matches OfficeNavEnv + SIMAGIA settings.py)")
    ax.grid(True, alpha=0.3)

    # Arena boundary
    arena_rect = mpatches.FancyBboxPatch(
        (0, 0), arena, arena,
        boxstyle="square,pad=0", linewidth=2,
        edgecolor="black", facecolor="#f5f5f5"
    )
    ax.add_patch(arena_rect)

    # Zone colours
    colours = {
        "exterior":    "#4e9af1",
        "server_room": "#e05c5c",
        "lab":         "#e0a85c",
        "corridor":    "#7ac47a",
        "lobby":       "#b07ac4",
    }

    for name, pos in zones.items():
        colour = colours.get(name, "#aaaaaa")
        # Draw goal-radius circle
        circle = plt.Circle(pos, goal_r, color=colour, alpha=0.25, zorder=3)
        ax.add_patch(circle)
        # Zone centre dot
        ax.scatter(*pos, s=120, color=colour, zorder=5)
        # Label
        ax.annotate(
            name.replace("_", "\n"),
            xy=pos, xytext=(pos[0], pos[1] + 1.2),
            ha="center", va="bottom", fontsize=9, fontweight="bold",
            color=colour,
        )
        # Grid coords for reference
        gx, gy = zone_grid[name]
        ax.annotate(
            f"({gx:.0f}, {gy:.0f})",
            xy=pos, xytext=(pos[0], pos[1] - 1.2),
            ha="center", va="top", fontsize=7, color="#666666",
        )

    # Patrol base / dock
    ax.scatter(*base, s=200, marker="D", color="#333333", zorder=6, label="Patrol dock")
    ax.annotate(
        "base", xy=base, xytext=(base[0] + 1.0, base[1]),
        fontsize=8, color="#333333", va="center",
    )

    # Example trajectory line from base to server_room
    if "server_room" in zones:
        tgt = zones["server_room"]
        ax.annotate(
            "", xy=tgt, xytext=base,
            arrowprops=dict(arrowstyle="->", color="#999999", lw=1.2, linestyle="dashed"),
        )

    # Velocity envelope info
    vl = cfg.get("velocity_limits", {})
    info = (
        f"Velocity envelope (Booster T1)\n"
        f"  vx:   {vl.get('vx', '?')} m/s\n"
        f"  vy:   {vl.get('vy', '?')} m/s\n"
        f"  vyaw: {vl.get('vyaw', '?')} rad/s\n"
        f"Goal radius: {goal_r} m\n"
        f"Arena: {arena:.0f} x {arena:.0f} m"
    )
    ax.text(0.02, 0.98, info, transform=ax.transAxes,
            fontsize=8, va="top", family="monospace",
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.8))

    legend_patches = [
        mpatches.Patch(color=c, label=n.replace("_", " ").title())
        for n, c in colours.items()
    ]
    legend_patches.append(
        mpatches.Patch(color="#333333", label="Patrol dock")
    )
    ax.legend(handles=legend_patches, loc="lower right", fontsize=8)

    out = Path("data/layout.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(out, dpi=150)
    print(f"Layout saved to {out.resolve()}")
    plt.show()


if __name__ == "__main__":
    main()
