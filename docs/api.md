# Phoenix 9 dashboard API

The contract between `phoenix9/api/server.py` and the web app in `web/`. The server does no work itself:
every endpoint calls one function in `phoenix9/ops/`. Paths are relative to the page's own address
(the app may be served at a site root or under a prefix such as `/proxy/<port>/`), so the web app never uses an absolute `/api/...`.

## Rules

- Listens on 127.0.0.1 only.
- Every reply is JSON: `{"ok": true, "data": ...}` or `{"ok": false, "message": "<plain English>"}`.
- HTTP status: 200 fine, 400 bad request or refused by ops, 403 forbidden, 404 not found, 409 conflict,
  500 unexpected failure, 503 busy or not available.
- Every POST needs the header `X-Phoenix: 1` and an `Origin` in the allowed origins (`PHOENIX_API_ORIGINS`, else the
  `allowed_origins` global setting, default the dashboard address's origin; architecture 5.5), otherwise 403 with
  "Refused: this page was opened from <origin>, which Phoenix doesn't allow yet. Add it in Global settings >
  Dashboard addresses (or run `phoenix settings global set allowed_origins=...`)."
- Every request, any method and any route (reads, the live streams and the web app's files too), must come from
  a process owned by an allowed uid on this server (looked up in `/proc/net/tcp`; global.toml `[access] peer_uids`,
  default `[0]` = root only; the older name `write_peer_uids` also works): any other user gets 403 "Refused: this
  request came from a program on the server that isn't run by root (or another user Phoenix allows).", and an owner
  that cannot be found gets 403 "Refused: Phoenix couldn't tell which program on the server sent this request."
  When global.toml `[access] team_domain` and `aud` are both set, every request also needs a valid Cloudflare Access
  token in `Cf-Access-Jwt-Assertion` (else 403 "Refused: Phoenix needs a Cloudflare Access sign-in. ..."; architecture
  8.5). The one exception to both is `GET /api/health`, open to any local program (doctor, the updater and
  `phoenix service restart` call it); it shows only the version, release tag and a digest of the allowed origins.
  The CLI never goes through the API (it calls ops directly).
- POST bodies are JSON objects of at most 64 KB (`/api/agent/send` allows a full-size message).
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
| GET | `/api/projects/<name>` | `ops.projects.show` (plus `repo_url` and the state fields of rows: `needs_you`, `questions`, `run`, `last_build_failed`, `activity`, `status_line`, `run_text`, `harness`, `worker`, `chat`: the chat state or null) | | Project row + `setup` `{kind, source, template, preset, merge, created, services_set_up[{name, at, run, run_name}], waiting_for_keys[title]}` (what was chosen at setup, from `.phoenix/project.json` and `phoenix.toml`; any may be null. When setup did not record them, `created` is the date of the first commit in code/, else the folder's date, and `source` is `repo` (code/ has an origin), `code` (code/ is a git repo) or `empty`; `preset` is the project's default preset, each build shows its own) + `changelog`, `gates` | 404 |
| GET | `/api/projects/<name>/changelog?limit=20` | `ops.projects.changelog` | | list of `{date, who, text}`, newest last | 404 |
| GET | `/api/projects/<name>/delete-plan` | `ops.projects.delete_plan` | | the dry run for deleting a project entirely: `{name, folder, size, repo, repo_delete: {repo, delete, why, reason?, repo_id?}, open_prs, unpushed, unsaved_edits, runs, keys, keys_note?, chat, deployments, refusals, safety_copy, keep_days}` | 404 |
| GET | `/api/projects/<name>/keys` | `ops.keys.rows` (records no command) | | list of `{name, secret, has_value, value_if_not_secret}` | 404 |
| GET | `/api/projects/<name>/settings` | `ops.settings.show` | | `{project, values, source}` | 400, 404 |
| GET | `/api/projects/<name>/explain` | `ops.settings.explain` | | `{project, text}` | 400, 404 |
| GET | `/api/chat/<name>` | `ops.chat.chat_state` | | `{state, bridge_session_id, web_url, app_url, last_active}` (state: off, starting, sleeping, live, working) | 404 |
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
| POST | `/api/global/addresses` | `ops.app.set_addresses` (`phoenix settings global set`) | `{dashboard_url?, allowed_origins?: [origin], vscode_url?}` (`vscode_url: ""` = not set) | `{values {dashboard_url, allowed_origins, vscode_url}, api_restart: "asked" \| "not needed" \| "failed: ..."}`; a change of the allowed origins rewrites api.env and restarts the API just after the reply. Origins are normalised like a browser's Origin header (no default :443/:80, IPv6 in brackets); bad host names, `null` and `*` are refused, and so is a list without the dashboard_url's origin or the request's own Origin (it would lock the dashboard out) | 400 (plain message naming the address to add) |
| POST | `/api/global/models` | `ops.app.set_default_models` (`phoenix models set`) | `{steps: {step: {model, fallback_models}}}` | `{saved, default_models}`; written to `global.toml [models.<step>]` | 400 |
| GET | `/api/doctor?mode=quick\|full` | `ops.doctor.run` | | `{ok, checks: [{name, ok, detail, fix}], checked_at}` | 400 |
| GET | `/api/services` | `ops.services.list_` | | `{supported: true, services: [row + endpoints {connect, disconnect}]}`; row = `{name, title, description, support, connected, note, account_keys, checked, checked_at, project_keys, hosts, used_by}` | |
| GET | `/api/keys/audit` | `ops.keys.audit` | | `{global: [{file, names, used_by, modified, mode, mode_ok}], projects: [{project, name, secret, set, used, last_touched, service}], problems: [text]}` (never a value) | |
| GET | `/api/health` | none (`ops.app.release_tag` read once at start) | | `{ok: true, version, tag, origins_digest}`; `tag` is the running copy's release tag, `""` when unknown; `origins_digest` = 16 hex characters of the SHA-256 of the sorted allowed page origins (one per line), so the doctor can compare them with the setting without the reply showing them. Open to any local program, no Access token needed (the only such route) | |
| GET | `/api/update?refresh=1` | `ops.update.status(refresh)` | | updater status: `{supported, installed {tag, commit} \| null, previous, newest, update_available, can_rollback, busy, busy_reason, running, waiting, phase, interrupted, last {action, tag, result, reason, at}, log_tail: [line], off_release, off_release_note}` (`off_release_note` says how to get back to a release when the installed copy is on a commit with no release tag, else `""`); `refresh=1` asks GitHub for the newest tag | |
| GET | `/api/update/log?lines=200` | `ops.update.log` | | `{lines, checks_file}` | |
| GET | `/api/update/history` | `ops.update.history` | | `{history: [{at, action, tag, result, reason, who}]}` newest first (from `HOME/update/history.jsonl`) | |
| GET | `/api/projects/<name>/deploys` | `ops.deploy.status` | | `{project, deployer {name, title, supported}, recent (newest first), live_url, last_good_commit, last_good_at}` | 404 |
| POST | `/api/update/install` | `ops.update.install` (queues the updater unit; never runs it) | `{tag?, yes: true}` | `{ok, queued, tag}` | 400 |
| POST | `/api/update/rollback` | `ops.update.rollback` | `{yes: true}` | `{ok, queued}` | 400 |
| POST | `/api/projects/<name>/deploy` | `ops.deploy.now` (in a background thread) | `{yes: true}` | `{job}` | 400, 404, 409 |
| POST | `/api/service/<name>/restart` (name `api` or `runner`) | `ops.service.restart_api_soon` (api) / `ops.service.restart` in a background job (runner; `phoenix service restart`) | `{yes: true}` | api: `{service, restarted, queued: true}` (systemctl `--no-block`; the API restarts just after replying); runner: `{job}` (kind `restart`; waits up to 30 min for builds to reach a task boundary; `result` = `{service, restarted, waited, doctor}`) | 400, 409 (a restart is waiting) |
| POST | `/api/images/build` | `ops.images.build` (in a background thread; `phoenix images build`) | `{profiles?: [name], all?: bool, changed?: bool}` (none = the profiles projects use) | `{job}` (kind `images`; `result` = `{ok, built: [{profile, tag, ok, log}], skipped}`) | 400 (bad body or unknown profile), 409 (a build is running) |
| GET | `/api/jobs/<id>` | none (held by the API) | | Job (see Shapes) | 404 |
| GET | `/api/events` | server-sent events (`stream.py`) | | stream | |
| GET | `/api/events/recent?project=&after=&limit=` | polling fallback | | `{events: [{id, ...event}], next}` | |
| GET | `/api/cards?type=&query=&title=` | `ops.cards.build` | `query` is a JSON object (default `{}`) | `{type, title, data, actions, watch, inline}` (see "Reply blocks and dashboard control" in architecture.md) | 400 (bad JSON, unknown type, bad query: the reason in words), 404 (no such project or run) |
| GET | `/api/agent` | `ops.agent.status` | | `{state: asleep|idle|working|queued, pid, session_id, name}` | |
| GET | `/api/agent/messages?after=&limit=&session=` | `ops.agent.messages` | | `{items: [Agent item], unknown, last_line, session_id}` (items after line `after`, at most `limit`, default 100, cap 1000; `session` = an id from `/api/agent/sessions` reads that earlier conversation instead of the current one) | 400 |
| GET | `/api/agent/stream?after=` | server-sent events (`stream.agent_stream`) | | stream of `item`, `update` and `session` frames (see "Agent stream frames" below) | 503 (too many streams) |
| POST | `/api/agent/send` | `ops.agent.send` | `{text, context?: {page, project, run}}` (context values that are not allowed are dropped: `project` must be a listed project, `page`/`run` must match `[A-Za-z0-9/_.-]{1,80}`; newlines are stripped) | `{sent, at, after_line}` | 400 (empty text or over 100000 characters), 403, 503 (the agent is asleep or its inbox refused the message) |
| GET | `/api/agent/sessions` | `ops.agent.sessions` | | list of `{session_id, started, lines}`, newest first | |
| POST | `/api/agent/restart` | `ops.agent.restart` (restarts the `agent.unit` service and tells Alex) | `{confirm: true}` | `{restarted, unit}` | 403, 409 (no `confirm: true`; nothing restarted) |
| POST | `/api/ui/go` | `ops.ui.go` | `{to, params?: {}}` | `{hash, label}`; the open dashboard follows through a `ui.go` event | 400 (not a page, bad option: the reason), 404 (no such project, run, gate or log) |
| POST | `/api/blocks/check` | `ops.blocks.check` | `{kind: card\|choice\|confirm\|nav, json: text}` | `{ok, reason, resolved}` (not ok gives a plain reason; nav `resolved` is `{links: [{hash, label}], dropped: [{link, to, reason}]}`) | 400 (kind or json missing) |
| GET | `/api/logs?project=&run=&task=&step=&kind=` | `ops.logs.list_` | | list of `{id, kind, run, task, attempt, step, title, size, modified}` | 400, 404 |
| GET | `/api/logs/read?project=&id=` | `ops.logs.read` | | `{id, kind, title, text, truncated, is_diff}` (last 2 MB, scrubbed) | 400, 404 |
| POST | `/api/services/<name>/connect` | `ops.services.connect` (who `dashboard`; body never logged, reply never echoes values) | `{values: {NAME: value}, settings?: {name: text}}`; an already-connected service may leave a key out to keep it | `{name, connected, checked, message}` | 400 |
| POST | `/api/services/<name>/test` | `ops.services.test` (nothing saved; pasted key, else the saved one) | `{values?: {NAME: value}}` | `{name, ok, message}` | 400 |
| POST | `/api/services/<name>/disconnect` | `ops.services.disconnect` | `{yes: true}` | `{name, connected, used_by, warning}` | 400 |
| POST | `/api/projects` | `ops.projects.new` (in a background thread) | create form | `{job}` | 400, 409 |
| GET | `/api/import/candidates` | `ops.projects.import_candidates` | | list of `{name, path, repo \| null, removed_on \| null, kind: removed\|folder}`; removed projects first | |
| GET | `/api/folders?path=` | `ops.projects.list_folders` | | `{path, root, parent \| null, folders: [{name, path}]}`; sub-folders only, never hidden ones or symlinks leaving the projects folder; empty path = the projects folder | 400 (outside the projects folder), 404 |
| POST | `/api/import` | `ops.projects.import_` | `{target}` (a name or a path directly under the projects folder) | `{name, path, repo, was_removed, added: [files added]}`; also takes it off the removed list and adds the trust entry; starts no service | 400, 404, 409 |
| POST | `/api/chat/<name>/open` | `ops.chat.open_chat` | | `{state, web_url, app_url, bridge_session_id, message}` | 404, 503 |
| POST | `/api/chat/<name>/sleep` | `ops.chat.sleep_chat` | | `{state, changed, message}` | 404 |
| POST | `/api/chat/<name>/off` | `ops.chat.off_chat` | `{confirm: true}` | `{state, changed, message}` | 400, 404 |
| POST | `/api/projects/<name>/remove` | `ops.projects.remove` | `{confirm: true}` | `{name, path, repo, removed_on, kept}`; undoes the trust entry, records it in `global.toml` `[[removed_projects]]`; deletes nothing; refuses `phoenix9` and `home` | 400, 404, 409 |
| POST | `/api/projects/<name>/delete` | `ops.projects.delete` | `{confirm: "<name>"}` | `{name, backup, steps: [{step, ok, words, kept?}], not_done: [{what, how}], still_live}`; writes the safety copy first, then deletes everything; the GitHub repo only when it is the project's own (`kept: true` with the reason otherwise; architecture 9.5); only as `dashboard`; refuses `phoenix9`, `home` (also by real name), a linked folder, active builds or delegate sessions, a working chat, and while another change holds the project lock | 400 (wrong confirm), 404, 409 (refused) |
| POST | `/api/projects/<name>/delete-repo` | `ops.projects.delete_repo` | `{}` | same shape; retries only the GitHub repo delete, reading the repo and its `repo_delete` verdict from the newest safety copy's manifest; refused when the folder exists again or another project uses the repo | 404, 409 |
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
| POST | `/api/runs/<project>/<run_id>/discard` | `ops.runs.discard` (`phoenix run discard <run> --yes [--force]`) | `{"confirm": true, "force"?: bool}` | `{run_id, status, discarded: true, notes}`; deletes the worktree, local branch and pushed GitHub branch of a failed or stopped run. Without `force: true` it is refused when that would lose work: an open merge request (merge-request.txt whose `gh pr view` state is not MERGED/CLOSED; no answer counts as open) or commits on the run's branch (local, else pushed) that main doesn't have | 400 (not failed or stopped, no confirm, or `force` not a bool), 404, 409 (already discarded; or would lose work: `{ok: false, message, needs_force: true, would_lose: [plain lines]}`) |
| GET | `/api/gates/<gate_id>/review` | `ops.gates.review` | | merge gates only: `{gate, run, project, title, why, answered, summary, tasks{passed,total,retried[]}, full_suite{status,note}, safety{flag,files}, files[{path,added,removed,binary,safety,diff}], added, removed, merge_request}`; diff from the run's own branch, else its patch files, else `gh pr diff`; scrubbed. CLI `phoenix gate review <id>` | 400, 404 |
| POST | `/api/gates/<gate_id>/answer` | `ops.gates.answer` | `{action, note}` | `{gate, action, note, who, at}` | 400, 404, 409 |

## Shapes

**Project row** (`ops.projects.rows`): every field of `phoenix9/project.py:info()` unchanged:
`name`, `description`, `path`, `repo` (string, `""` when none; may be a URL), `repo_owner`, `repo_name`,
`profile`, `services` (list), `size` (int bytes or null),
`vscode {url, reason}` (`url` null with a reason when the VS Code address is not set or `/srv/projects/<name>` does not exist), `vscode_url` (same as `vscode.url`), `last_used`, `last_used_at` (the newest of Phoenix's and proj's used marks and the last change of any of the project's runs),
`harness` (the harness column in words, from `status.project_state`: "idle" | "queued" | "running task N of M" |
"running" | "paused (usage limit)" | "needs you"), `has_phoenix_toml`;
plus the project's state, worked out ONCE by `phoenix9/status.py` `project_state` (every API route, CLI
command and dashboard display reads these fields; nothing else works them out again):
- `repo_url`: `https://github.com/<owner>/<name>` when `repo_owner` is set, else null.
- `needs_you`: number of open questions of the project; `questions`: their gate ids. A question is open only
  when it has no answer file, its run is not done/failed/stopped, and the run waits on it (`gates.is_open`).
- `run`: the current build `{run_id, status, task, tasks, carrying_on, why, now, worker}`, else null. It is the run
  with an open question, else the newest running, paused-limit, waiting (carrying on) or queued run.
  `status` is as Alex should see it (a waiting run whose questions are all answered reads `running` with
  `carrying_on: true`); `task` = `current.task` (while running: the first task not passed yet);
  `why` = why it is the current build; `now` = the "Now: ..." line of the Current build card.
- `last_build_failed`: true when the newest finished run (done, failed or stopped) failed.
- `activity`: `need` (an open question), else `fail` (paused at a limit), else `run` (any current build),
  else `fail` (`last_build_failed`), else `idle`.
- `worker`: `"alive"`, or `"not responding"` when the current build says running and the runner's heartbeat
  (`HOME/runner/heartbeat.json`) is missing or over 120 s old; the run view carries the same `worker`.
- `status_line`: the sidebar line ("1 question waiting", "Building, task 2 of 4", "Build queued", "Paused at a
  limit", "Last build failed", "Idle, used 3h ago"); `run_text`: the Projects page words ("Running task 2 of 4",
  "Queued", "Paused (usage limit)", "Idle").

`vscode_url` is the `vscode_url` global setting + `/?folder=<PHOENIX_PROJECTS>/<name>`; null when that setting is empty
(`vscode.reason` = "Set the VS Code address in Global settings.") or the folder is missing.

**Info** (`/api/info`): `version` (`phoenix9.__version__`), `label` (what the header shows: the install tag, else `v` + major.minor, e.g. `v9.1`), `update {supported, installed, newest,
available, can_install, reason, endpoints {install, rollback}}`, `github {connected, accounts}`, `services {supported}` (true),
`dashboard_url`, `vscode_url` (the dashboard address settings; `vscode_url` `""` = not set).

**Build** (`ops.runs.builds`): the run summary `{run_id, project, status, created, updated, current,
tasks_total, tasks_passed, usage}` plus `title`, `preset`, `started`, `finished` (ISO or `""`),
`duration` (plain words or `""`), `cost` (like `"$0.42"`), `tasks_failed`, `discarded` (true once the run's work was discarded).

**Run detail** (`ops.runs.detail`): the run's state.json fields, `gates` (open), `recent_events`, plus
`plan` (the plan.json shape: `groups`, `sources`, `off`, `steps`), `plan_frozen` (false when the run has
not started and `plan` is a preview from its overrides), `title`, `preset`, `max_tries`, `branch` (`phoenix/<run-id>` while that branch exists in the project's code/, else null: a stopped or discarded run has none),
`image {tag, id}` (the exact step image, once the run has started), `discarded` (and `discarded_at`, `discarded_by`) after `phoenix run discard`.

**Global view** (`ops.app.global_view`): `values` (non-secret contents of `HOME/config/global.toml`),
`addresses {dashboard_url, allowed_origins, vscode_url}` (defaults filled in),
`github {connected, accounts}`, `default_models {<ai step>: {model, fallback_models}}`,
`telegram {connected}`, `supported {services, update, secrets}` (false for parts not built yet).

**Settings** (`ops.settings.show`): `values` nested with every key filled; `source` maps a flat dotted key
to `"library"`, `"profile:<p>"`, `"preset:<p>"`, `"project"` or `"run"`.

**Create form** (`POST /api/projects`): `{name, description, source: {kind: "empty"|"repo"|"template"|"code",
repo?, template?, path?}, profile, new_repo: {on, owner}, services: [], keys: [{name, value, secret}]}`.
The reply is `{job}` at once; ops runs in the background (one create at a time, else 409). Key values go
straight to the keys store (`opts["keys"]`), never to a file.

**Job** (`GET /api/jobs/<id>`, kept 1 hour): `{id, kind: "create" \| "deploy" \| "images" \| "restart", project, status: "running"|"done"|"failed",
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

## Agent items

Items come from the agent's transcript (`phoenix9/transcript.py`); each has `type` and `line` (its transcript line
number). Types: `user` `{text, origin: panel|app|peer:<name>, at}`, `agent` `{markdown, at}`,
`thinking` `{duration_s, at}`, `action` (a tool call: its title, `status`, and an excerpt of the result),
`queued` `{text, pending, at}` (`pending` turns false when the queue-operation dequeue/remove for it arrives),
`session` `{session_id}` (a divider when the session id changes inside a transcript) and `notice` (system lines;
hook summaries and turn timings are left out). An `action` has `{id (the tool id), tool, title, input_summary,
status: running|ok|error, excerpt?, done_line?}`; `done_line` is the transcript line of its result. A user line
made of text blocks is a `user` item (an image shows as `[image]`).
`/api/agent/messages` wraps them as `{items, unknown, last_line, session_id}`.

## Agent stream frames

`GET /api/agent/stream` sends server-sent events; every `id` is `<session id>:<transcript line>`.

- `event: item`, data = one Agent item (above); id = `<session>:<item line>`.
- `event: update`, data = `{type: "update", id, line, status, excerpt}`: an action already sent (usually while
  `running`) has finished; `id` is the action's tool id (the same `id` as its item), `line` its item's line;
  the SSE id = `<session>:<line of the result>`. A stream resumed from line N also gets updates for actions at or
  before N that finished after N. (The web panel uses these from build 2.)
- `event: session`, data = `{session_id}`: the agent's session changed; items from line 1 of the new transcript
  follow. Also sent first when a `Last-Event-ID` names another session (or no session).
- Where it starts: `?after=<n>` = after line n of the current session; else a `Last-Event-ID` of
  `<session>:<n>` is honoured only when that session is the current one (otherwise: a session frame, then from
  line 1); else at the end. Only new lines are parsed on each tick (the parser keeps its state). Same tail and
  ping timing as `/api/events`.

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

`GET /api/events?project=` is a server-sent stream (the peer and Access checks as every route; no header/origin check): it starts after the `Last-Event-ID` line,
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
