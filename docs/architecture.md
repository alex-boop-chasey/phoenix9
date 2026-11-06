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
  pytest is the only dev dependency and is already installed system-wide for root and the grunt user.
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
                               keys.py update.py deploy.py (also `deployers`) images.py doctor.py
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
  runner.py                    the step runner (phase 1 = run-level + simple task loop; phase 2 = full)
  failmodes.py                 retry / escalation / on_failure handling (section 7)
  aistep.py                    prompt rendering and helpers shared by the ai steps
  checklock.py reports.py      locked task checks (fingerprints); test report readers + verdict fallback
  summary.py                   run summary facts -> summary.md / summary.html (assets/summary.html)
  chat.py                      the `chat` adapter: delegate mode (section 9)
  templates.py images.py       templates menu loader; profile Dockerfile checks
  stepctx.py                   StepContext and StepResult (section 4.4)
  claude.py docker.py git.py watch.py   ports of V8, adapters (section 9)
  scrub.py                     secret redaction for every log line written
  project.py                   phoenix project (proj folded in) (phase 2)
  keys.py                      per-project keys (phase 2; global secrets store phase 4)
  services.py                  services library loader (phase 2); project_services.py: a project's set
  proxy.py                     key proxy (phase 4)
  assets/                      static files the package ships (summary.html)
  updater.py                   install / roll back a release tag, with recovery (phase 4, section 15)
  hold.py                      the update hold: runs stop at a task boundary; harness_busy() (phase 4)
  deploy.py                    deployers runner (phase 4)
  doctor.py                    the `phoenix doctor` checks (phase 4; section 15); ops/doctor.py runs them
  images (ops/images.py)       `phoenix images build`: build the profile images, label `phoenix9.commit`
  stepproxy.py                 starts the key proxies a step's `proxy` key asks for (section 14)
  api/server.py                phoenix-api: JSON API + SSE + static web/dist (phase 3)
steps/<name>/                  step library: step.toml + prompt.md (ai) and/or run.py (script)
steps/_delegate/               delegate-mode prompt (a `_` folder: not a step, the loader skips it)
steps/_things.toml             every "thing" a step can need/produce, with its fallback
presets/<name>.toml            simple, quick, full (custom = no file; it is "start from a preset")
profiles/<name>/profile.toml   web, mobile, desktop, python-script, research, platform (+ image/Dockerfile)
services/<name>/service.toml   expected project keys + hosts (phase 2); recipes, proxy rules (phase 4)
deployers/<name>/deployer.toml deployers library, section 4.7 (+ deploy.py)
templates/<name>/template.toml project templates menu (phase 2)
image/                         base step image files ported from V8 (init-firewall.sh, entry.sh, ...)
deploy/                        phoenix-api.service, phoenix-runner.service, phoenix9-update.service, install.sh,
                               update.sh, self-project.toml (section 15); README.md for the server owner
web/                           React app (phase 3)
                               src/pages, src/features/<area>, src/components/ui (shadcn), src/lib (api client, types, theme), e2e/ (Playwright)
tests/                         pytest; tests/fakes/__init__.py holds every fake adapter; tests/helpers/ shared test helpers
CLI groups (`phoenix <group> --help`; each writes a `command` event when it changes something):
  run gate settings steps profiles presets project doctor api   phases 1-3
  services list|connect|test|disconnect|recipes   account services and their keys (section 4.6)
  keys audit                                  which keys exist, where used, problems (never a value)
  models list|set                             Phoenix's default models per AI step (global.toml [models])
  update status|install|rollback|log|release  the updater (section 15); install and rollback only queue
  deploy now|status, deployers list           deployers (section 4.7); `deploy now` needs --yes
  images build                                build the step images, label `phoenix9.commit`
  doctor [--quick|--for-update]               the checks in section 15
(reference/ held read-only copies of V8, proj and the project-selector for porting; it was removed at
 the end of phase 4. `# ported from reference/...` comments remain as history.)
