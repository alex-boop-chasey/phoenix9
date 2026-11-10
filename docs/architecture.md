# Phoenix 9 build: shared contracts (2026-11-01)

Every step sheet in phases 1-4 builds against this file. It fixes names, folders and file formats so
steps written separately fit together. It is copied into the code repo as `docs/architecture.md` before
phase 1 and is the code's reference from then on (steps may extend it, never contradict it; a step that
must change a contract says so in its sheet and updates `docs/architecture.md` in the same step).

Specs this implements: notes/specs/2026-11-01-*.md (harness, project-setup, updates, services-and-keys,
control-and-workflows, dashboard, deployment). Where a sheet and a spec disagree, the spec wins unless
this file records a deliberate simplification (section 12).

## 1. Language, tools, tests

- Python: system `python3` (3.14 on the server; code must run on 3.12+). **Standard library only.**
  pytest is the only dev dependency and is already installed system-wide for root and the grunt user
  (and in the step image, pinned in image/versions.env). `pyproject.toml` declares no dependencies at
  all (`dependencies = []`, no optional ones), so the Lockfile step asks phoenix9 for no uv/poetry
  lockfile; tests/test_self_project.py checks this.
- Front end (phase 3 on): `web/`, React + TypeScript + Vite + Tailwind + shadcn/ui, Vitest, Playwright.
  Node 24, pnpm 12 (corepack). Versions pinned in `web/package.json` + `pnpm-lock.yaml`. The
  `@playwright/test` version must equal the browser build installed in `/opt/pw-browsers`
  (`PLAYWRIGHT_BROWSERS_PATH`). check.sh installs packages only when `node_modules` is missing, so a
  step that adds a package runs `pnpm -C web install` itself.
- One check command for every step of every phase: `./check.sh` (repo root). It runs
  `python3 -m pytest -q` and, when `web/package.json` exists, `pnpm -C web install --frozen-lockfile`
  (only if `web/node_modules` is missing) then `pnpm -C web test` (Vitest, no browser) and
  `pnpm -C web build`. Playwright is **not** in check.sh (needs a browser); it has its own
  `./check-browser.sh` run by the phase 3 sheets that need it and by the chat between phases.
  check-browser.sh seeds a demo HOME, starts `tests/demo_server.py` (fake adapters) and runs Playwright at phone and
  desktop widths; it needs the shared browser at `/opt/pw-browsers`.
- Tests never touch the real server: no real Docker, Claude, GitHub, systemd, journalctl, network or
  /srv/projects. Everything external goes through an **adapter** with a fake in `tests/fakes/`
  (section 9). Tests set `PHOENIX_HOME` and `PHOENIX_PROJECTS` to temp folders.

## 2. Repo layout (code/ = github alex-boop-chasey/phoenix9)

```
check.sh, check-browser.sh     the check commands (never weaken them)
bin/phoenix                    wrapper: exec python3 -m phoenix9 "$@" (PYTHONPATH = repo root)
pyproject.toml                 name phoenix9, no runtime deps, pytest testpaths = ["tests"]
docs/architecture.md           this file
phoenix9/                      the Python package
  __main__.py                  CLI entry (argparse); one sub-module per command group in phoenix9/cli/
  cli/                         one module per command group (thin: parse args, call ops, print): project.py
                               (also `project keys` and `project services`) run.py gate.py settings.py library.py
                               (steps, profiles, presets) runner.py api.py output.py, and from phase 4 services.py
                               keys.py update.py deploy.py (also `deployers`) images.py doctor.py, and `repair.py` (`phoenix repair
                               check|report|apply|undo|resume`, section 8.4; code in `phoenix9/repair/`)
  ops/                         the ONE backend layer. CLI and API both call these functions and nothing
                               else. Every function returns plain dicts/lists (JSON-able). Modules:
                               common runs gates settings library projects keys (phases 1-2), logs app github (phase 3),
                               services update deploy doctor images (phase 4; global settings live in app.py and
                               settings.py, there is no global_ module). Errors: OpsError.
  paths.py                     where things live (section 3)
  tomlw.py                     small TOML writer (stdlib has no writer); round-trips what we use
  atomic.py                    write_json/write_text atomically (tmp file + os.replace), read_json
  library.py                   loads the plug-in libraries (section 4)
  settings.py                  phoenix.toml schema, layering, validation, explain (section 5)
  resolve.py                   needs/produces/fallback resolver (section 4.3)
  spec.py                      markdown spec -> spec.json (section 6)
  runs.py                      run folders, run ids, queue (section 7)
  state.py                     state.json read/update
  events.py                    events.jsonl append/read/tail (section 8)
  gates.py                     gate files and answers (section 8)
  status.py                    what a project is doing now, worked out once (section 8, "One truth")
  runend.py                    how a run ends: run lock, stop request, end_run (section 7)
  heartbeat.py                 the runner service's heartbeat (section 7)
  runner.py                    the step runner (phase 1 = run-level + simple task loop; phase 2 = full)
  failmodes.py                 retry / escalation / on_failure handling (section 7)
  aistep.py                    prompt rendering and helpers shared by the ai steps
  checklock.py reports.py      locked task checks (fingerprints); test report readers + verdict fallback
  checklint.py                 self-contained checks: env read but never set; red run that is a setup crash
  summary.py                   run summary facts -> summary.md / summary.html (assets/summary.html)
  chat.py                      the Phoenix agent's restart and each project's chat unit (section 8)
  templates.py images.py       templates menu loader; profile Dockerfile checks
  stepctx.py                   StepContext and StepResult (section 4.4)
  claude.py docker.py git.py watch.py   ports of V8, adapters (section 9)
  scrub.py                     secret redaction for every log line written
  project.py                   phoenix project (proj folded in) (phase 2)
  project_delete.py            delete a project entirely: plan, safety copy, delete steps (safety file)
  keys.py                      per-project keys (phase 2; global secrets store phase 4)
  services.py                  services library loader (phase 2); project_services.py: a project's set
  proxy.py                     key proxy (phase 4)
  assets/                      static files the package ships (summary.html)
  updater.py                   install / roll back a release tag, with recovery (phase 4, section 15)
  hold.py                      the update hold: runs stop at a task boundary; harness_busy() (phase 4)
  deploy.py                    deployers runner (phase 4)
  projectchat.py               project chat: .phoenix/chat.md and the five chat states (Project chats)
  ops/chat.py, cli/chatcmd.py  chat open_chat / sleep_chat / off_chat / catch_up and `phoenix chat ...`
  doctor.py                    the `phoenix doctor` checks (phase 4; section 15); ops/doctor.py runs them
                               (full mode also has five agent lines: agent-unit, agent-session, agent-socket, agent-transcript, agent-folder,
                               and `access`, the optional Cloudflare Access lock; a missing or empty transcript is a problem)
  access.py                    who may use the API: allowed peer uids and the optional Cloudflare Access lock (section 8.5)
  agentlink.py transcript.py   the Phoenix agent link: find the session, parse its transcript (section 8.6)
  agentnext.py                 adapter: the client for the new agent's service (section 8.7; fake in tests/fakes)
  agentaccess.py               the caller who `agent`: its routes, its one settings key (section 8.7)
  images (ops/images.py)       `phoenix images build`: build the profile images, label `phoenix9.commit`
  stepproxy.py                 starts the key proxies a step's `proxy` key asks for (section 14)
  api/server.py                phoenix-api: JSON API + SSE + static web/dist (phase 3)
steps/<name>/                  step library: step.toml + prompt.md (ai) and/or run.py (script)
steps/_things.toml             every "thing" a step can need/produce, with its fallback
presets/<name>.toml            simple, quick, full (custom = no file; it is "start from a preset")
profiles/<name>/profile.toml   web, mobile, desktop, python-script, research, platform (+ image/Dockerfile)
services/<name>/service.toml   expected project keys + hosts (phase 2); recipes, proxy rules (phase 4)
deployers/<name>/deployer.toml deployers library, section 4.7 (+ deploy.py)
templates/<name>/template.toml project templates menu (phase 2)
image/                         base step image files ported from V8 (init-firewall.sh, entry.sh, ...)
deploy/                        phoenix-api.service, phoenix-runner.service, phoenix9-update.service, install.sh,
                               update.sh, self-project.toml (section 15); README.md for the server owner;
                               claude-rc-chat@.service (template unit, one chat per project)
                               Service env: all three units set `Environment=HOME=/root` (they have no `User=`, so
                               systemd would set no HOME; git then cannot read /root/.gitconfig, whose credential
                               helper is `gh auth git-credential`, and gh cannot find its login), plus
                               PHOENIX_HOME, PHOENIX_INSTALL (and PYTHONUNBUFFERED for api/runner)
web/                           React app (phase 3)
                               src/pages, src/features/<area>, src/components/ui (shadcn), src/lib (api client, types, theme), e2e/ (Playwright)
agentkit/                      the new agent's core and site packs, its own package, venv and lock file (section 8.7)
tests/                         pytest; tests/fakes/__init__.py holds every fake adapter; tests/helpers/ shared test helpers
CLI groups (`phoenix <group> --help`; each writes a `command` event when it changes something):
  run gate settings steps profiles presets project doctor api   phases 1-3
  services list|connect|test|disconnect|recipes   account services and their keys (section 4.6)
  keys audit                                  which keys exist, where used, problems (never a value)
  models list|set                             Phoenix's default models per AI step (global.toml [models])
  update status|install|rollback|log|release  the updater (section 15); install and rollback only queue
  deploy now|status, deployers list           deployers (section 4.7); `deploy now` needs --yes
  images build                                build the step images, label `phoenix9.commit`
  project check-files [NAME | --all]          add missing memory files (CLAUDE.md, notes/*); never overwrites, no phoenix.toml
  doctor [--quick|--for-update]               the checks in section 15
(reference/ held read-only copies of V8, proj and the project-selector for porting; it was removed at
 the end of phase 4. `# ported from reference/...` comments remain as history.)
```

## 3. Where things live at runtime (`phoenix9/paths.py`)

| Name | Default | Env override | Holds |
| --- | --- | --- | --- |
| HOME | `/var/lib/phoenix9` | `PHOENIX_HOME` | everything below |
| config | HOME/config | | `global.toml` (non-secret global settings; `proxy_ports = "47100-47199"` (key proxy port range, section 14); `[update]` table: `project = "phoenix9"`, `repo = "alex-boop-chasey/phoenix9"`, `tag_prefix = "v9."`, defaults when absent; read by `settings.read_global()`; `[dashboard]` table:
`dashboard_url`, `allowed_origins`, `vscode_url` (section 5.5); `[access]` table: `peer_uids` (uids the API answers, default `[0]`), `team_domain` + `aud` (optional Cloudflare Access lock; section 8.5); `[[removed_projects]]` rows `name`, `path`, `repo`, `removed_on` for projects taken off Phoenix's list by `phoenix project remove`, section 3 of `docs/design/phase-4-5-project-list.md`), `services.toml` (which account services are connected: names only, never values), `api.env` (`PHOENIX_API_PORT=<port>`, written once by `install.sh`, read by the API unit and by doctor, default
8095; `PHOENIX_API_ORIGINS=<origin>,<origin>`, written only from the `allowed_origins` setting, section 5.5), `doctor.json` (advisor availability, written by the doctor's `advisor` check, section 15) |
| secrets | HOME/secrets (0700) | | `<name>.env` files, 0600: `claude.env`, `github.env`, `telegram.env`, `service-<name>.env` |
| keys | HOME/keys (0700) | | per-project keys `<project>.toml`, 0600 (section 10) |
| runs | HOME/runs/<project>/<run-id>/ | | run folders (section 7) |
| work | HOME/work/<project>/<run-id>/ | | the run's git worktree of the project's code/ on branch `phoenix/<run-id>` (removed, with its branch, when the run is stopped; after a merge Phoenix made itself the branch is deleted too, see below) |
| edits | HOME/edits/<id>/ and <id>.json | | quick edits (`phoenix9/edits.py`): the worktree of the project's code/ on branch `edit/<id>` (id = `yyyymmdd-slug`), and its record `{id, project, title, branch, folder, started, who, status: open|stalled|finished|abandoned, last_activity}`; one open edit per project, none while a build runs on it |
| plans | HOME/plans/<id>.json and <id>/ | | planning sessions (`phoenix9/plans.py`, `plansession.py`): record `{id, project, brief, model, started, who, status: queued|running|waiting|done|failed|abandoned, job, session_id, spec, open_questions, report, usage, budget_usd, last_activity}`; one queued or running per project; the folder holds `prompt.md`, `session-prompt.md`, `out/` (the container's /out), `claude/` (its session files), `session.jsonl` (stream-json, scrubbed); the session's copy of the repo is HOME/work/plan-<id>/code (removed after each job) |
| logs | HOME/logs | | `commands.jsonl` (who ran what), `updater.log`, `api.log` |
| cache | HOME/cache | | recomputable data, e.g. `sizes.json` (project folder sizes, refreshed in the background) |
| events | HOME/events.jsonl | | global event stream (section 8) |
| runner | HOME/runner | | `heartbeat.json` `{at, pid}` (the runner service is alive; section 7) |
| projects | `/srv/projects` | `PHOENIX_PROJECTS` | one folder per project |
| install | `/opt/phoenix9` | `PHOENIX_INSTALL` | the installed copy (updater only) |
| install neighbours | `<install>-next`, `-prev`, `-failed` | | the candidate being tested; the copy before the last swap (rollback point); a copy that failed its health check (kept for inspection) |
| update | HOME/update | | `request.json` `{action, tag, who, at}` (queued by `updater.request`), `status.json` (below), `lock` (flock while an update runs), `hold` `{why, at}` (runs stop at their next task boundary; counts only while `lock` is held) |
| library | repo root of the running copy | `PHOENIX_LIBRARY` | steps/ presets/ profiles/ services/ deployers/ templates/ |

`HOME/update/status.json`: `{last: {action, tag, result, reason, at, who}, newest, checked,
waiting: "waiting: <reason>" (only while waiting for the harness), job: {kind, tag, who, from: {tag,
commit}, to: {tag, commit}, phase, reverting, started, at}}` (`job` only while an update is under
way; section 15). Written only while holding `HOME/update/lock`. Also `HOME/logs/updater.log`
(timestamped, scrubbed lines) and `HOME/logs/update-<tag>-checks.txt` (test, web build and image
build output of one install).

Per project (`/srv/projects/<name>/`): `CLAUDE.md`, `notes/`, `code/` (git), `phoenix.toml`
(settings, no secrets), `.phoenix/project.json` (facts Phoenix records: created, source, repo,
services set up: `services_set_up` is a list of `{name, at, run, run_name}`; older
files may hold plain name strings), `.phoenix/deploys.jsonl` (one line per deploy or preview attempt;
fields in section 4.7). Older files may still hold `chat_session_url`, `environment_id` and `chat_env_*` from the
removed per-project chat; nothing reads them.

## 4. The plug-in libraries

### 4.1 Step folder: `steps/<name>/step.toml`

```toml
name = "builder"                 # = folder name
title = "Builder"
description = "Writes the code for one task."
kind = "ai"                      # script | ai | gate
level = "task"                   # run | task
phase = ""                       # run-level only: "start" | "finish"
order = 30                       # sort key inside (level, phase)
needs = ["task", "worktree", "failures"]
produces = ["diff"]
safety = false
default = "always"               # "always" (cannot be switched off) | "on" | "off"
only_with = []                   # step names that must be on for this one to be on (red-check: ["check-writer"])
proxy = []                       # service names whose key proxy runs for this step (e.g. ["supabase"]), or
                                 # "@project" = every connected store-and-wire service in the project's
                                 # `services` (unconnected ones are left out and logged). An unknown name is a
                                 # library problem. Script steps get the proxy on 127.0.0.1; ai and check
                                 # containers on the Docker bridge gateway, with env PHOENIX_PROXY_<SERVICE> and
                                 # PHOENIX_PROXY_TOKEN_<SERVICE> and the firewall opened for that IP:port only
                                 # (file mounted at /etc/hands/allowed-proxy). Deploys start their own proxy.

[settings]                       # the step's own options and their defaults (validated by type)
once = false                     # example: a task step that runs until it has passed once

[ai]                             # ai steps only; full block in section 5.3
model = "claude-sonnet-5-5"
```
- `kind = "script"`: the folder has `run.py` with `def run(ctx: StepContext) -> StepResult`.
- `kind = "ai"`: the folder has `prompt.md` (the instructions, with `{{task}}`, `{{failures}}`,
  `{{checks}}`, `{{spec_title}}` placeholders) and may have `run.py` with optional
  `before(ctx) -> dict` (extra placeholder values) and `after(ctx, session) -> StepResult` (judge the
  session's outcome by looking at files only, never by trusting what the session said).
- `kind = "gate"`: no code needed; the runner opens a gate (section 8) and waits.
- Two `[settings]` keys the runner itself reads (any step may set them; the runner knows no step by
  name): `once = true` (task step) runs on every attempt until all the task's once-steps have passed
  (in earlier attempts), then never again for that task; a failed once-step makes every once-step run
  again (Red check refusing the checks makes Check-writer write them again); after the once-steps the worktree's commit is the task's `attempt_base`.
  `after_stop = true` (finish step) still runs when Alex answers `stop` (Notify sets it); every other
  finish step is left out of a stopped run.
- Optional step hook `on_approved(ctx, produces) -> dict | None`: when Alex answers `approve` on a gate
  the step opened, the runner calls it before the step is recorded as passed. The returned dict is added
  to the step's `run.step.finished` event data (Planner returns `{"plan_adopted": true}`). A crash in it
  fails the run with a reason.
- Planner is a run-start step at `order = 45`, after Branch (40): its session needs the run's worktree
  (read-only) as context. Spec check (20) accepts a brief (title only, tasks optional, `"brief": true`
  in spec.json) when Planner is on. The Planner writes the plan to `plan.md` in the run folder (never
  `plan.json`, which is the resolver's step plan) and opens a `plan` gate; approve adopts its tasks
  (`runs.adopt_plan`), skip keeps the brief as written (a brief with no tasks then fails the run).
- Service setup is a run-start step at `order = 50`, after Branch (40) and Planner (45), `proxy =
  ["@project"]`, on by default. Per chosen service (phoenix.toml `services`): unknown service fails;
  project keys without a value open a `human-task` gate (actions `done`, `defer`, `skip`, `stop`; `defer` = "Build without it for now": the service is not wired, `services.md` tells the Builder to read the values from the environment and keep the site working without them, `<run>/deferred-services.json` and project.json `services_deferred` record it, and the summary and Overview show "Waiting for keys: X" until the keys are saved, a later run wires it fully; `done` calls
  the step again and it re-checks, still missing = fail; `skip` continues without them); hosts missing
  from the project's `[domains] allow` are added (and to this run's frozen settings); the service's
  `recipe.py` `wire(ctx, service, proxy)` runs once (recorded in `.phoenix/project.json`
  `services_set_up`). It writes `<run>/services.md` (titles, env var names, install notes; never
  values) and produces `service-notes`.
- Library loading imports `run.py` with `importlib.util.spec_from_file_location`; a broken folder is
  reported by `phoenix steps list` and skipped, it never crashes the runner.

### 4.2 Things: `steps/_things.toml`

```toml
[spec]  # always available, from Pick-up
provided = "run"
[task]  # the current task (task-level only)
provided = "task"
[worktree]  # from Branch
provided = "run"
[failures]  # earlier attempts' failure reasons (may be empty)
provided = "task"
[plan]
fallback = "spec-as-written"
[checks]
fallback = "spec-done-when"
[baseline]  # main's test result before the run (Branch)
fallback = "not-run"
[diff]  # no fallback: something must produce it (Builder)
fallback = ""
[exit-codes]  # Acceptance's results (always on)
fallback = ""
[commit]  # the task's commit sha (Commit)
fallback = ""
[merged]  # merge result (Merge)
fallback = "not-merged"
[test-report]
fallback = "exit-codes-only"
[verdict]
fallback = "pass-if-checks-passed"
[service-notes]  # services.md from Service setup (the text "This project uses no third-party services." when off)
fallback = "no-services"
```
One key per line under each `[name]` (valid TOML). `provided` things never need a producer. A thing with an empty fallback must be produced by an
enabled earlier step.

### 4.3 The resolver (`phoenix9/resolve.py`)

`resolve(library, enabled: dict[str,bool]) -> Plan` returns the ordered effective step list
(run-start, task, run-finish), and for every step and every need, where it comes from
(`step:<name>` | `provided` | `fallback:<name>`). Rules (harness spec section 3):
1. `default = "always"` steps are on regardless of `enabled`; switching one off is an error.
2. A step with `only_with` is forced off (with a reason) when any listed step is off.
3. A need is met by the latest *earlier* enabled producer (run-start before task before run-finish;
   inside a group by `order`); else `provided`; else the thing's fallback; else the step cannot be on:
   `ResolveError` naming the step, the need and why.
4. Unknown step names in `enabled` are errors. Order ties are errors at library load.
`Plan.explain()` gives the plain-English list `phoenix settings explain` prints.

### 4.4 StepContext and StepResult (`phoenix9/stepctx.py`)

```python
@dataclass
class StepResult:
    status: str                  # "pass" | "fail" | "skip" | "gate"
    reasons: list[str] = ()      # plain-English failure reasons fed to the next attempt
    produces: dict = {}          # thing name -> value (a path inside the run folder, or small JSON)
    gate: dict | None = None     # when status == "gate": the gate to open (section 8)
