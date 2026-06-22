"""
Generic Webots .wbt floor-plan extractor.

Reads Wall, Door, and zone-mark Solid nodes directly out of a .wbt file and
turns them into the 2D geometry path_planner.py needs (wall segments, door
waypoints, zone centres). This is what makes the navigation stack
deployable to a different building without touching any code: point it at
a new .wbt and the wall layout, doors, and zones are re-derived automatically.

What is NOT affected by a new building: the trained PPO policy. It only
ever sees local point-to-point hops in open space — it has no idea what
building it's in. Only this parsing layer needs to change per deployment.

Scope / limitations (documented honestly, not hidden):
  - Assumes a flat 2D floor plan: wall rotations are about the Z axis only
    (true for every world file in this project). A rotation axis that isn't
    (0,0,1) or (0,0,-1) is treated as a best-effort Z rotation with a warning.
  - Wall/Door nodes are read as flat field lists (translation/rotation/size/
    name on one node, no nested children) — true for how this project's
    world files instantiate the official Webots Wall/Door PROTOs.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path

Segment = tuple[float, float, float, float]

_FIELD_VEC3 = r"([\-\d.eE]+)\s+([\-\d.eE]+)\s+([\-\d.eE]+)"
_FIELD_VEC4 = r"([\-\d.eE]+)\s+([\-\d.eE]+)\s+([\-\d.eE]+)\s+([\-\d.eE]+)"


def _find_node_blocks(text: str, node_type: str) -> list[str]:
    """Return the raw `{ ... }` body of every top-level instance of
    `node_type`, handling an optional leading `DEF <NAME>` and nested braces
    (e.g. a Solid's `children [ ... ]` block)."""
    blocks = []
    pattern = re.compile(rf"(?:DEF\s+\w+\s+)?{node_type}\s*\{{")
    for m in pattern.finditer(text):
        depth = 1
        i = m.end()
        while depth > 0 and i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        blocks.append(text[m.end():i - 1])
    return blocks


def _extract_translation(block: str) -> tuple[float, float, float]:
    m = re.search(rf"translation\s+{_FIELD_VEC3}", block)
    if not m:
        return (0.0, 0.0, 0.0)
    return tuple(float(g) for g in m.groups())


def _extract_rotation_angle(block: str) -> float:
    """Z-axis rotation angle in radians, sign-corrected for axis direction."""
    m = re.search(rf"rotation\s+{_FIELD_VEC4}", block)
    if not m:
        return 0.0
    ax, ay, az, angle = (float(g) for g in m.groups())
    if abs(ax) > 1e-6 or abs(ay) > 1e-6:
        warnings.warn(
            f"Non-Z rotation axis ({ax}, {ay}, {az}) found in a wall/door "
            f"node — treating angle as a best-effort Z rotation. This parser "
            f"assumes a flat 2D floor plan."
        )
    return -angle if az < 0 else angle


def _extract_size_x(block: str) -> float:
    m = re.search(rf"size\s+{_FIELD_VEC3}", block)
    return float(m.group(1)) if m else 0.0


def _extract_name(block: str) -> str | None:
    m = re.search(r'name\s+"([^"]+)"', block)
    return m.group(1) if m else None


def _wall_segment(block: str) -> Segment:
    """A Wall/Door PROTO extends `size.x` along its local X axis, centred at
    `translation`, then rotated about Z by `rotation`."""
    tx, ty, _ = _extract_translation(block)
    angle = _extract_rotation_angle(block)
    half = _extract_size_x(block) / 2.0
    import math
    dx, dy = half * math.cos(angle), half * math.sin(angle)
    return (tx - dx, ty - dy, tx + dx, ty + dy)


def parse_walls_and_doors(wbt_path: str | Path) -> tuple[list[Segment], dict[str, tuple[float, float]]]:
    """Extract solid wall segments and door waypoints from a .wbt file.

    Doors are passable, so they contribute a *waypoint* (their centre) but
    no wall segment — the surrounding Wall nodes already stop short of the
    doorway, which is exactly how this project's world files are built.
    """
    text = Path(wbt_path).read_text(encoding="utf-8")

    walls: list[Segment] = []
    for block in _find_node_blocks(text, "Wall"):
        walls.append(_wall_segment(block))

    doors: dict[str, tuple[float, float]] = {}
    for i, block in enumerate(_find_node_blocks(text, "Door")):
        tx, ty, _ = _extract_translation(block)
        name = _extract_name(block) or f"door_{i}"
        key = "door_" + re.sub(r"\W+", "_", name.lower()).strip("_")
        doors[key] = (tx, ty)

    return walls, doors


def parse_zone_marks(wbt_path: str | Path) -> dict[str, tuple[float, float]]:
    """Extract zone centres from Solid nodes named 'zone mark <name>'.

    Used as a cross-check against configs/ppo.yaml's zone_pos to catch drift
    if the office layout changes without the RL config being updated —
    see check_map_sync.py.
    """
    text = Path(wbt_path).read_text(encoding="utf-8")
    zones: dict[str, tuple[float, float]] = {}
    for block in _find_node_blocks(text, "Solid"):
        name = _extract_name(block)
        if not name or not name.lower().startswith("zone mark "):
            continue
        key = re.sub(r"\W+", "_", name[len("zone mark "):].strip().lower())
        tx, ty, _ = _extract_translation(block)
        zones[key] = (tx, ty)
    return zones
