from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from importlib.resources import files
from pathlib import Path

from ..config import Settings
from ..errors import AdapterError, RuntimeBlockedError
from ..metrics import derive_metrics, evaluate_assertions
from ..project import ProjectWorkspace
from ..runtime_guard import RuntimeGuard
from ..specs import validate_scenario_spec
from .base import EngineAdapter


_NODE_RE = re.compile(r'^\[node\s+name="([^"]+)"(?:\s+type="([^"]+)")?(?:\s+parent="([^"]*)")?.*\]$')
_INPUT_KEY_RE = re.compile(r'^([A-Za-z0-9_.:/-]+)\s*=\s*\{$')


class GodotQAAdapter(EngineAdapter):
    def __init__(self, settings: Settings, project: ProjectWorkspace):
        self.settings = settings
        self.project = project
        self.guard = RuntimeGuard(settings, project)

    def _binary(self) -> str:
        candidates: list[str] = []
        if self.settings.godot_bin:
            candidates.append(self.settings.godot_bin)
        candidates.extend(["godot", "godot4", "godot-mono"])
        for candidate in candidates:
            expanded = str(Path(candidate).expanduser()) if any(sep in candidate for sep in ("/", "\\")) else candidate
            found = expanded if Path(expanded).is_file() else shutil.which(expanded)
            if found:
                return str(Path(found).resolve())
        raise AdapterError("Godot executable not found. Set SAFELOOP_QA_GODOT_BIN to the executable path.")

    @staticmethod
    def _safe_env() -> dict[str, str]:
        # Do not forward API keys, tokens, SSH variables, cloud credentials, or arbitrary host environment.
        allow = {
            "PATH", "SystemRoot", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR",
            "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "LANG", "LC_ALL",
            "DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "XDG_DATA_HOME", "XDG_CONFIG_HOME",
        }
        return {k: v for k, v in os.environ.items() if k in allow}

    def _run(self, args: list[str], timeout: int | None = None) -> subprocess.CompletedProcess[str]:
        binary = self._binary()
        try:
            return subprocess.run(
                [binary, *args],
                cwd=self.settings.workspace,
                env=self._safe_env(),
                capture_output=True,
                text=True,
                timeout=timeout or self.settings.max_runtime_seconds,
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AdapterError(f"Godot timed out after {timeout or self.settings.max_runtime_seconds}s") from exc

    @staticmethod
    def _trim(text: str, limit: int = 12_000) -> str:
        return text if len(text) <= limit else text[-limit:] + "\n... output truncated ..."

    def doctor(self) -> dict:
        binary = self._binary()
        result = self._run(["--version"], timeout=10)
        return {
            "found": result.returncode == 0,
            "binary": binary,
            "version": self._trim((result.stdout or result.stderr).strip(), 1000),
            "returncode": result.returncode,
        }

    def validate(self) -> dict:
        if not self.settings.allow_engine:
            raise RuntimeBlockedError("Engine execution is disabled by SAFELOOP_QA_ALLOW_ENGINE=0")
        if not (self.settings.workspace / "project.godot").exists():
            raise AdapterError("This workspace is not a Godot project (project.godot missing)")
        result = self._run([
            "--headless", "--editor", "--recovery-mode", "--path", str(self.settings.workspace),
            "--quit-after", "1", "--no-header",
        ])
        output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        return {
            "ok": result.returncode == 0 and "ERROR:" not in output,
            "returncode": result.returncode,
            "output": self._trim(output),
            "mode": "headless editor recovery-mode; game scene not intentionally executed",
        }

    def input_actions(self) -> list[str]:
        config = self.settings.workspace / "project.godot"
        if not config.exists():
            raise AdapterError("project.godot missing")
        lines = config.read_text(encoding="utf-8", errors="replace").splitlines()
        in_input = False
        actions: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                in_input = stripped == "[input]"
                continue
            if not in_input:
                continue
            match = _INPUT_KEY_RE.match(stripped)
            if match:
                actions.append(match.group(1))
        return sorted(set(actions))

    def scene_summary(self, scene: str) -> dict:
        path = self.project.policy.resolve_read(scene)
        if path.suffix.lower() != ".tscn":
            raise AdapterError("scene_summary currently supports text .tscn scenes only")
        nodes: list[dict] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = _NODE_RE.match(line.strip())
            if not match:
                continue
            name, node_type, parent = match.groups()
            nodes.append({"name": name, "type": node_type or "inherited/unknown", "parent": parent or "."})
        return {"scene": scene, "node_count": len(nodes), "nodes": nodes[:1000]}

    def _prepare_runner(self, run_dir: Path) -> str:
        target = run_dir / "godot_qa_runner.gd"
        source = files("safeloop_gameplay_qa").joinpath("runtime/godot_qa_runner.gd").read_text(encoding="utf-8")
        target.write_text(source, encoding="utf-8", newline="")
        # Godot officially accepts an absolute filesystem path for --script.
        # This avoids relying on whether hidden project directories are indexed as resources.
        return target.resolve().as_posix()

    def run_scenario(self, raw_spec: dict) -> dict:
        if not self.settings.allow_runtime:
            raise RuntimeBlockedError(
                "Gameplay runtime is disabled by default. Set SAFELOOP_QA_ALLOW_RUNTIME=1 in the MCP host configuration "
                "only for a project you trust."
            )
        if not (self.settings.workspace / "project.godot").exists():
            raise AdapterError("This workspace is not a Godot project (project.godot missing)")
        decision = self.guard.decision()
        if not decision["allowed_by_scan"]:
            raise RuntimeBlockedError(
                "Runtime guard blocked execution: " + "; ".join(decision["blocked_reasons"]) +
                ". Review scan_runtime_risks. Overrides must be configured outside the project."
            )

        spec = validate_scenario_spec(raw_spec, self.settings)
        if spec["scene"]:
            scene_path = self.project.policy.resolve_read(spec["scene"])
            if scene_path.suffix.lower() != ".tscn":
                raise AdapterError("Scenario scene must be a .tscn file")
            spec["scene"] = "res://" + scene_path.relative_to(self.settings.workspace).as_posix()

        run_id = uuid.uuid4().hex[:12]
        run_dir = self.settings.workspace / ".safeloop_qa" / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        spec_path = run_dir / "spec.json"
        out_path = run_dir / "result.json"
        spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        runner = self._prepare_runner(run_dir)
        spec_arg = spec_path.resolve().as_posix()
        out_arg = out_path.resolve().as_posix()

        timeout = min(
            self.settings.max_runtime_seconds,
            max(10, int(spec["duration_s"] * 2 + 10)),
        )
        result = self._run([
            "--headless",
            "--path", str(self.settings.workspace),
            "--fixed-fps", str(spec["physics_fps"]),
            "--disable-vsync",
            "--no-header",
            "--script", runner,
            "--",
            f"--qa-spec={spec_arg}",
            f"--qa-out={out_arg}",
        ], timeout=timeout)
        output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        if not out_path.exists():
            raise AdapterError(
                f"Godot QA runner produced no result file. Return code={result.returncode}. Output:\n{self._trim(output)}"
            )
        try:
            payload = json.loads(out_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AdapterError("Godot QA result was unreadable or invalid JSON") from exc

        metrics = derive_metrics(payload, spec["primary_watch_id"])
        verdict = evaluate_assertions(metrics, spec["assertions"])
        missing = bool(metrics.get("missing_watch_nodes") or metrics.get("missing_input_actions"))
        calibrated = bool(spec["assertions"])
        qa_pass = payload.get("ok") is True and calibrated and verdict["all_pass"] and not missing
        report = {
            "run_id": run_id,
            "ok": payload.get("ok") is True,
            "returncode": result.returncode,
            "calibration_status": "CALIBRATED" if calibrated else "UNCALIBRATED",
            "qa_pass": qa_pass,
            "metrics": metrics,
            "assertions": verdict,
            "grounding": payload.get("grounding"),
            "missing_watch_nodes": payload.get("missing_watch_nodes", []),
            "missing_input_actions": payload.get("missing_input_actions", []),
            "logs": self._trim(output, 8000),
            "result_path": str(out_path),
            "guard": {"counts": decision["counts"], "important": decision["important"]},
            "important": (
                "qa_pass can only be true when explicit numeric assertions exist and pass. "
                "UNCALIBRATED runs are measurement-only and must not be described as proving realism."
            ),
        }
        (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    def scan_ground_support(
        self,
        scene: str = "",
        mode: str = "rigid_and_group",
        group: str = "safeloop_grounded",
        settle_seconds: float = 2.0,
        max_gap_m: float = 0.08,
        ray_length_m: float = 3.0,
        max_vertical_speed_mps: float = 0.15,
        ignore_path_prefixes: list[str] | None = None,
    ) -> dict:
        raw_spec = {
            "name": "world-ground-support-scan",
            "scene": scene,
            "duration_s": settle_seconds,
            "physics_fps": 60,
            "sample_hz": 10,
            "watch": [{"id": "root", "node_path": "."}],
            "primary_watch_id": "root",
            "inputs": [],
            "markers": [],
            "assertions": [{"metric": "grounding.unsupported_count", "op": "==", "value": 0}],
            "grounding": {
                "enabled": True,
                "mode": mode,
                "group": group,
                "max_gap_m": max_gap_m,
                "ray_length_m": ray_length_m,
                "max_vertical_speed_mps": max_vertical_speed_mps,
                "ignore_path_prefixes": ignore_path_prefixes or [],
            },
        }
        result = self.run_scenario(raw_spec)
        if mode == "heuristic_all_meshes":
            result["qa_pass"] = False
            result["calibration_status"] = "HEURISTIC_ONLY"
            result["important"] = (
                "heuristic_all_meshes is discovery-only because it can flag intentional suspended geometry and floors. "
                "Convert expected-grounded objects to the configured group and rerun strict_group for an authoritative PASS/FAIL."
            )
        return result
