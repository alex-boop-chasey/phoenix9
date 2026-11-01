"""Generate real Vitest and Playwright JSON reports for the Step 7 fixtures."""
from pathlib import Path
from phoenix import checks, docker, config, git as pgit
repo = "alex-boop-chasey/tiny-site"
co = pgit.fresh_checkout(repo, pgit.head(pgit.clone_dir(repo)))
V = "import { test, expect } from 'vitest'\n\n"
P = "import { test, expect } from '@playwright/test'\n\n"
files = {
  # all pass
  "step-01/1-adds.test.ts": V + "test('adds numbers', () => { expect(1 + 1).toBe(2) })\n",
  "step-01/2-title.spec.ts": P + "test('the truth holds', async () => { expect(true).toBe(true) })\n",
  # one pass, one skip, one fail, one todo/fixme (the sample the step text asks for)
  "step-02/1-mixed.test.ts": V + "test('passes', () => { expect(1).toBe(1) })\n"
     "test.skip('is skipped', () => { expect(1).toBe(1) })\n"
     "test('fails', () => { expect(1).toBe(2) })\n"
     "test.todo('is todo')\n",
  "step-02/2-mixed.spec.ts": P + "test('passes', async () => { expect(1).toBe(1) })\n"
     "test.skip('is skipped', async () => { expect(1).toBe(1) })\n"
     "test('fails', async () => { expect(1).toBe(2) })\n"
     "test.fixme('is fixme', async () => { expect(1).toBe(1) })\n",
  # one fail
  "step-03/1-fail.test.ts": V + "test('passes', () => { expect(1).toBe(1) })\n"
     "test('the sum is right', () => { expect(1 + 1).toBe(3) })\n",
  "step-03/2-fail.spec.ts": P + "test('passes', async () => { expect(1).toBe(1) })\n"
     "test('the heading is right', async () => { expect('a').toBe('b') })\n",
  # one skip
  "step-04/1-skip.test.ts": V + "test('passes', () => { expect(1).toBe(1) })\n"
     "test.skip('is skipped', () => { expect(1).toBe(1) })\n",
  "step-04/2-skip.spec.ts": P + "test('passes', async () => { expect(1).toBe(1) })\n"
     "test.skip('is skipped', async () => { expect(1).toBe(1) })\n",
  # one todo (vitest) / fixme (playwright)
  "step-05/1-todo.test.ts": V + "test('passes', () => { expect(1).toBe(1) })\ntest.todo('is todo')\n",
  "step-05/2-fixme.spec.ts": P + "test('passes', async () => { expect(1).toBe(1) })\n"
     "test.fixme('is fixme', async () => { expect(1).toBe(1) })\n",
  # flaky (playwright, run with --retries=1): fails on the first try, passes on the retry
  "step-06/1-flaky.spec.ts": P + "test('passes', async () => { expect(1).toBe(1) })\n"
     "test('is flaky', async ({}, info) => { expect(info.retry).toBe(1) })\n",
  # vitest: only skipped tests (success true, 0 passed); a file that does not load
  "step-07/1-allskip.test.ts": V + "test.skip('is skipped', () => {})\ntest.todo('is todo')\n",
  "step-08/1-ok.test.ts": V + "test('passes', () => { expect(1).toBe(1) })\n",
  "step-08/2-broken.test.ts": V + "throw new Error('cannot load this file')\n",
}
for rel, text in files.items():
    p = co / "tests/phoenix" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
out = Path("/tmp/s7/out"); out.mkdir(parents=True, exist_ok=True); docker.hand_to_agent(out)
cfg = "/phoenix/testconfig"
parts = ["pnpm install --frozen-lockfile >/dev/null 2>&1", "vc=$(mktemp -d) && cp %s/vitest.config.mjs \"$vc/\"" % cfg]
for name, step in [("pass", 1), ("mixed", 2), ("fail", 3), ("skip", 4), ("todo", 5), ("allskip", 7), ("loaderror", 8)]:
    parts.append(f"npx vitest run tests/phoenix/step-0{step} --config \"$vc/vitest.config.mjs\" --reporter=json --outputFile=/out/vitest-{name}.json; echo vitest-{name} exit $?")
for name, step, extra in [("pass", 1, ""), ("mixed", 2, ""), ("fail", 3, ""), ("skip", 4, ""), ("fixme", 5, ""), ("flaky", 6, " --retries=1")]:
    parts.append(f"npx playwright test tests/phoenix/step-0{step} --config {cfg}/playwright.config.mjs{extra} --reporter=json > /out/playwright-{name}.json; echo playwright-{name} exit $?")
# the default (human) Vitest output of a failing run, for the fast-suite failing-test-name reader
parts.append(f"npx vitest run tests/phoenix/step-03 --config \"$vc/vitest.config.mjs\" > /out/vitest-fail-output.txt 2>&1; echo vitest-text exit $?")
parts.append(f"npx playwright test tests/phoenix/step-03 --config {cfg}/playwright.config.mjs --reporter=list > /out/playwright-fail-output.txt 2>&1; echo playwright-text exit $?")
cmd = "; ".join(parts)
rc, log = docker.run_check_container("s7gen", 1, 1, co, cmd, None, docker.domains_file_path(repo), 20,
                                     role="gen", mounts=checks.check_mounts(out))
print("exit", rc, log)
print(log.read_text()[-3000:])
pgit.remove_workspace(co)
