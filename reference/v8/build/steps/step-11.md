Step 11 of 11. Prove the core builds a real plan end to end. This is the Phase 1 gate. Read CLAUDE.md first.

Build:
1. Create an empty private repo `rebirth-wd/v8-smoke` (the owner creates it; stop and ask for the name if it is not there). Write `plans/smoke.md`: `Type: new`, 3 steps: (1) set up a Next.js project with Vitest and Playwright and a home page that shows the text "Hello from Phoenix"; (2) add an `/about` page with a heading and a link back home; (3) `For you: yes`, point a domain at the deploy. Each Done-when bullet must be checkable by a browser or unit test.
2. Drop the plan into the plans volume and watch the run with `phoenix status` until it is `done`.
3. Inspect: the PR exists on GitHub with 2 passed steps and the `For you` item listed; `3-product/reports/` holds Vitest and Playwright JSON for each try; `prompts/` holds a transcript per session; `usage.jsonl` shows cost; the full suite at the end is green.
4. Record in `deploy/README.md` under "First run": wall time, number of sessions, cost, and anything that needed a manual fix. Any manual fix becomes a bug to fix in the right step before the gate is called passed.

Done when:
- Status `done`, PR open, both code steps `passed` with no manual intervention after the plan was dropped in.
- The owner merges the PR on GitHub and within 2 minutes `phoenix status` shows `merged`.
- A second drop of the same plan into a `Type: change` plan that adds a step 4 (contact page) runs on a new branch from the merged main, base suite green, and ends `done`.
