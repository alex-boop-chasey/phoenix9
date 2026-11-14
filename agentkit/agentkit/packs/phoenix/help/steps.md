# Build steps

A build runs these steps in order. The first group runs once at the start, the task group runs for every task of
the spec, and the last group runs once at the end. Script steps are plain programs; AI steps are one fresh Claude
session each, inside a sealed container. Safety steps protect the project and are Alex's alone to turn off.
"Default" says whether a step is on unless turned off ("always" means it cannot be turned off).

`build-plan` shows the exact step plan for a project's settings; `settings-explain` says it in plain English.

## At the start

| Step | What it does | Kind | Default |
| --- | --- | --- | --- |
| Pick up (pick-up) | Reads the spec file the build was started from. | script | always |
| Spec check (spec-check) | Checks the spec is complete and makes sense before any work starts. | script | always |
| Branch (branch) | Makes the build's branch and work folder and records main's test result. | script | always |
| Planner (planner) | Writes a short plan for the whole spec before building. | AI | off |
| Service setup (service-setup) | Wires the project's chosen services in once: keys present, sites allowed, install notes for the builder. | script | on |

## For each task

| Step | What it does | Kind | Default |
| --- | --- | --- | --- |
| Check writer (check-writer) | Writes the task's checks before any code exists. | AI | off |
| Red check (red-check) | Proves the new checks fail before the code is written (only with the check writer). Safety step. | script | on |
| Builder (builder) | Writes the code for one task. | AI | always |
| Diff rules (diff-rules) | Refuses changes to files the builder may not touch. Safety step. | script | on |
| Secret scan (secret-scan) | Looks for keys and passwords in the change. Safety step. | script | on |
| Acceptance (acceptance) | Runs the task's checks and records the results. | script | always |
| Verify (verify) | Runs the project's tests and builds the test report. Safety step. | script | on |
| Reviewer (reviewer) | A fresh reader checks the change and gives a verdict. | AI | off |
| Commit (commit) | Commits the task's change if everything passed. | script | always |

## At the end

| Step | What it does | Kind | Default |
| --- | --- | --- | --- |
| Lockfile check (lockfile) | Checks that exact package versions are saved in a committed lockfile. Safety step. | script | on |
| Full suite (full-suite) | Runs the whole test suite once all tasks are done. Safety step. | script | on |
| Summary (summary) | Writes the plain-English summary of the build. | script | on |
| Preview (preview) | Puts the build's branch on a temporary address before the merge (only when the deploy preview setting is on). | script | on |
| Merge (merge) | Merges the build's branch into main, or asks Alex first. | script | on |
| Deploy (deploy) | Puts the merged code live with the project's deployer (only when the deploy mode is on-merge or button). | script | on |
| Notify (notify) | Tells Alex the build has finished. | script | on |

## What steps pass on

Each step needs some things and makes others. When a step is off, the next one uses a fallback:

- no plan: the spec as written
- no checks: the spec's "done when" lines
- no test report: just the checks' results
- no reviewer verdict: pass if the checks passed
- no services: nothing to set up
- no baseline (main's test result): not run

## Why a build stopped on a step

- Spec check: the spec is incomplete or contradicts itself; offer a planning session to fix it.
- Diff rules: the builder changed a file it may not touch; the try failed and the next try is told why.
- Secret scan: the change held something that looks like a key; it is never committed.
- Acceptance or verify: checks or tests failed; read the tries with `task-tries`.
- Red check: the new checks already passed before any code, so they prove nothing.
- Merge: waiting on Alex (`gate-review`, then `merge-answer` after his yes).

For any of these, read the failures topic and `run-diagnose` before offering a repair.
