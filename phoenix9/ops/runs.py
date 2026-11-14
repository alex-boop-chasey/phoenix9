"""Ops for runs: start, status, list, log and stop."""
import json
import secrets
from pathlib import Path

from phoenix9 import atomic, docker, events as events_core, gates as gates_core, paths, resolve, runs as core, scrub, settings, spec, state
from phoenix9 import edits as edits_core, tries as tries_core
from phoenix9 import pause as pause_core, runend, spec as spec_core, status as status_core
from phoenix9.ops import common
from phoenix9.repair import unlock
from phoenix9.ops.common import OpsError

FINISHED = ("done", "failed", "stopped")
PROJECT_LOCK_WAIT = 10.0   # seconds a run start waits for the project lock (a delete holds it)


def _run_folder(run_id: str) -> Path:
    folder = core.find_run(run_id)
    if folder is None:
        raise common.NotFound(f"There is no run called '{run_id}'.")
    return folder


def start(project: str, spec_path, overrides: dict | None = None, who: str = "cli") -> dict:
    """Queue a new run of a spec in a project and return its id."""
    folder = common.project_dir(project)
    _refuse_chat_overrides(who, overrides)
    try:
        text = Path(spec_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as err:
        raise OpsError(f"I cannot read the spec file {spec_path}: {err.strerror or err}.") from None
    parsed = spec.parse(text)
    strict = spec.check(text)
    description = bool(strict)   # not in the task format: only the Planner can turn it into tasks
    problems = spec.check_description(text)
    if problems:
        raise OpsError("The spec has problems:\n" + "\n".join(f"- {p}" for p in problems))
    named = "" if description else parsed.project
    if named and named != project:
        raise OpsError(f"The spec is for project '{named}', not '{project}'.")
    problems = settings.check(folder)
    if problems:
        raise OpsError("The project's settings have problems:\n" + "\n".join(f"- {p}" for p in problems))
    overrides = dict(overrides or {})
    written = parsed.preset if not description or parsed.preset in settings.PRESETS else ""
    if not overrides.get("preset") and written:   # the spec's `Preset:` line, unless one was given
        overrides["preset"] = written
    if overrides.get("preset") and overrides["preset"] not in settings.PRESETS:
        raise OpsError(f"'{overrides['preset']}' is not a preset. Use one of: {', '.join(settings.PRESETS)}.")
    if description and "planner" not in plan(project, overrides)["groups"].get("run-start", []):
        raise OpsError("The spec has problems:\n" + "\n".join(f"- {p}" for p in strict + [spec.NEEDS_PLANNER]))
    try:
        profile = settings.effective(folder, common.library(), overrides or None).get("profile")
    except settings.SettingsError as err:
        raise OpsError(f"The project's settings have problems: {err}") from None
    if not profile:
        raise OpsError(settings.no_profile_message(project))
    if settings.image_is_missing(common.make_adapters().docker, paths.library(), profile):
        raise OpsError(settings.missing_image_message(profile))
    lock = state.Lock(paths.project_lock(project), wait=PROJECT_LOCK_WAIT)
    try:
        lock.__enter__()
    except TimeoutError:
        raise OpsError(f"{project} is being changed right now (it may be being deleted). Try again in a minute.") from None
    try:
        common.project_dir(project)        # a delete may have finished while this waited
        run_dir = core.create_run(project, Path(spec_path), overrides)
    except (ValueError, OSError) as err:
        if isinstance(err, OpsError):
            raise
        raise OpsError(f"I could not start the run: {err}") from None
    finally:
        lock.__exit__(None, None, None)
    run_id = run_dir.name
    from phoenix9 import project as project_core
    project_core.mark_used(project)
    common.record_command(who, f"run start {project}", project, f"started run {run_id}")
    return {"run_id": run_id, "project": project, "status": "queued", "folder": str(run_dir)}


def _refuse_chat_overrides(who, overrides: dict | None) -> None:
    """A chat or the agent may not start a build with its own safety settings (like the spending cap or what
    happens on failure); the dashboard and the command line may."""
    from phoenix9.ops import settings as ops_settings
    if not overrides or not ops_settings._is_chat(who):
        return
    hit = sorted(k for k in settings._flatten(overrides) if ops_settings.is_safety_key(k, common.library()))
    if hit:
        raise OpsError(f"'{who}' may not start a build with its own {', '.join(hit)}. "
                       "This is a safety setting: Alex changes it in Settings or starts the build from the dashboard.")


def plan(project: str, overrides: dict | None = None) -> dict:
    """The step plan for the project's settings plus these overrides (a wrong override is reported in `errors`)."""
    lib = common.library()
    folder = common.project_dir(project)
    errors = []
    try:
        eff = settings.effective(folder, lib, overrides or None)
        found = resolve.resolve(lib, settings.enabled_map(eff))
    except (settings.SettingsError, resolve.ResolveError) as err:
        errors = [*err.problems] if isinstance(err, resolve.ResolveError) else [str(err)]
        try:
            eff = settings.effective(folder, lib)
            found = resolve.resolve(lib, settings.enabled_map(eff))
        except (settings.SettingsError, resolve.ResolveError) as own:
            return {"groups": {g: [] for g in resolve.GROUPS}, "steps": [], "errors": errors + [str(own)],
                    "settings": {}}
    data = found.to_json()
    ai_keys = settings.AI_SCHEMA
    steps = []
    for row in data["steps"]:
        table = eff.values.get("steps", {}).get(row["name"], {})
        ai = {k: settings._nested(table, k.split("."), None) for k in ai_keys} if row["kind"] == "ai" else None
        steps.append({**row, "ai": ai})
    keys = ("preset", "based_on", "max_tries", "on_failure", "budget_usd", "merge", "deploy")
    return {"groups": data["groups"], "steps": steps, "errors": errors,
            "settings": {k: eff.values.get(k) for k in keys}}


def _spec_inside_notes(folder: Path, spec_path: str) -> Path:
    """The spec file named relative to notes/, which must sit inside notes/specs or notes/plans."""
    if not isinstance(spec_path, str) or not spec_path:
        raise OpsError("Say which spec to build.")
    notes = (folder / "notes").resolve()
    target = (notes / spec_path).resolve()
    if not any(target.is_relative_to(notes / sub) for sub in ("specs", "plans")) or not target.is_file():
        raise OpsError("The spec has to be a file in the project's notes/specs or notes/plans folder.")
    return target


def start_from_notes(project: str, spec: str | None = None, brief: str | None = None,
                     overrides: dict | None = None, who: str = "cli") -> dict:
    """Start a run from a spec in the project's notes, or from a short brief (needs the Planner on)."""
    folder = common.project_dir(project)
    if bool(spec) == bool(brief and brief.strip()):
        raise OpsError("Give either a spec or a brief, not both and not neither.")
    if spec:
        return start(project, _spec_inside_notes(folder, spec), overrides=overrides, who=who)
    if "planner" not in plan(project, overrides)["groups"].get("run-start", []):
        raise OpsError("A brief needs the Planner step on.")
    first = spec_core.description_title(brief, project)
    cache = paths.cache()
    cache.mkdir(parents=True, exist_ok=True)
    temp = cache / f"brief-{secrets.token_hex(6)}.md"
    atomic.write_text(temp, f"# {first}\n\nProject: {project}\n\n## About\n{brief.strip()}\n")
    try:
        return start(project, temp, overrides=overrides, who=who)
    finally:
        temp.unlink(missing_ok=True)


HOTFIX_OVERRIDES = {"preset": "quick", "steps": {"planner": {"on": True}}}   # fixed here, never taken from a caller
HOTFIX_BRIEF_MAX = 2000   # the longest hotfix brief, in characters


def start_hotfix(project: str, brief: str, who: str = "cli") -> dict:
    """Start a short Quick-style build from a brief, when the project has no build going."""
    text = brief.strip() if isinstance(brief, str) else ""
    if not text:
        raise OpsError("Describe the change to make.")
    if len(text) > HOTFIX_BRIEF_MAX:
        raise OpsError(f"The brief is too long (at most {HOTFIX_BRIEF_MAX} characters).")
    busy = edits_core.build_running(project)
    if busy:
        raise OpsError(f"{project} already has a build going ({busy}). One hotfix at a time.")
    started = start_from_notes(project, brief=text, overrides=json.loads(json.dumps(HOTFIX_OVERRIDES)), who=who)
    common.record_command(who, f"run hotfix {project}", project, f"started hotfix run {started['run_id']}")
    return started


def status(run_id: str) -> dict:
    """The run's state plus its open questions and last few events."""
    folder = _run_folder(run_id)
    open_gates = [g for g in gates_core.run_gates(folder) if g["state"] == "open"]
    st = status_core.seen_run(state.load(folder), {g["id"] for g in open_gates})
    return {**st, "gates": open_gates, "recent_events": events_core.tail(folder / "events.jsonl", 5)}


def list_(project: str | None = None) -> list:
    """Summaries of runs (one project or all), newest first."""
    if project:
        common.project_dir(project)
    open_ids = {g["id"] for g in gates_core.list_gates(project)}
    return [status_core.seen_run(r, open_ids) for r in core.list_runs(project)]


def log(run_id: str, step: str | None = None, task: int | None = None) -> dict:
    """The run's events and step logs, optionally for one step and/or one task."""
    folder = _run_folder(run_id)
    found = [e for e in events_core.read(folder / "events.jsonl")
             if (step is None or e.get("step") == step) and (task is None or e.get("task") == task)]
    logs = {}
    log_dir = folder / "logs"
    if log_dir.is_dir() and task is None:
        for path in sorted(log_dir.glob("*.log")):
            if step is None or path.stem == step:
                logs[path.stem] = path.read_text(encoding="utf-8", errors="replace")
    return {"run_id": run_id, "events": found, "logs": logs}


def events(project: str, run_id: str, after: int | None = None, limit: int = 50) -> dict:
    """One run's events only, oldest first, each scrubbed, numbered by line; `after` skips up to that number."""
    common.project_dir(project)
    folder = _run_folder(run_id)
    if folder.parent.name != project:
        raise common.NotFound(f"There is no run called '{run_id}' in {project}.")
    limit = min(max(int(limit), 1), 1000)
    try:
        lines = (folder / "events.jsonl").read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        lines = []
    found = []
    for number, line in enumerate(lines, 1):
        if after is not None and number <= after:
            continue
        try:
            event = json.loads(scrub.scrub(line))
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("run") in (None, run_id):
            found.append({"id": number, **event})
        if len(found) >= limit:
            break
    return {"project": project, "run_id": run_id, "events": found,
            "next": found[-1]["id"] if found else (after or 0)}


def _stuck_task(st: dict) -> str | None:
    """The first failed or waiting task, else a task still marked running in a run that is not running."""
    tasks = st.get("tasks") or {}
    order = sorted(tasks, key=lambda n: int(n) if str(n).isdigit() else 0)
    for n in order:
        if tasks[n].get("status") in ("failed", "waiting"):
            return n
    for n in order:
        if tasks[n].get("status") in ("running", "pending") and st.get("status") != "running":
            return n
    return None


def task_tries(project: str, run_id: str, task: int | None = None) -> dict:
    """One task of a run (default: the first failed, waiting or stuck one) with the run's max tries and one line per try."""
    d = detail(project, run_id)
    st = state.load(_run_folder(run_id)) or {}
    key = str(task) if task is not None else _stuck_task(st)
    if key is None:
        return {"project": project, "run_id": run_id, "task": None, "title": None, "status": d.get("status"),
                "max_tries": d.get("max_tries"), "tries": []}
    if key not in (st.get("tasks") or {}) and key not in d["try_lines"]:
        raise common.NotFound(f"Run {run_id} has no task {key}.")
    info = (st.get("tasks") or {}).get(key) or {}
    title = info.get("title") or next((t.get("title") for t in d["plan"].get("tasks", [])
                                       if str(t.get("id")) == key), None)
    return {"project": project, "run_id": run_id, "task": int(key), "title": title,
            "status": info.get("status") or "pending", "max_tries": d.get("max_tries"),
            "tries": d["try_lines"].get(key, [])}


SESSION_CHARS = 2000   # most characters of a session excerpt
SESSION_LINES = 40     # most lines of a session excerpt


def _session_files(folder: Path, task: int, attempt: int | None, step: str | None) -> list[Path]:
    """The step session logs (logs/<task>-<attempt>-<role>.jsonl) of a task, inside the run folder only."""
    logs = (folder / "logs").resolve()
    if not logs.is_dir() or not logs.is_relative_to(folder.resolve()):
        return []
    found = []
    for path in logs.glob(f"{int(task)}-*-*.jsonl"):
        parts = path.stem.split("-", 2)
        if len(parts) == 3 and parts[1].isdigit() and path.resolve().parent == logs:
            found.append((int(parts[1]), parts[2], path))
    if attempt is None and found:
        attempt = max(a for a, _, _ in found)
    wanted = [(a, r, p) for a, r, p in found if a == attempt and (step is None or r == step)]
    wanted.sort(key=lambda t: (t[1] != "builder", t[1]))   # the builder's session first
    return [p for _, _, p in wanted]


def _session_text(raw: str) -> str:
    """The readable text of a stream-json session: assistant words and the final result, else the raw lines."""
    out = []
    for line in raw.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            out.append(line)
            continue
        if not isinstance(ev, dict):
            continue
        if ev.get("type") == "assistant":
            content = (ev.get("message") or {}).get("content")
            blocks = content if type(content) is type([]) else []
            out += [b["text"] for b in blocks if isinstance(b, dict) and isinstance(b.get("text"), str)]
        elif ev.get("type") == "result" and isinstance(ev.get("result"), str):
            out.append(ev["result"])
    return "\n".join(out)


def session_excerpt(project: str, run_id: str, task: int, attempt: int | None = None, step: str | None = None) -> dict:
    """The last lines of a step's AI session, scrubbed and capped, returned as quoted data."""
    folder = _run_folder(run_id)
    if folder.parent.name != project:
        raise common.NotFound(f"There is no run called '{run_id}' in {project}.")
    files = _session_files(folder, task, attempt, step)
    if not files:
        raise common.NotFound(f"Run {run_id} has no AI session for task {task}"
                              + (f" try {attempt}" if attempt else "") + ".")
    path = files[0]
    text = _session_text(path.read_text(encoding="utf-8", errors="replace"))
    text = "\n".join(text.splitlines()[-SESSION_LINES:])
    text = scrub.scrub(text)[-SESSION_CHARS:]
    return {"quoted": True, "source": f"logs/{path.name}", "text": text}


def summary(run_id: str) -> dict:
    """The text of the run's summary.md."""
    path = _run_folder(run_id) / "summary.md"
    if not path.exists():
        raise OpsError(f"Run {run_id} has no summary yet.")
    return {"run_id": run_id, "summary": path.read_text(encoding="utf-8", errors="replace")}


STOP_LOCK_WAIT_S = 5.0    # how long a stop waits for a waiting/queued run's lock before leaving a request


def _may_stop(project: str, who: str, folder=None, action: str | None = None) -> bool:
    """The same rule as answering an escalation question (gates.may_answer): chat:* callers need the project's permission.

    Without it, a grant Alex approved in the dashboard for this run and `action` ("stop" or "discard") lets the
    caller through once; the grant is used and recorded on the run here."""
    try:
        project_settings = settings.load_project(common.project_dir(project))
    except (settings.SettingsError, OpsError):
        project_settings = {}
    if gates_core.may_answer({"kind": "escalation"}, who, project_settings):
        return True
    return folder is not None and action is not None and unlock.use(folder, who, [action]) is not None


def stop(run_id: str, who: str = "cli", project: str | None = None) -> dict:
    """Stop a run the one clean way (`project`, when given, must own the run).

    A run the runner is not walking (queued, waiting, paused, or a runner between rounds) is stopped
    at once by the runner's own clean stop under the run lock. A run the runner is walking gets a stop
    request it acts on at its next boundary: the reply then says status "stop requested". Its
    containers are removed either way, so a live step ends quickly."""
    from phoenix9.runner import Runner
    folder = _run_folder(run_id)
    if project is not None and folder.parent.name != project:
        raise common.NotFound(f"There is no run called '{run_id}' in {project}.")
    st = state.load(folder)
    if st["status"] in FINISHED:
        raise OpsError(f"Run {run_id} is already {st['status']}.")
    if not _may_stop(st["project"], who, folder, "stop"):
        raise OpsError(f"'{who}' may not stop runs in {st['project']}.")
    adapters = common.make_adapters()
    removed = docker.cleanup_orphans(adapters.docker, run_id)
    wait = 0 if st["status"] == "running" else STOP_LOCK_WAIT_S
    try:
        ended = Runner(adapters, paths.library()).stop_now(folder, who=who, wait=wait)
        status, notes = ended["status"], ended["notes"]
    except TimeoutError:
        runend.request_stop(folder, who)
        status, notes = "stop requested", []
    common.record_command(who, f"run stop {run_id}", st["project"],
                          f"stopped run {run_id}" if status == "stopped" else f"asked run {run_id} to stop")
    return {"run_id": run_id, "status": status, "containers_removed": removed, "notes": notes}


def _running_step_kind(st: dict) -> str:
    """"ai" or "script": the kind of the step the run is on now ("script" when it cannot be told)."""
    name = (st.get("current") or {}).get("step")
    try:
        return common.library().step(name).kind if name else "script"
    except (KeyError, OSError, ValueError):
        return "script"


def pause(run_id: str, now: bool = False, who: str = "cli", project: str | None = None) -> dict:
    """Pause now: stop the running AI step's container (stop, not remove) and leave the run's worktree alone.

    The runner, which holds the run, sees the request and sets the step line and the run to `paused`
    (status "pause requested" until then). During a step that is not AI the step is left to end, then the
    run pauses (`waits_for_step` is true and the notes say so)."""
    if now is not True:
        raise OpsError("Say --now to pause the step that is running. (To end after the current step, use stop.)")
    folder = _run_folder(run_id)
    if project is not None and folder.parent.name != project:
        raise common.NotFound(f"There is no run called '{run_id}' in {project}.")
    st = state.load(folder)
    if st["status"] == "paused":
        raise common.Conflict(f"Run {run_id} is already paused.")
    if st["status"] != "running":
        raise OpsError(f"Run {run_id} is {st['status']}, so there is no running step to pause.")
    if not _may_stop(st["project"], who):
        raise OpsError(f"'{who}' may not pause runs in {st['project']}.")
    pause_core.request(folder, who)
    waits, stopped, notes = False, 0, []
    if _running_step_kind(st) == "ai":
        docker_ = common.make_adapters().docker
        for cid in docker_.ps_ids(f"{docker.LABEL}.run={run_id}"):
            docker_.stop(cid)
            stopped += 1
    else:
        waits = True
        notes.append("The step that is running is not an AI step, so Phoenix waits for it to end, then pauses.")
    common.record_command(who, f"run pause {run_id} --now", st["project"], f"asked run {run_id} to pause")
    return {"run_id": run_id, "status": "pause requested", "waits_for_step": waits,
            "containers_stopped": stopped, "notes": notes}


def resume(run_id: str, who: str = "cli", project: str | None = None) -> dict:
    """Resume a paused run: `running` (the runner picks it up), or `queued` when another run is going.

    The paused step runs again in a fresh container and, for an AI step, continues its Claude session."""
    folder = _run_folder(run_id)
    if project is not None and folder.parent.name != project:
        raise common.NotFound(f"There is no run called '{run_id}' in {project}.")
    st = state.load(folder)
    if st["status"] != "paused":
        raise OpsError(f"Run {run_id} is {st['status']}, not paused, so there is nothing to resume.")
    if not _may_stop(st["project"], who):
        raise OpsError(f"'{who}' may not resume runs in {st['project']}.")
    busy = any(r["run_id"] != run_id and r["status"] in ("running", "waiting", "paused-limit")
               for r in core.list_runs())
    new = "queued" if busy else "running"
    try:
        with runend.lock(folder, wait=STOP_LOCK_WAIT_S):
            after = state.update(folder, lambda s: s.__setitem__("status", new) if s["status"] == "paused" else None)
    except TimeoutError:
        raise common.Conflict(f"Run {run_id} is busy right now. Try again in a moment.") from None
    if after["status"] != new:
        raise OpsError(f"Run {run_id} is {after['status']}, not paused, so there is nothing to resume.")
    pause_core.clear(folder)
    events_core.emit("run.resumed", project=st["project"], run=run_id, who=who, status=new)
    common.record_command(who, f"run resume {run_id}", st["project"], f"resumed run {run_id}")
    return {"run_id": run_id, "status": new, "queued": new == "queued"}


def note(run_id: str, task: int, text: str, who: str = "cli", project: str | None = None) -> dict:
    """Append a dated note under `## Fix notes` in a task's task.md; the next attempt's prompt carries it."""
    from phoenix9 import taskfile
    folder = _run_folder(run_id)
    if project is not None and folder.parent.name != project:
        raise common.NotFound(f"There is no run called '{run_id}' in {project}.")
    st = state.load(folder)
    if st["status"] in FINISHED:
        raise OpsError(f"Run {run_id} is already {st['status']}, so it takes no more notes.")
    if isinstance(task, bool) or not isinstance(task, int) or str(task) not in st["tasks"]:
        raise common.NotFound(f"Run {run_id} has no task {task}.")
    if not isinstance(text, str) or not text.strip():
        raise OpsError("The note is empty. Write what the next attempt should know.")
    if len(text.strip()) > taskfile.MAX_NOTE:
        raise OpsError(f"The note is {len(text.strip())} characters long; the most is {taskfile.MAX_NOTE}.")
    taskfile.add_note(folder, task, who, text)
    events_core.emit("run.note", project=st["project"], run=run_id, task=task, who=who)
    common.record_command(who, f"run note {run_id} {task}", st["project"])
    return {"run_id": run_id, "task": task, "file": str(taskfile.path(folder, task)),
            "file_id": f"{run_id}/tasks/{task}/task.md"}


DISCARDABLE = ("failed", "stopped")


class WouldLoseWork(common.Conflict):
    """Discarding would lose work (an open merge request, or commits not on main); `lost` lists it in plain words."""

    def __init__(self, message: str, lost: list[str]):
        super().__init__(message)
        self.lost = lost


def _open_merge_request(adapters, folder: Path) -> str | None:
    """The run's merge request URL while it may still be open (an unknown state counts as open), else None."""
    mr = folder / "merge-request.txt"
    if not mr.is_file():
        return None
    url = mr.read_text(encoding="utf-8", errors="replace").strip()
    if not url:
        return None
    try:
        rc, out, _ = adapters.host.gh("pr", "view", url, "--json", "state", "--jq", ".state")
    except Exception:   # noqa: BLE001 - no answer means we cannot prove it is closed
        rc, out = 1, ""
    if rc == 0 and out.strip().upper() in ("MERGED", "CLOSED"):
        return None
    return url


def _commits_not_on_main(adapters, project: str, run_id: str) -> int:
    """How many commits the run's branch (local, else its pushed copy) has that main does not."""
    from phoenix9 import git as gitmod
    code = common.project_dir(project) / "code"
    if not (code / ".git").exists():
        return 0
    try:
        branch = gitmod.branch_name(run_id)
        main = adapters.git.default_branch(code)
        for ref in (f"refs/heads/{branch}", f"refs/remotes/origin/{branch}"):
            if gitmod.git(code, "rev-parse", "-q", "--verify", ref, check=False).strip():
                count = gitmod.git(code, "rev-list", "--count", f"{main}..{ref}", check=False).strip()
                return int(count) if count.isdigit() else 0
    except (gitmod.GitError, OSError, ValueError):
        return 0
    return 0


def would_lose(adapters, folder: Path, project: str, run_id: str) -> list[str]:
    """What discarding this run would throw away, in plain words (empty when nothing unmerged would be lost)."""
    lost = []
    url = _open_merge_request(adapters, folder)
    if url:
        lost.append(f"its merge request {url} is still open (deleting the branch closes it)")
    count = _commits_not_on_main(adapters, project, run_id)
    if count:
        lost.append(f"its branch has {count} commit{'s' if count != 1 else ''} that main doesn't have")
    return lost


def discard(run_id: str, who: str = "cli", project: str | None = None, force: bool = False) -> dict:
    """Throw away a failed or stopped run's work: its worktree, local branch and GitHub branch (if pushed).

    Refused (WouldLoseWork) when the run has an open merge request or commits not on main, unless `force`."""
    folder = _run_folder(run_id)
    if project is not None and folder.parent.name != project:
        raise common.NotFound(f"There is no run called '{run_id}' in {project}.")
    st = state.load(folder)
    if st.get("discarded"):
        raise common.Conflict(f"Run {run_id}'s work was already discarded.")
    if st["status"] not in DISCARDABLE:
        why = ("its work was merged or waits as a merge request" if st["status"] == "done"
               else "stop it first with `phoenix run stop`")
        raise OpsError(f"Run {run_id} is {st['status']}, so its work can't be discarded ({why}).")
    allowed = _may_stop(st["project"], who)        # the same rule as stop: chat:* callers need the project's permission
    if not allowed and unlock.find(folder, who, ["discard"]) is None:
        raise OpsError(f"'{who}' may not discard runs in {st['project']}.")
    if not allowed and force:        # Alex's one-time approval covers a plain discard, never throwing away unmerged work
        raise OpsError(f"'{who}' may not force a discard: only Alex can throw away work that is not on main.")
    adapters = common.make_adapters()
    if not force:
        lost = would_lose(adapters, folder, st["project"], run_id)
        if lost:
            raise WouldLoseWork(f"Run {run_id} still has work that would be lost: " + "; ".join(lost)
                                + ". Discard it anyway only if you mean to throw that away (--force).", lost)
    if not allowed and unlock.use(folder, who, ["discard"]) is None:     # used only once nothing else refuses
        raise OpsError(f"'{who}' may not discard runs in {st['project']}.")
    notes = core.discard_branch(adapters, st["project"], run_id)
    stamp = state.now()

    def mark(s: dict) -> None:
        s.update(discarded=True, discarded_at=stamp, discarded_by=who, **({"discard_forced": True} if force else {}))
    state.update(folder, mark)
    events_core.emit("run.discarded", project=st["project"], run=run_id, who=who, notes=notes, forced=bool(force))
    common.record_command(who, f"run discard {run_id}", st["project"], f"discarded the work of run {run_id}")
    return {"run_id": run_id, "status": st["status"], "discarded": True, "notes": notes}


def _merged_head(adapters, url: str) -> tuple[str, str]:
    """GitHub's state of a merge request and the branch commit it merged ("", "" when GitHub does not answer)."""
    try:
        rc, out, _ = adapters.host.gh("pr", "view", url, "--json", "state,headRefOid",
                                      "--jq", '.state + " " + .headRefOid')
    except Exception:   # noqa: BLE001 - no answer means we cannot prove it is merged
        return "", ""
    words = out.split() if rc == 0 else []
    return (words[0].upper() if words else ""), (words[1] if len(words) > 1 else "")


def _branch_beyond(project: str, run_id: str, head: str) -> bool:
    """True when the run's local branch has commits that the merged commit `head` does not (or that can't be told)."""
    from phoenix9 import git as gitmod
    code = paths.projects() / project / "code"
    if not (code / ".git").exists():
        return False
    try:
        ref = f"refs/heads/{gitmod.branch_name(run_id)}"
        tip = gitmod.git(code, "rev-parse", "-q", "--verify", ref, check=False).strip()
        if not tip or tip == head:
            return False
        gitmod.git(code, "merge-base", "--is-ancestor", tip, head)
        return False
    except (gitmod.GitError, OSError):
        return True


def _tidy_refusal(adapters, folder: Path, st: dict, who: str) -> tuple[str, str]:
    """Why this run may not be tidied ("" when it may) and the merged commit of its merge request."""
    run_id, project = st["run_id"], st["project"]
    if st["status"] not in FINISHED:
        return f"it is {st['status']}, not finished", ""
    if st.get("discarded"):
        return "its work was already discarded", ""
    if st.get("tidied"):
        return "it was already tidied", ""
    if not _may_stop(project, who):
        return f"'{who}' may not tidy runs in {project}", ""
    mr = folder / "merge-request.txt"
    url = mr.read_text(encoding="utf-8", errors="replace").strip() if mr.is_file() else ""
    if not url:
        return "it has no merge request", ""
    found, head = _merged_head(adapters, url)
    if found == "OPEN":
        return f"its merge request {url} is still open", ""
    if found == "CLOSED":
        return f"its merge request {url} was closed without merging", ""
    if found != "MERGED":
        return f"GitHub did not say whether its merge request {url} was merged", ""
    if not head:
        return f"GitHub did not say which commit its merge request {url} merged", ""
    if _branch_beyond(project, run_id, head):
        return "its branch has commits that were not in the merged merge request", ""
    if _unsaved(project, run_id):
        return "its worktree has changes that were never committed", ""
    return "", head


def _unsaved(project: str, run_id: str) -> bool:
    """True when the run's worktree holds uncommitted changes (or can't be read); .env-style files don't count."""
    from phoenix9 import git as gitmod
    work = paths.work(project, run_id)
    if not work.exists():
        return False
    try:
        return bool(gitmod.pending_paths(work, skip_env=True))
    except (gitmod.GitError, OSError):
        return True


def tidy(run_id: str, who: str = "cli", project: str | None = None) -> dict:
    """Remove a finished run's worktree, local branch and GitHub branch once its merge request is merged on GitHub.

    The run's records stay. Refused for a run that is not finished, or whose merge request is open, closed
    without merging or unknown; the message says why."""
    folder = _run_folder(run_id)
    if project is not None and folder.parent.name != project:
        raise common.NotFound(f"There is no run called '{run_id}' in {project}.")
    st = state.load(folder)
    adapters = common.make_adapters()
    why, head = _tidy_refusal(adapters, folder, st, who)
    if why:
        raise OpsError(f"Run {run_id} was not tidied: {why}.")
    return _tidy(adapters, folder, st, head, who)


def _tidy(adapters, folder: Path, st: dict, head: str, who: str) -> dict:
    """Remove the run's worktree and branches, mark the run tidied and record it."""
    run_id, project = st["run_id"], st["project"]
    removed, notes = core.tidy_branch(adapters, project, run_id, head)
    stamp = state.now()
    state.update(folder, lambda s: s.update(tidied=True, tidied_at=stamp, tidied_by=who))
    events_core.emit("run.tidied", project=project, run=run_id, who=who, removed=removed, notes=notes)
    common.record_command(who, f"run tidy {run_id}", project, f"tidied the merged run {run_id}")
    return {"run_id": run_id, "project": project, "status": st["status"], "tidied": True,
            "removed": removed, "notes": notes}


def tidy_merged(who: str = "cli") -> dict:
    """Tidy every finished run of every project whose merge request is merged; list each run left alone and why."""
    adapters, tidied, skipped = common.make_adapters(), [], []
    for row in core.list_runs():
        folder = core.run_dir(row["project"], row["run_id"])
        st = state.load(folder)
        if st["status"] in FINISHED and not st.get("discarded") and not st.get("tidied") \
                and not _anything_left(row["project"], row["run_id"]):
            why, head = "nothing is left to tidy", ""
        else:
            why, head = _tidy_refusal(adapters, folder, st, who)
        if why:
            skipped.append({"run_id": row["run_id"], "project": row["project"], "status": st["status"], "why": why})
        else:
            tidied.append(_tidy(adapters, folder, st, head, who))
    return {"tidied": tidied, "skipped": skipped}


def _anything_left(project: str, run_id: str) -> bool:
    """True while the run still has a worktree, a local branch or a remembered GitHub branch in the project's code/."""
    from phoenix9 import git as gitmod
    if paths.work(project, run_id).exists():
        return True
    code = paths.projects() / project / "code"
    if not (code / ".git").exists():
        return False
    try:
        branch = gitmod.branch_name(run_id)
        return any(gitmod.git(code, "rev-parse", "-q", "--verify", ref, check=False).strip()
                   for ref in (f"refs/heads/{branch}", f"refs/remotes/origin/{branch}"))
    except (gitmod.GitError, OSError):
        return True


list = list_


def _failure_line(folder: Path) -> tuple:
    """The failed or stuck task number of a run and its one-line reason (None, "" when there is none)."""
    st = state.load(folder) or {}
    key = _stuck_task(st)
    if key is None:
        return None, ""
    found = tries_core.by_task(folder, st).get(key) or []
    reason = next((t["reason"] for t in reversed(found) if t["reason"]), "")
    return (int(key) if str(key).isdigit() else key), reason


def builds(project: str, limit: int = 10) -> list:
    """Recent builds of a project, newest first (10 by default), with title, preset, times, cost and the failed task."""
    from phoenix9 import summary
    if limit < 1:
        raise OpsError("'limit' must be 1 or more.")
    rows = []
    for r in list_(project)[:limit]:
        folder = core.run_dir(project, r["run_id"])
        f = summary.facts(folder)
        task, reason = _failure_line(folder)
        rows.append({**r, "title": f["title"], "preset": f["preset"], "started": f["started"],
                     "finished": f["finished"], "duration": f["duration"], "cost": f["cost"],
                     "tasks_failed": f["counts"]["failed"], "tasks_skipped": f["counts"]["skipped"],
                     "tasks_retried": sum(1 for t in f["tasks"] if (t.get("tries") or 0) > 1), "failed_task": task, "failed_reason": reason})
    return rows


def _preview_plan(project: str, overrides: dict) -> dict:
    """The step plan the project's settings plus these overrides would give."""
    try:
        lib = common.library()
        eff = settings.effective(common.project_dir(project), lib, overrides or None)
        return resolve.resolve(lib, settings.enabled_map(eff)).to_json()
    except (settings.SettingsError, resolve.ResolveError) as err:
        raise OpsError(str(err)) from None


def _repairs(folder: Path) -> "list[dict]":
    """The repairs applied to a run, read from its repair.applied events (never from the notes)."""
    found = []
    for e in events_core.read(folder / "events.jsonl"):
        if e.get("type") == "repair.applied":
            d = e.get("data") or {}
            found.append({"n": len(found) + 1, "who": d.get("who"), "title": d.get("title"),
                          "note_id": d.get("note"), "at": e.get("ts"), "rolled_back": bool(d.get("rolled_back"))})
    return found


def _unlocks_used(folder: Path) -> "list[dict]":
    """Every repair the agent or a chat did with Alex's dashboard approval, read from the run's repair.unlock events."""
    return [{"at": e.get("ts"), "who": (e.get("data") or {}).get("who"), "steps": (e.get("data") or {}).get("steps") or [],
             "text": (e.get("data") or {}).get("text")}
            for e in events_core.read(folder / "events.jsonl")
            if e.get("type") == "repair.unlock" and (e.get("data") or {}).get("what") == "used"]


def detail(project: str, run_id: str) -> dict:
    """One run: status plus the plan (frozen, or a preview when not started), title, preset, max_tries,
    and its branch (None once the branch is gone)."""
    from phoenix9 import summary
    common.project_dir(project)
    folder = _run_folder(run_id)
    if folder.parent.name != project:
        raise common.NotFound(f"There is no run called '{run_id}' in {project}.")
    data = status(run_id)
    facts = summary.facts(folder)
    frozen = atomic.read_json(folder / "settings.json") or {}
    plan = atomic.read_json(folder / "plan.json")
    frozen_plan = plan is not None
    overrides = atomic.read_json(folder / "overrides.json") or {}
    if plan is None:
        plan = _preview_plan(project, overrides)
    max_tries = frozen.get("max_tries")
    if max_tries is None:
        max_tries = overrides.get("max_tries")
    if max_tries is None:
        try:
            eff = settings.effective(common.project_dir(project), common.library(), overrides or None)
            max_tries = eff.get("max_tries")
        except settings.SettingsError:
            pass
    cap = frozen.get("budget_usd") if frozen_plan else overrides.get("budget_usd")
    if cap is None and not frozen_plan:
        try:
            cap = settings.effective(common.project_dir(project), common.library(), overrides or None).get("budget_usd")
        except settings.SettingsError:
            pass
    spent = float((state.load(folder) or {}).get("usage", {}).get("cost_usd") or 0.0)
    tries, try_lines = tries_core.of_run(folder)
    return {**data, "tries": tries, "try_lines": try_lines, "plan": plan, "plan_frozen": frozen_plan, "title": facts["title"],
            "preset": facts["preset"], "max_tries": max_tries, "budget_usd": cap, "spent_usd": round(spent, 2),
            "branch": _live_branch(project, run_id), "repairs": _repairs(folder),
            "unlocks_used": _unlocks_used(folder)}


def _live_branch(project: str, run_id: str) -> str | None:
    """The run's branch name while it still exists in the project's code/ (a discarded run has none)."""
    from phoenix9 import git as gitmod
    code = common.project_dir(project) / "code"
    branch = gitmod.branch_name(run_id)
    if not (code / ".git").exists():
        return None
    try:
        found = gitmod.git(code, "rev-parse", "-q", "--verify", f"refs/heads/{branch}", check=False).strip()
    except (gitmod.GitError, OSError):
        return None
    return branch if found else None
