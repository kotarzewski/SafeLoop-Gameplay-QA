from __future__ import annotations

import fnmatch
from pathlib import Path

from .config import Settings
from .errors import PolicyError


class WorkspacePolicy:
    """Enforces least-privilege access to a single project workspace."""

    BLOCKED_PARTS = {
        ".git",
        ".safeloop",
        ".safeloop_qa",
        ".codex",
        ".agents",
        ".ssh",
        ".gnupg",
        ".aws",
        ".azure",
        ".config",
    }
    BLOCKED_BASENAMES = {
        ".env",
        ".env.local",
        ".env.production",
        ".env.development",
        "agents.md",
        "skill.md",
        "credentials",
        "credentials.json",
        "credentials.toml",
        "credentials.yaml",
        "credentials.yml",
        "secrets.json",
        "secrets.toml",
        "secrets.yaml",
        "secrets.yml",
        ".npmrc",
        ".pypirc",
        ".netrc",
        "auth.json",
        "id_rsa",
        "id_ed25519",
    }
    BLOCKED_GLOBS = (
        "*.pem",
        "*.key",
        "*.p12",
        "*.pfx",
        "*.keystore",
    )
    BINARY_WRITE_EXTENSIONS = {
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".bin",
        ".app",
        ".msi",
        ".com",
        ".scr",
    }

    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.workspace.resolve()

    def _validate_relative(self, relative_path: str) -> Path:
        if not relative_path or "\x00" in relative_path:
            raise PolicyError("Path must be a non-empty relative path")
        raw = Path(relative_path)
        if raw.is_absolute():
            raise PolicyError("Absolute paths are not allowed")
        current = self.root
        for part in raw.parts:
            if part in {"", "."}:
                continue
            current = current / part
            if current.exists() and current.is_symlink():
                raise PolicyError("Symlinked project paths are not allowed")
        candidate = (self.root / raw).resolve(strict=False)
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise PolicyError("Path escapes the configured workspace") from exc
        return candidate

    def _check_blocked(self, relative_path: str, for_write: bool) -> None:
        normalized = relative_path.replace("\\", "/").strip("/")
        parts = [p.lower() for p in normalized.split("/") if p]
        if any(part in self.BLOCKED_PARTS for part in parts):
            raise PolicyError("Access to agent/configuration metadata is blocked")
        name = parts[-1] if parts else ""
        if name in self.BLOCKED_BASENAMES:
            raise PolicyError("Access to secret or agent-instruction files is blocked")
        if any(fnmatch.fnmatch(name, pattern) for pattern in self.BLOCKED_GLOBS):
            raise PolicyError("Access to possible credential/secret material is blocked")
        if for_write and Path(name).suffix.lower() in self.BINARY_WRITE_EXTENSIONS:
            raise PolicyError("Writing executable/native binary files is blocked")

    def resolve_read(self, relative_path: str) -> Path:
        target = self._validate_relative(relative_path)
        self._check_blocked(relative_path, for_write=False)
        if not target.exists() or not target.is_file():
            raise PolicyError(f"File does not exist: {relative_path}")
        if target.stat().st_size > self.settings.max_read_bytes:
            raise PolicyError("File exceeds SAFELOOP_QA_MAX_READ_BYTES")
        return target

    def resolve_write(self, relative_path: str, content_bytes: int | None = None) -> Path:
        target = self._validate_relative(relative_path)
        self._check_blocked(relative_path, for_write=True)
        if content_bytes is not None and content_bytes > self.settings.max_write_bytes:
            raise PolicyError("Write exceeds SAFELOOP_QA_MAX_WRITE_BYTES")
        return target

    def visible(self, relative_path: str) -> bool:
        try:
            self._validate_relative(relative_path)
            self._check_blocked(relative_path, for_write=False)
            return True
        except PolicyError:
            return False
