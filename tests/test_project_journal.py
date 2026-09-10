from __future__ import annotations

from safeloop_gameplay_qa.config import Settings
from safeloop_gameplay_qa.project import ProjectWorkspace


def test_checkpoint_write_diff_restore(tmp_path):
    target = tmp_path / "player.gd"
    target.write_text("old\n", encoding="utf-8")
    project = ProjectWorkspace(Settings(workspace=tmp_path))
    cp = project.journal.create("before fix")["checkpoint_id"]
    project.write_file("player.gd", "new\n", "test")
    assert "-old" in project.journal.diff(cp)
    assert "+new" in project.journal.diff(cp)
    project.journal.restore(cp)
    assert target.read_text(encoding="utf-8") == "old\n"


def test_created_file_removed_on_restore(tmp_path):
    project = ProjectWorkspace(Settings(workspace=tmp_path))
    cp = project.journal.create()["checkpoint_id"]
    project.write_file("new.gd", "x\n")
    assert (tmp_path / "new.gd").exists()
    project.journal.restore(cp)
    assert not (tmp_path / "new.gd").exists()
