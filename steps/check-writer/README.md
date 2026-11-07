Writes the task's checks before any code exists.

The checks go in `<checks_dir>/<run-id>/task-<n>/` (one folder per run, so a later build never
finds an earlier build's merged checks in its own task folder); Phoenix commits and locks them.

Checks must be self-contained: they make their own temp folders and set every environment variable
they read (only PATH, HOME, TMPDIR, the check container's env and the project's keys are given).
Before locking, the step refuses a check file that reads a variable it never sets
(`phoenix9/checklint.py` `unset_env`) and names the variable, so the next try rewrites it. On a retry
the prompt lists why earlier tries failed (including a Red check that found the checks broken).
