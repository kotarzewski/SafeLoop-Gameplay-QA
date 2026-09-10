from __future__ import annotations

import math
from typing import Any


def _v3(value: Any) -> tuple[float, float, float] | None:
    if not isinstance(value, list) or len(value) != 3:
        return None
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError):
        return None


def _distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _speed(row: dict) -> float | None:
    """Horizontal ground speed; vertical motion is reported separately."""
    vel = _v3(row.get("velocity"))
    if vel is None:
        return None
    return math.hypot(vel[0], vel[2])


def _angle_abs(degrees: float) -> float:
    value = (degrees + 180.0) % 360.0 - 180.0
    return abs(value)


def _crossing_time(rows: list[dict], target_kph: float, start_time: float = 0.0) -> float | None:
    for row in rows:
        t = float(row["t"])
        if t + 1e-9 < start_time:
            continue
        speed = _speed(row)
        if speed is not None and speed * 3.6 >= target_kph:
            return t - start_time
    return None


def _nearest_index(rows: list[dict], time_s: float) -> int:
    return min(range(len(rows)), key=lambda i: abs(float(rows[i]["t"]) - time_s))


def _path_distance(rows: list[dict], start_idx: int = 0, end_idx: int | None = None) -> float | None:
    if end_idx is None:
        end_idx = len(rows) - 1
    total = 0.0
    have = False
    prev = None
    for row in rows[start_idx : end_idx + 1]:
        pos = _v3(row.get("position"))
        if pos is None:
            continue
        if prev is not None:
            total += _distance(prev, pos)
            have = True
        prev = pos
    return total if have else None


