# Security model

## Trust boundary

The model is treated as an untrusted planner. It does not receive a generic process launcher or arbitrary network client from SafeLoop Gameplay QA.

The MCP server accepts bounded structured operations and enforces policy in Python before touching the project or launching the engine.

## Workspace containment

All model-visible file operations are constrained to one configured workspace. Absolute paths, `..` escapes and symlink traversal are rejected. Secret-like filenames, agent instructions, Git metadata and SafeLoop internal state are hidden.

## Runtime containment

The QA runner is bundled with this package and copied into `.safeloop_qa/runtime` by the server. The model supplies JSON scenario data; it does not supply arbitrary GDScript for the runner.

Godot is launched through `subprocess.run(..., shell=False)` with a fixed argument structure. SafeLoop does not expose that subprocess function as a generic MCP tool.

The child environment is allowlisted so API keys and arbitrary host environment variables are not intentionally inherited.

## Static runtime guard

Before gameplay execution, visible Godot/C# source is scanned for common dangerous capabilities including process spawning, shell opening, native extensions and network APIs.

Critical or network findings block execution unless the user explicitly opts in through host-side environment variables. Project files cannot grant themselves those permissions.

This scan is intentionally conservative and incomplete. Reflection, custom native code or unusual APIs can evade static pattern matching. It is not a formal security proof or OS sandbox.

## Machine verdicts

LLM prose does not decide PASS. The assertion evaluator supports a small numeric DSL only:

- `<=`
- `>=`
- `<`
- `>`
- `==`
- `between`
- `approx`

No `eval`, Python expressions or GDScript expressions are accepted.

A runtime scenario without assertions is `UNCALIBRATED` and cannot return `qa_pass=true`.

## Vehicle realism

The system distinguishes measurement from calibration. Telemetry can always be recorded, but a realism-oriented PASS requires explicit numeric target constraints whose provenance should be recorded with `record_qa_contract`.

A PASS certifies only the tested metrics and scenario. It does not prove all real-world dynamics.

## Ground-support limitations

Geometry-only scans are heuristic because some meshes are intentionally unsupported, collision geometry can differ from render geometry and floors themselves may have no lower support.

`heuristic_all_meshes` is therefore discovery-only. `strict_group` should be used for authoritative checks on nodes deliberately marked as expected-grounded.

## Host capabilities

SafeLoop controls only its own MCP tools. If Codex separately has unrestricted shell, filesystem or network access, those capabilities remain available to Codex. Use an appropriate Codex sandbox/approval profile.
