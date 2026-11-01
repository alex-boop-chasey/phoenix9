Step 2 of 11. Build `phoenix/plan.py`: parse a `plan.md` into steps and check it against the plan rules. Read CLAUDE.md first.

Plan format (exact):
- Line 1: `# Plan: <name>`.
- Header lines, one per line, before the first `##`: `Type: new|change` (required), `Repo: <owner>/<name>` (required), `Stack:`, `Style:`, `Sites the app may contact: host, host` (all optional). Any other `Word:` line before the first `##` is an error.
- `## About` : free text. `## Every step` : optional free text given to every builder.
- `## Step <n>: <title>` sections. Inside: optional lines `Depends on: 1, 3`, `For you: yes`, `Changes existing behaviour: yes`; free description text; then `Done when:` followed by `- ` bullets to the end of the section.

Rules (errors must read like a note to a person, with the step number and the line number):
1. Steps numbered 1..n with no gaps, at most 60.
2. Every step has a title, a description and at least one Done-when bullet. `For you: yes` steps need no Done-when.
3. `Depends on` names only earlier steps. A step with no `Depends on` depends on the previous step (step 1 on nothing).
4. `Type: new` requires that step 1's title or description mentions setting up the project (contains "set up", "setup", "scaffold" or "create the project"). `Type: change` has no such rule.
5. Every Done-when bullet is at least 15 characters and does not end with vague words from a short list: `professional`, `nice`, `good`, `clean`, `modern`, `works well`. This is a cheap guard, not a judge.
Also: hostnames in `Sites the app may contact` must match 0.6.0's HOST regex (borrow from `hands/planner.py:46`). Fail closed on anything unknown.

Build:
1. Dataclasses `Plan` (name, type, repo, stack, style, sites, about, every_step, steps) and `Step` (number, title, description, done_when, depends_on, for_you, changes_behaviour, text_hash). `text_hash` = sha256 of the step's raw text.
2. `parse(text) -> Plan` and `check(plan) -> list[str]` (empty list = valid).
3. `plan_order(plan)` returns steps in number order; `dependents_of(plan, n)` returns every step that depends on n directly or indirectly.
4. CLI: `phoenix plan check <file>`: prints "Plan OK: <n> steps" or the error list, exit 1 on errors.

Done when:
- A sample plan from the template in the design doc (3 steps, one `For you`) parses and passes.
- pytest covers each of the 5 rules failing with a message that names the step, plus: duplicate step numbers, `Depends on` a later step, unknown header line, bad hostname.
- `python -m pytest` passes. Commit "Step 2: plan parser".
