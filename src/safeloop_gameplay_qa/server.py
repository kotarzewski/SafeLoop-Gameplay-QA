from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from mcp.server.mcpserver import MCPServer

from . import __version__
from .adapters import GodotQAAdapter
from .config import Settings
from .metrics import evaluate_assertions
from .project import ProjectWorkspace
from .prompts import gameplay_qa_loop_prompt
from .runtime_guard import RuntimeGuard
from .specs import validate_assertions
from .vehicle import build_vehicle_suite


SERVER_INSTRUCTIONS = """SafeLoop Gameplay QA exposes least-privilege runtime measurement and bounded project editing tools.
Use it for behavioral QA: define measurable acceptance criteria -> checkpoint -> run deterministic scenario -> inspect telemetry -> fix -> rerun.
It deliberately exposes no arbitrary shell and no arbitrary network tool.
Do not claim visual QA; use the separate SafeLoop Visual agent for that.
Do not claim realistic vehicle behavior without a calibrated numeric target profile.
Runtime execution is disabled by default and must be opted into by the human outside the project.
"""


def build_server(settings: Settings) -> MCPServer:
    project = ProjectWorkspace(settings)
    godot = GodotQAAdapter(settings, project)
    guard = RuntimeGuard(settings, project)
    mcp = MCPServer(
        "safeloop-gameplay-qa",
        title="SafeLoop Gameplay QA",
        description="Local least-privilege gameplay and physics QA loop for Codex.",
        instructions=SERVER_INSTRUCTIONS,
        version=__version__,
    )

    @mcp.tool()
    def project_info() -> dict:
        """Inspect workspace type, security switches and active QA checkpoint."""
        info = project.info()
        info["agent"] = "SafeLoop Gameplay QA"
        info["state_dir"] = ".safeloop_qa"
        return info

    @mcp.tool()
    def list_project_files(pattern: str = "**/*", limit: int = 250) -> list[str]:
        """List visible project files. Secret/config/agent metadata paths are hidden."""
        return project.list_files(pattern, limit)

    @mcp.tool()
    def read_project_file(path: str, start_line: int = 1, end_line: int = 400) -> str:
        """Read UTF-8 project text within the configured workspace."""
        return project.read_file(path, start_line, end_line)

    @mcp.tool()
    def search_project_text(query: str, pattern: str = "**/*", case_sensitive: bool = False, max_results: int = 50) -> list[dict]:
        """Search text inside visible project source/config files."""
        return project.search_text(query, pattern, case_sensitive, max_results)

    @mcp.tool()
    def create_checkpoint(label: str = "") -> dict:
        """Start a transactional QA checkpoint before behavior-changing edits."""
        return project.journal.create(label)

    @mcp.tool()
    def write_project_file(path: str, content: str, reason: str = "") -> dict:
        """Create or replace a UTF-8 project file subject to workspace policy."""
        return project.write_file(path, content, reason)

    @mcp.tool()
    def replace_project_text(path: str, old: str, new: str, expected_replacements: int = 1, reason: str = "") -> dict:
        """Perform an exact non-ambiguous text replacement in a project file."""
        return project.replace_text(path, old, new, expected_replacements, reason)

    @mcp.tool()
    def delete_project_file(path: str, reason: str = "") -> dict:
        """Delete one project file only when deletion was opted into outside the project."""
        return project.delete_file(path, reason)

    @mcp.tool()
    def checkpoint_diff(checkpoint_id: str = "") -> str:
        """Show a bounded diff of mutations recorded since a checkpoint."""
        cid = checkpoint_id or project.journal.active_id()
        if not cid:
            return "No active checkpoint."
        return project.journal.diff(cid)

    @mcp.tool()
    def restore_checkpoint(checkpoint_id: str) -> dict:
        """Undo SafeLoop Gameplay QA-recorded mutations back to a checkpoint."""
        return project.journal.restore(checkpoint_id)

    @mcp.tool()
    def scan_runtime_risks() -> dict:
        """Statically scan Godot project code/native files before gameplay execution."""
        return guard.decision()

    @mcp.tool()
    def godot_doctor() -> dict:
        """Locate Godot and report its version. Does not run the game."""
        return godot.doctor()

    @mcp.tool()
    def validate_godot_project() -> dict:
        """Run a basic headless Godot editor validation without intentionally starting gameplay."""
        return godot.validate()

    @mcp.tool()
    def godot_input_actions() -> list[str]:
        """Read configured InputMap action names from project.godot without executing the game."""
        return godot.input_actions()

    @mcp.tool()
    def godot_scene_summary(scene: str) -> dict:
        """List node declarations in a text .tscn scene to help identify QA targets."""
        return godot.scene_summary(scene)

    @mcp.tool()
    def evaluate_qa_assertions(metrics: dict, assertions: list[dict]) -> dict:
        """Machine-evaluate numeric metrics against a safe threshold DSL; no arbitrary expressions/eval."""
        return evaluate_assertions(metrics, validate_assertions(assertions))

    @mcp.tool()
    def run_godot_scenario(spec: dict) -> dict:
        """Execute one deterministic Godot gameplay scenario, collect telemetry and machine-evaluate assertions."""
        return godot.run_scenario(spec)

    @mcp.tool()
    def scan_godot_ground_support(
        scene: str = "",
        mode: str = "rigid_and_group",
        group: str = "safeloop_grounded",
        settle_seconds: float = 2.0,
        max_gap_m: float = 0.08,
        ray_length_m: float = 3.0,
        max_vertical_speed_mps: float = 0.15,
        ignore_path_prefixes: list[str] | None = None,
    ) -> dict:
        """Check whether expected-grounded Godot objects have support below them after settling. Heuristic mode never certifies PASS."""
        return godot.scan_ground_support(
            scene, mode, group, settle_seconds, max_gap_m, ray_length_m,
            max_vertical_speed_mps, ignore_path_prefixes,
        )

    @mcp.tool()
    def vehicle_qa_suite_template(
        vehicle_node: str,
        accelerate_action: str,
        brake_action: str,
        steer_left_action: str,
        target_profile: dict | None = None,
        scene: str = "",
    ) -> dict:
        """Build launch/brake/steering scenario specs. Without target_profile this is measurement-only and cannot certify realism."""
        return build_vehicle_suite(vehicle_node, accelerate_action, brake_action, steer_left_action, target_profile, scene)

    @mcp.tool()
    def run_vehicle_qa_suite(
        vehicle_node: str,
        accelerate_action: str,
        brake_action: str,
        steer_left_action: str,
        target_profile: dict | None = None,
        scene: str = "",
    ) -> dict:
        """Run the deterministic vehicle suite. A REALISM PASS is impossible when target_profile has no numeric constraints."""
        suite = build_vehicle_suite(vehicle_node, accelerate_action, brake_action, steer_left_action, target_profile, scene)
        runs = [godot.run_scenario(spec) for spec in suite["scenarios"]]
        calibrated_runs = [r for r in runs if r["calibration_status"] == "CALIBRATED"]
        realism_pass = bool(suite["calibrated"]) and bool(calibrated_runs) and all(r["qa_pass"] for r in calibrated_runs)
        return {
            "calibration_status": "CALIBRATED" if suite["calibrated"] else "UNCALIBRATED",
            "realism_pass": realism_pass,
            "runs": runs,
            "profile": suite["profile"],
            "important": (
                "realism_pass only applies to the supplied numeric target profile. It is not a universal proof of real-world realism. "
                "With no profile, the suite is telemetry-only."
            ),
        }

    @mcp.tool()
    def record_qa_contract(name: str, scope: str, assertions: list[dict], source_notes: str = "", assumptions: list[str] | None = None) -> dict:
        """Persist the acceptance thresholds and their provenance before testing, so thresholds are auditable and not moved after failures."""
        clean = validate_assertions(assertions)
        state = settings.workspace / ".safeloop_qa"
        state.mkdir(parents=True, exist_ok=True)
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "name": str(name)[:120],
            "scope": str(scope)[:500],
            "assertions": clean,
            "source_notes": str(source_notes)[:2000],
            "assumptions": [str(x)[:500] for x in (assumptions or [])[:30]],
        }
        with (state / "qa_contracts.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    @mcp.prompt()
    def gameplay_qa_loop(goal: str, max_iterations: int = 6) -> str:
        """Prompt for a complete measure/fix/retest gameplay QA loop."""
        return gameplay_qa_loop_prompt(goal, max_iterations)

    return mcp


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SafeLoop Gameplay QA MCP server")
    parser.add_argument("--workspace", help="Project workspace. Overrides SAFELOOP_QA_WORKSPACE.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    settings = Settings.from_env(args.workspace)
    build_server(settings).run(transport="stdio")


if __name__ == "__main__":
    main()
