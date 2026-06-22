from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class OdometerReading:
    x: float
    y: float
    theta: float
    sim_time: float | None = None


@dataclass(frozen=True)
class OdometryComparison:
    corrected: OdometerReading
    vendor: OdometerReading | None
    position_error: float | None
    heading_error: float | None
    summary: str


def normalize_angle(angle: float) -> float:
    wrapped = (float(angle) + math.pi) % (2.0 * math.pi) - math.pi
    if math.isclose(wrapped, -math.pi) and angle > 0.0:
        return math.pi
    return wrapped


def odometer_from_webots_pose(position, rpy) -> OdometerReading:
    return OdometerReading(
        x=float(position[0]),
        y=float(position[1]),
        theta=normalize_angle(float(rpy[2])),
    )


def compare_odometry(
    corrected: OdometerReading,
    vendor: OdometerReading | None,
) -> OdometryComparison:
    if vendor is None:
        summary = (
            "corrected="
            f"(x={corrected.x:.3f}, y={corrected.y:.3f}, theta={corrected.theta:.3f}) "
            "vendor=unavailable"
        )
        return OdometryComparison(
            corrected=corrected,
            vendor=None,
            position_error=None,
            heading_error=None,
            summary=summary,
        )

    position_error = math.hypot(corrected.x - vendor.x, corrected.y - vendor.y)
    heading_error = abs(normalize_angle(corrected.theta - vendor.theta))
    summary = (
        "corrected="
        f"(x={corrected.x:.3f}, y={corrected.y:.3f}, theta={corrected.theta:.3f}) "
        "vendor="
        f"(x={vendor.x:.3f}, y={vendor.y:.3f}, theta={vendor.theta:.3f}) "
        f"position_error={position_error:.3f} heading_error={heading_error:.3f}"
    )
    return OdometryComparison(
        corrected=corrected,
        vendor=vendor,
        position_error=position_error,
        heading_error=heading_error,
        summary=summary,
    )