def derive_metrics(result: dict, primary_watch_id: str | None = None) -> dict:
    samples = result.get("samples", [])
    if not isinstance(samples, list):
        samples = []
    if primary_watch_id is None:
        primary_watch_id = result.get("spec", {}).get("primary_watch_id")
    rows = sorted(
        [r for r in samples if isinstance(r, dict) and r.get("id") == primary_watch_id],
        key=lambda r: float(r.get("t", 0.0)),
    )
    metrics: dict[str, Any] = {
        "sample_count": len(rows),
        "missing_watch_nodes": result.get("missing_watch_nodes", []),
        "missing_input_actions": result.get("missing_input_actions", []),
    }
    grounding = result.get("grounding")
    if isinstance(grounding, dict):
        metrics["grounding"] = {
            "candidate_count": int(grounding.get("candidate_count", 0)),
            "unsupported_count": int(grounding.get("unsupported_count", 0)),
            "all_supported": int(grounding.get("candidate_count", 0)) > 0 and int(grounding.get("unsupported_count", 0)) == 0,
            "mode": grounding.get("mode"),
        }
    if not rows:
        return metrics

    markers = {m.get("name"): float(m.get("time_s", 0.0)) for m in result.get("spec", {}).get("markers", []) if isinstance(m, dict)}
    accel_start = float(markers.get("accel_start", rows[0].get("t", 0.0)))

    speeds = [(float(r["t"]), s) for r in rows if (s := _speed(r)) is not None]
    positions = [(float(r["t"]), p) for r in rows if (p := _v3(r.get("position"))) is not None]
    metrics["duration_s"] = float(rows[-1]["t"]) - float(rows[0]["t"])
    if speeds:
        metrics["start_speed_kph"] = speeds[0][1] * 3.6
        metrics["max_speed_kph"] = max(v for _, v in speeds) * 3.6
        metrics["final_speed_kph"] = speeds[-1][1] * 3.6
        metrics["zero_to_50_s"] = _crossing_time(rows, 50.0, accel_start)
        metrics["zero_to_100_s"] = _crossing_time(rows, 100.0, accel_start)
        accelerations: list[float] = []
        for (t0, v0), (t1, v1) in zip(speeds, speeds[1:]):
            dt = t1 - t0
            if dt > 1e-9:
                accelerations.append((v1 - v0) / dt)
        if accelerations:
            metrics["peak_accel_mps2"] = max(accelerations)
            metrics["peak_decel_mps2"] = min(accelerations)

    if positions:
        metrics["distance_m"] = _path_distance(rows)
        metrics["displacement_m"] = _distance(positions[0][1], positions[-1][1])
        ys = [p[1] for _, p in positions]
        metrics["vertical_excursion_m"] = max(ys) - min(ys)

    roll_values = []
    pitch_values = []
    yaw_rates = []
    vertical_speeds = []
    for row in rows:
        rot = _v3(row.get("rotation_deg"))
        if rot is not None:
            pitch_values.append(_angle_abs(rot[0]))
            roll_values.append(_angle_abs(rot[2]))
        ang = _v3(row.get("angular_velocity"))
        if ang is not None:
            yaw_rates.append(abs(math.degrees(ang[1])))
        vel = _v3(row.get("velocity"))
        if vel is not None:
            vertical_speeds.append(abs(vel[1]))
    if roll_values:
        metrics["max_abs_roll_deg"] = max(roll_values)
    if pitch_values:
        metrics["max_abs_pitch_deg"] = max(pitch_values)
    if yaw_rates:
        metrics["max_abs_yaw_rate_dps"] = max(yaw_rates)
    if vertical_speeds:
        metrics["max_abs_vertical_speed_mps"] = max(vertical_speeds)

    first_pos = _v3(rows[0].get("position"))
    last_pos = _v3(rows[-1].get("position"))
    forward = _v3(rows[0].get("forward"))
    if first_pos and last_pos and forward:
        fx, _, fz = forward
        mag = math.hypot(fx, fz)
        if mag > 1e-9:
            fx, fz = fx / mag, fz / mag
            right = (fz, -fx)
            dx, dz = last_pos[0] - first_pos[0], last_pos[2] - first_pos[2]
            metrics["straight_lateral_drift_m"] = abs(dx * right[0] + dz * right[1])


    # Aggregate explicitly requested custom numeric properties.
    prop_names: set[str] = set()
    for row in rows:
        props = row.get("props")
        if isinstance(props, dict):
            prop_names.update(str(k) for k in props)
    if prop_names:
        metrics["props"] = {}
        for prop in sorted(prop_names):
            values = []
            for row in rows:
                props = row.get("props")
                if isinstance(props, dict) and prop in props and isinstance(props[prop], (int, float)) and not isinstance(props[prop], bool):
                    values.append(float(props[prop]))
            if values:
                metrics["props"][prop] = {"start": values[0], "final": values[-1], "min": min(values), "max": max(values)}

    stop_kph = float(result.get("spec", {}).get("stop_speed_kph", 2.0))
    if "brake_start" in markers and speeds:
        start_idx = _nearest_index(rows, markers["brake_start"])
        start_speed = _speed(rows[start_idx])
        metrics["speed_at_brake_start_kph"] = None if start_speed is None else start_speed * 3.6
        stop_idx = None
        for i in range(start_idx, len(rows)):
            s = _speed(rows[i])
            if s is not None and s * 3.6 <= stop_kph:
                stop_idx = i
                break
        if stop_idx is not None:
            metrics["brake_time_s"] = float(rows[stop_idx]["t"]) - float(rows[start_idx]["t"])
            metrics["brake_distance_m"] = _path_distance(rows, start_idx, stop_idx)
        else:
            metrics["brake_time_s"] = None
            metrics["brake_distance_m"] = None

    if "steer_start" in markers:
        start_idx = _nearest_index(rows, markers["steer_start"])
        threshold = float(result.get("spec", {}).get("yaw_response_threshold_dps", 3.0))
        response = None
        for row in rows[start_idx:]:
            ang = _v3(row.get("angular_velocity"))
            if ang is not None and abs(math.degrees(ang[1])) >= threshold:
                response = float(row["t"]) - float(rows[start_idx]["t"])
                break
        metrics["steering_response_s"] = response

    return metrics


def _metric(metrics: dict, name: str) -> Any:
    cur: Any = metrics
    for part in name.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def evaluate_assertions(metrics: dict, assertions: list[dict]) -> dict:
    results = []
    for assertion in assertions:
        name = assertion["metric"]
        op = assertion["op"]
        actual = _metric(metrics, name)
        passed = False
        reason = ""
        if actual is None:
            reason = "metric unavailable"
        else:
            try:
                actual_num = float(actual)
                if op == "<=":
                    passed = actual_num <= float(assertion["value"])
                elif op == ">=":
                    passed = actual_num >= float(assertion["value"])
                elif op == "<":
                    passed = actual_num < float(assertion["value"])
                elif op == ">":
                    passed = actual_num > float(assertion["value"])
                elif op == "==":
                    passed = actual_num == float(assertion["value"])
                elif op == "between":
                    passed = float(assertion["min"]) <= actual_num <= float(assertion["max"])
                elif op == "approx":
                    passed = abs(actual_num - float(assertion["value"])) <= float(assertion.get("tolerance", 0.0))
                if not passed:
                    reason = "threshold not met"
            except (TypeError, ValueError):
                reason = "metric is not numeric"
        results.append({**assertion, "actual": actual, "passed": passed, "reason": reason})
    return {
        "assertion_count": len(results),
        "passed_count": sum(1 for r in results if r["passed"]),
        "failed_count": sum(1 for r in results if not r["passed"]),
        "all_pass": bool(results) and all(r["passed"] for r in results),
        "results": results,
    }
