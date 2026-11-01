Step 7 of 11. Build `phoenix/verify.py`: run a step's checks plus the project's fast suite in one throwaway container and decide pass or fail from the report files, never from the exit code alone. Read CLAUDE.md first.

Known facts to design around (measured on 30 Oct):
- Vitest reports `success: true` with 0 tests passed when every test is skipped or todo.
- Playwright exits 0 with skipped tests, and counts a flaky test (failed, then passed on retry) as passed.
So the judge reads counts.

Build:
1. `judge_vitest(path) -> Verdict` and `judge_playwright(path) -> Verdict`. `Verdict` = `passed, failed, skipped, flaky, ok (bool), reason`. `ok` only when `passed >= 1`, `failed == 0`, `skipped == 0`, `flaky == 0`, and every check file in the step folder appears in the report. A missing or unreadable report file = `ok False, reason "no report"`. Write the parsers against the real JSON shapes: generate fixture files by running both tools once in the image on a 2-test sample (one pass, one skip, one fail, one `test.fixme`) and keep those files in `tests/fixtures/`. The Playwright stats field names are not documented; take them from the fixture, not from memory.
2. `verify_step(run, step, sha) -> Verdict`: `fresh_checkout` (Step 5), then one check container (Step 4) running: install (`pnpm install --frozen-lockfile`), the project's fast suite if the plan's `Every step` text names one (default: `pnpm test` when `package.json` has a `test` script), then the step's check command (Step 6). Output to `/runs/<id>/logs/<step>-<try>-verify.txt`, reports to `/runs/<id>/3-product/reports/<step>-<try>/`. Copy Playwright screenshots and traces there too. Fast-suite failure = `ok False, reason "fast suite: <first failing test name>"`. Container timeout `checker_timeout_min`.
3. `feedback(verdict, log_path) -> str`: the reason plus the last 80 lines of output (borrow the tail idea from `hands/loop.py:843-847`), with env values redacted (Step 5's scan list).

Done when:
- pytest: the fixture reports give the right `Verdict` in every case: all pass; one fail; one skip; one todo; flaky; missing file; a report that lists fewer files than the step folder has.
- pytest: `verify_step` with a fake container returning exit 0 but a 0-passed report is `ok False`.
- Manual: run `verify_step` on the tiny repo from Step 6 and show the verdict and the saved report folder.
- `python -m pytest` passes. Commit "Step 7: verify".
