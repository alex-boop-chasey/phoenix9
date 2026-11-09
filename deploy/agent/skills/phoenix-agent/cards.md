<!-- phoenix 9.1.0 inputs 771b61a43de3d483 -->
# Cards

A card is shown in the Agent panel; its query keys and types:

## `builds`

a project's recent builds, newest first.

- query: `limit` (int), `project` (str)

## `chart`

a small bar chart or sparkline of numbers proposed by the agent.

- query: `kind` (str), `series` (list)

## `diff`

the changes of one task attempt, split into files with added and removed counts.

- query: `id` (str), `project` (str)

## `edits`

quick edits (all, or one project's) with status, merge request link and Abandon.

- query: `project` (str)

## `gates`

the open gates (questions waiting for Alex), optionally for one project.

- query: `project` (str)

## `log`

the last lines of one log of a project, scrubbed, with a link to the Logs page.

- query: `id` (str), `lines` (int), `project` (str), `tail` (int)

## `plans`

planning sessions (all, or one project's) with status, spec and Abandon.

- query: `project` (str)

## `projects`

the projects list (same filters as the Projects page), with a link to each project.

- query: `attention` (bool), `names` (list[str]), `owner` (str), `q` (str), `sort` (str), `status` (str)

## `prs`

pull requests of one project (or every project with a GitHub repo), with a link to each.

- query: `project` (str), `state` (str)

## `repair`

a run's repair summary (status line, findings) and a proposed repair note with its dry-run result.

- query: `note` (str), `project` (str), `run` (str)

## `run`

one build run, with a link to the Build tab and a Stop button while it is active.

- query: `project` (str), `run_id` (str)

## `settings-preview`

a change to a project's settings proposed by the agent, checked without saving, with an Apply button.

- query: `project` (str), `set` (dict)

## `table`

a small table of text and numbers proposed by the agent.

- query: `columns` (list[str]), `rows` (list)

## `update`

the Phoenix 9 version status, with a link to the update settings and Install when one is ready.

- query: (no keys)
