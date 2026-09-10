# Codex setup

SafeLoop Gameplay QA runs as a local stdio MCP server.

## Install

Clone the repo, create a virtual environment and run `pip install -e .`.

## Configure

```toml
[mcp_servers.safeloop_gameplay_qa]
command = "C:\\Tools\\safeloop-gameplay-qa\\.venv\\Scripts\\python.exe"
args = ["-m", "safeloop_gameplay_qa.server", "--workspace", "C:\\Projects\\MyGodotGame"]
env = {
  SAFELOOP_QA_ALLOW_RUNTIME = "0",
  SAFELOOP_QA_ALLOW_DELETE = "0"
}
```

Use absolute paths. Do not provide API keys.

First run: `project_info`, `scan_runtime_risks`, `godot_doctor`, `validate_godot_project`.

For a trusted project, set `SAFELOOP_QA_ALLOW_RUNTIME="1"` and restart Codex/MCP. Network-capable or critical-risk projects remain blocked unless separately and deliberately opted into outside the project.

Use the MCP prompt `gameplay_qa_loop` for iterative measure/fix/retest work.
