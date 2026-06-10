from __future__ import annotations


def first_items(values, limit=5):
    return list(values[:limit])


def topic_candidates(base_name: str, robot_name: str = "booster_t1") -> list[str]:
    clean_base = base_name.strip("/")
    clean_robot = robot_name.strip("/")
    return [f"/{clean_robot}/{clean_base}", f"/{clean_base}"]


def _format_number(value) -> str:
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return str(value)


def _format_vector(vector) -> str:
    return (
        f"({_format_number(vector.x)}, "
        f"{_format_number(vector.y)}, "
        f"{_format_number(vector.z)})"
    )


def _format_orientation(orientation) -> str:
    return (
        f"({_format_number(orientation.x)}, "
        f"{_format_number(orientation.y)}, "
        f"{_format_number(orientation.z)}, "
        f"{_format_number(orientation.w)})"
    )


def format_joint_state(msg, count: int) -> str:
    names = first_items(getattr(msg, "name", []), 5)
    positions = first_items(getattr(msg, "position", []), 5)
    formatted_positions = [_format_number(value) for value in positions]
    joint_count = len(getattr(msg, "name", []))
    return (
        f"message #{count}: joint_count={joint_count}, "
        f"first_names={names}, first_positions={formatted_positions}"
    )


def format_imu(msg, count: int) -> str:
    return (
        f"message #{count}: "
        f"orientation={_format_orientation(msg.orientation)}, "
        f"angular_velocity={_format_vector(msg.angular_velocity)}, "
        f"linear_acceleration={_format_vector(msg.linear_acceleration)}"
    )
