Step 8 of 11. Build `phoenix/loop.py` and `prompts/builder.md`: the loop that takes a run through its steps, with tries, dependents, and resume after a restart. Read CLAUDE.md first.

Build:
1. `prompts/builder.md`: the builder receives: the plan's About and Every-step text; this step's title, description and Done-when bullets; the exact check command (Step 6) and the rule that `tests/phoenix/` is read-only; `git log --oneline base..HEAD` of the run so far; and, on tries 2 and 3, the feedback text from the previous try (Step 7). It is told to run the check command itself before finishing, that its own claims are not the gate, and to end with `STEP DONE` or `STEP BLOCKED: <reason>`. Keep it under 80 lines. Do not replace Claude Code's system prompt; use `--append-system-prompt-file`.
2. `run_step(run, step)`: skip with status `for_you` when `For you: yes`; skip with `blocked` when any step it depends on is not passed. Otherwise: `write_checks` + `lock` + `red_check` (Step 6, once per step, not per try); then up to `max_tries` times: `fresh_workspace`, builder container (`max_turns 200`, `builder_timeout_min`, `no_output_timeout_min`), `snapshot` with lock check and secret scan, `commit_step` as a candidate commit, `verify_step` on that commit. Pass = keep the commit, status `passed`. Fail = `git reset --hard` to the previous head, save feedback, next try. After the last try: status `failed`, reason saved, every dependent marked `blocked`. A `rate_limited` result goes through `wait_for_limit` (Step 3) and repeats the same try. `crashed`, `timed_out` and `no_output` count as a failed try.
3. `run_plan(run)`: steps in order, `run.json` updated after every change (`atomic_write`), `current_step` set before each step starts.
4. Resume: on start, if `run.json` says `running`, rebuild the passed set from git trailers (Step 5 `passed_steps`), treat `current_step` as not started (its candidate commit, if any, is reset), remove leftover workspaces and containers (`cleanup_orphans`), and continue. Git wins over `run.json` when they disagree.
5. CLI: `phoenix run <run-id>` and `phoenix status <run-id>` (one line per step: number, title, status, tries, reason).

Done when:
- pytest with fake container, verify and claude functions: a 3-step plan where step 2 fails 3 times ends with step 1 passed, step 2 failed, step 3 blocked, and 3 builder calls were made for step 2.
- pytest: a `For you` step is skipped and listed; a `rate_limited` result waits (fake clock) and does not use a try.
- pytest: kill the loop after step 1 passes (raise in the fake), start again, and step 2 begins with the passed set read from git.
- `python -m pytest` passes. Commit "Step 8: loop".
