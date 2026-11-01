Step 9 of 11. Build `phoenix/run.py` and `phoenix/watch.py`: pick up plans, start a run, finish it with the full suite, the PR, the run record and a notification. Read CLAUDE.md first.

Build:
1. `watch.py`: `phoenix watch` loops forever. Every 30 seconds it lists `/plans/*.md`. For each file: move it to `/runs/<new-run-id>/1-concept/plan.md` (rename, so it is picked up once), parse and check it (Step 2). Errors: write `/runs/<id>/ERROR.txt` in plain English, set status `failed`, notify, continue. Valid: status `queued`. One run at a time: start the oldest queued run only when no run is `running`. Resume a `running` run first (Step 8).
2. `start_run(run)`: `ensure_clone`, `start_branch`, `commit_plan` (Step 5); write the domains file (Step 4); copy the parsed plan as `2-plan/plan.json`; run the full suite once on the base in a check container: for `Type: change`, `pnpm run test:all` if that script exists, else `pnpm test`; a red base = status `failed`, reason "main is already red: <test name>". For `Type: new` skip this (empty repo).
3. `finish_run(run)`: full suite on the head (same command), one automatic re-run if red; if still red, status `done` with `full_suite.end = red` and the failing test named (no fix loop in core). Push the branch (Step 5). Open the PR with `gh pr create` using `GH_TOKEN`, title `Phoenix run <id>: <plan name>`, body = the summary below. Save the PR URL in `run.json`.
4. Run record: `3-product/` gets `final-commit.txt`, every report folder from Step 7, and screenshots. `summary.md` in the run folder: plan name, repo, branch, PR link, full-suite results at start and end, one line per step (status, tries, reason), cost and session count, `For you` items listed under "Things only you can do". Also write `summary.html` with the same content, built from a 100-line template, plain HTML, no JavaScript.
5. `notify(text)`: if `telegram_script` is set in config, run it with the text as the argument (the existing `ph-notify` script); else print. Send on: plan rejected, run done, run failed, limit wait longer than 1 hour.
6. Merge detection: on each `watch` loop, for runs with status `done` and a PR: `git fetch` and `git merge-base --is-ancestor <head> origin/main`, or the PR state via `gh pr view --json state`. Merged = status `merged`; closed unmerged = `abandoned`. Nothing else changes.

Done when:
- pytest with fakes: a plan dropped in `/plans/` becomes a queued run with the file moved; a bad plan produces `ERROR.txt` and a notify call; two queued runs start one at a time.
- pytest: `finish_run` with a fake red suite re-runs once, then records `red` and still opens the PR.
- pytest: `summary.md` lists a `For you` step under "Things only you can do".
- `python -m pytest` passes. Commit "Step 9: run start and end".
