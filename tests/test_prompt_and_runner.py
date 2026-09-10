from __future__ import annotations

from importlib.resources import files

from safeloop_gameplay_qa.prompts import gameplay_qa_loop_prompt


def test_prompt_forbids_subjective_realism_pass():
    text = gameplay_qa_loop_prompt("test a car")
    assert "UNCALIBRATED" in text
    assert "machine-evaluated assertions" in text
    assert "SafeLoop Visual" in text


def test_bundled_runner_has_no_process_or_network_calls():
    text = files("safeloop_gameplay_qa").joinpath("runtime/godot_qa_runner.gd").read_text(encoding="utf-8")
    forbidden = ["OS.execute", "OS.create_process", "OS.shell_open", "HTTPRequest", "HTTPClient", "WebSocketPeer"]
    assert all(x not in text for x in forbidden)
    assert "Input.action_press" in text
    assert "Input.parse_input_event" in text
    assert "intersect_ray" in text