```
StepContext carries: `project` (name, paths, settings), `run` (id, folder, spec), `step` (its effective
settings incl. ai block), `task` (or None at run level), `attempt` (int), `worktree` (Path or None),
`things` (dict of everything produced so far, after fallbacks; `failures` = every earlier failure
reason of this task, including notes sent with `back` or `acknowledged`), `adapters` (docker, claude,
git, host, clock, notify, chat; real or fake), `emit(type, **data)` (writes an event), `log(text)`
(scrubbed log line into the run folder), `answer` (None, or the gate answer `{action, note, who, at}`
when Alex sent this step back with `back` and the runner calls it again).

### 4.5 Profile folder: `profiles/<name>/profile.toml`

`title`, `image` (step image tag), `allowed_domains` (list), `diff_allow_extra` (list),
`lockfiles` (list of accepted lockfile names; replaces the defaults of the Lockfile check finish step, which
fails a run whose root `package.json` / `Cargo.toml` / dependency-declaring `pyproject.toml` has no
committed lockfile),
`screenshots` (bool), `suggested_deployer`, and a `[test]` block:
- `cmd` (full suite command, = `{{suite_command}}`), `task_cmd` (optional, a single task's checks);
- `report`: one of `pytest-junit | vitest-json | playwright-json | exit-code`, or a list of them
  (e.g. `["vitest-json", "playwright-json"]`), and `report_path`;
- `checks_dir` (where locked task checks live in the repo: each run writes into its own folder,
  `<checks_dir>/<run-id>/task-<n>/` (`checklock.task_checks_dir`), so checks an earlier build merged
  into main never land in a later run's task folder; the builder is told `<checks_dir>/<run-id>/` is
  read-only), `check_files` (glob(s), space-separated, the
  check writer must use), `check_command` (runs given check files; `{files}` = space-joined paths) and
  `report_args` (appended so the report reader finds its file in `/out`).

Optional `[steps.<name>]` tables override step defaults (layer 2 in 5.1).
The profile's container image files live in `profiles/<name>/image/`.

A run needs a profile: `ops/runs.start` refuses (before creating anything) when the effective settings, including
per-run overrides, have none, and `Runner._setup` fails a run whose plan has an AI step and no profile, so an empty
image never reaches docker. The refusal (`settings.no_profile_message`) points at `phoenix settings set <name> profile <type>`.

Where the profile and template show up (the owner calls the profile "Type" and a template "Framework"): both are chosen only on the New project page (Type and Framework pickers). Afterwards the dashboard shows them read-only on the Overview's About card (`Type` = profile title, `Framework` = the template's title, or "None"). The Settings tab has no Type control; `phoenix settings set <project> profile <type>` and the edit API still accept a change. Projects with no type are left as they are.

### 4.6 Service folder: `services/<name>/service.toml`

```toml
name = "supabase"                 # = folder name
title = "Supabase"
description = "Postgres database, auth and file storage."
support = "store-and-wire"        # "store-and-wire" | "keys-only"
docs = "https://supabase.com/docs"
website = "https://supabase.com/dashboard/account/tokens"   # optional: where the key is made; shown as a "Website" link
account_keys = ["SUPABASE_ACCESS_TOKEN"]   # names stored in HOME/secrets/<secrets_file>
secrets_file = "service-supabase.env"      # default "service-<name>.env"; github: "github.env"
hosts = ["supabase.co"]           # added to a project's allowed domains (bare names, suffix match)

[[project_keys]]                  # rows pre-filled in the project keys form
name = "PUBLIC_SUPABASE_URL"     # the exact env var name the project code reads
secret = false                    # default true
public = true                     # default false: safe in browser code (never together with secret = true)
required = true                   # default true; false = optional, a project can build without it
help = "Project dashboard > Connect: the project URL."   # one line: where to find it in the provider dashboard

[proxy]                           # store-and-wire only: the account API, through the key proxy
upstream = "https://api.supabase.com"
auth_header = "Authorization"
auth_format = "Bearer {key}"
key = "SUPABASE_ACCESS_TOKEN"     # which account key the proxy adds (must be in account_keys)
extra_headers = {}
[[proxy.allow]]
method = "GET"
path = "/v1/projects"             # optional per-rule: upstream = "https://other.host"

[check]                           # how `phoenix services connect` tests a pasted key
method = "GET"
path = "/v1/projects"             # must match one proxy.allow rule
expect = [200]
fallback_path = "/accounts/{account_id}/tokens/verify"   # optional: tried when path gives no expected status;
                                  # {name} is filled from the service's saved account settings (must be an allowed call)

[[account_settings]]              # optional plain (non-secret) account settings, shown in Phoenix settings > Configure
name = "organisation"             # lower_case_with_underscores; saved in services.toml under [<service>.settings]
label = "Organisation"
kind = "text"                     # "text" (default) | "select" (then `options = [...]`, optional `default`)
placeholder = "my-organisation"   # optional; also optional `help`
```

Phoenix settings also lists **Claude** (`claude.env`, `CLAUDE_CODE_OAUTH_TOKEN`) and **Telegram**
(`telegram.env`, `TELEGRAM_BOT_TOKEN`, setting `chat_id`) as built-in rows (`ops/services.py BUILTIN`); they
have no library folder, proxy or `[check]`. Saved secrets are shown as their last four characters only.
`global.toml` may hold `[models.<step>]` (`model`, `fallback_models`): Phoenix's default models, applied
under presets, profiles and project settings (`settings.global_models`). The updater also appends one JSON
line per finished install or roll-back to `HOME/update/history.jsonl` (`at, action, tag, result, reason, who`).

Rules (checked by `phoenix9/services.py`; a broken folder is reported and skipped, never a crash):
name = folder name; `support` is one of the two values; `account_keys` match `^[A-Z][A-Z0-9_]*$`;
`[[project_keys]]` rows: `name` matches `^[A-Z][A-Z0-9_]*$`, `secret` (default true), `public` (default false, not with `secret`), `required` (default true), `help`. Names are final env var names: a browser-safe value carries the web profile's `PUBLIC_` prefix in its name (no per-profile prefixing; services are used by the web profile). `[proxy]` and `[check]` are required for store-and-wire and forbidden for keys-only; `proxy.key` is in
`account_keys`; `[proxy]` is checked by `proxy.spec_from_service` (so rules by `proxy.parse_rules`: no `//`;
a trailing `/` is allowed only as the whole last part, for APIs like Sentry's that need it, and then only matches a request with it); `hosts` are bare domain names (no scheme, port, path or `*`; subdomains match by
suffix, and each name must resolve on its own). Beside it: `install.md` (store-and-wire: plain
instructions for the Builder: package names per profile, where config goes, env var names, never values)
and an optional `recipe.py` (`def wire(ctx, service, proxy) -> dict`). Services with account API access
list no `hosts` for that API: account calls go only through the proxy (github, sentry have none).

### 4.7 Deployer folder: `deployers/<name>/deployer.toml` (+ `deploy.py`)

