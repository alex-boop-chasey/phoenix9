# Phoenix 9 dashboard API

The contract between `phoenix9/api/server.py` and the web app in `web/`. The server does no work itself:
every endpoint calls one function in `phoenix9/ops/`. Paths are relative to the page's own address
(the app is served under `/proxy/<port>/`), so the web app never uses an absolute `/api/...`.

## Rules

- Listens on 127.0.0.1 only.
- Every reply is JSON: `{"ok": true, "data": ...}` or `{"ok": false, "message": "<plain English>"}`.
- HTTP status: 200 fine, 400 bad request or refused by ops, 403 forbidden, 404 not found, 409 conflict,
  500 unexpected failure, 503 busy or not available.
- Every POST needs the header `X-Phoenix: 1` and an `Origin` listed in `PHOENIX_API_ORIGINS`
  (comma list, default `https://files.rebirthwebdesign.com.au`), otherwise 403.
- POST bodies are JSON objects of at most 64 KB.
- The API passes `who="dashboard"` to every ops call that changes something.
- Key values are only ever returned by the reveal endpoint.
- Nothing in the API does work itself; it calls ops.
- Dashboard open question 2 unanswered; built as one Projects list with a filter by repo owner.

## Errors

`ops.common.NotFound` gives 404, `ops.common.Conflict` gives 409, any other `OpsError` gives 400.
The message is the ops message, unchanged. The CLI catches all three as `OpsError` (exit 1, same text).

## Endpoints

| Method | Path | Ops function | Request body | `data` | Errors |
| --- | --- | --- | --- | --- | --- |
| GET | `/api/info` | `ops.app.info` | | Info | |
| GET | `/api/projects` | `ops.projects.rows` | | list of Project row | |
| GET | `/api/projects/check-name?name=` | `ops.projects.check_name` | | `{ok, message}` | |
| GET | `/api/projects/<name>` | `ops.projects.show` (plus `needs_you`, `run`, `repo_url` like rows) | | Project row + `changelog`, `gates` | 404 |
| GET | `/api/projects/<name>/changelog?limit=20` | `ops.projects.changelog` | | list of `{date, who, text}`, newest last | 404 |
| GET | `/api/projects/<name>/keys` | `ops.keys.rows` (records no command) | | list of `{name, secret, has_value, value_if_not_secret}` | 404 |
| GET | `/api/projects/<name>/settings` | `ops.settings.show` | | `{project, values, source}` | 400, 404 |
| GET | `/api/projects/<name>/explain` | `ops.settings.explain` | | `{project, text}` | 400, 404 |
| GET | `/api/projects/<name>/specs` | `ops.projects.specs` | | list of `{path, title, modified}`, newest first | 404 |
| GET | `/api/projects/<name>/runs` | `ops.runs.builds` | | list of Build, newest first | 404 |
| GET | `/api/runs/<project>/<run_id>` | `ops.runs.detail` | | Run detail | 404 |
| GET | `/api/gates?project=` | `ops.gates.list_` | | list of gate objects (architecture section 7) | 404 |
| GET | `/api/library/steps` | `ops.library.steps` | | `{steps, problems}` | |
| GET | `/api/library/profiles` | `ops.library.profiles` | | `{profiles, problems}` | |
| GET | `/api/library/presets` | `ops.library.presets` | | `{presets: [{name, title, has_file, description}]}` | |
| GET | `/api/library/templates` | `ops.projects.templates_menu` | | list of `{name, title, profile, kind, check}` | |
| GET | `/api/library/services` | `ops.library.services` | | `{services: [{name, title, project_keys}], problems}` | |
| GET | `/api/github/repos` | `ops.github.repos` | | `{connected, repos: [{full_name, owner, private}]}` | |
| GET | `/api/global` | `ops.app.global_view` | | Global view | |
| GET | `/api/services` | `ops.app.services_view` (phase 4 repoints this at `ops.services.list`) | | `{supported: false, services: []}` | |
| GET | `/api/jobs/<id>` | none (held by the API; step 03) | | `{id, state, lines, result, error}` | 404 |
| GET | `/api/events` | server-sent events (step 04) | | stream | |
| GET | `/api/events/recent?project=&after=&limit=` | polling fallback (step 04) | | list of events | |
| GET | `/api/logs?project=&run=&task=&step=&kind=` | `ops.logs.list_` (step 04) | | list of log entries | 404 |
| GET | `/api/logs/read?project=&id=` | `ops.logs.read` (step 04) | | `{id, text}` | 404 |
| POST | `/api/projects` | `ops.projects.new` (step 03) | create form | `{job}` | 400 |
| POST | `/api/projects/<name>/edit` | `ops.projects.edit`; services: `ops.projects.set_services` (step 03) | `{description?, repo?, profile?, services?}` | edited project | 400, 404 |
| POST | `/api/projects/<name>/keys/save` | `ops.keys.save` (step 03) | `{name, value, secret}` | `{project, name, secret}` | 400, 404 |
| POST | `/api/projects/<name>/keys/reveal` | `ops.keys.reveal` (step 03) | `{name}` | `{name, value}` | 400, 404 |
| POST | `/api/projects/<name>/keys/remove` | `ops.keys.remove` | `{name}` | `{project, name, removed}` | 400, 404 |
| POST | `/api/projects/<name>/settings` | `ops.settings.set_many` (step 03) | `{"set": {"steps.builder.model": "..."}}` | `{project, set}` | 400, 404 |
| POST | `/api/projects/<name>/settings/preset` | `ops.settings.preset` | `{name}` | `{project, preset}` | 400, 404 |
| POST | `/api/projects/<name>/settings/check` | `ops.settings.check` | `{}` | `{project, ok, problems}` | 404 |
| POST | `/api/projects/<name>/plan` | `ops.runs.plan` (step 03) | `{overrides}` | plan (see Run detail) | 400, 404 |
| POST | `/api/projects/<name>/defaults` | `ops.settings.save_defaults` (step 03) | `{overrides}` | `{project}` | 400, 404 |
| POST | `/api/projects/<name>/runs` | `ops.runs.start_from_notes` (step 03) | `{spec \| brief, overrides}` | `{run_id, project, status}` | 400, 404 |
| POST | `/api/runs/<project>/<run_id>/stop` | `ops.runs.stop` | `{"confirm": true}` | `{run_id, status, containers_removed}` | 400, 404 |
| POST | `/api/gates/<gate_id>/answer` | `ops.gates.answer` | `{action, note}` | `{gate, action, note, who, at}` | 400, 404, 409 |

