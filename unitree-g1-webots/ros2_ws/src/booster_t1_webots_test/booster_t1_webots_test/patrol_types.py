"""Shared data types for the Booster patrol behavior."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Pose2D:
    """2-D pose used by the patrol controller and mission planner."""
    x: float
    y: float
    theta: float = 0.0


@dataclass(frozen=True)
class Waypoint:
    """A named waypoint along a safe patrol route."""
    x: float
    y: float
    note: str = ""
    arrive_distance: float | None = None
    forward_speed: float | None = None
    ignore_route_blocks: bool = False

    @property
    def xy(self):
        return (self.x, self.y)


@dataclass(frozen=True)
class Mission:
    """A patrol mission dispatched by the security supervisor."""
    kind: str            # 'detain', 'investigate', or 'assist'
    x: float
    y: float
    target: str | None = None
    model: str | None = None
    zone: str | None = None
    reason: str = ""
