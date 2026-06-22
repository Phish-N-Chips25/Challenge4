"""JSONL file bridge between the Webots supervisor and the ROS patrol node.

The supervisor cannot call ROS directly, so missions and status updates are
exchanged through append-only JSONL files under .logs/:

- .logs/booster_missions.jsonl  — supervisor writes DISPATCH events
- .logs/booster_status.jsonl    — ROS patrol node writes status updates

Each line is a compact JSON object with at minimum 'time' and 'type' fields.
Readers track a byte offset to avoid rereading old events.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .patrol_types import Mission


def _trace(message: str) -> None:
    print(f"[patrol_bridge] {message}", flush=True)


def append_mission(
    path: str | Path,
    mission: Mission,
    event_type: str = "DISPATCH",
) -> None:
    """Append a mission event to a JSONL file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "time": time.time(),
        "type": event_type,
        "kind": mission.kind,
        "x": mission.x,
        "y": mission.y,
        "target": mission.target,
        "model": mission.model,
        "zone": mission.zone,
        "reason": mission.reason,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, separators=(",", ":")) + "\n")
    _trace(
        "append_mission "
        f"path={path} kind={mission.kind} target={mission.target} "
        f"zone={mission.zone} xy=({mission.x:.3f},{mission.y:.3f}) "
        f"reason={mission.reason!r}"
    )


def read_new_missions(
    path: str | Path,
    offset: int,
) -> tuple[list[Mission], int]:
    """Read DISPATCH missions appended after *offset* bytes.

    Returns (missions, new_offset). Callers should persist new_offset for
    subsequent reads.
    """
    file_path = Path(path)
    if not file_path.exists():
        return [], offset
    missions: list[Mission] = []
    with file_path.open("r", encoding="utf-8") as fh:
        fh.seek(offset)
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                _trace(f"read_new_missions skip invalid_json line={line_no} error={exc}")
                continue
            if payload.get("type") != "DISPATCH":
                continue
            missions.append(
                Mission(
                    kind=payload["kind"],
                    x=float(payload["x"]),
                    y=float(payload["y"]),
                    target=payload.get("target"),
                    model=payload.get("model"),
                    zone=payload.get("zone"),
                    reason=payload.get("reason", ""),
                )
            )
        new_offset = fh.tell()
    if missions:
        _trace(
            f"read_new_missions path={file_path} old_offset={offset} "
            f"new_offset={new_offset} count={len(missions)}"
        )
    return missions, new_offset


def append_status(
    path: str | Path,
    event_type: str,
    **fields: Any,
) -> None:
    """Append a status event from the ROS patrol node."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "time": time.time(),
        "type": event_type,
        **fields,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, separators=(",", ":")) + "\n")
    _trace(f"append_status path={path} type={event_type} fields={fields}")


def read_new_statuses(
    path: str | Path,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    """Read status events appended after *offset* bytes.

    Returns (events, new_offset).
    """
    file_path = Path(path)
    if not file_path.exists():
        return [], offset
    events: list[dict[str, Any]] = []
    with file_path.open("r", encoding="utf-8") as fh:
        fh.seek(offset)
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as exc:
                _trace(f"read_new_statuses skip invalid_json line={line_no} error={exc}")
        new_offset = fh.tell()
    if events:
        _trace(
            f"read_new_statuses path={file_path} old_offset={offset} "
            f"new_offset={new_offset} count={len(events)}"
        )
    return events, new_offset


def append_target_pos(
    path: str | Path,
    target: str,
    x: float,
    y: float,
) -> None:
    """Append a TARGET_POS event to a JSONL file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "time": time.time(),
        "type": "TARGET_POS",
        "target": target,
        "x": x,
        "y": y,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, separators=(",", ":")) + "\n")
    _trace(
        f"append_target_pos path={path} target={target} xy=({x:.3f},{y:.3f})"
    )


def read_new_target_positions(
    path: str | Path,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    """Read TARGET_POS events appended after *offset* bytes.

    Returns (events, new_offset). Each event dict has keys:
    'target' (str), 'x' (float), 'y' (float).
    """
    file_path = Path(path)
    if not file_path.exists():
        return [], offset
    events: list[dict[str, Any]] = []
    with file_path.open("r", encoding="utf-8") as fh:
        fh.seek(offset)
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                _trace(f"read_new_target_positions skip invalid_json line={line_no}")
                continue
            if payload.get("type") != "TARGET_POS":
                continue
            events.append({
                "target": payload.get("target", ""),
                "x": float(payload["x"]),
                "y": float(payload["y"]),
            })
        new_offset = fh.tell()
    if events:
        _trace(
            f"read_new_target_positions path={file_path} old_offset={offset} "
            f"new_offset={new_offset} count={len(events)}"
        )
    return events, new_offset
