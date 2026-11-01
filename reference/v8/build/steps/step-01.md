Step 1 of 11. Create the Phoenix v8 core repo skeleton. Read CLAUDE.md first; it holds the fixed facts.

Build:
1. `pyproject.toml` (name phoenix, Python 3.12, pytest as the only dev dependency), `phoenix/__init__.py`, `phoenix/__main__.py` with a tiny argparse CLI. Commands for now: `phoenix version`, `phoenix paths` (prints the resolved folders).
2. `phoenix/config.py`: reads `PHOENIX_HOME` (default `./var`) and `phoenix.toml` inside it. Settings with defaults: `max_tries = 3`, `builder_timeout_min = 90`, `checker_timeout_min = 20`, `check_writer_timeout_min = 20`, `no_output_timeout_min = 15`, `usage_probe_min = 30`, `usage_max_wait_h = 12`, `container_memory = "4g"`, `container_cpus = 1.5`, `container_pids = 512`, `image = "phoenix-step:0.6.0"`, `telegram_script = ""`. Missing file = defaults. Unknown keys = error in plain English.
3. `phoenix/state.py`: borrow `atomic_write` and `Lock` from 0.6.0 `hands/state.py:16-19,79-111`. Add `load_json(path, default)` and `save_json(path, data)` built on them.
4. `phoenix/runs.py`: `new_run_id()` = `YYYYMMDD-HHMM-<4 random letters>`; `run_dir(run_id)` creates `/runs/<run-id>/` with sub-folders `1-concept/`, `2-plan/`, `3-product/`, `prompts/`, `logs/` and an empty `run.json`. `run.json` fields: `run_id, repo, plan_path, plan_sha, branch, base_sha, status, current_step, steps, full_suite, cost_usd, sessions, started_at, updated_at`. `status` is one of `queued, running, paused, done, failed`.
5. `phoenix/log.py`: one function `log(run_id, text)` that appends a timestamped line to `/runs/<run-id>/logs/phoenix.log` and to stdout.

Done when:
- `python -m phoenix version` prints a version.
- `PHOENIX_HOME=/tmp/p python -m phoenix paths` prints the five folders and creates them.
- pytest covers: defaults load with no toml; an unknown key gives a readable error; `atomic_write` leaves no partial file; `new_run_id` is unique across 100 calls.
- `python -m pytest` passes. Commit with message "Step 1: skeleton".
