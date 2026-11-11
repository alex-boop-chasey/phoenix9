"""Ops for runs: start, status, list, log and stop."""
import json
import secrets
from pathlib import Path

from phoenix9 import atomic, docker, events as events_core, gates as gates_core, paths, resolve, runs as core, scrub, settings, spec, state
from phoenix9 import tries as tries_core
from phoenix9 import pause as pause_core, runend, spec as spec_core, status as status_core
from phoenix9.ops import common
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


def summary(run_id: str) -> dict:
    """The text of the run's summary.md."""
    path = _run_folder(run_id) / "summary.md"
    if not path.exists():
        raise OpsError(f"Run {run_id} has no summary yet.")
    return {"run_id": run_id, "summary": path.read_text(encoding="utf-8", errors="replace")}


STOP_LOCK_WAIT_S = 5.0    # how long a stop waits for a waiting/queued run's lock before leaving a request


def _may_stop(project: str, who: str) -> bool:
    """The same rule as answering an escalation question (gates.may_answer): chat:* callers need the project's permission."""
    try:
        project_settings = settings.load_project(common.project_dir(project))
    except (settings.SettingsError, OpsError):
        project_settings = {}
    return gates_core.may_answer({"kind": "escalation"}, who, project_settings)


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
    if not _may_stop(st["project"], who):
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
    if not _may_stop(st["project"], who):        # the same rule as stop: chat:* callers need the project's permission
        raise OpsError(f"'{who}' may not discard runs in {st['project']}.")
    adapters = common.make_adapters()
    if not force:
        lost = would_lose(adapters, folder, st["project"], run_id)
        if lost:
            raise WouldLoseWork(f"Run {run_id} still has work that would be lost: " + "; ".join(lost)
                                + ". Discard it anyway only if you mean to throw that away (--force).", lost)
    notes = core.discard_branch(adapters, st["project"], run_id)
    stamp = state.now()

    def mark(s: dict) -> None:
        s.update(discarded=True, discarded_at=stamp, discarded_by=who, **({"discard_forced": True} if force else {}))
    state.update(folder, mark)
    events_core.emit("run.discarded", project=st["project"], run=run_id, who=who, notes=notes, forced=bool(force))
    common.record_command(who, f"run discard {run_id}", st["project"], f"discarded the work of run {run_id}")
    return {"run_id": run_id, "status": st["status"], "discarded": True, "notes": notes}


list = list_


def builds(project: str) -> list:
    """Previous builds of a project, newest first, with title, preset, times, duration, cost."""
    from phoenix9 import summary
    rows = []
    for r in list_(project):
        f = summary.facts(core.run_dir(project, r["run_id"]))
        rows.append({**r, "title": f["title"], "preset": f["preset"], "started": f["started"],
                     "finished": f["finished"], "duration": f["duration"], "cost": f["cost"],
                     "tasks_failed": f["counts"]["failed"]})
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
            "branch": _live_branch(project, run_id), "repairs": _repairs(folder)}


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