```

## 3. Where things live at runtime (`phoenix9/paths.py`)

| Name | Default | Env override | Holds |
| --- | --- | --- | --- |
| HOME | `/var/lib/phoenix9` | `PHOENIX_HOME` | everything below |
| config | HOME/config | | `global.toml` (non-secret global settings; `proxy_ports = "47100-47199"` (key proxy port range, section 14); `[update]` table: `project = "phoenix9"`, `repo = "alex-boop-chasey/phoenix9"`, `tag_prefix = "v9."`, defaults when absent; read by `settings.read_global()`; `[[removed_projects]]` rows `name`, `path`, `repo`, `removed_on` for projects taken off Phoenix's list by `phoenix project remove`, section 3 of `docs/design/phase-4-5-project-list.md`), `services.toml` (which account services are connected: names only, never values), `api.env` (`PHOENIX_API_PORT=<port>`; written once by `install.sh`, read by the API unit and by doctor; default 8095), `doctor.json` (advisor availability, written by the doctor's `advisor` check, section 15) |
| secrets | HOME/secrets (0700) | | `<name>.env` files, 0600: `claude.env`, `github.env`, `telegram.env`, `service-<name>.env` |
| keys | HOME/keys (0700) | | per-project keys `<project>.toml`, 0600 (section 10) |
| runs | HOME/runs/<project>/<run-id>/ | | run folders (section 7) |
| work | HOME/work/<project>/<run-id>/ | | the run's git worktree of the project's code/ on branch `phoenix/<run-id>` (removed when the run ends; the branch stays) |
| logs | HOME/logs | | `commands.jsonl` (who ran what), `updater.log`, `api.log` |
| cache | HOME/cache | | recomputable data, e.g. `sizes.json` (project folder sizes, refreshed in the background) |
| events | HOME/events.jsonl | | global event stream (section 8) |
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
chat link, environment id, services set up: `services_set_up` is a list of `{name, at, run, run_name}`; older
files may hold plain name strings), `.phoenix/deploys.jsonl` (one line per deploy or preview attempt;
fields in section 4.7). The environment id is found by a background journal search (newest first, stops at the first
hit, skipped when the chat is off) that the Projects list waits for at most 1 s, like folder sizes; until found the chat link reads as not ready.

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
  name): `once = true` (task step) runs on every attempt until it has passed once, then never again
  for that task; after the once-steps the worktree's commit is the task's `attempt_base`.
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
`screenshots` (bool), `suggested_deployer`, and a `[test]` block:
- `cmd` (full suite command, = `{{suite_command}}`), `task_cmd` (optional, a single task's checks);
- `report`: one of `pytest-junit | vitest-json | playwright-json | exit-code`, or a list of them
  (e.g. `["vitest-json", "playwright-json"]`), and `report_path`;
- `checks_dir` (where locked task checks live in the repo), `check_files` (glob(s), space-separated, the
  check writer must use), `check_command` (runs given check files; `{files}` = space-joined paths) and
  `report_args` (appended so the report reader finds its file in `/out`).

Optional `[steps.<name>]` tables override step defaults (layer 2 in 5.1).
The profile's container image files live in `profiles/<name>/image/`.

### 4.6 Service folder: `services/<name>/service.toml`

```toml
name = "supabase"                 # = folder name
title = "Supabase"
description = "Postgres database, auth and file storage."
support = "store-and-wire"        # "store-and-wire" | "keys-only"
docs = "https://supabase.com/docs"
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

