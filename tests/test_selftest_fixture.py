from safeloop_gameplay_qa.selftest import PROJECT_GODOT, SCENE, SCRIPT


def test_smoke_fixture_contains_required_parts():
    assert 'run/main_scene="res://main.tscn"' in PROJECT_GODOT
    assert '[node name="Mover" type="CharacterBody3D"' in SCENE
    assert 'Input.is_action_pressed("accelerate")' in SCRIPT
