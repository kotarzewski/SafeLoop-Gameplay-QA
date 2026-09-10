from __future__ import annotations

import tempfile
from pathlib import Path

from .adapters import GodotQAAdapter
from .config import Settings
from .project import ProjectWorkspace


PROJECT_GODOT = '''[application]\nconfig/name="SafeLoop QA Smoke"\nrun/main_scene="res://main.tscn"\n\n[display]\nwindow/size/viewport_width=320\nwindow/size/viewport_height=180\n\n[input]\naccelerate={\n"deadzone": 0.5,\n"events": []\n}\n'''

SCENE = '''[gd_scene load_steps=2 format=3]\n\n[ext_resource type="Script" path="res://mover.gd" id="1"]\n\n[node name="Main" type="Node3D"]\n\n[node name="Mover" type="CharacterBody3D" parent="."]\nscript = ExtResource("1")\n'''

SCRIPT = '''extends CharacterBody3D\n\nfunc _physics_process(_delta):\n    if Input.is_action_pressed("accelerate"):\n        velocity.x = 10.0\n    else:\n        velocity.x = 0.0\n    move_and_slide()\n'''


def run_godot_smoke_test(godot_bin: str | None = None) -> dict:
    with tempfile.TemporaryDirectory(prefix="safeloop-qa-smoke-") as td:
        root = Path(td)
        (root / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
        (root / "main.tscn").write_text(SCENE, encoding="utf-8")
        (root / "mover.gd").write_text(SCRIPT, encoding="utf-8")
        settings = Settings(workspace=root, allow_runtime=True, godot_bin=godot_bin, max_runtime_seconds=20)
        adapter = GodotQAAdapter(settings, ProjectWorkspace(settings))
        report = adapter.run_scenario({
            "name": "bundled-runner-smoke",
            "scene": "main.tscn",
            "duration_s": 1.0,
            "physics_fps": 60,
            "sample_hz": 30,
            "watch": [{"id": "mover", "node_path": "Mover"}],
            "primary_watch_id": "mover",
            "inputs": [{"action": "accelerate", "start_s": 0.05, "end_s": 0.85, "strength": 1.0}],
            "assertions": [{"metric": "displacement_m", "op": ">=", "value": 3.0}],
        })
        return {
            "ok": report["qa_pass"],
            "metrics": report["metrics"],
            "assertions": report["assertions"],
            "logs": report["logs"],
        }