```toml
preset = "quick"              # simple | quick | full | custom
profile = "python-script"
merge = "auto"                # auto | ask
max_tries = 3                 # tries per task (harness spec 13); the one place this is set
on_failure = "pause"          # continue | pause | delegate
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

### 5.3 The ai block (any ai step; harness spec section 5)
`model`, `fallback_models` (list), `tools` (list, empty = Claude default), `tools_denied` (list),
`mcp_servers` (list of names from the registry), `claude_md` (`library` | `project` | `both`),
`skills` (list of skill folder names), `max_turns`, `timeout` (minutes), and
`[advisor]` `on`, `model`, `when` (list of `blocked` | `before-done` | `on-demand`), `instructions`.
The advisor is passed to the session as a mounted skill plus settings; Phoenix does not run it.
**Unverified:** that `/advisor` exists in headless `claude -p`; `phoenix doctor` reports whether it does
and the session is told to carry on without it when absent.

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

## 7. Runs

- Run id: `YYYYMMDD-HHMMSS-<spec-slug>` (UTC). Branch: `phoenix/<run-id>`.
- Folder `HOME/runs/<project>/<run-id>/`:
  `spec.md` (copy, read-only), `spec.json`, `settings.json` (frozen effective settings), `plan.json`
  (resolver output), `state.json`, `events.jsonl`, `tasks/<n>/attempt-<k>/` (`prompt.md`,
  `session.jsonl`, `diff.patch`, `checks.txt`, `result.json`), `gates/<gate-id>.json` and
  `gates/<gate-id>.answer.json`, `logs/<step>.log`, `summary.md` and `summary.html`; also `plan.md`
  (Planner), `progress.md` (Commit), `merge-request.txt` / `merge-note.md` (Merge).
- `state.json`: `{run_id, project, status, created, updated, current: {group, task, step, attempt,
  gate}, tasks: {"1": {title, status, tries, failures: [..], depends_on: [..], escalations, flagged,
  gate, attempt_base, delegate, note, rerun}}, steps: [ {group, task, step, attempt, status, started,
  finished, note, gate, produces, reasons, answers} ], usage: {cost_usd, sessions}}`.
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
  - task `tries` = the attempt being worked on (0 = not started). `escalations` = acknowledged
    escalations so far (max `failmodes.MAX_ESCALATIONS` = 2). `flagged` = why it failed (Build tab,
    summary). `gate` = the task's own gate (human-task or escalation). `attempt_base` = the commit
    each attempt starts from (a failed attempt is reset to it; an outside fix moves it).
    `delegate` = `{gate, handle, started_at, log, notified}` while the project chat has the
    escalation. `note` = why it was skipped ("depends on task 1, which failed", "skipped by cli").
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
  - `once` steps (e.g. Checks) are skipped once they passed in an earlier attempt; a failed once-step
    runs again. attempt_base is taken before the first non-once step (fallback: HEAD at attempt start).
- The attempt loop (`phoenix9/runner.py` + `phoenix9/failmodes.py`, harness spec 13): a task runs
  attempts of its task steps. A failed attempt (a step `fail`, or a crash: "step <name> crashed: ...")
  adds its reasons to `failures` and is retried until `max_tries`, unless it was already escalated,
  a reason starts with `SPEC_PROBLEM` or `AUTH_ERROR`, or it failed for exactly the same reasons as
  the attempt before. Then `on_failure`: `continue` = task `failed` + flagged, dependents `skipped`;
  `pause` = escalation gate + one notify; `delegate` = the same gate (flag "delegated to project
  chat") handed to the project chat (section 9 `chat`, 12). `acknowledged` = commit any outside fix,
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
- Queue: a run starts as `queued`. The runner service takes the oldest queued run when no run is
  `running`/`waiting` anywhere (one build at a time across the server, decision 2026-11-01). Restart
  resumes `running` runs from `state.json`.

## 8. Events and gates

- Event line (JSON): `{"ts": iso, "type": "...", "project": ..., "run": ..., "task": n|null,
  "step": name|null, "data": {...}}`. Written to the run's `events.jsonl` and to HOME/events.jsonl.
  Types: `run.queued run.started run.finished run.step.started run.step.finished task.started
  task.finished gate.opened gate.answered project.created project.changed settings.changed
  update.started update.installed update.failed update.rolledback deploy.finished run.held command`.
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
  waiting run ends it; a later answer is ignored.
- Answer file `gates/<gate-id>.answer.json`: `{action, note, who, at}`. Written only by
  `gates.answer()` (CLI `phoenix gate answer`, API, Home chat through the CLI). The runner polls for it.
  Gate ids: `<run-id>.<n>`.

## 8.5 The API (phoenix-api, phase 3)

- Stdlib `ThreadingHTTPServer` on 127.0.0.1 (port 8090 once installed). JSON under `/api/...`, the
  event stream at `/api/events` (server-sent events; each event's id = its line number in
  HOME/events.jsonl, so `Last-Event-ID` resumes), everything else = static files from `web/dist`.
- Writes (POST/PUT/DELETE) need header `X-Phoenix: 1` and an `Origin` in `PHOENIX_API_ORIGINS`
  (comma list; default the code-server address). Revealing a key is a POST for that reason.
- The web app uses hash routes (`#/`, `#/new`, `#/p/<name>/<tab>`, `#/settings`) and relative asset
  and API paths, so it works behind code-server's `/proxy/<port>/` prefix.
