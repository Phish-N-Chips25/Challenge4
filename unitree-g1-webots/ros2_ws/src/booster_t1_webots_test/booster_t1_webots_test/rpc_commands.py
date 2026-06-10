from __future__ import annotations

import json
from dataclasses import dataclass


API_CHANGE_MODE = 2000
API_MOVE = 2001

MODE_DAMPING = 0
MODE_PREPARE = 1
MODE_WALKING = 2
MODE_CUSTOM = 3


@dataclass(frozen=True)
class BoosterRpcRequest:
    api_id: int
    body: str


@dataclass(frozen=True)
class MovementCommand:
    vx: float
    vy: float
    vyaw: float


MOVEMENT_COMMANDS = {
    "forward": MovementCommand(0.7, 0.0, 0.0),
    "backward": MovementCommand(-0.1, 0.0, 0.0),
    "left": MovementCommand(0.0, 0.1, 0.0),
    "right": MovementCommand(0.0, -0.1, 0.0),
    "turn_left": MovementCommand(0.0, 0.0, 0.2),
    "turn_right": MovementCommand(0.0, 0.0, -0.2),
    "stop": MovementCommand(0.0, 0.0, 0.0),
}


def _compact_json(body: dict[str, float | int]) -> str:
    return json.dumps(body, separators=(",", ":"), sort_keys=True)


def make_change_mode_request(mode):
    return BoosterRpcRequest(
        api_id=API_CHANGE_MODE,
        body=_compact_json({"mode": int(mode)}),
    )


def make_move_request(vx, vy, vyaw):
    return BoosterRpcRequest(
        api_id=API_MOVE,
        body=_compact_json(
            {
                "vx": float(vx),
                "vy": float(vy),
                "vyaw": float(vyaw),
            }
        ),
    )


def get_movement_command(name):
    try:
        return MOVEMENT_COMMANDS[name]
    except KeyError as exc:
        supported = ", ".join(sorted(MOVEMENT_COMMANDS))
        raise ValueError(
            f"Unknown movement command {name!r}. Supported commands: {supported}"
        ) from exc
