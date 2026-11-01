Step 3 of 11. Build `phoenix/claude.py`: the one place that runs a Claude Code session and reads its result. All AI calls go through this file so the auth method can change later in one place. Read CLAUDE.md first. This step does not touch Docker; it produces the command line and parses output. Step 4 runs it in a container.

Build:
1. `build_command(prompt_file, cwd, max_turns, allowed_tools, disallowed_tools, append_system_prompt_file=None) -> list[str]`: `claude -p --output-format stream-json --verbose --permission-mode bypassPermissions --max-turns N --disallowedTools ...`, prompt read from the file. Never `--bare`.
2. `Result` dataclass: `kind` (ok, error, rate_limited, crashed, timed_out, no_output), `text` (the final result text), `session_id`, `cost_usd`, `turns`, `resets_at` (datetime or None), `raw_path`. Borrow `parse`, `_read_result` and `Result.kind` logic from 0.6.0 `hands/claude.py:27-138`: the result is only the single final `type: result` line; anything else is `crashed`. Borrow rate-limit detection and `parse_resets_at` from `hands/claude.py:12-57`. Also treat a result text matching `hit your .* limit` with `resets` as `rate_limited`.
3. `run(cmd, cwd, env_files, log_path, timeout_min, no_output_timeout_min) -> Result`: starts the process, streams every stdout line to `log_path`, kills the process if no line arrives for `no_output_timeout_min` (kind `no_output`) or the total time passes `timeout_min` (kind `timed_out`). Kill = SIGINT, wait 30 s, then SIGKILL. This function takes a callable that starts the process, so Step 4 can plug in `docker run`.
4. `wait_for_limit(result, probe, now)`: when `kind == rate_limited`, sleep until `resets_at` plus 2 minutes; if `resets_at` is unknown, call `probe()` every `usage_probe_min` minutes; give up after `usage_max_wait_h` hours and return False. Borrow the shape from 0.6.0 `hands/loop.py:973-997`. A wait is never counted as a try.
5. `record_usage(run_id, result)`: appends `{at, session_id, kind, cost_usd, turns}` to `/runs/<id>/usage.jsonl` and adds cost to `run.json`.

Done when:
- pytest feeds canned stream-json files (write them as fixtures: a normal result, a rate-limit result with `resets 3:45pm`, a forged extra result line, output that stops mid-way) and `parse` returns the right `kind` each time.
- A test with a fake process that prints one line then hangs ends with `no_output` within 2 seconds (use a 1-second timeout in the test).
- `wait_for_limit` with a fake clock returns True at the reset time and False after the max wait.
- `python -m pytest` passes. Commit "Step 3: claude wrapper".