- Endpoints and the ops function behind each are listed in `docs/api.md` (written in phase 3 step 1).
- The wizard's "remember these" writes its answers into the project's phoenix.toml (preset, steps
  on/off, per-step ai settings, max_tries, on_failure, merge, deploy); "notifications" = `steps.notify.on`.

## 9. Adapters (everything external, each with a fake in tests/fakes/)

| Adapter | Real | Fake |
| --- | --- | --- |
| `docker` | V8 docker.py port: run a step container with limits, firewall, mounts | records calls, returns scripted exit codes and files |
| `claude` | V8 claude.py port: `claude -p` stream-json in the container, usage-limit and model-unavailable detection | scripted sessions: writes given files into the worktree, returns given result/usage |
| `git` | V8 git.py port: clones, worktrees, safe flags, diffs | real git on temp repos (git is always available) |
| `host` | systemctl, journalctl, `gh`, `du`, filesystem outside HOME | records calls, returns canned output |
| `http` | urllib for service/deployer APIs | canned responses per (method, url) |
| `clock` | time.time / sleep | manual clock |
| `notify` | Telegram: write `/srv/phoenix-inbox/jobs/notify.msg` (phoenix-notify.path sends it) | list of messages |
| `proxy` | `Proxy.start(spec, key, *, log_path, step, bind)` starts the per-step key proxy (`proxy.serve`, section 14) and returns its handle | `FakeProxyFactory`: forwards nothing and listens nowhere; records `(service, rules, step, bind, key_len, key_seen)` (never the key), returns a handle with `url = http://proxy.fake/<service>`, a fixed token and a recorded `stop()`; `.started`, `.stopped`, `.running()`. Tests script `FakeHttp` at that url |
| `chat` | delegate mode (`phoenix9/chat.py`): `delegate(project, project_dir, gate_id, prompt, log_path) -> {started, handle, error}` starts a detached headless `claude -p <prompt> --permission-mode bypassPermissions --output-format text` in the project folder (own session, output to the log, env `PHOENIX_WHO=chat:delegate`, never `--bare`); `status(handle) -> running \| exited` (section 11, rule 1 exception) | `FakeChat.mode`: answer (acknowledges as chat:delegate) / exit / run / fail |
`phoenix9/adapters.py` builds the real set; tests build the fake set. Nothing else in the code calls
`subprocess` for these tools directly.

## 10. Keys and secrets

- Project keys: `HOME/keys/<project>.toml` (0600): `[[key]] name, value, secret (bool)`. Never in the
  repo or notes/. Non-secret keys are also written to `code/.env.example` (names and values; secret ones
  as `NAME=` with no value). Secret values are added to the scrub list of every run of that project.
- Global secrets: `HOME/secrets/<name>.env` (0600), read only by the host process that needs them.
- The dashboard's Reveal button (behind the code-server login) is the only way to see a saved
  secret value; the CLI has no reveal.
- Values are never printed by any command (`phoenix keys` shows `••••••`), never passed on a command
  line (read from stdin or a file), never logged. `scrub.py` redacts every known secret value.

## 11. Fixed safety rules (always on; harness spec 8)

1. No AI runs in Phoenix's own processes. Claude only runs inside step containers. One recorded
   exception: the `delegate` failure mode starts a headless Claude session in the project folder with
   the same permissions as the project's own chat (Alex's decision: the project chat agent handles it).
   It is a separate process, never imported or driven step-by-step by the runner. `phoenix9/chat.py`
   is the only place in phoenix9 that starts Claude on the host.
