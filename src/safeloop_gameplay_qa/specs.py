from __future__ import annotations

import math
import re
from typing import Any

from .config import Settings
from .errors import SafeLoopError

_SAFE_TOKEN = re.compile(r"^[^\x00-\x1f]{1,200}$")
_ALLOWED_OPS = {"<=", ">=", "<", ">", "==", "between", "approx"}
_ALLOWED_GROUND_MODES = {"rigid_and_group", "strict_group", "heuristic_all_meshes"}


def _finite(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SafeLoopError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise SafeLoopError(f"{name} must be finite")
    return number


def _token(value: Any, name: str, max_len: int = 200) -> str:
    text = str(value)
    if len(text) > max_len or not _SAFE_TOKEN.match(text):
        raise SafeLoopError(f"{name} contains invalid/control characters or is too long")
    return text


def validate_assertions(assertions: Any) -> list[dict]:
    if assertions is None:
        return []
    if not isinstance(assertions, list) or len(assertions) > 50:
        raise SafeLoopError("assertions must be a list with at most 50 items")
    clean: list[dict] = []
    for i, raw in enumerate(assertions):
        if not isinstance(raw, dict):
            raise SafeLoopError(f"assertions[{i}] must be an object")
        metric = _token(raw.get("metric", ""), f"assertions[{i}].metric", 120)
        op = str(raw.get("op", ""))
        if op not in _ALLOWED_OPS:
            raise SafeLoopError(f"assertions[{i}].op must be one of {sorted(_ALLOWED_OPS)}")
        item: dict[str, Any] = {"metric": metric, "op": op}
        if op == "between":
            item["min"] = _finite(raw.get("min"), f"assertions[{i}].min")
            item["max"] = _finite(raw.get("max"), f"assertions[{i}].max")
            if item["min"] > item["max"]:
                raise SafeLoopError(f"assertions[{i}] min cannot exceed max")
        else:
            item["value"] = _finite(raw.get("value"), f"assertions[{i}].value")
            if op == "approx":
                item["tolerance"] = max(0.0, _finite(raw.get("tolerance", 0.0), f"assertions[{i}].tolerance"))
        if "label" in raw:
            item["label"] = _token(raw["label"], f"assertions[{i}].label", 200)
        clean.append(item)
    return clean


def validate_scenario_spec(spec: dict, settings: Settings) -> dict:
    if not isinstance(spec, dict):
        raise SafeLoopError("scenario spec must be an object")

    name = _token(spec.get("name", "qa-scenario"), "name", 100)
    scene = str(spec.get("scene", "")).strip()
    if scene:
        scene = _token(scene, "scene", 300)

    duration_s = _finite(spec.get("duration_s", 5.0), "duration_s")
    if not 0.1 <= duration_s <= settings.max_scenario_seconds:
        raise SafeLoopError(f"duration_s must be between 0.1 and {settings.max_scenario_seconds}")
    physics_fps = int(_finite(spec.get("physics_fps", 60), "physics_fps"))
    if not 15 <= physics_fps <= 240:
        raise SafeLoopError("physics_fps must be between 15 and 240")
    sample_hz = int(_finite(spec.get("sample_hz", min(60, physics_fps)), "sample_hz"))
    if not 1 <= sample_hz <= physics_fps:
        raise SafeLoopError("sample_hz must be between 1 and physics_fps")
    estimated_samples = int(duration_s * sample_hz * max(1, len(spec.get("watch", []))))
    if estimated_samples > settings.max_samples:
        raise SafeLoopError("scenario would exceed SAFELOOP_QA_MAX_SAMPLES")

    watch_raw = spec.get("watch", [])
    if not isinstance(watch_raw, list) or not 1 <= len(watch_raw) <= 12:
        raise SafeLoopError("watch must contain between 1 and 12 node definitions")
    watch: list[dict] = []
    ids: set[str] = set()
    for i, raw in enumerate(watch_raw):
        if not isinstance(raw, dict):
            raise SafeLoopError(f"watch[{i}] must be an object")
        wid = _token(raw.get("id", f"node{i}"), f"watch[{i}].id", 80)
        node_path = _token(raw.get("node_path", ""), f"watch[{i}].node_path", 300)
        if not node_path:
            raise SafeLoopError(f"watch[{i}].node_path cannot be empty")
        if wid in ids:
            raise SafeLoopError(f"duplicate watch id: {wid}")
        ids.add(wid)
        props_raw = raw.get("properties", [])
        if not isinstance(props_raw, list) or len(props_raw) > 20:
            raise SafeLoopError(f"watch[{i}].properties must be a list with at most 20 entries")
        properties = [_token(x, f"watch[{i}].properties", 120) for x in props_raw]
        watch.append({"id": wid, "node_path": node_path, "properties": properties})

    inputs_raw = spec.get("inputs", [])
    if not isinstance(inputs_raw, list) or len(inputs_raw) > 100:
        raise SafeLoopError("inputs must be a list with at most 100 entries")
    inputs: list[dict] = []
    for i, raw in enumerate(inputs_raw):
        if not isinstance(raw, dict):
            raise SafeLoopError(f"inputs[{i}] must be an object")
        action = _token(raw.get("action", ""), f"inputs[{i}].action", 120)
        start = _finite(raw.get("start_s", 0.0), f"inputs[{i}].start_s")
        end = _finite(raw.get("end_s", duration_s), f"inputs[{i}].end_s")
        strength = _finite(raw.get("strength", 1.0), f"inputs[{i}].strength")
        if not 0.0 <= start <= end <= duration_s:
            raise SafeLoopError(f"inputs[{i}] must satisfy 0 <= start_s <= end_s <= duration_s")
        if not 0.0 <= strength <= 1.0:
            raise SafeLoopError(f"inputs[{i}].strength must be within 0..1")
        inputs.append({"action": action, "start_s": start, "end_s": end, "strength": strength})

    markers_raw = spec.get("markers", [])
    if not isinstance(markers_raw, list) or len(markers_raw) > 50:
        raise SafeLoopError("markers must be a list with at most 50 entries")
    markers: list[dict] = []
    for i, raw in enumerate(markers_raw):
        if not isinstance(raw, dict):
            raise SafeLoopError(f"markers[{i}] must be an object")
        marker_name = _token(raw.get("name", ""), f"markers[{i}].name", 80)
        at = _finite(raw.get("time_s"), f"markers[{i}].time_s")
        if not 0.0 <= at <= duration_s:
            raise SafeLoopError(f"markers[{i}].time_s outside scenario")
        markers.append({"name": marker_name, "time_s": at})

    grounding = spec.get("grounding")
    clean_grounding = None
    if grounding is not None:
        if not isinstance(grounding, dict):
            raise SafeLoopError("grounding must be an object")
        mode = str(grounding.get("mode", "rigid_and_group"))
        if mode not in _ALLOWED_GROUND_MODES:
            raise SafeLoopError(f"grounding.mode must be one of {sorted(_ALLOWED_GROUND_MODES)}")
        ignore_raw = grounding.get("ignore_path_prefixes", [])
        if not isinstance(ignore_raw, list):
            raise SafeLoopError("grounding.ignore_path_prefixes must be a list")
        clean_grounding = {
            "enabled": bool(grounding.get("enabled", True)),
            "mode": mode,
            "group": _token(grounding.get("group", "safeloop_grounded"), "grounding.group", 100),
            "max_gap_m": max(0.0, min(5.0, _finite(grounding.get("max_gap_m", 0.08), "grounding.max_gap_m"))),
            "ray_length_m": max(0.1, min(50.0, _finite(grounding.get("ray_length_m", 3.0), "grounding.ray_length_m"))),
            "max_vertical_speed_mps": max(0.0, min(20.0, _finite(grounding.get("max_vertical_speed_mps", 0.15), "grounding.max_vertical_speed_mps"))),
            "ignore_path_prefixes": [
                _token(x, "grounding.ignore_path_prefixes", 300)
                for x in ignore_raw[:100]
            ],
        }

    primary_watch_id = _token(spec.get("primary_watch_id", watch[0]["id"]), "primary_watch_id", 80)
    if primary_watch_id not in ids:
        raise SafeLoopError("primary_watch_id must refer to an id present in watch")

    return {
        "name": name,
        "scene": scene,
        "duration_s": duration_s,
        "physics_fps": physics_fps,
        "sample_hz": sample_hz,
        "watch": watch,
        "inputs": inputs,
        "markers": markers,
        "assertions": validate_assertions(spec.get("assertions", [])),
        "grounding": clean_grounding,
        "primary_watch_id": primary_watch_id,
        "stop_speed_kph": max(0.0, min(20.0, _finite(spec.get("stop_speed_kph", 2.0), "stop_speed_kph"))),
        "yaw_response_threshold_dps": max(0.1, min(180.0, _finite(spec.get("yaw_response_threshold_dps", 3.0), "yaw_response_threshold_dps"))),
    }