```toml
name = "vps-docker"
title = "This VPS (Docker)"
description = "..."
supported = true              # false = stub: "<title> is not yet supported"
proxy_service = ""            # service whose account key a deploy needs (github-release: "github")
preview = true                # can deploy a branch preview
for_profiles = ["web", "platform"]
required_settings = ["live_port"]   # [settings] keys a project must set (default value alone is not enough)
[settings]                    # defaults; a project overrides them in [deploy.settings]
live_port = 0
[health]
timeout_s = 60
tries = 5
```
`deploy.py` has `deploy(dctx) -> {target, url, version, details}` (raises `DeployError(reason)`),
`health(dctx, result) -> (bool, words)`, `rollback(dctx, result, previous) -> dict`, and optionally
`preview(dctx)` and `stop_preview(dctx, record)`. A deployer without `health` and `rollback` is refused
(except `none`, which needs no deploy.py). `phoenix9/deploy.py` runs them: starts the `proxy_service` proxy
on 127.0.0.1, gives the deployer a `DeployContext` (project, settings, source_dir, commit, run_id, adapters,
proxy `{url, token}`, a 0600 `env_file` of the project's keys, a scrubbing `log`), then runs `health` up to
`tries` times spaced `timeout_s / tries` on the clock adapter; unhealthy or failed deploys roll back to the
last good record. Every attempt is a line in `<project>/.phoenix/deploys.jsonl` (`at, deployer, commit,
version, url, ok, rolled_back, reason, who, run, kind: deploy|preview`), a `deploy.finished` event, a
changelog line and a notify message. Commands: `phoenix deploy now <project> --yes`,
`phoenix deploy status <project>`, `phoenix deployers list`. Profiles' `suggested_deployer` names a deployer.

## 5. Settings

### 5.1 Layering (lowest first)
library step defaults → profile (`profiles/<p>/profile.toml` `[steps.*]`) → preset (`presets/<p>.toml`)
→ project `phoenix.toml` → run overrides (the wizard's answers, frozen into the run folder as
`settings.json`). `settings.effective(project, run_overrides=None)` returns the merged dict plus, for
every value, which layer set it (for `explain`).

### 5.2 `phoenix.toml` (per project; unknown keys are errors)

When Phoenix creates a new GitHub repo (empty or non-GitHub template source), it writes `code/.github/dependabot.yml` before the first commit, so it is in the first push: one weekly entry (directory `/`, 5 open PRs) per ecosystem found in code/ (package.json → npm, Cargo.toml → cargo, pyproject.toml/requirements.txt → pip), else from the profile (web/mobile/platform → npm, desktop → npm+cargo, python-script → pip). Nothing is written when none is found, and existing repos and `--code` folders are never touched.

New projects get a `phoenix.toml` only when a profile is known (from `--profile` or the template), and then it holds just `profile = "<name>"`. With no profile there is no `phoenix.toml`; `.phoenix/project.json` records the profile as an empty string.

```toml
preset = "quick"              # simple | quick | full | custom
profile = "python-script"
merge = "auto"                # auto | ask
max_tries = 3                 # tries per task (harness spec 13); the one place this is set
on_failure = "pause"          # continue | pause | delegate
# budget_usd = 25             # spending cap in dollars; leave out for no cap (checked after every step)
services = []                 # e.g. ["supabase", "resend"]
safety_files = []             # paths flagged "changes safety code" on merge requests (updates spec 4)
home_chat_may_answer = []     # gate kinds the Home chat may answer itself; default none

[diff]
allow_extra = []              # widen the default allowlist (harness spec 8)
deny_extra = []

[domains]
allow = []                    # extra hosts for step containers

[steps.<name>]
on = true
# any key from that step's [settings] or [ai] block

[deploy]
with = "none"                 # deployer name
mode = "off"                  # on-merge | button | off
preview = false

[deploy.settings]             # keys the chosen deployer's [settings] declares, typed like its defaults
live_port = 8080              # unknown keys are an error; `required_settings` of the deployer must be set
```
`tomlw.py` writes it back with keys in this order and a one-line comment header.
For the project named in global.toml `[update] project` (phoenix9) `merge` must be `ask` and `[deploy] with`
must be `none` (`settings.self_project_problems`). `deploy/self-project.toml` is its phoenix.toml.
A merge of that project tags the merge commit as the next `v9.<n>` release (`phoenix9/release.py`).

### 5.2b Chat settings
`[chat]` in `global.toml` (`settings.chat_settings()`): `sleep_after_minutes` (default 120), `off_after_days` (3),
`start_wait_seconds` (60), `wrap_up_minutes` (3), `claude_home` (`/root/.claude`).

### 5.3 The ai block (any ai step; harness spec section 5)
`model`, `fallback_models` (list), `tools` (list, empty = Claude default), `tools_denied` (list),
`mcp_servers` (list of names from the registry), `claude_md` (`library` | `project` | `both`),
`skills` (list of skill folder names), `max_turns`, `timeout` (minutes), and
`[advisor]` `on`, `model`, `when` (list of `blocked` | `before-done` | `on-demand`), `instructions`.
The advisor is passed to the session as a mounted skill plus settings; Phoenix does not run it.
**Unverified:** that `/advisor` exists in headless `claude -p`; `phoenix doctor` reports whether it does
and the session is told to carry on without it when absent.

### 5.4 Changing settings from the command line
`phoenix settings set <project> key=value` (one key, typed from text; lists as a comma list, replacing the
whole list), `phoenix settings add <project> <list key> <item>` and `phoenix settings remove <project>
<list key> <item>` (one item in or out of a list key such as `safety_files`, `services`,
`domains.allow` or `steps.<name>.tools`; the change starts from the key's effective value, the item is
checked like any value of that key, adding an item that is already there or removing one that is not is
refused, and non-list keys are refused). Each writes phoenix.toml, a `settings.changed` event, the command
record and a changelog line (`settings.change_list`, `ops.settings.change_list`).

### 5.5 Dashboard addresses (`phoenix9/addresses.py`; Global settings > Dashboard addresses)
No address is hard-coded anywhere else. HOME/config/global.toml `[dashboard]`:
- `dashboard_url` (default `https://phoenix.rebirthwebdesign.com.au/`): where the dashboard lives
  (`/api/info` `dashboard_url`, for any link Phoenix builds to its own pages).
- `allowed_origins` (list; default = the dashboard URL's origin): the page origins whose writes the API takes.
  Values are reduced to origins exactly as a browser sends them in its Origin header (`scheme://host[:port]`:
  lower-case host, IPv6 kept in brackets, no port when it is the default `:443` for https or `:80` for http),
  so the guard's plain string compare matches. Host names may only hold letters, digits, dots and dashes (or be
  an IP address); quotes, `\`, `*`, `%`, spaces and the entries `null` / `*` are refused. The API reads `PHOENIX_API_ORIGINS` (how api.env hands
  the setting to the process) and falls back to the setting when it is unset; `/api/health` gives a digest of the origins
  the running API has (not the origins themselves), and the doctor's `origins` check compares it with the setting. A refused write says
  "Refused: this page was opened from <origin>, which Phoenix doesn't allow yet. Add it in Global settings >
  Dashboard addresses (or run `phoenix settings global set allowed_origins=...`)."
- `vscode_url` (default empty = not set): the VS Code base address; project links are
  `<vscode_url>/?folder=<projects>/<name>`. Not set = `vscode_url` null with the reason "Set the VS Code
  address in Global settings." (the dashboard hides its VS Code buttons and shows that as a tooltip; the CLI
  prints it).

Changing them: `phoenix settings global show`, `phoenix settings global set key=value [key=value ...]`
(allowed_origins as a comma list), `POST /api/global/addresses` (`ops.app.set_addresses`). Each checks the
values (http/https addresses only; at least one origin) and refuses a result that would lock the dashboard
out: the allowed origins must include the dashboard URL's origin and, for an API save, the Origin of the page
making the request (a plain message saying which address to add; the Dashboard addresses tab shows it under
the Save button). Then it writes global.toml, writes a `settings.changed` event
(project null) and the command record; when the allowed origins changed it rewrites the `PHOENIX_API_ORIGINS`
line of api.env (other lines kept) and asks systemd to restart phoenix-api (`systemctl restart --no-block`
through the host adapter, `ops.service.restart_unit`, so the API can restart itself after replying).
One-time migration (`addresses.migrate_once`, `phoenix settings global migrate`): when global.toml has no
`allowed_origins` yet it becomes the origins api.env already allows plus the dashboard URL's origin. It runs
when the API starts (`phoenix api serve`, which then uses the new list at once) and after every healthy install
(the updater runs the NEW copy's `bin/phoenix settings global migrate --json`; a failure is a log line). Once
set it does nothing.

## 6. Specs (`phoenix9/spec.py`, extends V8 plan.py)

Markdown for humans, JSON for Phoenix (harness spec open question 1, recommended answer taken):
```
# <title>
Project: <name>
Preset: quick                (optional; run override)

## About
free text

## Task 1: <title>
<goal text>
Depends on: none | 2, 3
For you: no | yes
Done when:
- `<shell command>`  (backticked = a check command run in the worktree; exit code is the gate)
- plain text bullet  (a human-readable condition, shown, not run)
```
`parse(text) -> dict` and `check(text) -> list[str]` (problems in plain English). Also accepts V8's
`## Step N` headings as tasks. Max 60 tasks. Spec check writes `spec.json` into the run folder.
`Preset:` is used as the run's preset override (`ops.runs.start` writes it into `overrides.json`) unless a
preset is given for the run (`phoenix run start --preset`, or the wizard's own choice).

## 7. Runs

- Run id: `YYYYMMDD-HHMMSS-<spec-slug>` (UTC). Branch: `phoenix/<run-id>`.
- Folder `HOME/runs/<project>/<run-id>/`:
  `spec.md` (copy, read-only), `spec.json`, `settings.json` (frozen effective settings), `plan.json`
  (resolver output), `state.json`, `events.jsonl`, `tasks/<n>/attempt-<k>/` (`prompt.md`, `claude/`
  (mounted as the container user's `~/.claude/projects`, so a session can be continued), `session.jsonl`, `diff.patch`, `checks.txt`, `result.json`), `gates/<gate-id>.json` and
  `gates/<gate-id>.answer.json`, `run.lock` (held by the runner while it walks the run), `stop-request.json`
  `{who, at}` (only until the runner acts on it), `pause-request.json` `{who, at}` (same, for Pause now), `logs/<step>.log`, `summary.md` and `summary.html`; also `plan.md`
  (Planner), `progress.md` (Commit), `merge-request.txt` / `merge-note.md` (Merge).
- **Task file** (`phoenix9/taskfile.py`): `tasks/<n>/task.md` is the one readable file of a task. Above the fixed
  line `## Fix notes` Phoenix writes a view from the real state (goal, status, tries, each failed attempt's
  reasons and last 10 scrubbed check-output lines, log paths); it is regenerated (`taskfile.refresh`, at each
  attempt start and end and when the task finishes) and never parsed back. Below the line people and the agent
  append notes (`phoenix run note <run> <task> "<text>"`, `POST /api/runs/<run>/note`, `ops.runs.note`: dated,
  with who recorded it, at most 2,000 characters; refused when empty, too long, for an unknown run or task, or
  for an ended run; event `run.note` carries no text). That section is the only part read back: all of it goes
  into the next attempt's prompt as "Notes from Alex / the Phoenix agent" (`{{fix_notes}}` in the builder and
  check-writer prompts), fenced with `aistep.fence` as information, never instructions.
- **Pause now / Resume** (`phoenix9/pause.py`, `ops.runs.pause` / `resume`): run and step statuses include `paused`.
  `phoenix run pause <run> --now --yes` writes `pause-request.json` and `docker stop`s (never removes) the running
  AI step's container; the runner, which holds the run, sees the stopped session, marks the step line `paused`
  (keeping `session_id`, read from the session log if the session never finished) and sets the run `paused`, leaving
  the worktree untouched. During a non-AI step the request waits for that step to end. A paused run frees the queue
  like `stopped` but keeps its worktree. `phoenix run resume <run>` sets `running` (or `queued` when another run is
  going); the same step line runs again in a fresh container with `--resume <session_id>` and the prompt's first line
  "You were paused mid-step. Check the files you were changing, then carry on."; it is not a new try. A missing session
  file or a failed `--resume` resets the worktree to the attempt's `attempt_base`, starts the step clean, and the step
  line's `resume_note` says so.
- `state.json`: `{run_id, project, status, created, updated, current: {group, task, step, attempt,
  gate}, tasks: {"1": {title, status, tries, failures: [..], depends_on: [..], escalations, flagged,
  gate, attempt_base, note, rerun}}, steps: [ {group, task, step, attempt, status, started,
  finished, note, gate, produces, reasons, answers, session_id, resume_note} ], usage: {cost_usd, sessions}, image: {tag, id}}`.
  `image` = the profile's step image tag and its exact id (`docker image inspect --format {{.Id}}` through
  the docker adapter's `image_id`; `""` when the image was missing), written once at the run's first drive
  (`runner._record_image`), so a later rebuild never changes what the run says it used. The Build tab shows
  the first 12 characters of the id in the run header.
  Run status: `queued | running | waiting | paused-limit | done | failed | stopped`.
  Task status: `pending | running | passed | failed | skipped | waiting`.
  Step line status: `pending | running | passed | failed | skipped | waiting`.
  Phase 2 fields (old files without them still load; code reads them with `.get`):
  - `current.gate`: the ONE gate the run waits on now. The service loop re-drives a waiting run only
    when this gate has an answer file (`gates.current_answer`). Opening a gate and recording who
    holds it (`current.gate` + task `gate` or step line `gate`) is one helper, `runner._open_gate`,
    with one state update. If a crash lands between the gate file and that update, the run is
    waiting with no `current.gate`: `drive()` and `check_waiting` then adopt the newest unanswered
    gate in `gates/` (`runner.adopt_gate`, re-attached to its task, or to its step's latest line).
    The service loop's `check_waiting` and the public `adopt_gate` take the run lock with wait=0 and
    skip the run when it is busy (being ended or walked); adoption only ever changes a run whose
    status is still `waiting`, checked inside the same locked state update.
  - task `tries` = the attempt being worked on (0 = not started). `escalations` = acknowledged
    escalations so far (max `failmodes.MAX_ESCALATIONS` = 2). `flagged` = why it failed (Build tab,
    summary). `gate` = the task's own gate (human-task or escalation). `attempt_base` = the commit
    each attempt starts from (a failed attempt is reset to it; an outside fix moves it).
    (Old files may carry a `delegate` field from before build 5; it is ignored.) `note` = why it was skipped ("depends on task 1, which failed", "skipped by cli").
    `rerun` = an escalation was acknowledged: the next attempt starts whatever `should_retry` says;
    starting it sets `tries = k+1, rerun = false` in one update.
  - step lines: task steps get one line per attempt (`attempt`). A step that returned a gate has
    status `waiting` plus `gate`, and keeps what it said (`produces`, `reasons`) so the answer can be
    acted on after a restart; `answers` = every answer it was called again with (back, or an action
    the runner does not know). `ctx.answer` = the latest answer plus `notes` = every back note in order.
  - `tasks/<n>/attempt-<k>/result.json` `{attempt, status, reasons, at}` is written when attempt k is
    over (passed or failed and reset). No result.json = the attempt is still going (a restart
    continues it from its first unfinished step). Early escalation compares these files. What comes
    after attempt k is decided at the top of the loop from these files: passed = task passed; failed
    and no `rerun` and `should_retry` false = `on_failure`; else attempt k+1. So a restart after a
    failed result.json never runs an extra attempt past `max_tries` (default 1 when unset).
  - `current.held` (phase 4): true while the run waits at a task boundary for an update
    (`runner._hold_point`, section 15); set false when the hold is released, and gone again when the
    next step starts (each step start rewrites `current`). Read with `.get`; a `held = true` left
    by a restart is set false at the next task boundary when no hold is asked for.
  - `once` steps (e.g. Check-writer, Red check) are skipped once all of them passed in earlier
    attempts; while any of them has not, they all run again (the failed attempt's checks commit is
    reset away, and the Check-writer prompt lists the earlier failures). attempt_base is taken before the first non-once step (fallback: HEAD at attempt start).
- Spending cap (`budget_usd`, frozen in the run's settings.json): at every step boundary the runner
  compares `usage.cost_usd` with the cap. When reached it opens a gate of kind `budget` ("Spending cap of
  $X reached at $Y", held by `current.gate` only) with actions `raise` (answer field `by` = dollars, added to
  the frozen cap) and `stop`. Usage-limit waits cost nothing, so they never count. `gates.may_answer` refuses
  every `chat:*` caller on budget gates: Alex alone raises or stops.
- The attempt loop (`phoenix9/runner.py` + `phoenix9/failmodes.py`, harness spec 13): a task runs
  attempts of its task steps. A failed attempt (a step `fail`, or a crash: "step <name> crashed: ...")
  adds its reasons to `failures` and is retried until `max_tries`, unless it was already escalated,
  a reason starts with `SPEC_PROBLEM` or `AUTH_ERROR`, or it failed for exactly the same reasons as
  the attempt before. Then `on_failure`: `continue` = task `failed` + flagged, dependents `skipped`;
  `pause` = escalation gate + one notify; `delegate` = the same gate (flag "handed to the Phoenix
  agent") plus one message to the agent (section 12). `acknowledged` = commit any outside fix,
  `attempt_base` = the worktree's HEAD (always, so a crash after the fix commit keeps the fix), one
  more attempt; if that fails, the mode once more, then `failed`. .env-style files found in the
  worktree at that point are moved to `tasks/<n>/outside-env/<path>` (never committed), with the
  failure line and notify "env file <path> was moved out of the worktree; keys belong in Phoenix
  secrets". A `For you: yes` task runs no
  steps: it is a `human-task` gate. A usage limit is not a try (the same attempt goes on afterwards).
  Run-level steps have no retries and no `on_failure`: a failed start step fails the run, a failed
  finish step makes it `failed` while the other finish steps still run; a run-level step that needs
  Alex returns a gate (for a failure: kind `escalation`). Deploy (finish, order 40) does exactly this
  when a deploy fails and rolls back: escalation gate, flag "deploy rolled back", actions `acknowledged`
  (the step stays failed, so the run ends `failed`; Notify still runs), `skip`, `stop`, plus one notify
  message. With `[deploy] mode = "button"` Deploy opens a `deploy` gate (`deploy | skip | stop`) and
  deploys when called again with the `deploy` answer. Preview (finish, order 25) never fails a run.
  Run end: `done` unless a task or a run-level
  step failed (`failed`) or Alex stopped it (`stopped`).
- **How a run ends (one end function, one stop path; `phoenix9/runend.py`).** `runend.end_run` is the only
  place a run becomes `done | failed | stopped`. Its FIRST state update does everything a reader looks at:
  unfinished tasks and `waiting | running | pending` step lines become `skipped`, `current.gate` is cleared
  and the final status is set (`error` = the reason for a failure); the run's open questions are closed
  (section 8) straight after. Only then does the slow work run: finish steps with `after_stop = true`
  (stop only; they see the final status and add their own step lines), the branch and worktree are
  discarded (stop only; a failed run keeps them for repair), `run.finished` is emitted (`who` when not
  phoenix) and the summary is refreshed. So the service loop can never see a half-ended run as waiting
  and re-adopt its gate. Apart from those after-stop step lines a run that already ended is never
  changed again. Every end goes through it: the runner's own finish and `stop` answers, `watch._fail`
  (three crashes in a row, a usage limit that never cleared) and `phoenix run stop` / the API stop.
  The **run lock** (`<run>/run.lock`) is held by `Runner.drive` for the whole walk. `ops.runs.stop`
  (CLI, API, dashboard) first checks the caller like answering an escalation question
  (`gates.may_answer`: a `chat:*` caller needs `home_chat_may_answer` to list `escalation`; `cli`
  and `dashboard` may), removes the run's containers, then: when it gets the run lock
  (the runner is not walking the run: queued, waiting, paused-limit, or between rounds) it calls the
  runner's own clean stop (`Runner.stop_now`) at once and replies `status: stopped`; when the lock is
  busy (the runner is walking it) it writes `<run>/stop-request.json` `{who, at}` and replies
  `status: "stop requested"`. The runner reads the request at its next boundary (section 7 "boundaries")
  and stops through the same function. `phoenix run stop` then waits up to 60 s for the run to show
  `stopped` and says so plainly if it has not.
- **Boundaries (the runner never revives an ended run).** Before every step (except the after-stop
  steps of a stop), before opening a gate, and before finishing, the runner re-reads the run
  (`runend.check`): a stop request -> clean stop; a status that is already ended -> the walk ends and
  nothing is written. `gates.open_gate` refuses a run that has ended and `end_run` never overwrites an
  ended status, so a stop that lands mid-walk can never be turned back into waiting, done or failed.
  The usage-limit pause (`watch.wait_out_limit`) moves a run to `paused-limit`, and later back to `running`,
  only through one locked state update (`watch._move_if_live`) that does nothing once the run has ended or has
  a stop request (and, for the resume, unless it is still `paused-limit`); a stop is then carried out.
- **Runner heartbeat** (`phoenix9/heartbeat.py`): `HOME/runner/heartbeat.json` `{at, pid}`, written at the
  start of every service loop round (`watch.watch_once`) and every 30 s by a side thread started in
  `watch.watch_forever` (a long step blocks the loop, so the loop alone would look dead). The heartbeat
  proves progress, not just a live process: the loop records its last progress time in memory
  (`heartbeat.mark_progress`: every round, every step start and end, every tick of a usage-limit wait or an
  update hold), and a step's container counts as progress for as long as it runs (`heartbeat.busy()`,
  held by `DockerRunner.run`, which has its own time limit). The side thread only writes the heartbeat
  while `heartbeat.making_progress()`: progress in the last 10 minutes (`PROGRESS_WINDOW_S` = 600), or a
  container running now. A loop hung anywhere else (a stuck host command, a deadlock) stops beating. When a project's
  current build says `running` and the heartbeat is missing or older than 120 s (`heartbeat.STALE_S`),
  `status.project_state` reports `worker: "not responding"` (also on the run view, with `why`/`now`
  saying so, `activity: fail`, `status_line`/`run_text` "Worker not responding"), and the Current build
  card shows "Worker not responding", for a dead runner and for a hung loop alike (about 10 minutes plus
  `STALE_S` after its last progress).
- Queue: a run starts as `queued`. The runner service takes the oldest queued run when no run is
  `running`/`waiting` anywhere (one build at a time across the server, decision 2026-11-01). Restart
  resumes `running` runs from `state.json`.

## 8. Events and gates

- Event line (JSON): `{"ts": iso, "type": "...", "project": ..., "run": ..., "task": n|null,
  "step": name|null, "data": {...}}`. Written to the run's `events.jsonl` and to HOME/events.jsonl.
  Types: `run.queued run.started run.finished run.step.started run.step.finished task.started
  task.finished gate.opened gate.answered project.created project.changed settings.changed
  update.started update.installed update.safety_files_added update.safety_files_skipped update.failed update.rolledback deploy.finished run.held run.discarded repair.applied run.note run.paused run.resumed run.pause.dropped edit.started edit.finished edit.abandoned edit.stalled agent.sync_skipped agent.restarted_for_rules command`.
  `update.safety_files_skipped {path, why}` and `agent.sync_skipped {path, symlink, why}` come from `phoenix update after-install` (nothing was written); `agent.restarted_for_rules {why}` from the runner's agent watchdog.
  `edit.started|finished|abandoned|stalled {edit, branch, who?, title?, pr?}` (project set, run null) come from `phoenix edit`.
  `plan.queued|continued|abandoned {plan, who}` come from `phoenix plan`; `plan.started|waiting|done|failed {plan, ...}` from the runner service.
  `repair.applied {who, note, title, steps, check_before, check_after, forced, rolled_back, snapshot}` (project and run set)
  is written for every applied repair note and every undo (section 8.4).
  `run.note {who}` (project, run and task set; never the text) is written by `phoenix run note`.
  `run.discarded {who, notes, forced}` (project and run set) is written by `phoenix run discard`.
  `run.paused {who}` is written by the runner when Pause now has stopped the step; `run.resumed {who, status}` by `phoenix run resume` (project and run set); `run.pause.dropped {who, reason}` when a Pause now request is thrown away because the run ended, waited for an answer or was queued (it never pauses a run later by surprise).
- Update event data (section 15; `project` and `run` are null): `update.started {tag, previous, who}`,
  `update.failed {tag, result: tests-failed|images-failed, reason}`, `update.installed {tag,
  previous, who}`, `update.rolledback {tag, previous, result: rolled-back|rolled-back-unhealthy|
  rolled-back-manual, reason?, who?}`. `deploy.finished {ok, rolled_back, url, deployer, reason}` (project
  set; run set when a run did it) is written for every deploy or preview attempt (section 4.7). `run.held {why}` is a run event (project, run set) written when
  a run stops at a task boundary for an update hold.
- Every `phoenix` command that changes something writes a `command` event and one line to
  HOME/logs/commands.jsonl `{ts, who, command, project}`; `who` = `--who` flag, else
  `$PHOENIX_WHO`, else `cli`. The API passes `dashboard`. It also appends a plain line to the
  project's `notes/changelog.md` for project changes (control spec section 2).
- Gate file `gates/<gate-id>.json`: `{id, run, project, kind, title, why, task, step, links: [{label,
  url}], actions, flags, created, answered: false}`. `kind`: `merge | plan | human-task | escalation |
  deploy | step`. `actions`: `["approve","back","skip","stop"]`, or for escalations see below.
  `flags`: e.g. `["changes safety code"]`.
  Escalation actions are `["acknowledged", "skip", "stop"]` (acknowledged = rerun the task once).
- `back` always needs a note (it is fed to the step that runs again).
- What each answer does (`runner.STEP_ANSWERS`, `runner.TASK_ANSWERS`):

  | Gate held by | approve | back | skip | stop | acknowledged |
  | --- | --- | --- | --- | --- | --- |
  | a step (any kind it returns: step, plan, merge, deploy, escalation, ...) | step passed with its `produces` | same step called again with `ctx.answer`; note added to `failures` | step skipped; a task step skips the whole task and its dependents | run `stopped` | step stays failed; normal failure handling goes on (it does NOT rerun the step) |
  | a `human-task` task | task passed | - | task + dependents skipped | run `stopped` | - |
  | an `escalation` task (after the last try) | - | - | task + dependents skipped | run `stopped` | outside fix committed, one more attempt |

  Service setup's "Paste keys" gate offers `done` (not in the table: the step is called again with
  `ctx.answer` and re-checks), `skip` and `stop`; the dashboard shows any action it does not know as a
  plain button labelled with its name (`done` = "Done, keys pasted"). The Deploy step's `deploy` gate
  (kind `deploy`) offers `deploy`, `skip` and `stop`; `deploy` calls the step again with `ctx.answer`
  and it deploys. Both are the "any other action" rule below; they need no runner change.

  Any other action a step's gate offers (a new gate kind's own action) calls the step again with
  `ctx.answer`, like back, but adds nothing to `failures`; the step decides what it means
  (`runner._handle_gate`, where step 07's on_approved hook also plugs in).
  Run-level steps (start/finish) get no retries and no `on_failure`; `acknowledged` on a gate a
  run-level step opened leaves that step failed (a failed start step fails the run).
  `stop` leaves out every finish step except those with `after_stop = true` (Notify). A new gate
  kind returned by a step needs no runner change. The runner never blocks on a gate: `drive()`
  returns "waiting" and the service loop drives the run again when `current.gate` is answered
  (an answer written while the runner was down is acted on the same way). `phoenix run stop` on a
  waiting run ends it and closes its question; a later answer is refused.
- **One truth (2026-11-06).** A question is *open* only when (a) it has no answer file, (b) its run is not
  `done | failed | stopped`, and (c) the run waits on it: `current.gate`, a task's `gate` or a `waiting`
  step line holding it, or (a waiting run that holds nothing, after a crash) the run's newest unanswered
  gate, which `runner.adopt_gate` takes. This rule is `gates.is_open`, used by `gates.list_gates`; listed
  gates carry `state: open | answered | closed`. What a project is doing now (current build and why, open
  questions, `needs_you`, `activity` need/run/fail/idle, `last_build_failed`, the plain lines) is worked
  out once, by `phoenix9/status.py` `project_state`; the API rows, `phoenix gate list`, `phoenix run
  status`, `phoenix project list`/`show` (harness) and every dashboard display (sidebar, Projects rows,
  Overview, header bell, tab badge, Current build card) read its fields and never re-derive them. The
  "answered, carrying on" view of a waiting run whose questions are all answered is `status.seen_run`.
- Answer file `gates/<gate-id>.answer.json`: `{action, note, who, at}`. Written only by
  `gates.answer()` (CLI `phoenix gate answer`, API, Home chat through the CLI). The runner polls for it.
- **Question lifecycle**: open (rule above) -> answered (an answer file written by `gates.answer`) or
  closed. Every way a run ends (done, failed, stopped; the runner's end, `watch._fail`, `phoenix run stop`)
  closes its unanswered questions with `gates.close_questions`: answer file `{action: "closed", reason:
  "run stopped" | "run failed" | "run done", note: "", who, at}` and a `gate.answered` event with
  `action: closed, reason`. The gate log reads "Answer: closed: run stopped" and the summary
  "Task n: closed: run stopped". Answering a closed question, a question of an ended run, or one the run no
  longer waits on is refused (`gates.NotOpen`; the API answers 409) with a plain message, e.g. "Run X is
  already stopped; its question X.1 cannot be answered any more." Start-up catch-up: when the runner
  service starts (`watch.watch_forever` -> `watch.catch_up`), it closes the open questions of runs that
  already ended (who = `phoenix`, one event each), so questions left by older code disappear without
  hand edits.
  Gate ids: `<run-id>.<n>`.

## 8.4 Repairs: report and notes (`phoenix9/repair/`, `ops/repair.py`, `phoenix repair`)

The repair kit is DOCUMENT BASED. Phoenix writes a plain-English **run report** from the real run state; a
fixer (the agent or Alex) writes a short **repair note**; Phoenix checks the note, snapshots, applies it,
checks again and writes the result back into the note. Documents are views or instructions, never a second
copy of the state: `state.json`, the gates and the worktree stay the only truth.

**Files** (all under the run folder `HOME/runs/<p>/<run>/repairs/`):
`report.md` (rewritten afresh each time), `notes/<n>-<slug>.md` (every applied note, n = 1, 2, 3 ... in
order), `<n>/before/...` (snapshot n: run-state files, attempt folder names, worktree head, branch, a
patch of uncommitted changes, the names of env files; never keys or env values), `<n>/removed/` (what undo
or a redo moved aside), `frozen.json` (see below).

**Modules**: `snapshot.py` (take, roll back, undo), `check.py` (`run_checks`: run state invariants, worktree,
settings, spec, server), `report.py`, `notes.py` (parser, result writer), `apply.py` (the engine),
`steps.py` (one function per step), `resume.py`.

**The report** (`phoenix repair report <run>`, `GET /api/repair/<run>/report`) has the sections: what the run
is doing, Tasks (one line each, with the tail of the last `checks.txt`, scrubbed), Open question, Worktree
(branch, HEAD, dirty files, env files), What the check found, Repair note lines (one ready line per finding,
in the note vocabulary), Details (paths).

**The note format** is strict markdown:

```
# Repair <run-id>
Why: one plain sentence (becomes the title in the event, log and changelog)

## Steps
- <step>
- force            (optional: keep the result although the check finds new problems)

## Result           (written by Phoenix; replaced on every apply or dry run)
```

Unknown or malformed lines are refused with their line number. Full step vocabulary (`notes.STEP_FORMS`):

| Step | Does |
| --- | --- |
| `redo task N from scratch` | task N and every later task back to pending, tries 0, failures cleared; attempts moved aside |
| `mark task N done because <why>` | task N passed |
| `mark task N skipped because <why>` | task N skipped, unfinished dependents skipped too |
| `retry task N` | task N pending with rerun on, failures kept |
| `clear failures of task N` | forget its failure reasons |
| `add a note to task N: <text>` | adds a note the next attempt reads |
| `set <key>=<value> for this run` | one setting in the run's `settings.json`; `plan.json` made again |
| `turn off step <name> for this run` | takes the step out of the plan (never `diff-rules`, `secret-scan` or a step a safety rule needs) |
| `replace the spec with <path>` | swaps the spec for a file under the project's `notes/`, keeping matching tasks |
| `keep my hand fix with message "<m>"` | commits uncommitted worktree changes as an outside fix |
| `reset the worktree to <sha>` | hard reset to a commit of `phoenix/<run>` or main |
| `rebuild the worktree` | removes and makes the worktree again from the branch |
| `close question <id> as <action>` | answers (or `closed`) one question the normal way (`gates.answer`/`gates.close_questions`) |
| `rewrite the checks of task N because <why>` | throws away the locked checks so Check-writer and Red check run again on resume; needs approval |
| `rerun finish step <name>` | runs one finish step again on a failed run |
| `resume` | puts the run back to `running` (or `queued`) so the runner carries on |

**Apply order** (`apply.apply`): read and parse the note; find the run; refuse if the runner is walking it;
(dry run: stop here, see below); copy the note to `notes/<n>-<slug>.md`; run the check (before); take
snapshot n; take the run lock (`runend.lock`); do the steps in note order, stopping at the first refused
step; run the check again; roll back to snapshot n if a step was refused or the check found a problem that
was not there before, unless the note says `force` (a refused step always rolls back). Then write the
`repair.applied` event, a `HOME/logs/commands.jsonl` line with who, a plain line in the project's
`notes/changelog.md`, and the `## Result` section (in the stored copy and the original file).

**Dry run** (`--dry-run`, API `dry_run`): the steps run on a scratch copy of the run folder; nothing real
changes, no snapshot, no event; the `## Result` says "Dry run" and the outcome has `would_roll_back`.

**Snapshot and undo**: a snapshot holds the run folder files (not `run.lock`), the worktree head and branch,
and a worktree patch that went through `git.scan_secrets` and the scrubber; a patch with a finding is
refused, not written. `phoenix repair undo <run> [--to N] --yes` restores snapshot N (default the newest);
new attempts go aside into `repairs/<m>/removed/`. Undo is itself a repair: it takes a snapshot first and
writes the same `repair.applied` event, log line and changelog line.

**The walked-run refusal**: a repair never touches a run the runner is walking: status `running` with a
heartbeat fresher than `heartbeat.STALE_S`, or a busy run lock. The answer is "The runner is walking this run.
Stop it first or wait for a question." (API 409). A `running` run with a stale heartbeat may be repaired.

**Never reachable by a step**: `docker.py`, images, firewall files, safety files, keys, secrets, and the
settings `domains`, `diff.allow_extra`, `services`, `safety_files` (`steps.FORBIDDEN_TOP`, `FORBIDDEN_KEYS`);
a setting may not shrink the diff deny list. Git commands go through `phoenix9/git.py` (hard rule 5 flags).

**Approval for unlocking checks**: `rewrite the checks` removes locked check files, so it needs
`--approve-unlock` (API `approve_unlock`) AND an asker who may answer an escalation in that project
(`gates.may_answer`); otherwise the step is refused ("needs Alex's approval: it unlocks checks"). It marks
the task with `check_objection` (the failure reasons that blamed the checks: SPEC_PROBLEM or a locked file),
so the next attempt and the report see why the checks were redone. No AI runs: the step only sets the state
up; Check-writer and Red check run in their containers when the run resumes.

**`repairs/frozen.json`**: written when a step changes the plan or a setting. The check normally demands
that `plan.json` equals what the resolver makes of the run's settings; when `frozen.json` exists the repair
is accepted as the reason they differ.

**The repair exception**: section 7 says an ended run is never changed again by the runner. The repair kit
is the one place allowed to change an ended run (`failed` or `stopped` with its worktree kept), and only by
an applied note, under the run lock, through `state.update`. Runs end only through `runend.end_run`; questions
open only via the gate helpers and close only with `gates.close_questions` or `gates.answer`.

## 8.5 The API (phoenix-api, phase 3)

- Stdlib `ThreadingHTTPServer` on 127.0.0.1 (port 8095 once installed). JSON under `/api/...`, the
  event stream at `/api/events` (server-sent events; each event's id = its line number in
  HOME/events.jsonl, so `Last-Event-ID` resumes), everything else = static files from `web/dist`.
- Writes (POST/PUT/DELETE/PATCH) need header `X-Phoenix: 1` and an `Origin` in the allowed origins
  (`PHOENIX_API_ORIGINS`, else the `allowed_origins` setting; section 5.5). Revealing a key is a POST for that reason.
- Every request (any method, any route: reads, `/api/events`, `/api/agent/stream` and the web app's files too)
  needs the far end of the TCP connection to be a process owned by an allowed uid: global.toml
  `[access] peer_uids` (a non-empty list of uids, default `[0]` = root only; `write_peer_uids` is the older name
  for the same setting; anything that is not such a list is ignored, root only, and doctor's `upstream` line says
  so). The API asks the host adapter (`Host.socket_uid`, which reads `/proc/net/tcp` and `tcp6` for the socket
  whose ends match the connection) and refuses any other owner (for example the `grunt` user or `nobody`) with a
  plain 403, and refuses when the owner cannot be found. The dashboard's real traffic arrives through cloudflared
  and code-server, which both run as root; doctor's `upstream` line reports the uid each runs as (found by
  program name in `/proc/*/cmdline`, `Host.program_uids`) and fails when one is not allowed. The only exception is
  `GET /api/health` (exact path, GET only): any local program may call it (doctor, the updater's health check
  through doctor, `phoenix service restart`), and it shows only `version`, `tag` and `origins_digest`. The CLI and
  the updater otherwise never go through the API (they call ops directly).
- Optional second lock: when global.toml has both `[access] team_domain` (e.g. `rebirth.cloudflareaccess.com`)
  and `aud` (the Access application's audience tag), writes also need a valid Cloudflare Access token in
  `Cf-Access-Jwt-Assertion` (`phoenix9/access.py`): RS256 checked with the standard library alone
  (RSASSA-PKCS1-v1_5 / SHA-256), keys from `https://<team_domain>/cdn-cgi/access/certs` kept for an hour
  (fetched again early, at most once a minute, for an unknown key id), `aud`, `exp` and `nbf` checked with 30 s
  leeway, `iss` (when present) must be `https://<team_domain>`. Set it by editing global.toml; doctor's
  `access` line reports it off, on, or half set up (a problem). When on it covers every request (reads and the
  web app's files too) except `GET /api/health`, so the dashboard only works through the Access address.
- At start (`phoenix` main and `make_server`) every saved secret (the global `secrets/*.env` files and every
  project's secret keys) is loaded into the scrubber, so transcript excerpts and logs never show them.
- The web app uses hash routes (`#/`, `#/new`, `#/p/<name>/<tab>`, `#/settings`) and relative asset
  and API paths, so it works behind code-server's `/proxy/<port>/` prefix.
- Endpoints and the ops function behind each are listed in `docs/api.md` (written in phase 3 step 1).
- The wizard's "remember these" writes its answers into the project's phoenix.toml (preset, steps
  on/off, per-step ai settings, max_tries, on_failure, merge, deploy); "notifications" = `steps.notify.on`.

## 8.6 The Phoenix agent link (`phoenix9/agentlink.py`, `transcript.py`, `api/stream.py`)

- **Finding the session**: `find()` reads Claude's registry `/root/.claude/sessions/<pid>.json` (never the
  `*.key` peer files or Claude's login file; a test checks). A session counts when its cwd is the agent folder,
  its pid is alive and its inbox socket sits directly in `/tmp/cc-socks-0` (no `..`, no sub-folder). With more
  than one, the choice is stable: the agent unit's main process or its direct child (`systemctl show -p
  MainPID`; claude remote-control runs sessions as children), else the session picked last time while it is
  alive, else the oldest (`startedAt`). Sessions named "Phoenix agent" come before others.
- **Transcript path**: `/root/.claude/projects/<folder>/<session>.jsonl`, where `<folder>` is the *real* path of
  the working folder (symlinks resolved: `/srv/projects` points into Docker's storage) with every character
  that is not a letter or digit replaced by `-` (Claude Code's rule; e.g. `-var-lib-docker-volumes-phoenix-cache--data-projects-home`).
  The session id must be a UUID before it is put in a path.
- **Parser**: `transcript.Parser` keeps its state between `feed()` calls (the stream feeds only new lines);
  `parse()` is one feed. Claude Code's bookkeeping lines (attachment, atis-latch, last-prompt, custom-title,
  agent-name, mode, summary, file-history-*, api-request*, pr-link, bridge-session, ai-title, tools-used,
  frame-link, cost-state, permission-mode, artifact-*) are known and ignored, as are system hook summaries and
  turn timings. Only `queue-operation` enqueue makes a queued item; dequeue (oldest) and remove (same text)
  clear it. Each line is parsed in its own try/except: an odd line counts as unknown and is rolled back.
  `tests/fixtures/agent-transcript-real.jsonl` is a sanitised copy of real transcripts (text replaced by
  placeholders); its unknown rate must stay under 2 %.
- **Sending**: the panel context is cleaned first: `project` only when it is a listed project, `page`/`run`
  only when they match `[A-Za-z0-9/_.-]{1,80}`, newlines stripped; the folder line is `/srv/projects/<project>`
  or the agent folder, nothing else.
- **Brief** (`phoenix agent brief`): project and NOW.md lines cut to 120 characters, the whole text at most 7,900
  (projects dropped from the end first, as "N more projects", then NOW.md lines).
- **Watchdog** (`agentwatch.py`): two bad checks in a row restart the unit (then the count starts again, and
  10 minutes' back-off); a unit that is inactive with `Result=success` was stopped on purpose: recorded as
  `stopped` in `logs/agent-watch.json` and left alone, and doctor's agent-unit line says "stopped by someone".
  `phoenix agent restart --yes` restarts it by hand.
  `phoenix agent stop` (`POST /api/agent/stop`, no confirm, no write lock) is the panel's Stop button: Phoenix
  itself ends the command the agent is running (SIGTERM, then SIGKILL after 2 seconds, to each tool shell, the
  process whose command line contains `/.claude/shell-snapshots/`, and everything under it; never the agent
  process, never its helper processes such as MCP servers, never a pid outside the agent's own process tree,
  re-checked before each signal), then posts one fixed message asking the agent to stop and say what was left
  half-done. Returns `{stopped, sent}`; an asleep agent is refused. Recorded in the send log (who, time, no text).
  `phoenix agent new --yes` (`POST /api/agent/new`) starts a fresh conversation: it asks the agent to save its
  notes (fixed text), waits until it is not working (at most `[chat] wrap_up_minutes`), then restarts the unit;
  an asleep agent is just started. It does not hold the API write lock; one at a time (else 409).
- **Registry**: the list of Claude sessions in `/root/.claude/sessions/<pid>.json` (see "Finding the session").
  Phoenix reads only those `.json` files and the transcripts, nothing else in Claude's home.
- **Wire format**: `agentlink.wire_line()` builds one JSON line `{msgV: 1, msg_id, type: "user", message: {role:
  "user", content}, priority: "next", from}`; the content is the text inside a `<cross-session-message>` wrapper
  (the wrapper's own closing tag is escaped inside the text), with the panel envelope line first.
  `connect_and_write()` writes it to the inbox socket within a timeout; failure is a `SendError`.
- **Only the socket and files are touched**: Phoenix talks to the agent through its inbox socket, reads the
  registry and transcript files, and restarts its unit. It never reads Claude's login file or the `*.key`
  peer files (`tests/test_no_credentials_read.py`), never starts Claude for this and never drives the agent's
  terminal.
- **Settings**: `[agent]` in `global.toml`: `agent.folder` (default `/srv/projects/home`), `agent.unit` (default
  `claude-rc@home`), `agent.watchdog` (default true).
- **Who it is**: `deploy/agent/settings.json` sets `env.PHOENIX_WHO=chat:home`, so every `phoenix` command the agent
  runs is logged as `chat:home` (and is refused for project deletes). For belt and braces, give the unit the same:
  a drop-in `/etc/systemd/system/claude-rc@home.service.d/phoenix-who.conf` holding `[Service]` and
  `Environment=PHOENIX_WHO=chat:home`, then `systemctl daemon-reload` and restart the unit. Project chats get
  `Environment=PHOENIX_WHO=chat:%i` from `deploy/claude-rc-chat@.service`.
- **Doctor lines**: `agent-unit`, `agent-session`, `agent-socket` (folder 700, socket 600), `agent-transcript`
  (unknown lines at most 5 %), `agent-folder` (has CLAUDE.md and `.claude/settings.json`).
- **Deploy files** (`deploy/agent/`): `agent-rules.md` (the rulebook; the admin setup step copies it to the agent
  folder as `CLAUDE.md`, because builds may not write a file of that name), `settings.json` (the session-start
  hook running `phoenix agent brief`) and `agents/` (navigator, editor, checker helpers).
- **Safety files**: `phoenix9/agentlink.py` (the only code that writes to the agent's socket; path and
  message rules), `phoenix9/transcript.py` (reads untrusted agent output; must never act on it) and
  `deploy/agent/agent-rules.md` (the agent's own rules) and `phoenix9/project_delete.py` (deletes a whole project) are in `safety_files` in `deploy/self-project.toml`.
- **Delete project** (`phoenix9/project_delete.py`, a safety file): `plan(name, who, adapters)` is the dry run for
  "Delete project entirely": folder and size, GitHub repo with `repo_verdict` (deleted only when it is the project's
  own, see section 9.5), open merge requests, unpushed commits, unsaved edits, runs, key names (never values; not
  kept in the copy), chat unit, live deployments (listed, never touched) and `refusals` (phoenix9/home also by real
  name, a linked folder, an active build, a working chat, any caller but `dashboard`/`cli`). The safety copies go under `paths.deleted_projects()`
  (`$PHOENIX_DELETED`, default `/root/deleted-projects`).
  `backup(name, who, adapters)` writes `<name>-<YYYYMMDD-HHMM>/` (mode 700) with `repo.bundle` (verified; skipped
  with a note when there is no git repo or no commits; `git fetch --all` first), `files.tar.gz` (everything in the project folder, including all of code/'s working copy with unsaved edits and nested repos, except code/.git and pure caches), `runs.tar.gz`
  (HOME/runs/<name> and HOME/work/<name>), `manifest.json` and `RESTORE.md`; any error removes the half-made
  copy and raises `OpsError`. `prune_backups(adapters, now)` removes copies older than global `[delete] keep_days`
  (default 30, clamped to 1..3650); the runner loop calls it once per pass through `watch.prune_deleted_copies`,
  which never raises (a failure is one stderr line in the runner's journal).

## 8.7 The new agent (agentkit) and the Phoenix pack

Built beside the old agent (section 8.6), which stays as it is. Two layers:

- **`agentkit/`** (Python package `agentkit`): the core, the same on every site. Agent loop (Pydantic AI,
  behind `agentkit/llm.py`), typed tools with risk levels, the event stream (AG-UI over SSE, behind
  `agentkit/wire.py`), approvals, conversations, the spending cap and the service. It knows nothing about Phoenix.
- **`agentkit/packs/phoenix/`**: the Phoenix pack, kept thin: its tools, browser actions, cards and
  instructions. It reaches Phoenix only through Phoenix's HTTP API (`http://127.0.0.1:8095`).

The chat screen is `#/agent-next` (`web/src/features/agentnext/`; assistant-ui behind `runtime.ts`).

**The service.** `phoenix-agentkit.service`, system user `phoenix-agentkit` (it refuses to start as uid 0),
listening on `127.0.0.1:8097`. Its folder `/var/lib/phoenix9/agentkit/` holds `config.toml`, `api-key` (mode 600,
owned by the agent user, put there by Alex), `token` (the shared token, root:phoenix-agentkit, mode 640),
`agentkit.db` (SQLite) and `venv/`. The code runs from the installed copy `/opt/phoenix9/agentkit`. Every request
needs `Authorization: Bearer <token>`, else 401. Routes: `GET /status`, `GET|POST /threads`, `GET /threads/{id}`,
`POST /threads/{id}/runs`, `GET /threads/{id}/stream?after=N`, `POST /threads/{id}/stop`, `POST /approvals/{id}`,
`POST /browser-results/{id}`, `GET /spend`. Its tools are exactly the pack's list plus `suggest_next_actions`; it
has no shell, no file tools and no way to run a `phoenix` command.

**The passthrough.** phoenix-api passes the browser's calls at `/api/agent-next/<same path>` to the service, after
its usual checks, adding the token. global.toml `[agent_next]` holds `url` (default `http://127.0.0.1:8097`),
`token_file` (default `/var/lib/phoenix9/agentkit/token`) and `uid` (the agent user's uid; with no `uid`, agent
access is off). The Phoenix-side client is the adapter `phoenix9/agentnext.py`, with a fake in tests/fakes.

**Who `agent`.** A connection whose peer uid equals `[agent_next] uid` is the caller who `agent`. It needs
`X-Phoenix: 1` but no Origin, because it is not a browser. It may use only the routes on the generated allowlist in
`phoenix9/agentaccess.py` (see "The controls registry" below). Everything
else is refused with 403, whatever the agent does. Every reply to the agent goes through the `phoenix9/scrub.py`
rules, so no secret value enters a conversation. Changes the agent makes are recorded as `command` events with
who `agent`. The uid must not be 0 or one of `[access] peer_uids` (the `upstream` doctor check tests this).

**The controls registry.** `phoenix9/ops/controls.py` (part of the ops layer) is the single source of truth: one entry
per dashboard control with `name`, `ops` (the `module.function` it calls), `method`, `route` (the same pattern as in
`server.ROUTES`), `risk` (`read`, `change`, `destructive` or `alex-only`), `agent`, typed `inputs`, `fixed` body
values, `card` (the result card) and, for destructive ones, `confirm_with`. Several controls may share one route
(approve plan and send back plan both use the gate answer route). `agent` says what the agent may do with it:
`tool` (an agent tool), `alex-only`, `key-card` (saved only through the masked key card), `secret` (would put a
secret value through the model, so never a tool) or `later` (a later agent build), the last with a `why`. Each input
has `name`, `type` (string, integer, boolean, choice, list or object), `required`, `description`, `choices` and
`where` (path, query or body).

**The description file.** `agentkit/agentkit/packs/phoenix/controls.json` is written by `phoenix9/controlsgen.py`
from the registry: a JSON list with one object per control holding `name`, `description` (the registry text, else
the first docstring line of the ops function), `inputs`, `risk`, `agent`, `why`, `method`, `route`, `fixed`,
`fixed_query`, `card` and `confirm_with`. It is a data file, not code: the pack reads it at start-up and builds one
server tool per `agent: tool` entry, so the pack never imports phoenix9. A test fails when the file differs from
what the generator makes.

**The allowlist.** `agentaccess.ALLOWED` is generated: exactly the (method, route) pairs of entries with
`agent: tool`, so a control becomes reachable for the agent only by being marked `tool` in the registry. A test
checks the allowlist against the description file.

**The settings rule.** Every settings change still goes through an approval card. On the settings routes the agent
may change any setting that is not a safety setting, sent as `{"set": {...}}`. `agentaccess.settings_refusal`
refuses, with a plain message: any safety key (`is_safety_key`); a `preset` inside `set` (use the preset control);
a preset that would change a safety setting; a body that is anything other than `{set}`; and an `/edit` body with
anything but `services`.

**Typed-name confirmation.** A destructive tool names an input in `confirm_with` (stopping a build: the run id;
changing the dashboard addresses: the setting being changed). The approval card shows the exact change and keeps
Approve off until Alex types that value exactly. The service checks it again on `POST /approvals/{id}`; the
decision is made only there, never by a chat message.

**Result fields.** A browser tool lists the result keys, and for each the values, the service may pass on
(`result_fields`). Anything else the browser sends back is dropped before it reaches the model.

**The key card.** The browser tool `ask_for_key` makes the panel draw a masked key card. Alex types the value into
it and the dashboard posts it straight to `POST /api/projects/{name}/keys/save` (not through the agent user). The
card answers the agent with only `{status: saved | cancelled}`, so the value never reaches the model, the thread
or the logs. Revealing a key and connecting or testing a service with values are `secret` controls: never tools.

**Alex-only controls.** Deleting a project (`POST /api/projects/{name}/delete`) and deleting a repo
(`POST /api/projects/{name}/delete-repo`) are `alex-only` in the registry and the description file. They are not
tools and have no route on the allowlist; the agent tells Alex to use the dashboard button.

**The API key rule.** Only agentkit uses the Claude API key; everything else in Phoenix keeps using the Claude Max
subscription. The key is read from the file named by the agentkit setting `api_key_file` and passed straight to the
Anthropic provider object. It is never put in the environment or in any file of builds, steps, project chats,
phoenix-api or the runner, and no phoenix9 module reads that file or sets `ANTHROPIC_API_KEY`. Prices in
`config.toml` are internal; while any price in use is not a number the service refuses model calls. Alex only
ever sees spending as a share of the monthly allowance, in words.

**Import boundaries.** `agentkit` imports nothing from `phoenix9`, and `phoenix9` imports nothing from `agentkit`
(tests check both). The root `pyproject.toml` keeps `dependencies = []`; agentkit has its own
`agentkit/pyproject.toml`, `agentkit/.venv/` (built by `agentkit/venv.sh`) and `agentkit/requirements.lock`.
`./check.sh` also runs agentkit's tests through `agentkit/test.sh`; no test calls the real Claude API.

**Doctor lines.** `agentkit-service` (the unit is active and answers `/status`), `agentkit-key` (the agent says
its key is present; the key file is never read by the doctor) and `agentkit-spend` (the allowance in words:
plenty left, getting low, or used up). Each passes with "not set up yet" when `[agent_next]` is absent.

## 9. Adapters (everything external, each with a fake in tests/fakes/)

| Adapter | Real | Fake |
| --- | --- | --- |
| `docker` | V8 docker.py port: run a step container with limits, firewall, mounts | records calls, returns scripted exit codes and files |
| `claude` | V8 claude.py port: `claude -p` stream-json in the container, usage-limit and model-unavailable detection | scripted sessions: writes given files into the worktree, returns given result/usage |
| `git` | V8 git.py port: clones, worktrees, safe flags, diffs | real git on temp repos (git is always available) |
| `host` | systemctl, journalctl, `gh`, `du`, filesystem outside HOME; reads and checks used by the agent link: `read_lines`, `list_dir`, `exists`, `stat`, `realpath`, `pid_alive`, `parent_pid`, `process_cwds` ({pid, name, cwd} of every process, from /proc), `cgroup(pid)` (the `0::` line of /proc/<pid>/cgroup), `now`, `sleep`; deletes: `remove_tree(path)`, `remove_file(path)` (both quiet when the path is gone; used only by `project_delete.py`); `run` refuses any command whose program is `claude` (`ClaudeOnHost`, rule 1) | records calls, returns canned output |
| `http` | urllib for service/deployer APIs | canned responses per (method, url) |
| `clock` | time.time / sleep | manual clock |
| `notify` | Telegram: write `/srv/phoenix-inbox/jobs/notify.msg` (phoenix-notify.path sends it) | list of messages |
| `proxy` | `Proxy.start(spec, key, *, log_path, step, bind)` starts the per-step key proxy (`proxy.serve`, section 14) and returns its handle | `FakeProxyFactory`: forwards nothing and listens nowhere; records `(service, rules, step, bind, key_len, key_seen)` (never the key), returns a handle with `url = http://proxy.fake/<service>`, a fixed token and a recorded `stop()`; `.started`, `.stopped`, `.running()`. Tests script `FakeHttp` at that url |
`phoenix9/adapters.py` builds the real set; tests build the fake set. Nothing else in the code calls
`subprocess` for these tools directly.

## 9.5 Deleting a project (`phoenix9/project_delete.py`, a safety file)

"Remove" only takes a project off the list; **Delete project entirely** is the one action that cannot be undone.
Only Alex can use it: the bottom of the project's Settings tab, or `phoenix project delete <name>`.

1. **Dry run** (`project_delete.plan`, `GET /api/projects/<name>/delete-plan`, `--dry-run`): folder and size, GitHub
   repo and whether it will really be deleted (`repo_delete: {repo, delete, why}`), open merge requests, commits never
   pushed, unsaved edits (`git status --porcelain` count, kept in the copy), runs, key names (never values) with
   `keys_note` saying the saved keys are deleted and NOT kept in the safety copy, chat unit, live deployments,
   `keep_days`.
2. **Confirm by typing the name** (`{"confirm": "<name>"}` in the API; in the CLI `--confirm <name>` and then the name
   typed again at a prompt on a real terminal: without a terminal (stdin not a tty, as in any Claude session) the
   CLI refuses, and it refuses `--who` other than `cli`/`dashboard` and any `$PHOENIX_WHO` other than those).
3. **Safety copy** (`backup`) in `paths.deleted_projects()` = `$PHOENIX_DELETED`, default `/root/deleted-projects`:
   `<name>-<YYYYMMDD-HHMM>/` (mode 700) holding `repo.bundle` (`git bundle --all`, checked with `git bundle verify`),
   `files.tar.gz` (the whole project folder: notes/, and all of code/ as it is on disk, so uncommitted and staged
   edits, untracked files, build output such as dist/build/target and nested repos with their own .git are kept;
   left out are only code/.git, which is the bundle, and pure caches: node_modules, .venv, venv, __pycache__,
   .pytest_cache, .mypy_cache, .ruff_cache, .next/cache, .turbo), `runs.tar.gz` (HOME/runs/<name>
   and HOME/work/<name>), `manifest.json` (name, folder, repo, who, when, notes, `repo_delete`, `bundle_of`: the
   origin repo the bundle was made from, plan) and `RESTORE.md`. Saved keys are NOT in the copy. If any part fails,
   the half-made copy is removed, nothing is deleted and the error is shown.
   Before bundling, `git fetch --all` (through the host adapter) brings in branches that are only on GitHub; a failed
   fetch is a note in the manifest, not a stop. A repo with no commits gets no bundle (its files are in the tar) and
   its GitHub repo is never deleted.
4. **Lock and last check**: the delete holds the per-project lock `paths.project_lock(name)`
   (`HOME/locks/project-<name>.lock`) from the first check to the last step; `phoenix run start` takes the same lock
   (waiting up to 10 s) to queue a run, and re-checks that the project still exists; project new, edit, remove and
   import take it too (`common.project_lock`). Right after the safety copy and
   before the first delete, the refusals are checked again; if anything is busy now, the copy is removed and nothing
   is deleted.
5. **Delete, in this order**, each step recorded in the result and as a `command` event: the chat unit
   `claude-rc-chat@<name>` (stopped, disabled, drop-ins removed; when that fails NOTHING else is deleted, only the
   GitHub step is recorded as not done), records and runs (with the project's quick-edit copies `HOME/edits/<id>/`
   and records, and its planning sessions' records, folders and `HOME/work/plan-<id>/`; these folders are in
   runs.tar.gz of the safety copy too), the project folder (right before it, the working-inside check runs again
   with no own-chat exclusion: anything still inside keeps the folder), `HOME/keys/<name>.toml`,
   Claude Code's folder trust entry (`project_removal.untrust`), the `removed_projects` row and INDEX.md line, and
   last the GitHub repo (`gh repo delete <owner/name> --yes`).
   **Which GitHub repo** (`repo_verdict`): only one that is the project's own. Checked first: the repo is not the
   projects folder's own repo and code/ does not sit inside a parent repo (reason "it is the projects folder's
   shared repo"). Then all must hold: `.phoenix/project.json` says Phoenix made it (`source` `empty` or `template`,
   the repo recorded, and `phoenix_made_repo` naming exactly that repo; that field and `phoenix_made_repo_id`, GitHub's
   id, are written only when Phoenix itself creates a repo, and `project edit --repo` and Import clear them, so
   projects made before this keep their repos); `git -C <folder>/code rev-parse --show-toplevel` is code/ itself;
   code/'s origin is the recorded repo; code/ has commits; and no other folder in the projects folder (listed or
   not; its recorded repo and the real origin of its code/ and of itself), removed-projects row or the projects
   folder's own repo points at the same owner/name (compared ignoring case). The GitHub step also needs a verified
   bundle of that repo in the copy and the folder really gone. **Right before every `gh repo delete`** (the delete
   and the retry): `gh repo view <repo> --json id,nameWithOwner` must give the recorded id, and every branch and tag
   on GitHub (`git ls-remote`, with its commit) must be in the bundle (`git bundle list-heads`; `origin/<b>` counts
   for `<b>`); any mismatch or failure keeps the repo. Otherwise the step is `kept` (`ok`, with "GitHub repo <x> not
   deleted: it ..."), or, when only the folder removal failed, not done, for the retry. The dry run (CLI and Danger
   zone) shows "(will be deleted)" or "(kept: <reason>)" on the GitHub repo line. Without a bundle (no commits),
   code/.git itself goes in files.tar.gz.
6. **GitHub scope**: without the `delete_repo` scope everything else still completes and the result says the repo
   was NOT deleted, with the fix (`gh auth refresh -h github.com -s delete_repo`). `POST
   /api/projects/<name>/delete-repo` / `phoenix project delete-repo <name>` retries only that step, reading the repo
   from the newest safety copy's manifest. The retry keeps the same rules (the manifest's `repo_delete` verdict and a
   bundle of that repo in the copy) and is refused when the project folder exists again or any current project,
   removed-projects row or the projects folder's own repo now uses that repo.
7. **Live deployments are never touched**: they are listed (`still_live`) with links.
8. **Keep time**: copies stay `delete.keep_days` days (global `[delete] keep_days`, default 30, clamped to 1..3650);
   the runner loop calls `prune_backups` on every pass, wrapped so a failure only logs a line.

**Refused** (409): `phoenix9` and `home` (`project_removal.PROTECTED`, checked against the folder's real name
too, so a link called something else cannot delete them); a project folder that is a link, or whose real parent is
not the real projects folder; a project with a build queued, running,
waiting or paused; a project whose chat state is `working`;
any program whose working folder is inside the project's real folder (`/proc/*/cwd`
through the host adapter's `process_cwds()`: a grunt job, a desktop or terminal session; this process and its
parent shell excepted, and the project's own chat: the chat unit's MainPID and processes below it whose
`/proc/<pid>/cgroup` (`Host.cgroup`) is that unit's `ControlGroup`, since the delete stops that unit itself); a
planning session of the project that is running; any caller other than `dashboard` or `cli` (the Phoenix
agent and every `chat:*` caller, whatever the project's permissions).

**Host adapter** (section 9): systemctl, `gh` and the filesystem deletes `remove_tree(path)` and `remove_file(path)`
all go through `adapters.host`; the fakes record them. Tests set `PHOENIX_DELETED` to a pytest tmp folder.

## 10. Keys and secrets

- Project keys: `HOME/keys/<project>.toml` (0600): `[[key]] name, value, secret (bool)`. Never in the
  repo or notes/. Non-secret keys are also written to `code/.env.example` (names and values; secret ones
  as `NAME=` with no value). Secret values are added to the scrub list of every run of that project.
- Global secrets: `HOME/secrets/<name>.env` (0600), read only by the host process that needs them.
- The dashboard's Reveal button (behind the code-server login) is the only way to see a saved
  secret value; the CLI has no reveal.
- Values are never printed by any command (`phoenix keys` shows `••••••`), never passed on a command
  line (read from stdin or a file), never logged. `scrub.py` redacts every known secret value, plus the shapes of common unregistered secrets
  (sk-ant-, GitHub token prefixes, PEM private keys) and `NAME=value` / `NAME: value` where one part of the name
  (split on `_ - .`, case changes and digits) is key(s), token(s), secret(s), password(s), passwd or pwd, or the
  name is one of a few joined forms such as `apikey` or `accesstoken`: `API_KEY`, `apiKey`, `GITHUB_TOKEN` and
  `db-password` are masked, `monkey`, `turkey` and `keyboard` are not.

## 11. Fixed safety rules (always on; harness spec 8)

1. No AI runs in Phoenix's own processes. Claude only runs inside step containers. There is no
   exception: the `delegate` failure mode only posts one message into the Phoenix agent's inbox
   (`agentlink.send`); the agent is a separate, already-running session that Phoenix never starts or drives.
   `phoenix9/chat.py` is the only place that restarts the Phoenix agent's service (`chat.agent_restart`, the one other process control there: a `systemctl restart` of the `agent.unit` setting, used by the
   watchdog `phoenix9/agentwatch.py`, which the runner loop calls every 60 s unless `agent.watchdog = false`;
   memory in `logs/agent-watch.json`). Project chats (`phoenix9/chat.py` and `phoenix9/projectchat.py`)
   add only unit and process control through the Host adapter: `chat_unit` (`claude-rc-chat@<listed
   project>`), `unit_state` (`systemctl is-active`), `unit_main_pid`, `start_unit` (`systemctl enable --now`),
   `stop_unit` (`systemctl disable --now`) and `stop_conversation` (`Host.stop_pid`, SIGTERM, only to the
   unit's MainPID's direct child or a registry entry of the project). Phoenix never starts Claude itself.
   Planning sessions are no exception: they run in step containers (below). Enforced twice: `Host.run`
   refuses any command with an argument named `claude`, or a shell/wrapper (sh, bash, env, timeout, xargs, npx,
   node...) with `claude` as a word in any argument (`adapters.refuse_claude`), and
   `tests/test_no_host_claude.py` walks phoenix9/ with `ast` and fails on a `claude` command line anywhere
   but `claude.build_command` (the container's command), docker.py and the Claude adapter, on a `claude` word in
   any string passed to a process-starting call, and on any os.exec*/os.spawn*/posix_spawn* use in phoenix9/.
2. Step containers never get the Docker socket, the GitHub token, SSH keys or account service keys.
   They get the Claude token, the project's secret keys as env vars, and the proxy address plus a
   per-step proxy token (phase 4; the token only identifies the step to the proxy, it is not a service key).
   Container env (built by `Claude.launch` / `docker.py`): `PHOENIX_PROXY_<SERVICE>` (the proxy URL) and
   `PHOENIX_PROXY_TOKEN_<SERVICE>`; `docker.py` refuses any other added name that does not start
   `PHOENIX_PROXY_`. The firewall opens only the proxy's `IP PORT`, read from the file mounted at
   `/etc/hands/allowed-proxy`; the proxy host is the Docker bridge gateway.
3. Phoenix trusts only exit codes, files it wrote, reports it read itself and git objects in its own
   worktrees. Nothing a session *says* counts.
4. The spec is mounted read-only; locked checks are fingerprinted (when Check-writer is on). The lock
   covers the files the check writer wrote plus no-added-files in their folder, which is per run
   (`<checks_dir>/<run-id>/task-<n>/`); older runs' check folders are ordinary repo files.
   **Locked checks are self-contained** (`phoenix9/checklint.py`), because a locked check the builder
   cannot fix skips the task (agent build 1b, task 6: a check read `PHOENIX_PROJECTS` it never set).
   - Before locking, Check-writer lists the environment variables each check file reads (shell `$X` /
     `${X}` outside single quotes, comments and quoted heredocs, where `${X:-..}`-style fallbacks do not
     count; python `os.environ["X"]`, `os.environ.get("X")` and `os.getenv("X")` with no default, also
     inside heredocs) and refuses any the file never sets (shell `X=`, `export`/`local`/`declare`/
     `readonly`, `for X in`, `read X`; python `os.environ["X"] =`, `setdefault`, `putenv`,
     `monkeypatch.setenv`). Assignments count anywhere in the file (no order check). Allowed without
     setting: PATH, HOME, TMPDIR, PWD, the shell's own variables, the check container's env
     (`docker.check_run`: `session_env()` minus `CLAUDE_*`, plus `GIT_ENV`), the project's key names
     (the env file) and `PHOENIX_PROXY_*`. The step fails naming the variable; the retry rewrites.
   - Red check counts a non-zero exit as red only when the output is not a crash in the check's own
     setup. A crash is: a Python error whose innermost frame outside Python's own library is in the
     check's own code (a check file, or a program it wrote outside /workspace: heredoc temp file,
     `<stdin>`, `<string>`) and is NameError, SyntaxError/IndentationError, KeyError on a line reading
     `environ`, ImportError/ModuleNotFoundError of a standard-library module, or FileNotFoundError of an
     absolute path outside /workspace; or the shell running a check file saying "unbound variable" /
     "parameter not set" / "command not found". Kept narrow on purpose: a missing project module, a
     missing project file or a KeyError in data the code returned are real reds (the task is not built
     yet). A broken red fails the attempt, so Check-writer writes the checks again (once-steps above).
   - Check files are run with `checklock.check_commands`: a shell `check_command` (`sh {files}`, `bash ...`)
     runs only its first script, so it becomes one command (and one check container) per file in Red
     check, Acceptance and Verify, and Red check judges each file (each must fail, none may crash); a test
     runner (pytest, vitest) still gets every file in one command.
5. Every git command on an untrusted checkout uses `-c core.fsmonitor=false -c core.hooksPath=/dev/null`.
6. Default diff denylist: `.git`, `.github/workflows`, `.env*`, symlinks, submodules, `CLAUDE.md`,
   `.claude/`, `.mcp.json`, locked check files. Everything else is allowed unless the project denies it.
7. Never `claude --bare` (it ignores the OAuth token).
8. Secrets scrubbed from every log line written to disk.

Planning sessions (`phoenix9/plans.py`, `phoenix9/plansession.py`, library step `steps/_plan-session/`; the
leading `_` keeps it out of every run's step list). `phoenix plan start <project> --brief` / `continue <id>` /
`reply <id> --text` only write the record (status `queued`) and its prompt file and return at once; callers poll
`phoenix plan status <id>`. The runner service runs the oldest queued plan between runs (one at a time, not while
an update holds the harness; a plan left `running` by a stopped runner is queued again at start) in a sealed step
container exactly like the Planner step: firewall with only api.anthropic.com, no-new-privileges, the non-root
session user, no Docker socket, no GitHub token, no project keys, no key proxy, env = the claude env file only.
Mounts: `/workspace` read-only = a standalone clone of the project's default branch (`git.snapshot_clone`,
HOME/work/plan-<id>/code; the live code/ folder is never mounted), `/project/CLAUDE.md` and `/project/notes`
read-only (links are not mounted), `/out` writable = HOME/plans/<id>/out/ (on continue seeded with the filed spec),
HOME/plans/<id>/claude/ as the session user's `~/.claude/projects`; cwd is always /workspace so `--resume <uuid>`
(checked with `pause.valid_session_id`) finds the session. Model: setting `plan.model` (default claude-fable-5-1),
then the step's fallback models. The session writes `/out/spec.md` (harness spec format plus `## Open questions`,
numbered, each with an `Answer:` line, and `## Decisions`; spec.py accepts both sections and runs ignore them).
Phoenix runs `spec.check` on it itself; on problems it resumes the same session with the list, at most 2 rounds,
then `failed`. A valid spec is written by Phoenix to `notes/specs/plan-<id>.md` (Phoenix picks the name; atomic
write; refused when notes/, notes/specs/ or the file is a link). Before filing, a spec holding the Claude login
(any value of claude.env, in any written form) is refused and the plan fails (the out file is removed); every other
known secret value and secret shape is masked. /out/spec.md is opened with O_NOFOLLOW|O_NONBLOCK and must be a
regular file; a code/.git `gitdir:` file pointing outside the project folder is refused. Phoenix counts the open questions from the file:
`waiting` (questions open) or `done`. Each session's cost goes into the record (`claude.record_usage`); over the
per-plan cap `plan.budget_usd` (default 5) the plan stops `failed` with a plain message; a session whose cost
could not be read stops it too ("Spending unknown"). The model must be one prices.py knows (or its short alias).
Refused (start, continue and reply): the agent's folder (`ops.projects.agent_name()`, and `home`) always, phoenix9
when the caller is a chat (`chat:*`). A chat may continue, reply to or abandon only a plan it started itself. CLI: `phoenix plan start|status|continue|reply|abandon|list`.

Quick edits (`phoenix9/edits.py`, `editfinish.py`; no Claude of their own, the Phoenix agent or its `editor` helper does the editing): `phoenix edit start <project> <title>`
makes a worktree of the project's code/ on branch `edit/<id>` in `HOME/edits/<id>/`; it never touches the main branch, code/ itself or another
project or the agent's folder, and refuses while a build runs on the project or another edit of it is open or stalled. `phoenix edit finish <id>`
first squashes the copy into ONE commit on top of its base (trailers `Phoenix-Edit: <id>`, `Phoenix-Fix-By: <who>`), then checks exactly that
commit on a clean checkout of it (`git.commit_checkout`): diff denylist, the project's safety files when the caller is a chat (`chat:*`, the same
rule as a repair's hand fix), secret scan, lockfile check, project test command in a sealed container. It pushes exactly that commit
(`<sha>:refs/heads/edit/<id>`), refused when the copy's HEAD moved or it has uncommitted changes by then, and opens a merge request with the
label `needs Alex` (created when missing; a label failure never loses the merge request) and the line "Made by <who>; Alex merges this.".
Alex merges. `phoenix edit heartbeat|list|abandon`; a chat may abandon only an edit it started.
Sidebar groups (`web/src/lib/switcher.ts`): 1 active quick edit or planning session (spinner), 2 build running, 3 paused or waiting for Alex, 4 the rest.

## 12. Deliberate simplifications (recorded so nobody "fixes" them)

- **CLI calls ops directly, not over HTTP.** The control spec says the CLI calls the API when it is up
  and falls back to direct work. State is files, so both paths would do the same thing; calling ops
  directly is that fallback, always. The guarantee that matters holds: the dashboard and the CLI call
  the same ops functions, so neither can do something the other cannot.
- **Runner and API are two host services; AI steps only in Docker** (decision 2026-11-01).
- **Merge uses the host `gh` login** (the key proxy replaces V8's credential helper for anything a
  container or service recipe needs; the host Merge step never needed the helper) through the `host` adapter in phase 2; phase 4's key proxy is for
  step containers and service setup. The Merge step is a script step on the host, so no container ever
  holds the GitHub token either way.
- **Hand to the Phoenix agent** (`on_failure = "delegate"`): when a task runs out of tries the escalation
  gate opens as in pause mode, with the flag "handed to the Phoenix agent", and Phoenix posts ONE message
  through `agentlink.send` (from-name "Phoenix (build escalation)"): `[Phoenix · escalation] <run id> task <n>`.
  Nothing else goes in it (no failure text, no file content): the agent reads the task file and
  `phoenix repair report`, fixes with a fix note, a repair note, settings or a quick edit on the build's
  own worktree, and answers `acknowledged` (`chat:home` may answer only that, only on a gate with the
  flag: `gates.may_answer`). If the agent is asleep or the send fails, the flag is replaced by a note on
  the gate saying so and Alex is told, exactly as in pause mode. At most `failmodes.MAX_ESCALATIONS` (2)
  hand-offs per task; after that the task fails as in pause mode. Old state files may still carry a task
  `delegate` field; it is read and ignored.

- **A step cut off mid-run by a crash reruns on an un-reset worktree.** The step line is still
  `running` with no result.json for the attempt, so the restart calls that step again as it is; the
  worktree is not reset to `attempt_base` first (half-written files from the cut-off session stay).
  Accepted: the step's own checks judge the result, and a failed attempt is reset as usual.

- **The update hold blocks `drive()`.** Gates never block the runner, but the update hold does: at a
  task boundary `Runner._hold_point` waits (5 s polls on the clock adapter) until the hold is gone.
  Acceptable because only one run is driven at a time and the updater releases the hold in every
  outcome. The hold counts only while the hold file exists AND an updater holds `HOME/update/lock`
  (probed read-only with `LOCK_SH|LOCK_NB`), so a killed updater (its flock dies with it) can never
  freeze the runner; there is no time limit.

## 13. Formats defined in later phases

All phase 4 formats now live in the sections above. Where to look:

| Format | Section |
| --- | --- |
| `services/<name>/service.toml` | 4.6 |
| `deployers/<name>/deployer.toml`, `deploy.py`, `.phoenix/deploys.jsonl` | 4.7, 3 |
| step.toml `proxy` key (incl. `@project`); Service setup, Deploy, Preview steps | 4.1 |
| `[deploy]` and `[deploy.settings]` in phoenix.toml | 5.2 |
| `HOME/update/` files, `HOME/config/global.toml [update]`, `services.toml`, `api.env`, `doctor.json` | 3, 15 |
| `services_set_up` in `.phoenix/project.json` | 3, 4.1 |
| run state `current.held`; the hold wait in `drive()` | 7, 12 |
| gate actions `done` and `deploy`; events `run.held`, `update.*`, `deploy.finished` | 8 |
| `proxy` adapter | 9 |
| step container env and `/etc/hands/allowed-proxy` | 11 (rule 2), 14 |
| key proxy | 14 |
| updater, doctor checks | 15 |
| CLI groups `services`, `keys audit`, `update`, `deploy`, `deployers`, `images`, `doctor` | 2 |

phoenix9's own `phoenix.toml` (holding `safety_files` and `merge = "ask"`) lives outside code/, so the repo
carries a template (`deploy/self-project.toml`) that the chat copies into place. `safety_files` entries are
`fnmatch` globs matched against each changed path (`*` also crosses `/`; a bare folder name matches nothing
inside it); Merge flags "changes safety code" for a match (`matches_safety` in `steps/merge/run.py`). The
template lists the firewall and container launch files, the diff rules and secret scan, the secrets and key
proxy modules, the updater and its units, the agent link (`phoenix9/agentlink.py` writes to the agent's socket,
`phoenix9/transcript.py` reads its untrusted output, `deploy/agent/agent-rules.md` is its rulebook), and the
check scripts, each with the reason beside it.

## 14. Key proxy (`phoenix9/proxy.py`, phase 4)

A small HTTP forwarder Phoenix starts on the host for one step and one service. It holds that service's
account key, forwards only the declared calls, adds the key on the way out, refuses and logs everything
else, and stops with the step. The caller gets an address and a per-step token, never the key.

```python
Rule(method, path, upstream="")          # method: GET POST PUT PATCH DELETE HEAD; upstream "" = the spec's
parse_rules(items: list[dict]) -> list[Rule]           # ValueError in plain English
ProxySpec(service, upstream, auth_header, auth_format, rules, extra_headers=())
spec_from_service(service: dict) -> ProxySpec          # from service.toml's [proxy] block (see below)
serve(spec, key, *, log_path, step, bind="127.0.0.1", port=0, ports=None, upstream_timeout=30.0,
      max_body=10_000_000, allow_plain_http_upstream=False, max_in_flight=8) -> RunningProxy
                                         # .url .token .port .stop(); ports=(lo, hi): first free port
                                         # of that range, else NoFreePort (names the range)
serving(spec, key, **kw)                 # context manager; stop() guaranteed
decide(spec, token, method, target, headers, *, max_body) -> Decision         # pure: the whole yes/no
pattern_matches(pattern, path), path_is_safe(path), find_rule(rules, method, path)   # pure, public
env_names(service) -> ("PHOENIX_PROXY_<SERVICE>", "PHOENIX_PROXY_TOKEN_<SERVICE>")
```

- **Structure**: everything that decides is pure (`decide`, the matcher, path safety, `outgoing_headers`,
  `redact`); I/O is `forward` (http.client, no redirects followed), `LogWriter`, the request handler and
  `RunningProxy`. Tests check the pure parts exhaustively and the I/O against a real local server.
- **Token**: every request carries `X-Phoenix-Proxy-Token: <token>` (`secrets.token_urlsafe(32)`, compared
  with `hmac.compare_digest`; exactly one such header). Missing, wrong or repeated: 401 `bad token`.
- **service.toml `[proxy]`**: fields `upstream`, `auth_header`, `auth_format`, `key`, `allow` (all
  required, no defaults) and `extra_headers` (optional table `name = "value"`, default `{}`). Any other
  field is an error; `allow` needs at least one `{method, path, upstream?}` entry. `key` names the key
  (spec_from_service only checks it is text). `extra_headers` may not set the auth header, hop-by-hop
  headers, Host, Content-Length, Cookie, Accept-Encoding or the token header.
- **Request target**: taken raw from the request line (`requestline.split()[1]`), not `self.path`
  (which collapses a leading `//`).
- **Order of checks** (first failure wins): token (401), any caller header name or value holding `\r`
  or `\n` (a folded, obs-fold header: 400 `folded or broken header`), method in the vocabulary (405; CONNECT,
  OPTIONS, TRACE, lower case and anything else), origin-form path (403), path safety (403
  `unsafe path`: the raw path may only hold `A-Z a-z 0-9 - . _ ~ % : @ ! $ & ' ( ) * + , = /` (so no
  `;`, `#`, space, quotes or non-ASCII); before or after one percent-decode, no `.`/`..` part, `//`,
  backslash, control character, `%2e %2f %5c %00` in any case, or invalid UTF-8 encoding; a control
  character in the query is refused the same way), a matching rule (403
  `not a declared call`), body (chunked/any Transfer-Encoding 411, bad or repeated Content-Length 400,
  over `max_body` 413). Then the in-flight cap: at most `max_in_flight` (default 8) forwarded requests
  at once; one more gets 503 `too busy` straight away (logged `refused`; the body is never read).
- **Matching**: on the raw path without the query; split on `/`; `*` = one non-empty part, `**` (last
  only) = one or more parts, anything else literal and case-sensitive. `HEAD` is not implied by `GET`.
  Rules reject: unknown or lower-case methods, no leading `/`, `**` not last, empty parts (incl. a
  trailing `/`), `.`/`..`, `*`, `%`, `\`, `?`, `#` or `;` inside a part, a rule upstream that is not https.
  Accepted gap: `*` matches a part holding an allowed percent-code (e.g. `%23` or `%3B`); upstreams
  decode it as data inside that one part, so it cannot reach another path.
- **Forwarding**: upstream (rule's, else spec's, keeping its base path) + path + query unchanged.
  Caller headers dropped: hop-by-hop (and any named in `Connection`), Host, Authorization, Cookie,
  the token header, Content-Length (recomputed), Expect, Accept-Encoding (always sent as `identity`),
  the spec's auth header and any header the spec's `extra_headers` set. Then `auth_header:
  auth_format.replace("{key}", key)` (other braces stay literal) and `extra_headers` are added.
- **Listening**: `bind` defaults to `127.0.0.1` and must be an IP literal (`ipaddress.ip_address`), so
  hostnames like `localhost`, `"0"`, `""` and non-text raise ValueError; so does any unspecified address
  (`0.0.0.0`, `::`). The key is
  checked first (no spaces, line breaks or non-ASCII; the error never contains it). Handler timeout 120 s.
- **Port range**: the real adapter (`adapters.Proxy.start`) always listens on the first free port of
  the fixed range `HOME/config/global.toml` `proxy_ports = "47100-47199"` (the default when absent;
  `settings.proxy_ports()`, ValueError naming the setting when it is not `LO-HI` with
  1024 <= LO <= HI <= 65535). It tries each port in turn and moves on only on EADDRINUSE; when all are
  taken it raises `proxy.NoFreePort` naming the range. A fixed range is what lets one host firewall
  rule name the proxy (`port=0`, any free port, is for tests only).
- **Host firewall (ufw)**: with ufw active (default INPUT drop), step containers cannot reach the
  bridge gateway at all, so `deploy/install.sh` adds ONE rule: TCP from the docker bridge subnet to the
  bridge gateway, on the proxy range only, in on the bridge interface. On this server:
  `ufw allow in on docker0 from 172.16.0.0/24 to 172.16.0.1 port 47100:47199 proto tcp comment 'phoenix9 key proxy'`.
  Subnet, gateway and interface come from `docker network inspect bridge`, the range from global.toml;
  `phoenix9/hostfw.py` builds the same text for doctor (a test checks the two agree). install.sh prints
  the rule and asks (`--yes` skips the question), skips it when `ufw status` already lists it and does
  nothing when ufw is off or not installed; `install.sh --firewall-only` runs just this step on an
  installed server and `--dry-run` only prints it. Changing `proxy_ports` needs the rule changed to match.
- **Upstreams**: https with the default SSL context. Plain http only with
  `allow_plain_http_upstream=True` and host `127.0.0.1`/`localhost` (tests); the real adapter never sets it.
- **Replies**: status and headers copied minus hop-by-hop; body read fully (over 50 MB: 502); a gzip or
  deflate reply is decoded first, so the key can always be found. Every Content-Encoding header is
  read and split on commas (empty items ignored): exactly one of `identity gzip x-gzip deflate` is
  accepted; anything else (unknown, more than one coding even `gzip` + `identity`, or none in a
  non-empty header) is 502, as is a gzip body with data after its first member (multi-member); the key
  (as is, base64, unpadded and url-safe base64, percent-encoded, JSON-escaped incl. `/` as `\/`) is replaced by `[redacted]` in the body and every header; Content-Length recomputed.
  Upstream unreachable 502, timeout 504. Proxy-made replies are short plain text (`refused: <reason>`); no
  error text or traceback ever reaches the caller or stderr.
- **Log** (`log_path`, created 0600, folders made, appended under a lock), one JSON line per request,
  written before the reply is sent (a failed write is not caught: the connection closes with no reply):
  `{"ts", "service", "step", "method", "path", "query": true|false, "decision": "forwarded"|"refused",
  "reason", "status", "ms"}`. `path` has no query; no query values, headers or bodies ever. Each line
  goes through `scrub.Scrubber([key]).text()` then `scrub.scrub()`. Upstream failures are `forwarded`
  with reason `upstream unreachable` / `upstream timeout`. Where: steps `<run>/logs/proxy-<service>.jsonl`;
  `phoenix services connect` `HOME/logs/proxy-services.jsonl`.
- **Stop**: `stop()` shuts the server down, closes the socket, joins the thread (5 s), drops the key
  (`_key = None`, log scrubber emptied) and is safe to call twice. HTTP/1.0, one request per connection.
- **Container use** (wired in grunt step 04): `PHOENIX_PROXY_<SERVICE>` (url) and
  `PHOENIX_PROXY_TOKEN_<SERVICE>` (token), `<SERVICE>` = name upper-cased with `-` as `_`. The token is
  per step and useless after `stop()`.

## 15. Updater (`phoenix9/updater.py`, `phoenix9/hold.py`, `deploy/update.sh`)

Installs a release tag `v9.<n>` (git tag on the phoenix9 repo; `phoenix9.__version__` is not the release
number) over the installed copy, health-checks it and rolls back on failure (updates spec section 3).

- **Who runs it.** `updater.request(action, tag, who)` writes `HOME/update/request.json` and runs
  `systemctl start --no-block phoenix9-update.service` (oneshot, no `[Install]`). The unit runs the
  INSTALLED copy's `deploy/update.sh`, which copies the installed `phoenix9/` package into a fresh
  `mktemp -d` folder (under `/run`), runs `python3 -m phoenix9.updater run-request` from that copy and
  deletes it on exit. Why the copy: the swap renames `/opt/phoenix9`, so the code doing the swap must
  not live in a folder being swapped, and new (untested) code must never run its own install or the
  rollback. update.sh never looks at `-next`. `request` also accepts `recover` (tag ignored): the unit
  then only repairs a half-done update. `run_request` takes the lock FIRST, then reads and deletes
  `request.json` (so a second unit start never steals the running update's request). Taking the lock
  retries for `LOCK_WAIT_S` (2 s, 50 ms sleeps) before refusing, because a status check's read-only
  probe holds a shared lock for a moment. If `run_request` is still refused it leaves `request.json`
  alone but writes `HOME/update/refused.json` (never status.json, which only the lock holder writes);
  `status().last` shows it until the next locked result replaces it, so the app never shows
  "queued" forever.
- **The unit file** (`deploy/phoenix9-update.service`): `Environment=HOME=/root` (gh reads root's login)
  and `ExecStartPre=-/bin/sh -c 'test -e /opt/phoenix9 || mv /opt/phoenix9-prev /opt/phoenix9'` (an
  update that died between its two renames would otherwise leave ExecStart missing).
  `TimeoutStartSec=5h`: the worst case is ~4.5 h (web build + checks 60 m, idle wait 120 m, images
  60 m, two health checks ~31 m); a test checks the unit's timeout beats the sum of the updater's
  own timeout constants. Grunt step 13's
  install.sh must COPY the unit into `/etc/systemd/system`, never symlink it from `/opt/phoenix9`
  (the swap renames that folder).
- **Install flow** (`install(tag)`): lock (non-blocking flock; held = `refused`); tag checked against
  `TAG_RE` before it reaches any argv; `recover()`; installed tag = the highest `v9.<n>` tag pointing at
  HEAD (`git tag --points-at`, not `describe`, because `pre-v9.<n>` points at the same commit), shown
  as `unknown` when none; `already-installed` is decided by COMMIT (the tag's commit = HEAD), checked
  before and after the fetch; `git fetch --no-tags origin refs/tags/<tag>:refs/tags/<tag>` (only the
  requested tag, after the `TAG_RE` check; no `--force`) with the host gh credential helper, so
  another tag that moved on origin never blocks updates; if the REQUESTED tag moved on origin the
  fetch fails and is `refused` "release v9.N changed on origin" (found with `ls-remote`); other fetch
  failures `refused` "could not fetch";
  tag missing = `refused`; `update.started`; `git tag -f pre-<tag> HEAD`; clone `install` into
  `-next`, checkout the tag, origin url copied, HEAD verified; in `-next`: `pnpm -C web install
  --frozen-lockfile` and `pnpm -C web build` (when web/package.json exists), `./check.sh` (output to
  the checks file) - a failure is `tests-failed`, `-next` removed, install untouched; hold + wait for
  idle (5 s polls, `idle_timeout_min` default 120, else `harness-busy`); THEN `bin/phoenix images
  build --changed --json` from `-next` when `git diff --name-only <installed> <tag> -- image profiles`
  is not empty (a failing diff is an error, never "nothing changed"; images are rebuilt only once no
  run is mid-task) - failure releases the hold, drops `-next`, `images-failed`, no swap. Note: a
  rollback (automatic or manual) does NOT revert rebuilt images; swap; unit sync (below); `systemctl restart
  phoenix-runner phoenix-api`; health = `<install>/bin/phoenix doctor --for-update --json`, 3 tries
  10 s apart; healthy = the new copy's one-time migrations (`<install>/bin/phoenix settings global migrate
  --json`, section 5.5; a failure is only a log line) then `installed`; unhealthy = `-prev` back, new copy to `-failed`, restart, health
  again: `rolled-back` or `rolled-back-unhealthy` (urgent notify "Phoenix 9 may be down").
- **Unit sync** (`_Update.sync_units`, run at the start of every `restart()`): compares the INSTALLED
  copy's `deploy/phoenix-api.service`, `deploy/phoenix-runner.service` and `deploy/phoenix9-update.service`
  with the files in the systemd folder (`PHOENIX_SYSTEMD_DIR`, default `/etc/systemd/system`, the same
  setting as install.sh), copies the ones that differ (mode 0644, one swap each), then runs `systemctl
  daemon-reload` (host adapter) once if anything changed; each copied unit and the reload are lines in
  `updater.log`. A unit file missing from the copy is left alone. Because it always follows whichever
  copy is installed right before a restart, an install brings in the new units after the swap and before
  the restart, and a failed health check, a manual rollback or a recovery puts the previous copy's units
  back. Note: the update is run by the OLD installed updater (update.sh), so the first install of a
  version that adds this sync does not sync yet; units hand-edited in the systemd folder are replaced by
  the installed copy's at the next restart.
- **Rollback** (`rollback()`): refused without `-prev`, and refused "could not read the installed
  version" when git cannot read the installed commit (recovery would not know which way to go); hold + idle wait; exchange `install` and
  `-prev` (stage `-prev` as `-next`, then the same swap as an install); restart; health; healthy =
  `rolled-back-manual` (rolling back twice returns to where it was); unhealthy = exchange back,
  restart, `refused` with the doctor's lines.
- **The job and its phases.** Every install or rollback is a job saved in `status.json.job` with
  its phase, written BEFORE each step that changes something. Allowed changes are the table
  `updater.TRANSITIONS`:
  install `preparing -> waiting -> swapping -> swapped -> restarted [-> restoring]`;
  rollback `waiting -> staged -> swapping -> swapped -> restarted [-> staged -> ... with reverting]`.
  Each folder move (`_swap_in`, `_stage`, `_restore`) checks which folders exist first, so running it
  again finishes a half-done move.
- **Recovery** (`recover()`, run first by every install, rollback and run_request, under the lock):
  with a job saved, it finishes the interrupted folder move, then puts back the version that was
  installed when the job started (the last one known to work): install job before the swap = drop
  `-next`; from `swapping` on = finish the swap, new copy to `-failed`, `-prev` back. Rollback job
  at `waiting` or `staged` (not reverting) = only undo the staging (the installed copy was never
  touched; git is not asked). Later rollback phases = end with the `from` commit installed (checked
  by commit) and the other copy as `-prev`; if the installed commit cannot be read, or the job has
  no `from` commit, NOTHING is moved: result `needs-person` ("recovery needs a person: could not
  read the installed version"), the job is kept (status `interrupted`), Alex is notified, and
  install/rollback stop at that result until a person sorts it out. Then
  restart if anything had moved, release the hold, clear the job, notify, result `recovered`. With
  no job but `install` missing and `-prev` present, `-prev` is put back. A hold left without an
  update running is released. Any unexpected error inside install/rollback runs the same recovery
  at once, and so does a stop signal: `main` turns SIGTERM into SystemExit, which is caught
  (`BaseException`), recovered, and then passed on (also KeyboardInterrupt). When that in-process
  recovery moved no folders (e.g. the clone failed while preparing), the result is `refused` with
  the error text, not `recovered`. A swap that crashed is therefore never left half-done and an
  unconfirmed version is never left installed.
- **The hold** (`hold.py`): `request_hold(why)` writes `HOME/update/hold`; the runner checks
  `hold_requested()` at each task boundary (before each task, and before the run-finish steps),
  sets `current.held = true`, emits `run.held` and waits; the service loop (`watch_once`) starts no
  queued run while a hold exists. `hold_requested()` is true only while the hold file exists AND
  `HOME/update/lock` is held (`hold.lock_held()`: opened read-only, `LOCK_SH|LOCK_NB` fails; a
  missing lock file = not held, since the API may not run as root); no expiry. `harness_busy()` = some run `running` and not held ("run X (project) is on task 3 of
  7"); `waiting`, `queued` and `paused-limit` runs are not busy (a restart resumes them from
  state.json). The hold is released after the health check, in every failure path, and by recovery.
- **Restarting a service** (`phoenix9/ops/service.py`, `phoenix service restart api|runner --yes`): `runner`
  takes `HOME/update/lock` (refused "An update of Phoenix is running" when an updater holds it), asks for the
  hold, waits (5 s polls through the clock adapter, up to 30 minutes) until `harness_busy()` is false, i.e.
  every running build is held at a task boundary, then `systemctl restart phoenix-runner` (host adapter) and
  releases the hold; still busy after 30 minutes = refused, nothing restarted. `api` restarts at once and
  waits up to 20 s for `/api/health`. Both then run `doctor --quick` and print it (exit 0 once restarted;
  the report shows any problem) and record the command. API: `POST /api/service/<api|runner>/restart`
  `{yes: true}`: `api` = `systemctl restart --no-block phoenix-api` (the reply comes before the API stops),
  `runner` = a background job (kind `restart`).
- **Results**: every public function returns `{ok, result, tag, previous, reason, log}`; `result` is
  one of `installed | already-installed | tests-failed | images-failed | harness-busy | rolled-back |
  rolled-back-unhealthy | rolled-back-manual | refused | recovered | needs-person` (`request` returns `queued: true`
  and `result: null`). `status(refresh)` returns `{supported, installed: {tag, commit}|null,
  previous, newest, update_available, can_rollback, busy, busy_reason, running, waiting, phase,
  interrupted, last, log_tail, off_release, off_release_note}`; `off_release` = the installed copy's HEAD
  has no `v9.<n>` tag (installed tag `unknown`), and `off_release_note` then reads "Installed copy is on
  commit <sha>, not a release. Run `phoenix update release` then `phoenix update install`." (printed by
  `phoenix update status`, shown on the Updates panel); `running` = the lock is held (read-only probe); `interrupted` = a job
  is recorded but the lock is free (the updater died: request `recover`); `refresh` runs `git
  ls-remote --tags origin "v9.*"` and caches `newest` (skipped quietly when HOME/update is not
  writable).
- **Doctor contract** (for grunt step 12): `<install>/bin/phoenix doctor --for-update --json`; exit 0 =
  healthy; any other exit = unhealthy, and its failing lines are printed on stdout (the updater
  quotes them as the reason).
- Every log line, status reason and notify text goes through `scrub.py`; every public updater call
  (install, rollback, recover, request, run_request, status) loads the global secret env files into
  the scrubber first. Imports: stdlib plus `phoenix9.{paths, atomic,
  adapters, events, scrub, hold}`, all at module top (a test checks).

### Doctor checks (`phoenix9/doctor.py`, `phoenix doctor [--quick | --for-update] [--json]`)

`run_checks(adapters, mode) -> {ok, checks: [{name, ok, detail, fix}]}`; one failing (or crashing) check
never stops the others; exit 0 only when all pass. Details name files and modes, never values.

| Check | What it tests | quick | for-update | full |
| --- | --- | --- | --- | --- |
| `python`, `library` | Python 3.12+; the step library loads | | | yes |
| `services` | `systemctl is-active phoenix-api phoenix-runner` (host adapter) | yes | yes | yes |
| `service-home` | "services: HOME set": for phoenix-api and phoenix-runner, `systemctl show -p MainPID --value` then `/proc/<pid>/environ` (host adapter `read_text`); a stopped service is judged by `systemctl show -p Environment --value`. PROBLEM when HOME is missing or the environment cannot be read; the fix is `Environment=HOME=/root` in the unit, `systemctl daemon-reload`, restart | yes | | yes |
| `api` | GET `127.0.0.1:<PHOENIX_API_PORT from HOME/config/api.env, default 8095>/api/health` is 200; in `for-update` its `tag` is one of the `v9.<n>` tags at the installed copy's HEAD | yes | yes (tag) | yes |
| `origins` | the `origins_digest` the running API reports in `/api/health` matches the digest of the `allowed_origins` setting (an older API's `origins` list is compared as it is; section 5.5); fix: `phoenix service restart api --yes` | yes | | yes |
| `upstream` | every running `cloudflared` and `code-server` process (what sits in front of the dashboard) runs as a uid in `[access] peer_uids` (default `[0]`), and that setting is valid; passes with a note when neither is running; fix: run it as root or add its uid to `peer_uids` (section 8.5) | yes | | yes |
| `home` | HOME folders exist; `secrets/`, `keys/` 0700; their files 0600 | yes | yes | yes |
| `secrets` | `claude.env` present; `github.env` present or "github not connected" | yes | | yes |
| `images` | every profile image used by a project exists (`DockerRunner.image_exists`) | | yes | yes |
| `proxy-rule` | "firewall rule for the key proxy": `ufw status` (host adapter) lists the section 14 rule; OK when ufw is not installed or not active; the fix is the exact `ufw allow ...` line | | yes | yes |
| `firewall` | `docker.probe_firewall` with a temporary proxy on the bridge gateway (no rules, dummy key, stopped in `finally`). The detail lists only the FAILED checks (`failed checks: ...`), or `the probe container stopped early (exit N): <last error line>` when the entrypoint stopped it before the probe ran; when the key proxy is unreachable the fix is the exact ufw rule | | yes | yes |
| `claude` | one tiny session (`max_turns` 1, firewall on) exits 0 with a result event | | | yes |
| `advisor` | writes `HOME/config/doctor.json` `{advisor_available, checked_at, claude_version}` from the session's `system/init` event; `claude.session_mounts` skips the advisor mounts (and the launcher adds one prompt line) when it says false or `skills/advisor` is missing | | | yes |
| `disk` | free space on HOME and `/var/lib/docker` (`df` via host adapter): fail under 5 GB, "getting low" under 15 GB | yes | | yes |
| `updater` | `update/status.json` readable; no hold file older than 3 h without a running update; `systemctl cat phoenix9-update.service` works | | | yes |

`phoenix images build [--profile P ...] [--all] [--changed] [--json]`: `docker build -f
profiles/<p>/image/Dockerfile -t <profile.toml image> --label phoenix9.commit=<HEAD> <library root>`;
the base image (`phoenix9-step:base`, context `image/`) only with `--profile base` or `--all`. Default =
profiles used by existing projects. `--changed` keeps images that are missing, unlabelled, or whose
`image/` or `profiles/<p>/` files differ from the label's commit. Exit 1 when any build failed.
API: `POST /api/images/build` `{profiles?: [names], all?: bool, changed?: bool}` (the same choices; an unknown
profile is refused at once with 400) builds in a background job (`{job}`, kind `images`, one at a time, 409
while one runs; each progress line is a job step, `result` = the `{ok, built, skipped}` reply).

### Project chats

Each project has one remote-control Claude conversation, run by the systemd template `deploy/claude-rc-chat@.service` (instance `claude-rc-chat@<project>`, working folder `/srv/projects/<name>`, `claude remote-control --name <name> --spawn same-dir`). `install.sh` copies the template into place. Phoenix only starts and stops these units (`phoenix9/chat.py` through the Host adapter) and writes messages into the conversation's inbox socket; no AI runs in Phoenix's own processes (rule 1). A build handed to the agent (`on_failure = "delegate"`) is only a message into that same inbox (section 7); no session is started.

- **Five states** (`projectchat.state` -> `{state, bridge_session_id, web_url, app_url, last_active}`): `off` (unit inactive or failed), `starting` (unit activating, or active with no conversation yet and no chat document), `sleeping` (unit active, no live session in Claude's registry, but a chat document exists), `live` (registry entry found, idle), `working` (registry entry found, status busy). The unit state comes from systemd, the session from the registry (`agentlink.find_in`); a live session refreshes the chat document (at most every 10 minutes).
- **Chat document** `.phoenix/chat.md`: heading `# Chat: <project>`, then one `Key: value` line each, in this order: `Project`, `Desktop app link`, `Web link`, `Conversation id`, `Local session id`, `Created`, `Last active` (times are UTC `YYYY-MM-DDTHH:MM:SSZ`). Written atomically (`projectchat.write_chat_doc`), read strictly (`read_chat_doc` returns fields or a reason).
- **Links**: desktop `claude://claude.ai/code/<id>`, web `https://claude.ai/code/<id>`, where `<id>` is the conversation (bridge session) id. Opening a sleeping chat returns the links without starting anything.
- **Sleep and off rules** (`[chat]` settings): a live chat idle for `sleep_after_minutes` goes to sleep (after a `wrap_up_minutes` wrap-up message); a sleeping chat unused for `off_after_days` is switched off. Writing to a sleeping chat wakes it. The runner guard (`watch.check_chats`) runs every 10 minutes, skips projects with a live run and `home`, and records each action as a `command` event with who `runner`.
- **Creation**: every new project and every Import sets up its chat (`projectchat.set_up`), which ends sleeping; `phoenix chat catch-up` lists existing projects without a chat document (`phoenix9` and `home` have their own), and `--all` sets them up one at a time.
- **Commands**: `phoenix chat open|sleep|off|catch-up` (`phoenix9/cli/chatcmd.py` over `phoenix9/ops/chat.py`: `open_chat`, `sleep_chat`, `off_chat`, `chat_state`, `catch_up`); `off` needs `--yes`.
- **Sender labels**: messages written into a chat say who sent them: `Phoenix (<who>)` for the CLI, runner and agent (who is cleaned to `[A-Za-z0-9/_.:-]`, 80 characters, else `unknown`) and `Alex (Phoenix panel)` for the dashboard panel.

Branch tidiness: main is the only long-lived branch. New GitHub repos get "automatically delete head branches" switched on (`gh repo edit --delete-branch-on-merge`; a failure is a "Warning:" line in the create steps, not a failed create). After the Merge step merges a run itself (auto mode, or a local-only approve) it removes the run's worktree (`git worktree remove --force`, run from the code folder through the git adapter) and deletes the run's branch locally and on origin when it was pushed; a failed removal or delete is a note on the step, not a failure (a worktree that cannot be removed is detached instead, so the branch can still go). A failed merge, and a failed run, keep their worktree for repair. A push that fails with git's "could not read Username" (no HOME, so no gh credential helper) fails the step with "Phoenix's worker can't reach your GitHub login: run `phoenix doctor`"; other push failures read "GitHub refused the push: <first line>". When the merge is left to GitHub (a merge request) nothing is deleted, the worktree included; GitHub's auto-delete does it. Stopping a run (`run stop`, or a stop answer at a gate) removes its worktree and local branch, and the remote branch if it was pushed (`runs.discard_branch`).

Discarding a run: a failed run keeps its worktree and branch (so it can be repaired) until `phoenix run discard
<run> --yes` (API `POST /api/runs/<project>/<run>/discard` `{confirm: true}`, the Build tab's "Discard work"
button on a failed or stopped build) throws them away with the same `runs.discard_branch` (worktree, local
branch, GitHub branch when it was pushed). The caller is checked like a stop (`ops.runs._may_stop`: a `chat:*` caller needs
the project's `home_chat_may_answer` to list `escalation`). Only `failed` and `stopped` runs can be discarded (queued,
running, waiting, paused-limit and done are refused; a second discard is a conflict). A failed run can still
hold work: the Merge step may have opened a merge request before a task failed the run. So discard refuses
(`WouldLoseWork`, API 409 `needs_force`) when the run's merge-request.txt names a request GitHub doesn't report
as MERGED or CLOSED (no answer counts as open) or when the run branch (local, else origin's copy) has commits
main lacks, unless `--force` / `force: true`. The Build tab's dialog says this up front; on the refusal it shows
a second dialog listing what would be lost, whose button "Discard anyway and lose this work" sends `force`.
It sets state.json `discarded: true`, `discarded_at`, `discarded_by` (plus `discard_forced` when forced; the
status stays as it was), writes a `run.discarded` event
and the command record; the Build tab then says "Work discarded" and the ledger row "work discarded".

## Reply blocks and dashboard control

(Agent build 3. Each task appends its own notes here.)

### Cards (`phoenix9/cards/`, `ops.cards`, `GET /api/cards`, `phoenix card`)
- A card type is a module in `phoenix9/cards/` (`-` written `_` in the file name). It has `schema` (allowed
  query key → type name), optional `inline = True`, and `build(query) -> {title, data, actions, watch}`.
  `cards.load`, `cards.types` and `cards.check_query` (returns a plain reason or None) live in `__init__.py`.
- `ops.cards.build(type, query, title)` returns `{type, title, data, actions, watch, inline}`; an unknown type or
  bad query is an `OpsError` (API 400).
- `projects` card: `names` keeps only those projects, in that order (the `top`/`rest` split is kept; `total` is the kept count).
  Its title is "Projects that need you" when `attention` is true, which the CLI summary uses.
- `run` card: `run_id` may be `latest` (the newest run of the project; none is a 404). Stop is offered while the run's
  status is in `status.ACTIVE`, with body `{"confirm": true}` as the Build tab sends it.
- `builds` card: `limit` 1-20, default 5 (outside that is a 400).
- `phoenix card <type> [--query JSON] [--title T] [--json]` prints the summary line, the fenced `phoenix-card`
  block (only `v`, `type`, `query`, `title`), then the summary again. `--json` gives `{summary, block, card}`.

- `repair` card: query `{project, run, note?}` (`note` = a file name in the run's `repairs/notes/`, default the
  newest). Data `{run_id, project, status, status_line, findings: [{code, text, task}], note: {name, text,
  dry_run} | null}`; `dry_run` is the dry-run outcome of the note (or `{error}`), `actions` is empty (the buttons
  live in the card body and call `POST /api/repair/<run>/apply`); it watches types `run` and `repair`.

### Pull requests (`ops.github.prs`, `prs` card)
- `ops.github.prs(project=None, state="open")` runs `gh pr list --repo <owner/name> --state <state> --json ...` through the Host adapter and returns rows `{project, number, title, state, draft, checks, url, updated_at}`. Answers are cached in memory for 60 s per (repo, state); a gh failure gives `{project, error}` for that project.
- The `prs` card lists those rows with one link per pull request. Each `projects` card row also carries `needs_merge` and `pr: {number, title, url}` (true when the project has an open, non-draft pull request).

### Log, diff and update cards
- `log` card (`project`, `id`, `tail` or `lines`): the last lines of `ops.logs.read` (already scrubbed). Count is clamped to 1-200 (default 50); `truncated` is true when lines were cut. Action: route `p/<name>/logs` with param `log`.
- `diff` card (`project`, `id`): refuses logs whose kind is not `diff`. Data is `files: [{name, added, removed, lines}]` from at most 2000 lines.
- `update` card (no query): data is `ops.update.status()`; actions are a route to `settings` (param `section: updates`) and, when an update is available, Install = `POST /api/update/install` body `{yes: true, tag: <newest>}` (as the Install button sends it), `confirm`, `danger`. Watches event types `["update"]`.

### Inline cards: settings-preview, table, chart
- Inline cards (`inline = True`) carry the agent's proposed content in `query`; their data has `footer: "proposed by the agent"`.
- `settings-preview` (`project`, `set` with 1-20 dotted keys): rows `{key, before, after, ok, reason}`; `before` comes from
  `ops.settings.show`, `ok`/`reason` from `ops.settings.dry_check` (the same validation as `set_many`, writes nothing).
  Safety keys (`ops.settings.is_safety_key`: `domains.*`, `diff.*`, `safety_files`, `services`, `home_chat_may_answer`,
  `profile`, any key naming a tool or MCP server such as `steps.*.tools`/`tools_denied`/`mcp_servers`, and every key of a
  `safety = true` step) are never ok here: their reason says "change this in Settings yourself" (`dry_check(..., agent=True)`).
  Apply = `POST /api/projects/<name>/settings` body `{set: {...}}` holding only the ok rows ("Apply n of m" when some are
  left out), with `confirm` listing exactly those; absent when no row is ok.
- `table` (`columns` 1-8, `rows` at most 50 lists, one cell per column, text cut to 200 characters) and `chart`
  (`kind` bars|spark, default bars; `series` of `{label, value}`, at most 20 for bars, 60 for spark) refuse bad shapes with a plain reason.

### Route catalogue (`phoenix9/routes.py`, `web/src/lib/routes.ts`)
The pages the agent may point at: `projects`, `new`, `p/<name>/overview|build|logs|settings`, `settings`, each with
an ordered param list. The two files hold the same list (`tests/test_routes.py` compares them). `routes.resolve(to,
params)` refuses unknown routes and params, a missing project, a gate that is not open, a missing run or log, a
wizard slide outside 1-7, a settings key not in the schema and a section not allowed (project settings: `project`,
`build`; Phoenix settings: `services`, `models`, `updates`, `addresses`). It returns `{hash, label}`; the label is a
breadcrumb such as `test-site › Settings › Build`. A run is accepted when it matches the run-id pattern (`runs.RUN_ID_RE`, `YYYYMMDD-HHMMSS-slug`, so `..` or `logs` never pass) and its folder exists.

### Dashboard address and `phoenix nav`
- `ops.app.dashboard_url()` returns env `PHOENIX_DASHBOARD_URL` (if a usable http(s) address), else the saved
  `dashboard_url`, else the default; `ops.app.info()` reports it.
- `phoenix nav <to> [--param k=v ...] [--check] [--json]` resolves the route with `routes.resolve`, then prints the
  label, the link (dashboard address + hash), a `phoenix-nav` block and the fallback line "Open <label>: <link>".
  A route that cannot be resolved prints the reason and exits 1. `--check` prints only `ok` or the reason.

### Deep links on Build, Logs and Settings pages
- Build tab: `run=<id>` opens that run; `wizard=N` opens the wizard on slide N (1-7, larger numbers clamp to 7; `new=1` still means slide 1).
- Logs tab: `run`, `step`, `task`, `kind` set the same filter state the controls set; `log=<id>` opens that log (the older `id=` is still read).
- Project settings: `section=project|build` opens and scrolls to the section; `key=<dotted key>` scrolls to the row holding that setting (rows list their keys in `data-settings`; a row listing `deploy` holds `deploy.*`) and glows it for 2 s.
- Global settings: `section=services|models|updates|addresses` opens that tab (the older `tab=` is still read; tabs now write `section=`).
- Shared helper `web/src/lib/focus.ts` (`scrollToAndHighlight`, `useScrollToId`): scrolls to the element (no animation under reduced motion) and adds the `focus-glow` class for 2 s. The Overview page uses it too.

### `phoenix ui go`
- `ops.ui.go(to, params, who)` resolves the route with `routes.resolve`, emits event `ui.go` (project null) with
  `{hash, label, by: "agent"}` on the global stream, and records a `command` event. `phoenix ui go <to> [--param k=v ...]`
  and `POST /api/ui/go {to, params}` call it; a bad route is exit 1 / HTTP 400 with the reason. Projects searches go
  only through the `projects` route params (`q`, `status`, ...).
- Task 10 (panel follows ui.go): `AppShell` feeds `ui.go` events to `useUiGo(open)` (`features/agent/uiGo.ts`). Panel open: set the hash through `navigateKeepingPanel` (`features/agent/navigate.ts`) and show "Moved to <label>" with Back (returns to the hash seen just before the latest move). Panel closed: ignored.

### Block check (`ops.blocks.check`, `POST /api/blocks/check`, `phoenix block check`)
- `check({kind, json})` returns `{ok, reason, resolved}`. Not ok (bad JSON, missing or wrong `v`, unknown keys, an `actions` key, over 8 KB, bad values) is a result, not an error; `resolved` is then null.
- card: `resolved` = `{type, query, title}` after `cards.check_query`. nav: each link goes through `routes.resolve`; `resolved` = `{links: [{hash, label}], dropped: [{link, to, reason}]}`, all failed = not ok. choice / confirm: `resolved` = the normalised block (`other` and `danger` default false; option keys must be unique).
- `phoenix block check <file|-> [--kind K] [--json]` reads a fenced block (kind from the tag) or bare JSON (needs `--kind`); exit 1 with the reason when not ok.

- `phoenix choice` / `phoenix confirm` (task 12) print a checked block plus one fallback line; `--json` gives `{block, fallback}`.

### Block parser in the panel (task 13)

`web/src/features/agent/blocks/parse.ts` splits agent markdown into text and `phoenix-*` block parts; the first non-empty line after a block is its fallback. `BlockView` checks each block once through `/api/blocks/check` (cached in memory by kind and text) and hides the fallback when the block renders; otherwise it shows the fallback plus "block could not be shown: <reason>". Only `AgentMessage` uses it. Items before the latest conversation divider are frozen (`frozen` prop, "as of <time>" line, no buttons). An unclosed `phoenix-` fence stays plain text.

#### AnswerCard and card buttons (task 14)
`web/src/features/agent/blocks/AnswerCard.tsx` fetches `GET /api/cards` for the checked card, shows loading and error
states, and refreshes (debounced 500 ms) on a live event matching `watch` (empty list = any; `command` and `ui.go`
events never match) or every `poll_s`. Frozen cards fetch once and show no buttons: `AnswerCard` passes `frozen` to the body, and the gates body shows its Needs-you cards `readOnly` (no answer buttons, no Review link). Bodies are picked by type from
`cardBodies.tsx` (plain JSON until tasks 15-17). `CardActions.tsx` draws the buttons from the answer only: link = new tab
(`rel="noopener"`), route = `navigateKeepingPanel`, op = the same POST route and body as the dashboard button (the
server records who=`dashboard`), behind the shared `ConfirmDialog` when `confirm` is set. A success shows a result line and
sends one `[Phoenix panel · button] <label> done` note; a failure shows only the reason. Only POST and GET ops are supported. A `link` action opens only an absolute http(s) address (`web/src/lib/safeUrl.ts`, shared with the prs body); any other href is not rendered.

### Card bodies: projects, gates, run, builds (`web/src/features/agent/blocks/bodies/`)
- `projects` shows `ProjectTile` (`web/src/features/projects/ProjectTile.tsx`, the Projects page row, now shared; without `onRemove` the Remove button is left out) plus a "PR #n waiting to merge" link (`.p-pr`, above the tile's click overlay) when `needs_merge`. `gates` reuses `NeedsYouCard` (compact), `run` reuses `StepList`, `builds` is a list of run id, result badge and relative time linking to the Build tab.

Task 18 (ChoiceBlock): `AgentMessage` and `BlockView` pass `later` (texts of the user items after the agent message) to blocks. A choice is answered, read-only, when a later user item starts with `[Phoenix panel · choice <id>` (followed by `]` or ` ·`); its answer text shows as "You chose: …". Multi mode joins labels with ", "; the "Other:" tile has its own text field and Send button.

### Documents: ids, API and CLI (`phoenix9/ops/docs.py`, task 21)
Documents are addressed by `run:<run id>/<path>` (inside the run's folder) or `notes:<project>/<path>` (inside the project's notes folder), never by a server path. Only `.md` and `.txt` are served; `..`, empty or absolute parts and anything that resolves (symlinks followed) outside the folder are refused. A document is opened once (`O_NOFOLLOW`, never reopened by name) and the kernel's path of the open file (`/proc/self/fd/<fd>`) must be inside the real folder, so a folder swapped for a symlink mid-request cannot reach outside; a file that is gone, unreadable or not a regular file is NotFound (404). `list` reads only the first 4 KB of each file for its title (a last line cut by that limit is dropped). `list`, `show` and `download` skip the same folders: `logs/`, `gates/`, `.git/` and any folder starting with `.` (NotFound). Text is scrubbed with the project's scrubber. `GET /api/docs/list|show|download`, `phoenix doc list <run>` and `phoenix doc show <id>` (both with `--json`). A gate link to a document is `{label, doc}` instead of `{label, url}` (planner: `run:<id>/plan.md`, merge: `summary.md`); the panel opens it at `#/doc?path=<id>` (task 22), rendered with the safe markdown renderer, so no server-rendered HTML page exists.

### Block formats and panel messages (summary)
- Blocks are fenced code with language `phoenix-card`, `phoenix-choice`, `phoenix-confirm` or `phoenix-nav`, one JSON object with `"v": 1`, at most 8 KB, unknown keys refused (an `actions` key too). card: `{v, type, query?, title?}`; nav: `{v, links: [{to, params?, label?}]}` (1-8); choice: `{v, id, question, mode: single|multi, options (2-8, at most one recommended), other?}`; confirm: `{v, id, action, command, danger?}`. `id` is 1-40 letters, digits, `-` or `_`. Every text field (question, option keys, labels and details, action, command, card title, nav labels) must be one line: control characters (newlines and tabs too) and line/paragraph separators are refused, and so is the text `[Phoenix panel` in any case, so a block cannot forge a panel answer. Blocks are parsed only from the agent's own text items, never from user bubbles or `ActionCard` excerpts.
- Cards carry only `type`, `query`, `title`; the panel fetches data from `GET /api/cards` and never trusts numbers in a block. Buttons come from the card builder only.
- Panel messages (sent through `/api/agent/send`, one each): `[Phoenix panel · choice <id>] <label>` (multi: labels joined by ", "), `[Phoenix panel · choice <id> · other] <text>`, `[Phoenix panel · confirm <id>] yes` / `no`, `[Phoenix panel · confirm <id> · other] <text>`, `[Phoenix panel · button] <label> done`. Every panel message is sent as one line (`blocks/oneLine.ts` turns control characters and line breaks into spaces).
- A confirm or choice counts as answered when a later user item starts with `[Phoenix panel · confirm|choice <id>` followed by `]` or ` ·`.

### ConfirmBlock, NavBlock, agent rules and demo (tasks 19-20)
- ConfirmBlock shows the action and exact command with Yes / No / Other. The agent runs the command, never Phoenix. It is read-only once answered or frozen and then shows "You answered: ...".
- NavBlock shows only the resolved links, leaves dropped links out, shows nothing when no link resolves, and disables its buttons when frozen.
- `deploy/agent/agent-rules.md` is the agent's rules file. `tests/seed_demo.py` plus `web/e2e/agent-blocks.spec.ts` make the demo and the end-to-end check.
- The `#/doc?path=<id>` page is not in the route catalogue, so the agent cannot `nav` or `ui go` to it.

### RunDocs (task 22)
`web/src/features/docs/RunDocs.tsx` lists `docs/list?run=<id>` and shows View/Download only for `plan.md` and `summary.md` ids (LogsTab, RunningView and the run card body use it); it renders nothing when the list is empty or the request fails.

### Edits and plans cards, agent wiring
- `edits` card (`project?`): rows `{id, project, title, status, last_activity, pr}`; actions link each merge request and give
  Abandon (`POST /api/edits/<id>/abandon` `{confirm: true}`, `confirm`, `danger`) on open or stalled edits.
- `plans` card (`project?`): rows `{id, project, brief, status, spec, open_questions, last_activity}`; Abandon
  (`POST /api/plans/<id>/abandon`) on queued, waiting, done or failed sessions. A running session cannot be abandoned.
- `phoenix plan reply <id> --text` queues a waiting session again with Alex's words; `phoenix plan abandon <id> --yes`.
- `phoenix agent brief` also returns `work`: one line per open quick edit and queued, running or waiting planning session.
