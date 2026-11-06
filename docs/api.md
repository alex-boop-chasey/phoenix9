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
| GET | `/api/projects?q=&status=&owner=&sort=&attention=` | `ops.projects.query` (step 3 of phase 5) | | `{top, rest, total, counts}` (see Shapes) | 400 |
| GET | `/api/projects/check-name?name=` | `ops.projects.check_name` | | `{ok, message}` | |
| GET | `/api/projects/<name>` | `ops.projects.show` (plus `repo_url` and the state fields of rows: `needs_you`, `questions`, `run`, `last_build_failed`, `activity`, `status_line`, `run_text`, `harness`) | | Project row + `setup` `{kind, source, template, preset, merge, created, services_set_up[{name, at, run, run_name}], waiting_for_keys[title]}` (what was chosen at setup, from `.phoenix/project.json` and `phoenix.toml`; any may be null) + `changelog`, `gates` | 404 |
| GET | `/api/projects/<name>/changelog?limit=20` | `ops.projects.changelog` | | list of `{date, who, text}`, newest last | 404 |
| GET | `/api/projects/<name>/keys` | `ops.keys.rows` (records no command) | | list of `{name, secret, has_value, value_if_not_secret}` | 404 |
| GET | `/api/projects/<name>/settings` | `ops.settings.show` | | `{project, values, source}` | 400, 404 |
| GET | `/api/projects/<name>/explain` | `ops.settings.explain` | | `{project, text}` | 400, 404 |
| GET | `/api/projects/<name>/specs` | `ops.projects.specs` | | list of `{path, title, modified}`, newest first | 404 |
| GET | `/api/projects/<name>/runs` | `ops.runs.builds` | | list of Build, newest first | 404 |
| GET | `/api/runs/<project>/<run_id>` | `ops.runs.detail` | | Run detail | 404 |
| GET | `/api/gates?project=` | `ops.gates.list_` | | the open questions only (`gates.is_open`), as gate objects (architecture section 8) plus `state: "open"` | 404 |
| GET | `/api/library/steps` | `ops.library.steps` | | `{steps, problems}` | |
| GET | `/api/library/profiles` | `ops.library.profiles` | | `{profiles, problems}` | |
| GET | `/api/library/presets` | `ops.library.presets` | | `{presets: [{name, title, has_file, description, steps}]}` (`title` and `description` come from the preset file; `steps` = `{step: on}` the preset file sets; the wizard needs it because a project's own `steps.<name>.on` sits above the preset layer in `/plan`) | |
| GET | `/api/library/templates` | `ops.projects.templates_menu` | | list of `{name, title, profile, kind, check}` | |
| GET | `/api/library/services` | `ops.library.services` | | `{services: [{name, title, project_keys}], problems}`; each project key = `{name, secret, public, required, help}` | |
| GET | `/api/library/tools` | `ops.library.tools` | | `{tools: [{name, label, help}]}`: the Claude Code tools Phoenix supports (`claude.SUPPORTED_TOOLS`: Read, Edit, Write, Glob, Grep, Bash, WebFetch, WebSearch). `ai.tools` empty = the step's defaults; `ai.tools_denied` names tools passed to `--disallowedTools` | |
| GET | `/api/github/repos` | `ops.github.repos` | | `{connected, repos: [{full_name, owner, private}]}` | |
| GET | `/api/global` | `ops.app.global_view` | | Global view; `default_models` is `{step: {model, fallback_models, title, library {model, fallback_models}}}` (Phoenix's saved defaults over the library's) | |
| GET | `/api/global/services` | `ops.services.list_global` | | `{supported, services: [row]}`: Claude, the library services, Telegram. Row adds `ends_in {KEY: "…abcd"}`, `account_settings [{name, label, kind, options, placeholder, help, value}]`, `can_test`, `endpoints {connect, disconnect, test}` | |
| POST | `/api/global/models` | `ops.app.set_default_models` (`phoenix models set`) | `{steps: {step: {model, fallback_models}}}` | `{saved, default_models}`; written to `global.toml [models.<step>]` | 400 |
| GET | `/api/doctor?mode=quick\|full` | `ops.doctor.run` | | `{ok, checks: [{name, ok, detail, fix}], checked_at}` | 400 |
| GET | `/api/services` | `ops.services.list_` | | `{supported: true, services: [row + endpoints {connect, disconnect}]}`; row = `{name, title, description, support, connected, note, account_keys, checked, checked_at, project_keys, hosts, used_by}` | |
| GET | `/api/keys/audit` | `ops.keys.audit` | | `{global: [{file, names, used_by, modified, mode, mode_ok}], projects: [{project, name, secret, set, used, last_touched, service}], problems: [text]}` (never a value) | |
| GET | `/api/health` | none (`ops.app.release_tag` read once at start) | | `{ok: true, version, tag}`; `tag` is the running copy's release tag, `""` when unknown | |
| GET | `/api/update?refresh=1` | `ops.update.status(refresh)` | | updater status: `{supported, installed {tag, commit} \| null, previous, newest, update_available, can_rollback, busy, busy_reason, running, waiting, phase, interrupted, last {action, tag, result, reason, at}, log_tail: [line]}`; `refresh=1` asks GitHub for the newest tag | |
| GET | `/api/update/log?lines=200` | `ops.update.log` | | `{lines, checks_file}` | |
| GET | `/api/update/history` | `ops.update.history` | | `{history: [{at, action, tag, result, reason, who}]}` newest first (from `HOME/update/history.jsonl`) | |
| GET | `/api/projects/<name>/deploys` | `ops.deploy.status` | | `{project, deployer {name, title, supported}, recent (newest first), live_url, last_good_commit, last_good_at}` | 404 |
| POST | `/api/update/install` | `ops.update.install` (queues the updater unit; never runs it) | `{tag?, yes: true}` | `{ok, queued, tag}` | 400 |
| POST | `/api/update/rollback` | `ops.update.rollback` | `{yes: true}` | `{ok, queued}` | 400 |
| POST | `/api/projects/<name>/deploy` | `ops.deploy.now` (in a background thread) | `{yes: true}` | `{job}` | 400, 404, 409 |
| GET | `/api/jobs/<id>` | none (held by the API) | | Job (see Shapes) | 404 |
| GET | `/api/events` | server-sent events (`stream.py`) | | stream | |
| GET | `/api/events/recent?project=&after=&limit=` | polling fallback | | `{events: [{id, ...event}], next}` | |
| GET | `/api/logs?project=&run=&task=&step=&kind=` | `ops.logs.list_` | | list of `{id, kind, run, task, attempt, step, title, size, modified}` | 400, 404 |
| GET | `/api/logs/read?project=&id=` | `ops.logs.read` | | `{id, kind, title, text, truncated, is_diff}` (last 2 MB, scrubbed) | 400, 404 |
| POST | `/api/services/<name>/connect` | `ops.services.connect` (who `dashboard`; body never logged, reply never echoes values) | `{values: {NAME: value}, settings?: {name: text}}`; an already-connected service may leave a key out to keep it | `{name, connected, checked, message}` | 400 |
| POST | `/api/services/<name>/test` | `ops.services.test` (nothing saved; pasted key, else the saved one) | `{values?: {NAME: value}}` | `{name, ok, message}` | 400 |
| POST | `/api/services/<name>/disconnect` | `ops.services.disconnect` | `{yes: true}` | `{name, connected, used_by, warning}` | 400 |
| POST | `/api/projects` | `ops.projects.new` (in a background thread) | create form | `{job}` | 400, 409 |
| GET | `/api/import/candidates` | `ops.projects.import_candidates` | | list of `{name, path, repo \| null, removed_on \| null, kind: removed\|folder}`; removed projects first | |
| GET | `/api/folders?path=` | `ops.projects.list_folders` | | `{path, root, parent \| null, folders: [{name, path}]}`; sub-folders only, never hidden ones or symlinks leaving the projects folder; empty path = the projects folder | 400 (outside the projects folder), 404 |
| POST | `/api/import` | `ops.projects.import_` | `{target}` (a name or a path directly under the projects folder) | `{name, path, repo, was_removed, added: [files added], chat: "on"}`; also takes it off the removed list and sets the chat up (trust, enable, start) | 400, 404, 409 |
| POST | `/api/projects/<name>/remove` | `ops.projects.remove` | `{confirm: true}` | `{name, path, repo, removed_on, kept}`; stops and disables `claude-rc@<name>`, undoes the trust entry, records it in `global.toml` `[[removed_projects]]`; deletes nothing; refuses `phoenix9` and `home` | 400, 404, 409 |
| POST | `/api/projects/<name>/chat/start` | `ops.projects.chat_start` | `{}` | `{project, already, chat}` (chat as in the row shape); enables and starts `claude-rc@<name>`; the link may not be in `chat.url` yet, so the page asks again (`GET /api/projects/<name>`) until it is | 404 |
| POST | `/api/projects/<name>/edit` | `ops.projects.edit`; services: `ops.projects.set_services` (added in step 03) | `{description?, repo?, profile?, services?, confirm?}` | fresh `GET /api/projects/<name>` data | 400, 404, 409 |
| POST | `/api/projects/<name>/keys/save` | `ops.keys.save` (added in step 03) | `{rows: [{name, value?, secret}]}` | masked key rows | 400, 404 |
| POST | `/api/projects/<name>/keys/reveal` | `ops.keys.reveal` (added in step 03) | `{name}` | `{name, value}` | 400, 404 |
| POST | `/api/projects/<name>/keys/remove` | `ops.keys.remove` | `{name}` | masked key rows | 400, 404 |
| POST | `/api/projects/<name>/settings` | `ops.settings.set_many` (added in step 03) | `{"set": {"steps.builder.model": "..."}}` | fresh settings data | 400, 404 |
| POST | `/api/projects/<name>/settings/preset` | `ops.settings.preset` | `{preset}` | fresh settings data | 400, 404 |
| POST | `/api/projects/<name>/settings/check` | `ops.settings.check` | `{}` | fresh settings data | 404 |
| POST | `/api/projects/<name>/plan` | `ops.runs.plan` (added in step 03) | `{overrides}` | Plan (see Shapes) | 400, 404 |
| POST | `/api/projects/<name>/defaults` | `ops.settings.save_defaults` (added in step 03) | `{overrides}` | `{project}` | 400, 404 |
| POST | `/api/projects/<name>/runs` | `ops.runs.start_from_notes` (added in step 03) | `{spec \| brief, overrides}` | `{run_id, project, status}` | 400, 404 |
| POST | `/api/runs/<project>/<run_id>/stop` | `ops.runs.stop` | `{"confirm": true}` | `{run_id, status, containers_removed, notes}`; `status` is `stopped` (the runner's clean stop ran at once) or `"stop requested"` (the runner is walking the run and stops it at its next boundary); refused with a plain message when the run already ended or the caller may not stop runs in the project (same rule as answering an escalation) | 400, 404 |
| GET | `/api/gates/<gate_id>/review` | `ops.gates.review` | | merge gates only: `{gate, run, project, title, why, answered, summary, tasks{passed,total,retried[]}, full_suite{status,note}, safety{flag,files}, files[{path,added,removed,binary,safety,diff}], added, removed, merge_request}`; diff from the run's own branch, else its patch files, else `gh pr diff`; scrubbed. CLI `phoenix gate review <id>` | 400, 404 |
| POST | `/api/gates/<gate_id>/answer` | `ops.gates.answer` | `{action, note}` | `{gate, action, note, who, at}` | 400, 404, 409 |

## Shapes

**Project row** (`ops.projects.rows`): every field of `phoenix9/project.py:info()` unchanged:
`name`, `description`, `path`, `repo` (string, `""` when none; may be a URL), `repo_owner`, `repo_name`,
`profile`, `services` (list), `size` (int bytes or null), `chat {state: "on"|"off", kind: "session"|"environment"|"none", url}` (`url` is null when the chat is off or no
environment id is known: the page then shows "Start chat" only if the chat is on; new and imported projects get no chat service, so a project whose chat is off shows no chat button; the id is read from the journal of `claude-rc@<name>`
since the unit's last start and stored in `.phoenix/project.json` as `chat_env_id`, `chat_env_seen`, `chat_env_start`),
`vscode {url, reason}` (`url` null with a reason when `/srv/projects/<name>` does not exist), `vscode_url` (same as `vscode.url`), `state` ("on"|"off", the chat service), `chats` (int), `last_used`, `last_used_at`,
`harness` (the harness column in words, from `status.project_state`: "idle" | "queued" | "running task N of M" |
"running" | "paused (usage limit)" | "needs you"), `has_phoenix_toml`;
plus the project's state, worked out ONCE by `phoenix9/status.py` `project_state` (every API route, CLI
command and dashboard display reads these fields; nothing else works them out again):
- `repo_url`: `https://github.com/<owner>/<name>` when `repo_owner` is set, else null.
- `needs_you`: number of open questions of the project; `questions`: their gate ids. A question is open only
  when it has no answer file, its run is not done/failed/stopped, and the run waits on it (`gates.is_open`).
- `run`: the current build `{run_id, status, task, tasks, carrying_on, why, now}`, else null. It is the run
  with an open question, else the newest running, paused-limit, waiting (carrying on) or queued run.
  `status` is as Alex should see it (a waiting run whose questions are all answered reads `running` with
  `carrying_on: true`); `task` = `current.task` (while running: the first task not passed yet);
  `why` = why it is the current build; `now` = the "Now: ..." line of the Current build card.
- `last_build_failed`: true when the newest finished run (done, failed or stopped) failed.
- `activity`: `need` (an open question), else `fail` (paused at a limit), else `run` (any current build),
  else `fail` (`last_build_failed`), else `idle`.
- `status_line`: the sidebar line ("1 question waiting", "Building, task 2 of 4", "Build queued", "Paused at a
  limit", "Last build failed", "Idle, used 3h ago"); `run_text`: the Projects page words ("Running task 2 of 4",
  "Queued", "Paused (usage limit)", "Idle").

`vscode_url` is `paths.VSCODE_URL` + `?folder=<PHOENIX_PROJECTS>/<name>`.

**Info** (`/api/info`): `version` (`phoenix9.__version__`), `label` (what the header shows: the install tag, else `v` + major.minor, e.g. `v9.1`), `update {supported, installed, newest,
available, can_install, reason, endpoints {install, rollback}}`, `github {connected, accounts}`, `services {supported}` (true).

**Build** (`ops.runs.builds`): the run summary `{run_id, project, status, created, updated, current,
tasks_total, tasks_passed, usage}` plus `title`, `preset`, `started`, `finished` (ISO or `""`),
`duration` (plain words or `""`), `cost` (like `"$0.42"`), `tasks_failed`.

**Run detail** (`ops.runs.detail`): the run's state.json fields, `gates` (open), `recent_events`, plus
`plan` (the plan.json shape: `groups`, `sources`, `off`, `steps`), `plan_frozen` (false when the run has
not started and `plan` is a preview from its overrides), `title`, `preset`, `max_tries`, `branch` (`phoenix/<run-id>`).

**Global view** (`ops.app.global_view`): `values` (non-secret contents of `HOME/config/global.toml`),
`github {connected, accounts}`, `default_models {<ai step>: {model, fallback_models}}`,
`telegram {connected}`, `supported {services, update, secrets}` (false for parts not built yet).

**Settings** (`ops.settings.show`): `values` nested with every key filled; `source` maps a flat dotted key
to `"library"`, `"profile:<p>"`, `"preset:<p>"`, `"project"` or `"run"`.

**Create form** (`POST /api/projects`): `{name, description, source: {kind: "empty"|"repo"|"template"|"code",
repo?, template?, path?}, profile, new_repo: {on, owner}, services: [], keys: [{name, value, secret}]}`.
The reply is `{job}` at once; ops runs in the background (one create at a time, else 409). Key values go
straight to the keys store (`opts["keys"]`), never to a file.

**Job** (`GET /api/jobs/<id>`, kept 1 hour): `{id, kind: "create" \| "deploy", project, status: "running"|"done"|"failed",
steps: [{label, status: "running"|"done"|"failed"}], message}`. Each progress line from ops starts a step and
marks the previous one done; `message` is the ops error on failure (empty otherwise). Deploy jobs have no steps and add `result` (the `ops.deploy.now` result, `null` while running). One job per kind at a time: a second create while one creates, or a second deploy while one deploys, is 409; a create and a deploy may run together.

**Plan** (`POST .../plan`): `{groups: {"run-start": [...], "task": [...], "run-finish": [...]}, steps: [{name,
title, group, order, kind: "script"|"ai"|"gate", safety, default, on, reason, sources, ai}], errors: [plain
English], settings: {preset, based_on, max_tries, on_failure, merge, deploy}}`. `ai` is the step's effective
ai block for ai steps, else null. Bad overrides are not an HTTP error: `errors` is filled and `steps` come
from the project's own settings.

**Edit**: changing `repo` or `profile` needs `"confirm": true`, else 409
`{ok: false, message, needs_confirm: true}`. **Keys**: a row without `value` keeps its saved value; every bad
row is named in one 400. **Settings**: `set` values are typed JSON by dotted key; one bad key means nothing is
written. **Runs**: exactly one of `spec` (path relative to `notes/`, inside `specs` or `plans`) or `brief`
(needs the Planner on); `overrides` are frozen into the run.

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
event ids are line numbers in `HOME/events.jsonl` (architecture 8.5).

`GET /api/events?project=` is a server-sent stream (no write guard): it starts after the `Last-Event-ID` line,
else at the end of the file; polls every `PHOENIX_API_TAIL_SECONDS` (0.5); sends `: ping` every
`PHOENIX_API_PING_SECONDS` (15); at most 20 open streams (the 21st gets 503). Frames are
`id: <line>\nevent: <type>\ndata: <line>`. If the file shrinks the stream restarts at line 0.
`GET /api/events/recent?project=&after=&limit=` is the polling fallback.

## Logs

Log ids are paths: `<run id>/<path inside the run folder>` or `logs/<file>` (inside HOME). Anything else is
refused (400). Kinds: `session`, `check`, `diff`, `step`, `gate`, `command`, `service`.

## Demo data

`python3 tests/seed_demo.py <home> <projects>` writes it; `python3 tests/demo_server.py <home> <projects> --port N`
serves it on fake adapters (no systemd, GitHub, Docker or Claude). Fixed times.

| Project | Repo | Runs |
|---|---|---|
| `demo-site` | `rebirth-wd/demo-site` (profile web, preset full; keys `RESEND_API_KEY` secret, `PUBLIC_SITE_URL`) | `20261020-090000-contact-form` done ($1.23, 14 min); `20261022-140000-blog-section` failed (task 2); `20261031-100000-pricing-page` waiting, open escalation gate `20261031-100000-pricing-page.1` |
| `tiny-tool` | `alex-boop-chasey/tiny-tool` (python-script, simple) | `20261101-080000-add-json-output` running (task 2 of 4) |
| `notes-only` | none (research) | none |
| `phoenix9` | `alex-boop-chasey/phoenix9` (platform) | `20261031-110000-api-and-dashboard` waiting, open merge gate `20261031-110000-api-and-dashboard.1` |


**Project search** (`GET /api/projects` with any of `q`, `status`, `owner`, `sort`, `attention`; with none of them the reply is
the plain list of rows). `q` = text in name or description (case-insensitive); `status` = `all|run|fail|idle|need`
(need = open question or run waiting; fail = failed or paused at a limit; run = running or queued); `owner` = `all`, `none`
(no repo) or a GitHub owner; `sort` = `name|active` (most recently used first)`|size` (largest first)`|created` (newest first, from `.phoenix/project.json`)`|modified` (newest first: latest of last run, changelog and project file changes); `attention=1` puts the
"need" projects in `top` (in sort order), the rest in `rest` (otherwise `top` is empty). Reply: `{top: [row], rest: [row],
total, counts: {all, run, fail, idle, need}}`; `total` = rows in top + rest; `counts` follow `q` and `owner` but ignore `status`
(so the status tabs can show their numbers). Bad `status`, `sort` or `attention` values answer 400.
CLI: `phoenix project list --filter TEXT --status S --owner O --sort S --attention [--json]` (the same reply with `--json`).
The page address carries the same values (`/?q=...&status=...`, defaults left out), read and written by `useProjectQuery`
(`web/src/features/projects/useProjectQuery.ts`); the Agent sets the same values.
