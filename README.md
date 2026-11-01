# Phoenix 9

A project manager plus a configurable AI coding harness. See CLAUDE.md for the rules and
docs/architecture.md for the design. Run the checks with `./check.sh`.

## How a run works

Every run starts with Pick up, Spec check and Branch, then builds each task, then finishes with Full suite, Summary, Merge and Notify.
Each task is one attempt loop. The presets change which steps are in it:

- **Simple:** Builder, Diff rules, Secret scan, Acceptance, Commit.
- **Quick:** Simple, plus Verify (the project's tests) before Commit.
- **Full:** Planner first (you approve its plan), then per task Check writer, Red check, Builder, Diff rules, Secret scan, Acceptance, Verify, Reviewer, Commit.

When a task fails, `on_failure` decides what happens once its tries are used up:

- **continue:** the task is marked failed, the tasks that depend on it are skipped, and the run carries on. The merge then asks you first.
- **pause:** the run stops and asks you ("Needs you"). Fix things, answer `acknowledged`, and the task gets one more attempt.
- **delegate:** the same question goes to the project's own chat first. If it fixes the task and answers, the run goes on; if it gives up, you are told.
