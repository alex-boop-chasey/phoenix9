<!-- phoenix 9.1.0 inputs 27c509529230cb1c -->
# Step library

Steps run in this order inside each group.

## run-start

### pick-up

Pick up. Reads the spec file the run was started from.

- kind: script
- default: always
- safety step: no
- needs: spec
- produces: (nothing)

### spec-check

Spec check. Checks the spec is complete and makes sense before any work starts.

- kind: script
- default: always
- safety step: no
- needs: spec
- produces: (nothing)

### branch

Branch. Makes the run's branch and worktree and records main's test result.

- kind: script
- default: always
- safety step: no
- needs: spec
- produces: baseline

### planner

Planner. Writes a short plan for the whole spec before building.

- kind: ai
- default: off
- safety step: no
- needs: spec
- produces: plan

### service-setup

Service setup. Wires the project's chosen services in once: keys present, hosts allowed, install notes for the Builder.

- kind: script
- default: on
- safety step: no
- needs: worktree
- produces: service-notes

## task

### check-writer

Check writer. Writes the task's checks before any code exists.

- kind: ai
- default: off
- safety step: no
- needs: task, worktree, failures
- produces: checks

### red-check

Red check. Proves the new checks fail before the code is written.

- kind: script
- default: on
- safety step: yes
- needs: checks
- produces: (nothing)
- only with: check-writer

### builder

Builder. Writes the code for one task.

- kind: ai
- default: always
- safety step: no
- needs: task, worktree, failures, plan, checks, service-notes
- produces: diff

### diff-rules

Diff rules. Refuses changes to files the agent may not touch.

- kind: script
- default: on
- safety step: yes
- needs: diff
- produces: (nothing)

### secret-scan

Secret scan. Looks for keys and passwords in the change.

- kind: script
- default: on
- safety step: yes
- needs: diff
- produces: (nothing)

### acceptance

Acceptance. Runs the task's checks and records the exit codes.

- kind: script
- default: always
- safety step: no
- needs: checks, worktree
- produces: exit-codes

### verify

Verify. Runs the project's tests and builds the test report.

- kind: script
- default: on
- safety step: yes
- needs: worktree, checks
- produces: test-report

### reviewer

Reviewer. A fresh reader checks the change and gives a verdict.

- kind: ai
- default: off
- safety step: no
- needs: worktree, test-report
- produces: verdict

### commit

Commit. Commits the task's change if everything passed.

- kind: script
- default: always
- safety step: no
- needs: diff, verdict, exit-codes
- produces: commit

## run-finish

### lockfile

Lockfile check. Checks that exact package versions are saved in a committed lockfile.

- kind: script
- default: on
- safety step: yes
- needs: worktree
- produces: (nothing)

### full-suite

Full suite. Runs the whole test suite once all tasks are done.

- kind: script
- default: on
- safety step: yes
- needs: worktree
- produces: test-report

### summary

Summary. Writes the plain-English summary of the run.

- kind: script
- default: on
- safety step: no
- needs: spec
- produces: (nothing)

### preview

Preview. Deploys the run's branch to a temporary address before Merge (off unless [deploy] preview = true)

- kind: script
- default: on
- safety step: no
- needs: worktree
- produces: preview-url

### merge

Merge. Merges the run's branch into main (or asks first).

- kind: script
- default: on
- safety step: no
- needs: worktree
- produces: merged

### deploy

Deploy. Puts the merged code live with the project's deployer (off unless [deploy] mode is on-merge or button).

- kind: script
- default: on
- safety step: no
- needs: merged
- produces: deployed

### notify

Notify. Tells Alex the run has finished.

- kind: script
- default: on
- safety step: no
- needs: spec
- produces: (nothing)

## Things

- `baseline` (fallback: not-run)
- `checks` (fallback: spec-done-when)
- `commit` (fallback: none)
- `deployed` (fallback: none)
- `diff` (fallback: none)
- `exit-codes` (fallback: none)
- `failures` (provided: task)
- `merged` (fallback: not-merged)
- `plan` (fallback: spec-as-written)
- `preview-url` (fallback: none)
- `service-notes` (fallback: no-services)
- `spec` (provided: run)
- `task` (provided: task)
- `test-report` (fallback: exit-codes-only)
- `verdict` (fallback: pass-if-checks-passed)
- `worktree` (provided: run)
