from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import Settings
from .project import ProjectWorkspace


@dataclass(frozen=True)
class RiskFinding:
    severity: str
    category: str
    path: str
    line: int
    rule: str
    excerpt: str

    def as_dict(self) -> dict:
        return asdict(self)


SCRIPT_EXTENSIONS = {".gd", ".cs"}
NATIVE_EXTENSIONS = {".dll", ".so", ".dylib", ".gdextension", ".gdnlib"}

RULES = [
    ("critical", "process", "godot_os_execute", re.compile(r"\bOS\s*\.\s*execute\s*\(")),
    ("critical", "process", "godot_create_process", re.compile(r"\bOS\s*\.\s*create_process\s*\(")),
    ("critical", "process", "godot_shell_open", re.compile(r"\bOS\s*\.\s*shell_open\s*\(")),
    ("critical", "process", "dotnet_process", re.compile(r"\b(?:System\s*\.\s*Diagnostics\s*\.\s*)?Process\s*\.\s*(?:Start|StartInfo)\b")),
    ("network", "network", "godot_http", re.compile(r"\b(?:HTTPRequest|HTTPClient)\b")),
    ("network", "network", "godot_socket", re.compile(r"\b(?:WebSocketPeer|WebSocketMultiplayerPeer|StreamPeerTCP|PacketPeerUDP|TCPServer)\b")),
    ("network", "network", "dotnet_network", re.compile(r"\b(?:HttpClient|WebClient|System\s*\.\s*Net\s*\.\s*Sockets)\b")),
    ("warning", "filesystem", "dynamic_file_access", re.compile(r"\bFileAccess\s*\.\s*open\s*\(")),
]


class RuntimeGuard:
    def __init__(self, settings: Settings, project: ProjectWorkspace):
        self.settings = settings
        self.project = project

    def scan(self, max_findings: int = 200) -> list[RiskFinding]:
        findings: list[RiskFinding] = []
        for rel in self.project.list_files("**/*", limit=5000):
            path = self.settings.workspace / rel
            suffix = path.suffix.lower()
            if suffix in NATIVE_EXTENSIONS:
                findings.append(RiskFinding(
                    severity="critical",
                    category="native",
                    path=rel,
                    line=0,
                    rule="native_extension",
                    excerpt="Native binary/extension present; SafeLoop cannot inspect its behavior.",
                ))
                if len(findings) >= max_findings:
                    break
                continue
            if suffix not in SCRIPT_EXTENSIONS:
                continue
            try:
                if path.stat().st_size > self.settings.max_read_bytes:
                    continue
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for line_no, line in enumerate(lines, start=1):
                for severity, category, rule, regex in RULES:
                    if regex.search(line):
                        # Literal res:// or user:// FileAccess is common and does not by itself imply external access.
                        if rule == "dynamic_file_access" and re.search(r"FileAccess\s*\.\s*open\s*\(\s*[\"'](?:res|user)://", line):
                            continue
                        findings.append(RiskFinding(severity, category, rel, line_no, rule, line.strip()[:300]))
                        if len(findings) >= max_findings:
                            return findings
        return findings

    def decision(self) -> dict:
        findings = self.scan()
        critical = [f for f in findings if f.severity == "critical"]
        network = [f for f in findings if f.severity == "network"]
        blocked_reasons = []
        if critical and not self.settings.allow_risky_runtime:
            blocked_reasons.append("critical runtime capabilities detected")
        if network and not self.settings.allow_networked_runtime:
            blocked_reasons.append("network-capable project code detected")
        return {
            "allowed_by_scan": not blocked_reasons,
            "blocked_reasons": blocked_reasons,
            "counts": {
                "critical": len(critical),
                "network": len(network),
                "warning": sum(1 for f in findings if f.severity == "warning"),
            },
            "findings": [f.as_dict() for f in findings],
            "important": (
                "This is a defensive static scan, not a security proof. Running any project executes its code. "
                "Only enable runtime for projects you trust."
            ),
        }
