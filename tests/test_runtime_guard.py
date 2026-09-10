from __future__ import annotations

from safeloop_gameplay_qa.config import Settings
from safeloop_gameplay_qa.project import ProjectWorkspace
from safeloop_gameplay_qa.runtime_guard import RuntimeGuard


def test_blocks_process_spawn(tmp_path):
    (tmp_path / "bad.gd").write_text('func x():\n    OS.execute("cmd", [])\n', encoding="utf-8")
    guard = RuntimeGuard(Settings(workspace=tmp_path), ProjectWorkspace(Settings(workspace=tmp_path)))
    out = guard.decision()
    assert out["allowed_by_scan"] is False
    assert out["counts"]["critical"] >= 1


def test_blocks_network_by_default(tmp_path):
    (tmp_path / "net.gd").write_text('var x = HTTPRequest.new()\n', encoding="utf-8")
    settings = Settings(workspace=tmp_path)
    out = RuntimeGuard(settings, ProjectWorkspace(settings)).decision()
    assert out["allowed_by_scan"] is False
    assert out["counts"]["network"] >= 1


def test_network_can_only_be_opted_in_via_settings(tmp_path):
    (tmp_path / "net.gd").write_text('var x = HTTPRequest.new()\n', encoding="utf-8")
    settings = Settings(workspace=tmp_path, allow_networked_runtime=True)
    out = RuntimeGuard(settings, ProjectWorkspace(settings)).decision()
    assert out["allowed_by_scan"] is True
