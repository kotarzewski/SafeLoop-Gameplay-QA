from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from safeloop_gameplay_qa.adapters.godot import GodotQAAdapter
from safeloop_gameplay_qa.config import Settings
from safeloop_gameplay_qa.errors import RuntimeBlockedError
from safeloop_gameplay_qa.project import ProjectWorkspace


def make_project(tmp_path):
    (tmp_path / "project.godot").write_text('[application]\nrun/main_scene="res://world.tscn"\n\n[input]\naccelerate={\n}\nbrake={\n}\n', encoding="utf-8")
    (tmp_path / "world.tscn").write_text('[gd_scene format=3]\n\n[node name="World" type="Node3D"]\n[node name="Car" type="RigidBody3D" parent="."]\n', encoding="utf-8")


def test_safe_env_does_not_forward_api_keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("FAL_KEY", "secret2")
    env = GodotQAAdapter._safe_env()
    assert "OPENAI_API_KEY" not in env
    assert "FAL_KEY" not in env


def test_runtime_off_by_default(tmp_path):
    make_project(tmp_path)
    settings = Settings(workspace=tmp_path)
    adapter = GodotQAAdapter(settings, ProjectWorkspace(settings))
    with pytest.raises(RuntimeBlockedError):
        adapter.run_scenario({"watch": [{"id": "car", "node_path": "Car"}]})


def test_parses_input_actions_and_scene(tmp_path):
    make_project(tmp_path)
    settings = Settings(workspace=tmp_path)
    adapter = GodotQAAdapter(settings, ProjectWorkspace(settings))
    assert adapter.input_actions() == ["accelerate", "brake"]
    summary = adapter.scene_summary("world.tscn")
    assert summary["node_count"] == 2
    assert summary["nodes"][1]["name"] == "Car"


def test_run_scenario_uses_bundled_runner_and_machine_verdict(tmp_path, monkeypatch):
    make_project(tmp_path)
    settings = Settings(workspace=tmp_path, allow_runtime=True)
    adapter = GodotQAAdapter(settings, ProjectWorkspace(settings))

    def fake_run(args, timeout=None):
        out_arg = next(a for a in args if a.startswith("--qa-out="))
        raw = out_arg.split("=", 1)[1]
        out = Path(raw) if Path(raw).is_absolute() else tmp_path / raw.removeprefix("res://")
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "ok": True,
            "spec": {
                "primary_watch_id": "car",
                "markers": [],
                "stop_speed_kph": 2.0,
                "yaw_response_threshold_dps": 3.0,
            },
            "samples": [
                {"t": 0.0, "id": "car", "position": [0,0,0], "rotation_deg": [0,0,0], "velocity": [0,0,0], "angular_velocity": [0,0,0], "forward": [1,0,0]},
                {"t": 1.0, "id": "car", "position": [10,0,0], "rotation_deg": [0,0,0], "velocity": [20,0,0], "angular_velocity": [0,0,0], "forward": [1,0,0]},
            ],
            "missing_watch_nodes": [],
            "missing_input_actions": [],
            "grounding": None,
        }
        out.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, "ok", "")

    monkeypatch.setattr(adapter, "_run", fake_run)
    report = adapter.run_scenario({
        "name": "test",
        "scene": "world.tscn",
        "duration_s": 1,
        "watch": [{"id": "car", "node_path": "Car"}],
        "assertions": [{"metric": "max_speed_kph", "op": ">=", "value": 70}],
    })
    assert report["calibration_status"] == "CALIBRATED"
    assert report["qa_pass"] is True
    assert (tmp_path / ".safeloop_qa/runs" / report["run_id"] / "godot_qa_runner.gd").exists()
    assert (tmp_path / ".safeloop_qa/runs" / report["run_id"] / "report.json").exists()


def test_uncalibrated_run_never_passes(tmp_path, monkeypatch):
    make_project(tmp_path)
    settings = Settings(workspace=tmp_path, allow_runtime=True)
    adapter = GodotQAAdapter(settings, ProjectWorkspace(settings))

    def fake_run(args, timeout=None):
        out_arg = next(a for a in args if a.startswith("--qa-out="))
        raw = out_arg.split("=", 1)[1]
        out = Path(raw) if Path(raw).is_absolute() else tmp_path / raw.removeprefix("res://")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"ok": True, "spec": {"primary_watch_id": "car", "markers": []}, "samples": [{"t":0,"id":"car","position":[0,0,0]}], "missing_watch_nodes": [], "missing_input_actions": [], "grounding": None}), encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(adapter, "_run", fake_run)
    report = adapter.run_scenario({"duration_s": 1, "watch": [{"id": "car", "node_path": "Car"}], "assertions": []})
    assert report["calibration_status"] == "UNCALIBRATED"
    assert report["qa_pass"] is False
