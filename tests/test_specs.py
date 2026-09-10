from __future__ import annotations

import pytest

from safeloop_gameplay_qa.config import Settings
from safeloop_gameplay_qa.errors import SafeLoopError
from safeloop_gameplay_qa.specs import validate_scenario_spec


def base_spec():
    return {
        "name": "test",
        "duration_s": 5,
        "watch": [{"id": "car", "node_path": "Car", "properties": ["engine_rpm"]}],
        "inputs": [{"action": "accelerate", "start_s": 0, "end_s": 4, "strength": 1}],
        "assertions": [{"metric": "max_speed_kph", "op": ">=", "value": 50}],
    }


def test_validates_and_preserves_custom_props(tmp_path):
    out = validate_scenario_spec(base_spec(), Settings(workspace=tmp_path))
    assert out["watch"][0]["properties"] == ["engine_rpm"]
    assert out["primary_watch_id"] == "car"


def test_rejects_too_long_runtime(tmp_path):
    spec = base_spec()
    spec["duration_s"] = 999
    with pytest.raises(SafeLoopError):
        validate_scenario_spec(spec, Settings(workspace=tmp_path))


def test_rejects_bad_input_window(tmp_path):
    spec = base_spec()
    spec["inputs"][0]["start_s"] = 4
    spec["inputs"][0]["end_s"] = 2
    with pytest.raises(SafeLoopError):
        validate_scenario_spec(spec, Settings(workspace=tmp_path))


def test_rejects_expression_instead_of_safe_operator(tmp_path):
    spec = base_spec()
    spec["assertions"] = [{"metric": "max_speed_kph", "op": "eval", "value": 1}]
    with pytest.raises(SafeLoopError):
        validate_scenario_spec(spec, Settings(workspace=tmp_path))


def test_rejects_unknown_primary_watch_id(tmp_path):
    spec = base_spec()
    spec["primary_watch_id"] = "missing"
    with pytest.raises(SafeLoopError):
        validate_scenario_spec(spec, Settings(workspace=tmp_path))


def test_rejects_non_list_grounding_ignores(tmp_path):
    spec = base_spec()
    spec["grounding"] = {"ignore_path_prefixes": "not-a-list"}
    with pytest.raises(SafeLoopError):
        validate_scenario_spec(spec, Settings(workspace=tmp_path))
