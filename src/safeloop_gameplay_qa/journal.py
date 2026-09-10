from __future__ import annotations

import difflib
import json
import shutil
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from .errors import SafeLoopError


class MutationJournal:
    """Transactional undo journal for changes made through SafeLoop tools."""

    def __init__(self, workspace: Path, path_validator: Callable[[str], Path] | None = None):
        self.workspace = workspace.resolve()
        self.path_validator = path_validator
        self.state_dir = self.workspace / ".safeloop_qa"
        self.checkpoints_dir = self.state_dir / "checkpoints"
        self.active_file = self.state_dir / "active_checkpoint"
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)

    def create(self, label: str = "") -> dict:
        checkpoint_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        folder = self.checkpoints_dir / checkpoint_id
        (folder / "backups").mkdir(parents=True, exist_ok=True)
        manifest = {
            "id": checkpoint_id,
            "label": label[:120],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "entries": {},
        }
        self._write_manifest(checkpoint_id, manifest)
        self.active_file.parent.mkdir(parents=True, exist_ok=True)
        self.active_file.write_text(checkpoint_id, encoding="utf-8")
        return {"checkpoint_id": checkpoint_id, "label": manifest["label"]}

    def active_id(self) -> str | None:
        if not self.active_file.exists():
            return None
        value = self.active_file.read_text(encoding="utf-8").strip()
        return value or None

    def ensure_active(self) -> str:
        return self.active_id() or self.create("automatic before first mutation")["checkpoint_id"]

    def _manifest_path(self, checkpoint_id: str) -> Path:
        if not checkpoint_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in checkpoint_id):
            raise SafeLoopError("Invalid checkpoint id")
        return self.checkpoints_dir / checkpoint_id / "manifest.json"

    def _load_manifest(self, checkpoint_id: str) -> dict:
        path = self._manifest_path(checkpoint_id)
        if not path.exists():
            raise SafeLoopError(f"Unknown checkpoint: {checkpoint_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_manifest(self, checkpoint_id: str, manifest: dict) -> None:
        path = self._manifest_path(checkpoint_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def record_before(self, relative_path: str, target: Path) -> str:
        checkpoint_id = self.ensure_active()
        manifest = self._load_manifest(checkpoint_id)
        if relative_path in manifest["entries"]:
            return checkpoint_id
        existed = target.exists()
        entry = {"existed": existed, "kind": "file"}
        if existed:
            if not target.is_file():
                raise SafeLoopError("SafeLoop Gameplay QA v0.1 only journals file mutations")
            backup = self.checkpoints_dir / checkpoint_id / "backups" / relative_path
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
            entry["backup"] = str(backup.relative_to(self.checkpoints_dir / checkpoint_id))
        manifest["entries"][relative_path] = entry
        self._write_manifest(checkpoint_id, manifest)
        return checkpoint_id

    def restore(self, checkpoint_id: str) -> dict:
        manifest = self._load_manifest(checkpoint_id)
        restored = []
        removed = []
        for relative_path, entry in reversed(list(manifest["entries"].items())):
            if self.path_validator is not None:
                target = self.path_validator(relative_path)
            else:
                target = (self.workspace / relative_path).resolve(strict=False)
                try:
                    target.relative_to(self.workspace)
                except ValueError as exc:
                    raise SafeLoopError("Corrupt checkpoint contains path outside workspace") from exc
            if entry["existed"]:
                checkpoint_root = (self.checkpoints_dir / checkpoint_id).resolve()
                backup = (checkpoint_root / entry["backup"]).resolve()
                try:
                    backup.relative_to(checkpoint_root)
                except ValueError as exc:
                    raise SafeLoopError("Corrupt checkpoint backup path escapes checkpoint directory") from exc
                if not backup.is_file():
                    raise SafeLoopError("Checkpoint backup is missing or invalid")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, target)
                restored.append(relative_path)
            elif target.exists() and target.is_file():
                target.unlink()
                removed.append(relative_path)
        return {"checkpoint_id": checkpoint_id, "restored": restored, "removed_created_files": removed}

    def diff(self, checkpoint_id: str, max_chars: int = 40_000) -> str:
        manifest = self._load_manifest(checkpoint_id)
        chunks: list[str] = []
        for relative_path, entry in manifest["entries"].items():
            current = self.workspace / relative_path
            before_text = ""
            after_text = ""
            try:
                if entry["existed"]:
                    backup = self.checkpoints_dir / checkpoint_id / entry["backup"]
                    before_text = backup.read_text(encoding="utf-8")
                if current.exists() and current.is_file():
                    after_text = current.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                chunks.append(f"Binary/non-text change: {relative_path}\n")
                continue
            diff = difflib.unified_diff(
                before_text.splitlines(True),
                after_text.splitlines(True),
                fromfile=f"before/{relative_path}",
                tofile=f"after/{relative_path}",
            )
            chunks.append("".join(diff))
            if sum(len(c) for c in chunks) >= max_chars:
                chunks.append("\n... diff truncated ...\n")
                break
        return "".join(chunks) or "No recorded changes since checkpoint."
