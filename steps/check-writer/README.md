Writes the task's checks before any code exists.

The checks go in `<checks_dir>/<run-id>/task-<n>/` (one folder per run, so a later build never
finds an earlier build's merged checks in its own task folder); Phoenix commits and locks them.
