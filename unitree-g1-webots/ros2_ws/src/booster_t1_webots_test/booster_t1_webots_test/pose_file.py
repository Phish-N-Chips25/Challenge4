from __future__ import annotations

import json
from pathlib import Path

from .odometry_helpers import OdometerReading, normalize_angle


def read_pose_file(path) -> OdometerReading | None:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return OdometerReading(
            x=float(payload["x"]),
            y=float(payload["y"]),
            theta=normalize_angle(float(payload["theta"])),
            sim_time=float(payload["time"]) if "time" in payload else None,
        )
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
