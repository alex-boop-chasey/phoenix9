Step 12. Add an MCP server so a Claude Code session can drive Phoenix: check and submit plans, list runs, read a run's status and report. Build it so later features add tools without touching the server core. Read CLAUDE.md first.

Design rules:
- Standard library only (CLAUDE.md). Write the MCP stdio transport yourself: JSON-RPC 2.0, one JSON message per line on stdin/stdout. stdout carries only protocol messages; anything else (logs, warnings) goes to stderr.
- Command: `python -m phoenix mcp`. Claude Code starts it with `docker exec -i phoenix python -m phoenix mcp`, so it runs inside the existing Phoenix container with the same code, folders and settings. No network port, no new service.
- Reuse existing code (plan.parse/check, runs.load_run, watch.all_runs, the status output) rather than re-implementing it. Do not change existing CLI behaviour.

Layout (the extension point):
1. `phoenix/mcp/server.py`: the protocol core only. Handles `initialize` (protocol version: answer the client's version if it is in a `SUPPORTED_VERSIONS` tuple kept in one place, else the newest supported), `notifications/initialized`, `ping`, `tools/list`, `tools/call`. Unknown methods get JSON-RPC error -32601; bad JSON -32700; bad params -32602. Declare only the capabilities that have something registered, so resources and prompts can be added later through the same registry without changing the core.
2. `phoenix/mcp/registry.py`: a `Tool` dataclass (`name`, `group`, `title`, `description`, `input_schema`, `handler`, `read_only: bool`) and a registry that imports every module in `phoenix/mcp/tools/` and collects each module's `TOOLS` list. Adding a feature's tools = adding one module there; the server core never changes. Duplicate names fail loudly at start.
3. Tool names are `<group>_<verb>`. Groups in this step: `plans`, `runs`, `system`. Reserve (do not build) these for later features and list them in the docs: `control` (stop/resume/retry a run), `merge` (auto-merge, merge a PR), `deploy` (hosting), `projects` (repos, env and domain files), `update` (Phoenix updating itself).
4. `phoenix.toml` gets an `[mcp]` table: `groups` (which groups are switched on; default all built groups) and `allowed_owners` (default `["rebirth-wd"]`). A switched-off group's tools do not appear in `tools/list` and a call to them returns an error saying the group is off.
5. Every tool returns a short plain-English `text` content block plus `structuredContent` (JSON) so a model and a program can both use it. A tool that fails returns `isError: true` with a plain-English reason, never a stack trace.

Tools to build:
- `plans_check(text)`: run the plan checker on plan text; return OK or the problem list. Read only.
- `plans_submit(text, filename?)`: check the plan first and refuse it (with the problems) if it fails; refuse a `Repo:` whose owner is not in `allowed_owners`. Otherwise write it into the plans folder atomically (temp file + rename, safe file name, never overwrite) and say the watcher picks it up within about 30 seconds.
- `runs_list(limit=10, status?)`: newest first: run id, plan title, repo, status, current step, started, PR link.
- `runs_status(run_id)`: the same facts as `python -m phoenix status`, per step (title, status, tries) plus PR link.
- `runs_report(run_id)`: the run's `summary.md` or `ERROR.txt`, capped at about 20 000 characters with a note when cut.
- `system_info()`: Phoenix version, which groups and tools are on, the reserved groups, and the plans/runs folder paths.

Docs:
- `docs/mcp.md`: what each tool does, the `.mcp.json` snippet below, and "How to add a tool for a new feature" (one module in `phoenix/mcp/tools/`, a group name, tests, nothing else).
- `deploy/README.md`: a short "Use Phoenix from Claude Code" section with the snippet:
  `{"mcpServers": {"phoenix": {"command": "docker", "args": ["exec", "-i", "phoenix", "python", "-m", "phoenix", "mcp"]}}}`

Done when:
- `tests/test_mcp.py` drives the server through in-memory streams: initialize, tools/list, every tool (good and bad input), unknown method, bad JSON, a switched-off group, a refused owner, and the registry picking up a throwaway tool module from a temp package.
- Manual: rebuild and restart with `bash deploy/install.sh` (press Enter at both token prompts to keep the saved tokens), then pipe `initialize` + `tools/list` + `runs_list` into `docker exec -i phoenix python -m phoenix mcp` and paste the output in BUILD-NOTES.md. `docker exec phoenix python -m phoenix doctor` still prints OK.
- Manual: one `claude -p` call with `--mcp-config` pointing at the snippet asks for the last two runs and gets them through `runs_list`. Paste the answer.
- Whole pytest suite green. Commit "Step 12: MCP server".