2. Step containers never get the Docker socket, the GitHub token, SSH keys or account service keys.
   They get the Claude token, the project's secret keys as env vars, and the proxy address plus a
   per-step proxy token (phase 4; the token only identifies the step to the proxy, it is not a service key).
   Container env (built by `Claude.launch` / `docker.py`): `PHOENIX_PROXY_<SERVICE>` (the proxy URL) and
   `PHOENIX_PROXY_TOKEN_<SERVICE>`; `docker.py` refuses any other added name that does not start
   `PHOENIX_PROXY_`. The firewall opens only the proxy's `IP PORT`, read from the file mounted at
   `/etc/hands/allowed-proxy`; the proxy host is the Docker bridge gateway.
3. Phoenix trusts only exit codes, files it wrote, reports it read itself and git objects in its own
   worktrees. Nothing a session *says* counts.
4. The spec is mounted read-only; locked checks are fingerprinted (when Check-writer is on).
5. Every git command on an untrusted checkout uses `-c core.fsmonitor=false -c core.hooksPath=/dev/null`.
6. Default diff denylist: `.git`, `.github/workflows`, `.env*`, symlinks, submodules, `CLAUDE.md`,
   `.claude/`, `.mcp.json`, locked check files. Everything else is allowed unless the project denies it.
7. Never `claude --bare` (it ignores the OAuth token).
8. Secrets scrubbed from every log line written to disk.

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
- **Delegate mode** (harness spec 13): the escalation gate opens exactly as in pause mode, with the
  flag "delegated to project chat"; the runner renders `steps/_delegate/prompt.md` (a `_` folder, so
  the library loader skips it) and starts the project chat once through the `chat` adapter, then
  forgets it. The chat either fixes the cause in the run's worktree and answers the gate
  `acknowledged --who chat:delegate`, or ends with `DELEGATE GAVE UP: <why>`. Alex is told once
  (with the last 20 scrubbed lines of the delegate log) when it could not be started, has exited
  without answering, its handle is gone after a restart, or 60 minutes passed
  (`failmodes.DELEGATE_TIMEOUT_MIN`); the run then simply waits as in pause mode. Anyone's
  `acknowledged` continues the run. The delegate is never started twice for one gate.
- **Chat link**: a project records `chat_session_url` when known (`phoenix project set-chat`) and always
  knows the environment link parsed from `journalctl -u claude-rc@<name>`
  (`https://claude.ai/code?environment=env_...`). The Projects page shows the session link if recorded,
  else the environment link.

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
proxy modules, the updater and its units, and the check scripts, each with the reason beside it.

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
  rollback (automatic or manual) does NOT revert rebuilt images; swap; `systemctl restart
  phoenix-runner phoenix-api`; health = `<install>/bin/phoenix doctor --for-update --json`, 3 tries
  10 s apart; healthy = `installed`; unhealthy = `-prev` back, new copy to `-failed`, restart, health
  again: `rolled-back` or `rolled-back-unhealthy` (urgent notify "Phoenix 9 may be down").
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
- **Results**: every public function returns `{ok, result, tag, previous, reason, log}`; `result` is
  one of `installed | already-installed | tests-failed | images-failed | harness-busy | rolled-back |
  rolled-back-unhealthy | rolled-back-manual | refused | recovered | needs-person` (`request` returns `queued: true`
  and `result: null`). `status(refresh)` returns `{supported, installed: {tag, commit}|null,
  previous, newest, update_available, can_rollback, busy, busy_reason, running, waiting, phase,
  interrupted, last, log_tail}`; `running` = the lock is held (read-only probe); `interrupted` = a job
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
| `api` | GET `127.0.0.1:<PHOENIX_API_PORT from HOME/config/api.env, default 8095>/api/health` is 200; in `for-update` its `tag` is one of the `v9.<n>` tags at the installed copy's HEAD | yes | yes (tag) | yes |
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

New and imported projects get no chat service (`claude-rc@<name>`) and no `.vscode/tasks.json`; `project open` / `close` still work for older projects. The dashboard shows a chat button only while a project's chat is on.
