from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from .config import Settings
from .errors import PolicyError
from .journal import MutationJournal
from .security import WorkspacePolicy


IGNORED_DIRS = {".godot", "node_modules", "Library", "Temp", "Build", "build", "dist", ".idea", ".vscode"}

TEXT_EXTENSIONS = {
    ".gd", ".cs", ".tscn", ".tres", ".godot", ".cfg", ".ini", ".toml", ".json",
    ".yaml", ".yml", ".xml", ".txt", ".md", ".py", ".js", ".ts", ".tsx", ".jsx",
    ".html", ".css", ".scss", ".svg", ".shader", ".glsl", ".lua", ".luau", ".rbxlx", ".csv",
}


class ProjectWorkspace:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.policy = WorkspacePolicy(settings)
        self.journal = MutationJournal(settings.workspace, self.policy.resolve_write)

    def detect_engine(self) -> str:
        root = self.settings.workspace
        if (root / "project.godot").exists():
            return "godot"
        if any(root.glob("*.uproject")):
            return "unreal"
        if (root / "ProjectSettings" / "ProjectVersion.txt").exists():
            return "unity"
        if any(root.glob("*.rbxl")) or any(root.glob("*.rbxlx")):
            return "roblox"
        if (root / "package.json").exists():
            return "web/node"
        return "unknown"

    def info(self) -> dict:
        return {
            "workspace": str(self.settings.workspace),
            "engine": self.detect_engine(),
            "security": {
                "allow_delete": self.settings.allow_delete,
                "allow_engine": self.settings.allow_engine,
                "allow_runtime": self.settings.allow_runtime,
                "allow_networked_runtime": self.settings.allow_networked_runtime,
                "allow_risky_runtime": self.settings.allow_risky_runtime,
                "raw_shell_exposed": False,
                "arbitrary_network_tool_exposed": False,
            },
            "active_checkpoint": self.journal.active_id(),
        }

    def _iter_files(self):
        root = self.settings.workspace
        for current_root, dirs, files in os.walk(root):
            current_path = Path(current_root)
            rel_dir = current_path.relative_to(root)
            kept_dirs = []
            for d in dirs:
                if d in IGNORED_DIRS:
                    continue
                rel = (rel_dir / d).as_posix()
                if self.policy.visible(rel):
                    kept_dirs.append(d)
            dirs[:] = kept_dirs
            for filename in files:
                rel = (rel_dir / filename).as_posix()
                if self.policy.visible(rel):
                    yield rel

    def list_files(self, pattern: str = "**/*", limit: int = 250) -> list[str]:
        limit = max(1, min(1000, limit))
        files = []
        for rel in self._iter_files():
            if pattern in {"", "**/*", "*"} or fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(Path(rel).name, pattern):
                files.append(rel)
                if len(files) >= limit:
                    break
        return sorted(files)

    def read_file(self, relative_path: str, start_line: int = 1, end_line: int = 400) -> str:
        target = self.policy.resolve_read(relative_path)
        start_line = max(1, start_line)
        end_line = max(start_line, min(start_line + 2000, end_line))
        try:
            lines = target.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise PolicyError("Only UTF-8 text files can be read through this tool") from exc
        selected = lines[start_line - 1:end_line]
        return "\n".join(f"{idx}: {line}" for idx, line in enumerate(selected, start=start_line))

    def search_text(self, query: str, pattern: str = "**/*", case_sensitive: bool = False, max_results: int = 50) -> list[dict]:
        if not query:
            return []
        needle = query if case_sensitive else query.lower()
        max_results = max(1, min(200, max_results))
        results = []
        for rel in self.list_files(pattern=pattern, limit=1000):
            path = self.settings.workspace / rel
            if path.suffix.lower() not in TEXT_EXTENSIONS and path.name != "project.godot":
                continue
            try:
                if path.stat().st_size > self.settings.max_read_bytes:
                    continue
                lines = path.read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for line_no, line in enumerate(lines, start=1):
                hay = line if case_sensitive else line.lower()
                if needle in hay:
                    results.append({"path": rel, "line": line_no, "text": line[:500]})
                    if len(results) >= max_results:
                        return results
        return results

    def write_file(self, relative_path: str, content: str, reason: str = "") -> dict:
        encoded = content.encode("utf-8")
        target = self.policy.resolve_write(relative_path, len(encoded))
        checkpoint_id = self.journal.record_before(relative_path, target)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".safeloop-qa-tmp")
        tmp.write_text(content, encoding="utf-8", newline="")
        tmp.replace(target)
        return {"path": relative_path, "bytes": len(encoded), "checkpoint_id": checkpoint_id, "reason": reason[:300]}

    def replace_text(self, relative_path: str, old: str, new: str, expected_replacements: int = 1, reason: str = "") -> dict:
        if not old:
            raise PolicyError("old text must not be empty")
        target = self.policy.resolve_read(relative_path)
        text = target.read_text(encoding="utf-8")
        count = text.count(old)
        if count != expected_replacements:
            raise PolicyError(f"Expected {expected_replacements} replacement(s), found {count}; refusing ambiguous edit")
        result = text.replace(old, new)
        if len(result.encode("utf-8")) > self.settings.max_write_bytes:
            raise PolicyError("Result exceeds SAFELOOP_QA_MAX_WRITE_BYTES")
        checkpoint_id = self.journal.record_before(relative_path, target)
        tmp = target.with_name(target.name + ".safeloop-qa-tmp")
        tmp.write_text(result, encoding="utf-8", newline="")
        tmp.replace(target)
        return {"path": relative_path, "replacements": count, "checkpoint_id": checkpoint_id, "reason": reason[:300]}

    def delete_file(self, relative_path: str, reason: str = "") -> dict:
        if not self.settings.allow_delete:
            raise PolicyError("Deletion is disabled. Set SAFELOOP_QA_ALLOW_DELETE=1 outside the project to opt in.")
        target = self.policy.resolve_read(relative_path)
        checkpoint_id = self.journal.record_before(relative_path, target)
        target.unlink()
        return {"path": relative_path, "deleted": True, "checkpoint_id": checkpoint_id, "reason": reason[:300]}
