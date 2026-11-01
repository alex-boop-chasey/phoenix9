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
  cli/                         project.py run.py gate.py settings.py global_.py services.py keys.py
                               steps.py update.py doctor.py deploy.py api.py runner.py  (thin: parse args, call ops, print)
  ops/                         the ONE backend layer. CLI and API both call these functions and nothing
                               else. Every function returns plain dicts/lists (JSON-able). Modules:
                               common runs gates settings library projects keys logs (phases 1-3),
                               global_ services update deploy doctor (phase 4). Errors: OpsError.
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
  stepctx.py                   StepContext and StepResult (section 4.4)
  claude.py docker.py git.py watch.py   ports of V8 (reference/v8/phoenix/*), adapters (section 9)
  scrub.py                     secret redaction for every log line written
  project.py                   phoenix project (proj folded in) (phase 2)
  keys.py                      per-project keys + global secrets store (phase 2; global part phase 4)
  services.py proxy.py         services registry, key proxy (phase 4)
  updater.py                   phoenix update (phase 4)
  deploy.py                    deployers runner (phase 4)
  doctor.py                    phoenix doctor (phase 4; stub in phase 1)
  api/server.py                phoenix-api: JSON API + SSE + static web/dist (phase 3)
steps/<name>/                  step library: step.toml + prompt.md (ai) and/or run.py (script)
steps/_things.toml             every "thing" a step can need/produce, with its fallback
presets/<name>.toml            simple, quick, full (custom = no file; it is "start from a preset")
profiles/<name>/profile.toml   web, mobile, desktop, python-script, research, platform (+ image/Dockerfile)
services/<name>/service.toml   expected project keys + hosts (phase 2); recipes, proxy rules (phase 4)
deployers/<name>/deployer.toml phase 4 (+ deploy.py)
templates/<name>/template.toml project templates menu (phase 2)
image/                         base step image files ported from V8 (init-firewall.sh, entry.sh, ...)
deploy/                        systemd units, install.sh, update.sh (phase 4)
web/                           React app (phase 3)
tests/                         pytest; tests/fakes/ holds every fake adapter
reference/                     READ-ONLY copies of V8, proj and the project-selector. Never imported,
                               never edited. Deleted at the end of phase 4.
```

## 3. Where things live at runtime (`phoenix9/paths.py`)

| Name | Default | Env override | Holds |
| --- | --- | --- | --- |
| HOME | `/var/lib/phoenix9` | `PHOENIX_HOME` | everything below |
| config | HOME/config | | `global.toml` (non-secret global settings), `services.toml` |
| secrets | HOME/secrets (0700) | | `<name>.env` files, 0600: `claude.env`, `github.env`, `telegram.env`, `service-<name>.env` |
| keys | HOME/keys (0700) | | per-project keys `<project>.toml`, 0600 (section 10) |
| runs | HOME/runs/<project>/<run-id>/ | | run folders (section 7) |
| work | HOME/work/<project>/<run-id>/ | | the run's git worktree of the project's code/ on branch `phoenix/<run-id>` (removed when the run ends; the branch stays) |
| logs | HOME/logs | | `commands.jsonl` (who ran what), `updater.log`, `api.log` |
| cache | HOME/cache | | recomputable data, e.g. `sizes.json` (project folder sizes, refreshed in the background) |
| events | HOME/events.jsonl | | global event stream (section 8) |
| projects | `/srv/projects` | `PHOENIX_PROJECTS` | one folder per project |
| install | `/opt/phoenix9` | `PHOENIX_INSTALL` | the installed copy (updater only) |
| library | repo root of the running copy | `PHOENIX_LIBRARY` | steps/ presets/ profiles/ services/ deployers/ templates/ |

Per project (`/srv/projects/<name>/`): `CLAUDE.md`, `notes/`, `code/` (git), `phoenix.toml`
(settings, no secrets), `.phoenix/project.json` (facts Phoenix records: created, source, repo,
chat link, environment id, services set up).

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
proxy = []                       # phase 4: services whose key proxy runs for this step (e.g. ["github"])

[settings]                       # the step's own options and their defaults (validated by type)
max_tries = 3

[ai]                             # ai steps only; full block in section 5.3
model = "claude-sonnet-5-5"
```
- `kind = "script"`: the folder has `run.py` with `def run(ctx: StepContext) -> StepResult`.
- `kind = "ai"`: the folder has `prompt.md` (the instructions, with `{{task}}`, `{{failures}}`,
  `{{checks}}`, `{{spec_title}}` placeholders) and may have `run.py` with optional
  `before(ctx) -> dict` (extra placeholder values) and `after(ctx, session) -> StepResult` (judge the
  session's outcome by looking at files only, never by trusting what the session said).
- `kind = "gate"`: no code needed; the runner opens a gate (section 8) and waits.
- Library loading imports `run.py` with `importlib.util.spec_from_file_location`; a broken folder is
  reported by `phoenix steps list` and skipped, it never crashes the runner.

### 4.2 Things: `steps/_things.toml`

```toml
[spec]        provided = "run"            # always available, from Pick-up
[task]        provided = "task"           # the current task (task-level only)
[worktree]    provided = "run"            # from Branch
[failures]    provided = "task"           # earlier attempts' failure reasons (may be empty)
[plan]        fallback = "spec-as-written"
[checks]      fallback = "spec-done-when"
[baseline]    fallback = "not-run"        # main's test result before the run (Branch)
[diff]        fallback = ""               # no fallback: something must produce it (Builder)
[exit-codes]  fallback = ""               # Acceptance's results (always on)
[commit]      fallback = ""               # the task's commit sha (Commit)
[merged]      fallback = "not-merged"     # merge result (Merge)
[test-report] fallback = "exit-codes-only"
[verdict]     fallback = "pass-if-checks-passed"
```
`provided` things never need a producer. A thing with an empty fallback must be produced by an
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
`things` (dict of everything produced so far, after fallbacks), `adapters` (docker, claude, git, host,
clock, notify; real or fake), `emit(type, **data)` (writes an event), `log(text)` (scrubbed log line
into the run folder).

### 4.5 Profile folder: `profiles/<name>/profile.toml`

`title`, `image` (step image tag), `allowed_domains` (list), `diff_allow_extra` (list),
`screenshots` (bool), `suggested_deployer`, and a `[test]` block: `cmd` (full suite command),
`task_cmd` (optional, a single task's checks), `report` (`pytest-junit | vitest-json | playwright-json
| exit-code`), `report_path`. Optional `[steps.<name>]` tables override step defaults (layer 2 in 5.1).
The profile's container image files live in `profiles/<name>/image/`.

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
```
`tomlw.py` writes it back with keys in this order and a one-line comment header.

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
  `gates/<gate-id>.answer.json`, `logs/<step>.log`, `summary.md`.
- `state.json`: `{run_id, project, status, created, updated, current: {group, task, step, attempt},
  tasks: {"1": {title, status, tries, failures: [..], depends_on: [..]}}, steps: [ {group, task, step,
  status, started, finished, note} ], usage: {cost_usd, sessions}}`.
  Run status: `queued | running | waiting | paused-limit | done | failed | stopped`.
  Task status: `pending | running | passed | failed | skipped | waiting`.
  Step line status: `pending | running | passed | failed | skipped`.
- Queue: a run starts as `queued`. The runner service takes the oldest queued run when no run is
  `running`/`waiting` anywhere (one build at a time across the server, decision 2026-11-01). Restart
  resumes `running` runs from `state.json`.

## 8. Events and gates

- Event line (JSON): `{"ts": iso, "type": "...", "project": ..., "run": ..., "task": n|null,
  "step": name|null, "data": {...}}`. Written to the run's `events.jsonl` and to HOME/events.jsonl.
  Types: `run.queued run.started run.finished run.step.started run.step.finished task.started
  task.finished gate.opened gate.answered project.created project.changed settings.changed
  update.started update.installed update.failed update.rolledback deploy.finished run.held command`.
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
| `proxy` | phase 4: start/stop the per-step key proxy (phoenix9/proxy.py) | in-process fake forwarder |
| `chat` | delegate mode: starts a detached headless `claude -p` in the project folder (section 11, rule 1 exception) | records the request, scripted outcome |
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
   It is a separate process, never imported or driven step-by-step by the runner.
2. Step containers never get the Docker socket, the GitHub token, SSH keys or account service keys.
   They get the Claude token, the project's secret keys as env vars, and the proxy address plus a
   per-step proxy token (phase 4; the token only identifies the step to the proxy, it is not a service key).
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
- **Chat link**: a project records `chat_session_url` when known (`phoenix project set-chat`) and always
  knows the environment link parsed from `journalctl -u claude-rc@<name>`
  (`https://claude.ai/code?environment=env_...`). The Projects page shows the session link if recorded,
  else the environment link.

## 13. Formats defined in later phases

Phase 4's sheets define these, and the phase 4 review step adds them here: `services/<name>/service.toml`,
`deployers/<name>/deployer.toml`, `HOME/config/services.toml`, global update settings and the
`HOME/update/` files, `[deploy.settings]` in phoenix.toml, `.phoenix/deploys.jsonl` and
`services_done` in `.phoenix/project.json`, the run state's `held` field, and the `phoenix images` CLI
group. phoenix9's own `phoenix.toml` (holding `safety_files` and `merge = "ask"`) lives outside code/,
so the repo carries a template (`deploy/self-project.toml`) that the chat copies into place.
