Step 6 of 11. Build `phoenix/checks.py` and `prompts/check-writer.md`: turn a step's Done-when list into locked automatic checks that must fail before the builder starts. Read CLAUDE.md first.

Where checks live: `tests/phoenix/step-<nn>/` in the project repo (unit checks `*.test.ts` run by Vitest, browser checks `*.spec.ts` run by Playwright). A `tests/phoenix/manifest.json` lists every locked file with its sha256. Phoenix owns both.

Build:
1. `prompts/check-writer.md`: a prompt that receives the plan's About and Every-step text, this step's title, description and Done-when bullets, the repo tree (`git ls-files`, capped at 400 lines), and the existing checks of passed steps. It must write one check per Done-when bullet into `tests/phoenix/step-<nn>/`, name each check after its bullet, use `@axe-core/playwright` when a bullet mentions accessibility, use Mailpit's API when a bullet mentions email, and must not touch any other file. It must end its final message with `CHECKS WRITTEN: <n>` or `CANNOT CHECK: <bullet>` with a reason. Borrow the "Finish" line contract idea from 0.6.0 `prompts/planner.md`.
2. `write_checks(run, step) -> list[path]`: fresh workspace (Step 5), run the check-writer container (Step 4, role `checker`, `max_turns 60`, `check_writer_timeout_min`), snapshot (Step 5) but accept only files under `tests/phoenix/step-<nn>/`; anything else = reject and retry once; then commit "Step <n>: checks".
3. `lock(repo, step, paths)`: add each file's sha256 to `manifest.json`, commit. `verify_lock(checkout)`: recompute every hash in the manifest; any mismatch or missing file = `LockBroken` with the file name. Step 5's `snapshot` must call this and reject the builder's whole snapshot when it fails.
4. `red_check(run, step) -> bool`: run the step's checks on the current branch head in a check container (Step 4) before any builder starts. Expected result: at least one failure. If every check passes, log the step as `vacuous checks` in `run.json` and carry on; do not block (the builder may already have done the work in an earlier step).
5. The check command for a step (also used by Step 7): `npx vitest run tests/phoenix/step-<nn> --reporter=json --outputFile=/out/vitest.json; npx playwright test tests/phoenix/step-<nn> --reporter=json > /out/playwright.json`, with configs supplied by Phoenix from `image/testconfig/` (mounted read-only), never from the repo. Skip the Playwright half when the folder has no `*.spec.ts`.

Done when:
- pytest: `lock` then a changed file makes `verify_lock` raise with that file's name; an untouched set passes.
- pytest: `write_checks` with a fake container function that drops a file outside `tests/phoenix/` is rejected.
- pytest: `red_check` with a fake report of all-pass logs `vacuous checks` and returns True.
- Manual: run the check-writer once against a tiny Next.js repo with one Done-when bullet and show the generated file.
- `python -m pytest` passes. Commit "Step 6: checks".
