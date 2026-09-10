from __future__ import annotations

import math

from safeloop_gameplay_qa.metrics import derive_metrics, evaluate_assertions


def row(t, speed_mps, x, yaw_rate=0.0, roll=0.0, rpm=None):
    r = {
        "t": t,
        "id": "car",
        "position": [x, 0.5, 0.0],
        "rotation_deg": [0.0, 0.0, roll],
        "velocity": [speed_mps, 0.0, 0.0],
        "angular_velocity": [0.0, math.radians(yaw_rate), 0.0],
        "forward": [1.0, 0.0, 0.0],
    }
    if rpm is not None:
        r["props"] = {"rpm": rpm}
    return r


def test_derives_vehicle_metrics_and_braking():
    result = {
        "spec": {
            "primary_watch_id": "car",
            "markers": [{"name": "brake_start", "time_s": 2.0}],
            "stop_speed_kph": 2.0,
            "yaw_response_threshold_dps": 3.0,
        },
        "samples": [
            row(0, 0, 0, rpm=1000),
            row(1, 15, 7, rpm=2500),
            row(2, 30, 25, rpm=4000),
            row(3, 20, 45, rpm=3000),
            row(4, 0.2, 55, rpm=900),
        ],
        "grounding": {"candidate_count": 4, "unsupported_count": 0, "mode": "strict_group"},
    }
    m = derive_metrics(result, "car")
    assert m["max_speed_kph"] == 108.0
    assert m["zero_to_100_s"] == 2.0
    assert m["brake_time_s"] == 2.0
    assert m["brake_distance_m"] == 30.0
    assert m["grounding"]["all_supported"] is True
    assert m["props"]["rpm"]["max"] == 4000


def test_assertions_are_machine_evaluated():
    verdict = evaluate_assertions(
        {"speed": 100.0, "nested": {"gap": 0.02}},
        [
            {"metric": "speed", "op": "between", "min": 95, "max": 105},
            {"metric": "nested.gap", "op": "<=", "value": 0.05},
        ],
    )
    assert verdict["all_pass"] is True
    assert verdict["passed_count"] == 2


def test_empty_assertions_never_pass():
    assert evaluate_assertions({}, [])["all_pass"] is False


def test_missing_metric_fails():
    out = evaluate_assertions({}, [{"metric": "x", "op": "<=", "value": 1}])
    assert out["all_pass"] is False
    assert out["results"][0]["reason"] == "metric unavailable"
