from __future__ import annotations

from typing import Any

from .specs import validate_assertions


def _constraint(metric: str, raw: Any, label: str) -> dict | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return {"metric": metric, "op": "<=", "value": float(raw), "label": label}
    if not isinstance(raw, dict):
        return None
    if "min" in raw and "max" in raw:
        return {"metric": metric, "op": "between", "min": raw["min"], "max": raw["max"], "label": label}
    if "max" in raw:
        return {"metric": metric, "op": "<=", "value": raw["max"], "label": label}
    if "min" in raw:
        return {"metric": metric, "op": ">=", "value": raw["min"], "label": label}
    return None


def build_vehicle_suite(
    vehicle_node: str,
    accelerate_action: str,
    brake_action: str,
    steer_left_action: str,
    profile: dict | None = None,
    scene: str = "",
) -> dict:
    """Build deterministic launch/brake/steering/stability scenarios.

    The profile is intentionally explicit. Missing profile constraints remain measurement-only.
    Supported keys: zero_to_100_s, max_speed_kph, brake_distance_m, brake_time_s,
    speed_at_brake_start_kph, steering_response_s, max_abs_roll_deg,
    straight_lateral_drift_m, max_abs_vertical_speed_mps.
    """
    profile = profile or {}
    common = {
        "scene": scene,
        "physics_fps": 60,
        "sample_hz": 60,
        "watch": [{"id": "vehicle", "node_path": vehicle_node}],
        "primary_watch_id": "vehicle",
    }

    launch_assertions = [x for x in [
        _constraint("zero_to_100_s", profile.get("zero_to_100_s"), "0-100 km/h target"),
        _constraint("max_speed_kph", profile.get("max_speed_kph"), "maximum speed target"),
        _constraint("straight_lateral_drift_m", profile.get("straight_lateral_drift_m"), "straight-line drift"),
        _constraint("max_abs_roll_deg", profile.get("max_abs_roll_deg"), "body roll limit"),
        _constraint("max_abs_vertical_speed_mps", profile.get("max_abs_vertical_speed_mps"), "vertical stability"),
    ] if x]

    brake_assertions = [x for x in [
        _constraint("speed_at_brake_start_kph", profile.get("speed_at_brake_start_kph"), "speed at braking marker"),
        _constraint("brake_distance_m", profile.get("brake_distance_m"), "braking distance"),
        _constraint("brake_time_s", profile.get("brake_time_s"), "braking time"),
    ] if x]

    steer_assertions = [x for x in [
        _constraint("steering_response_s", profile.get("steering_response_s"), "steering response"),
        _constraint("max_abs_roll_deg", profile.get("max_abs_roll_deg"), "body roll limit"),
        _constraint("max_abs_vertical_speed_mps", profile.get("max_abs_vertical_speed_mps"), "vertical stability"),
    ] if x]

    # Defensive normalization is performed here so caller errors surface before any runtime launch.
    launch_assertions = validate_assertions(launch_assertions)
    brake_assertions = validate_assertions(brake_assertions)
    steer_assertions = validate_assertions(steer_assertions)

    return {
        "calibrated": bool(launch_assertions or brake_assertions or steer_assertions),
        "profile": profile,
        "scenarios": [
            {
                **common,
                "name": "vehicle-launch-straight",
                "duration_s": 12.0,
                "inputs": [{"action": accelerate_action, "start_s": 0.25, "end_s": 11.5, "strength": 1.0}],
                "markers": [{"name": "accel_start", "time_s": 0.25}],
                "assertions": launch_assertions,
            },
            {
                **common,
                "name": "vehicle-accelerate-then-brake",
                "duration_s": 14.0,
                "inputs": [
                    {"action": accelerate_action, "start_s": 0.25, "end_s": 8.0, "strength": 1.0},
                    {"action": brake_action, "start_s": 8.0, "end_s": 13.5, "strength": 1.0},
                ],
                "markers": [{"name": "brake_start", "time_s": 8.0}],
                "assertions": brake_assertions,
            },
            {
                **common,
                "name": "vehicle-steering-step",
                "duration_s": 8.0,
                "inputs": [
                    {"action": accelerate_action, "start_s": 0.25, "end_s": 7.5, "strength": 0.65},
                    {"action": steer_left_action, "start_s": 4.0, "end_s": 5.25, "strength": 1.0},
                ],
                "markers": [{"name": "steer_start", "time_s": 4.0}],
                "assertions": steer_assertions,
            },
        ],
        "important": (
            "No calibrated realism PASS is possible without explicit target constraints. "
            "Targets should come from the user's design requirements or a trustworthy specification for the intended vehicle/class."
        ),
    }
