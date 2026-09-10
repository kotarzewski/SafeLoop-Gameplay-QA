from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adapters import GodotQAAdapter
from .config import Settings
from .project import ProjectWorkspace
from .runtime_guard import RuntimeGuard
from .server import build_server
from .selftest import run_godot_smoke_test


def main() -> None:
    parser = argparse.ArgumentParser(prog="safeloop-gameplay-qa")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Run stdio MCP server")
    serve.add_argument("--workspace", required=True)

    doctor = sub.add_parser("doctor", help="Inspect project and Godot availability")
    doctor.add_argument("--workspace", required=True)

    scan = sub.add_parser("scan", help="Run defensive runtime risk scan")
    scan.add_argument("--workspace", required=True)

    scenario = sub.add_parser("scenario", help="Run one scenario JSON file")
    scenario.add_argument("--workspace", required=True)
    scenario.add_argument("--spec", required=True)

    smoke = sub.add_parser("selftest-godot", help="Run a temporary end-to-end Godot harness smoke test")
    smoke.add_argument("--godot-bin", default=None)

    args = parser.parse_args()
    if args.command == "selftest-godot":
        print(json.dumps(run_godot_smoke_test(args.godot_bin), indent=2, ensure_ascii=False))
        return

    settings = Settings.from_env(args.workspace)
    project = ProjectWorkspace(settings)

    if args.command == "serve":
        build_server(settings).run(transport="stdio")
        return
    if args.command == "doctor":
        output = {"project": project.info()}
        if project.detect_engine() == "godot":
            try:
                output["godot"] = GodotQAAdapter(settings, project).doctor()
            except Exception as exc:
                output["godot"] = {"found": False, "error": str(exc)}
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return
    if args.command == "scan":
        print(json.dumps(RuntimeGuard(settings, project).decision(), indent=2, ensure_ascii=False))
        return
    if args.command == "scenario":
        raw = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        print(json.dumps(GodotQAAdapter(settings, project).run_scenario(raw), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
