from __future__ import annotations

from pathlib import Path

import pytest

from safeloop_gameplay_qa.config import Settings
from safeloop_gameplay_qa.errors import PolicyError
from safeloop_gameplay_qa.security import WorkspacePolicy


def policy(tmp_path: Path) -> WorkspacePolicy:
    return WorkspacePolicy(Settings(workspace=tmp_path))


def test_blocks_escape_and_absolute(tmp_path: Path):
    p = policy(tmp_path)
    with pytest.raises(PolicyError):
        p.resolve_write("../outside.txt", 1)
    with pytest.raises(PolicyError):
        p.resolve_write(str(tmp_path / "abs.txt"), 1)


def test_blocks_secrets_and_internal_state(tmp_path: Path):
    p = policy(tmp_path)
    for name in [".env", "id_rsa", ".safeloop_qa/result.json", ".git/config", "AGENTS.md", "SKILL.md"]:
        with pytest.raises(PolicyError):
            p.resolve_write(name, 1)


def test_blocks_native_binary_write(tmp_path: Path):
    with pytest.raises(PolicyError):
        policy(tmp_path).resolve_write("addons/x.dll", 10)


def test_blocks_symlink_traversal(tmp_path: Path):
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir(exist_ok=True)
    link = tmp_path / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(PolicyError):
        policy(tmp_path).resolve_write("link/escape.txt", 1)