## Shapes

**Project row** (`ops.projects.rows`): every field of `phoenix9/project.py:info()` unchanged:
`name`, `description`, `path`, `repo` (string, `""` when none; may be a URL), `repo_owner`, `repo_name`,
`profile`, `services` (list), `size` (int bytes or null), `chat {kind: "session"|"environment"|"none", url}`,
`vscode_url`, `state` ("on"|"off", the chat service), `chats` (int), `last_used`, `last_used_at`,
`harness` (a string: "idle" | "queued" | "running task N of M" | "needs you"), `has_phoenix_toml`;
plus:
- `repo_url`: `https://github.com/<owner>/<name>` when `repo_owner` is set, else null.
- `needs_you`: number of open gates of the project.
- `run`: `{run_id, status, task, tasks}` of the newest run that is queued, running, waiting or
  paused-limit (`task` = `current.task`, `tasks` = total), else null.

`vscode_url` is `paths.VSCODE_URL` + `?folder=<PHOENIX_PROJECTS>/<name>`.

**Info** (`/api/info`): `version` (`phoenix9.__version__`), `update {supported, installed, newest,
available, can_install, reason}`, `github {connected, accounts}`, `services {supported}`.

**Build** (`ops.runs.builds`): the run summary `{run_id, project, status, created, updated, current,
tasks_total, tasks_passed, usage}` plus `title`, `preset`, `started`, `finished` (ISO or `""`),
`duration` (plain words or `""`), `cost` (like `"$0.42"`), `tasks_failed`.

**Run detail** (`ops.runs.detail`): the run's state.json fields, `gates` (open), `recent_events`, plus
`plan` (the plan.json shape: `groups`, `sources`, `off`, `steps`), `plan_frozen` (false when the run has
not started and `plan` is a preview from its overrides), `title`, `preset`, `max_tries`.

**Global view** (`ops.app.global_view`): `values` (non-secret contents of `HOME/config/global.toml`),
`github {connected, accounts}`, `default_models {<ai step>: {model, fallback_models}}`,
`telegram {connected}`, `supported {services, update, secrets}` (false for parts not built yet).

**Settings** (`ops.settings.show`): `values` nested with every key filled; `source` maps a flat dotted key
to `"library"`, `"profile:<p>"`, `"preset:<p>"`, `"project"` or `"run"`.

## Overrides shape (wizard and defaults)

The same nesting as phoenix.toml (architecture 5.2) and the same keys `settings.effective(...,
run_overrides=)` validates, for example:

```json
{"preset": "full", "max_tries": 3, "on_failure": "pause", "merge": "ask",
 "steps": {"reviewer": {"on": false}, "builder": {"model": "..."}}}
```

`preset: "custom"` goes with `based_on`. Unknown keys are errors (400).

## Events

One event line is `{ts, type, project, run, task, step, data}` (architecture section 8). Server-sent
event ids are line numbers in `HOME/events.jsonl` (architecture 8.5); step 04 fills in the details.

## Not yet (phase 4)

Update install and rollback, services connect, global secret writes.
