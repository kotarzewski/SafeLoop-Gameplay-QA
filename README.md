# SafeLoop Gameplay QA

**SafeLoop Gameplay QA** is a local, least-privilege MCP agent/gateway for behavioral, gameplay and physics verification with Codex.

It is intentionally separate from **SafeLoop Visual**. Visual quality and gameplay correctness are different problems and should not share a PASS criterion.

SafeLoop Gameplay QA establishes this loop:

`inspect -> define measurable contract -> checkpoint -> run deterministic scenario -> collect telemetry -> machine-evaluate -> fix -> rerun`

Godot is the first runtime adapter. The core filesystem, checkpoint, threshold evaluation and safety model are engine-agnostic so adapters for Roblox, Unity, Unreal or web games can be added later.

## What it can verify

Examples:

- player movement behavior;
- vehicle acceleration, braking and steering response;
- speed, displacement and drift;
- body roll, yaw rate and vertical instability;
- custom numeric node properties;
- expected-grounded objects and dynamic rigid bodies after a settling period;
- deterministic regression scenarios with numeric PASS/FAIL thresholds.

## What it refuses to fake

A coding model saying "the car feels realistic" is not QA.

SafeLoop only returns a calibrated gameplay PASS when explicit numeric assertions exist and the runtime telemetry satisfies them. If a vehicle target profile is absent, the result is **UNCALIBRATED**: measurements are useful, but they do not prove realism.

Likewise, `heuristic_all_meshes` grounding scans are discovery-only. For an authoritative grounding check, deliberately mark objects expected to rest on support with the `safeloop_grounded` group (or another chosen group) and run `strict_group`.

## Security model

SafeLoop Gameplay QA deliberately does **not** expose:

- arbitrary shell execution;
- arbitrary URL/network fetching;
- package installation;
- access outside one configured workspace;
- `.env`, credentials, `.git`, `.codex`, `.agents`, `AGENTS.md`, `SKILL.md`, `.safeloop` or `.safeloop_qa` internals;
- native executable/binary writes;
- deletion unless explicitly opted into outside the project;
- game runtime unless explicitly opted into outside the project.

Runtime is launched only as a fixed Godot command with a bundled QA runner. The model supplies structured scenario data, not shell text and not arbitrary QA scripts.

Running a game still executes that game's own code. A defensive static scan blocks common process-spawning and network-capable code unless the human explicitly overrides it outside the project. This is defense in depth, not a perfect OS sandbox.

See [`docs/SECURITY_MODEL.md`](docs/SECURITY_MODEL.md).

## Requirements

- Python 3.10+
- Codex or another MCP-capable host
- Godot 4.x for the current automatic adapter

The MCP Python SDK 2.x is used.

## Install

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -e .
```

macOS/Linux:

```bash
source .venv/bin/activate
pip install -e .
```

Diagnostic:

```bash
safeloop-gameplay-qa doctor --workspace "C:\\Projects\\MyGodotGame"
safeloop-gameplay-qa scan --workspace "C:\\Projects\\MyGodotGame"
```

Optional end-to-end harness smoke test on a machine with Godot installed:

```bash
safeloop-gameplay-qa selftest-godot
```

## Connect to Codex

Example Windows config:

```toml
[mcp_servers.safeloop_gameplay_qa]
command = "C:\\Tools\\safeloop-gameplay-qa\\.venv\\Scripts\\python.exe"
args = ["-m", "safeloop_gameplay_qa.server", "--workspace", "C:\\Projects\\MyGodotGame"]
env = {
  SAFELOOP_QA_ALLOW_RUNTIME = "0",
  SAFELOOP_QA_ALLOW_DELETE = "0"
}
```

On the first connection keep runtime off, then ask Codex to call:

1. `project_info`
2. `scan_runtime_risks`
3. `godot_doctor`
4. `validate_godot_project`

After reviewing a trusted project, set:

```toml
SAFELOOP_QA_ALLOW_RUNTIME = "1"
```

and restart the MCP server/Codex session so startup settings reload.

If Godot is not on PATH, set `SAFELOOP_QA_GODOT_BIN` to its executable.

## MCP tools

The server exposes, among others:

- `project_info`
- `list_project_files`
- `read_project_file`
- `search_project_text`
- `create_checkpoint`
- `write_project_file`
- `replace_project_text`
- `checkpoint_diff`
- `restore_checkpoint`
- `scan_runtime_risks`
- `godot_doctor`
- `validate_godot_project`
- `godot_input_actions`
- `godot_scene_summary`
- `evaluate_qa_assertions`
- `run_godot_scenario`
- `scan_godot_ground_support`
- `vehicle_qa_suite_template`
- `run_vehicle_qa_suite`
- `record_qa_contract`
- MCP prompt: `gameplay_qa_loop`

## Scenario example

```json
{
  "name": "vehicle-braking",
  "scene": "world.tscn",
  "duration_s": 14,
  "physics_fps": 60,
  "sample_hz": 60,
  "watch": [
    {"id": "vehicle", "node_path": "World/PlayerCar"}
  ],
  "primary_watch_id": "vehicle",
  "inputs": [
    {"action": "accelerate", "start_s": 0.25, "end_s": 8.0, "strength": 1.0},
    {"action": "brake", "start_s": 8.0, "end_s": 13.5, "strength": 1.0}
  ],
  "markers": [
    {"name": "brake_start", "time_s": 8.0}
  ],
  "assertions": [
    {"metric": "speed_at_brake_start_kph", "op": "between", "min": 95, "max": 105},
    {"metric": "brake_distance_m", "op": "between", "min": 34, "max": 40}
  ]
}
```

Those numbers are only an example of the assertion format. Use targets appropriate to the specific game/vehicle specification; do not copy them blindly.

Supported assertion operators are `<=`, `>=`, `<`, `>`, `==`, `between` and `approx`. No Python/GDScript `eval` is used.

## Vehicle QA

`run_vehicle_qa_suite` runs deterministic launch, braking and steering-step scenarios. A profile can constrain metrics such as:

- `zero_to_100_s`
- `max_speed_kph`
- `speed_at_brake_start_kph`
- `brake_distance_m`
- `brake_time_s`
- `steering_response_s`
- `max_abs_roll_deg`
- `straight_lateral_drift_m`
- `max_abs_vertical_speed_mps`

Example profile syntax:

```json
{
  "zero_to_100_s": {"min": 5.5, "max": 6.5},
  "brake_distance_m": {"min": 34, "max": 40},
  "max_abs_roll_deg": {"max": 7},
  "steering_response_s": {"max": 0.25}
}
```

A PASS means "matches this supplied profile", not "scientifically proven to match every aspect of the real vehicle".

## Ground-support QA

Recommended workflow:

1. Run `heuristic_all_meshes` to discover suspicious gaps.
2. Review false positives such as floors, bridges, lamps and intentionally suspended geometry.
3. Mark objects that really must be supported using group `safeloop_grounded`.
4. Run `strict_group` with the required maximum gap.
5. Treat only the targeted strict result as authoritative PASS/FAIL.

Dynamic `RigidBody3D` objects are included by `rigid_and_group` and can be checked after settling.

## Cost

SafeLoop Gameplay QA itself calls no paid model API and no third-party generation service. When used as a local MCP server inside Codex, the model reasoning consumes the normal Codex usage available to the user's plan. There is no separate SafeLoop API bill.

## Project status

`0.1.0` is alpha. Runtime scenario execution currently targets Godot 4.x. Real projects can have custom input systems or physics architectures that require additional adapter support; the agent must report unsupported cases rather than pretend they were tested.

## License

MIT
