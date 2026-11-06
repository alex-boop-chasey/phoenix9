"""Ops for runs: start, status, list, log and stop."""
import secrets
from pathlib import Path

from phoenix9 import atomic, docker, events, gates as gates_core, paths, resolve, runs as core, settings, spec, state
from phoenix9 import status as status_core
from phoenix9.ops import common
from phoenix9.ops.common import OpsError

FINISHED = ("done", "failed", "stopped")


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
    problems = spec.check(text)
    if not spec.parse(text).tasks:   # a brief for the Planner has no tasks yet; Spec check decides if that is allowed
        problems = [p for p in problems if not p.startswith("The spec has no tasks")]
    if problems:
        raise OpsError("The spec has problems:\n" + "\n".join(f"- {p}" for p in problems))
    named = spec.parse(text).project
    if named and named != project:
        raise OpsError(f"The spec is for project '{named}', not '{project}'.")
    problems = settings.check(folder)
    if problems:
        raise OpsError("The project's settings have problems:\n" + "\n".join(f"- {p}" for p in problems))
    overrides = dict(overrides or {})
    if overrides.get("preset") and overrides["preset"] not in settings.PRESETS:
        raise OpsError(f"'{overrides['preset']}' is not a preset. Use one of: {', '.join(settings.PRESETS)}.")
    try:
        profile = settings.effective(folder, common.library(), overrides or None).get("profile")
    except settings.SettingsError as err:
        raise OpsError(f"The project's settings have problems: {err}") from None
    if not profile:
        raise OpsError(settings.no_profile_message(project))
    try:
        run_dir = core.create_run(project, Path(spec_path), overrides)
    except (ValueError, OSError) as err:
        raise OpsError(f"I could not start the run: {err}") from None
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
    keys = ("preset", "based_on", "max_tries", "on_failure", "merge", "deploy")
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
    first = brief.strip().splitlines()[0][:80]
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
    return {**st, "gates": open_gates, "recent_events": events.tail(folder / "events.jsonl", 5)}


def list_(project: str | None = None) -> list:
    """Summaries of runs (one project or all), newest first."""
    if project:
        common.project_dir(project)
    open_ids = {g["id"] for g in gates_core.list_gates(project)}
    return [status_core.seen_run(r, open_ids) for r in core.list_runs(project)]


def log(run_id: str, step: str | None = None, task: int | None = None) -> dict:
    """The run's events and step logs, optionally for one step and/or one task."""
    folder = _run_folder(run_id)
    found = [e for e in events.read(folder / "events.jsonl")
             if (step is None or e.get("step") == step) and (task is None or e.get("task") == task)]
    logs = {}
    log_dir = folder / "logs"
    if log_dir.is_dir() and task is None:
        for path in sorted(log_dir.glob("*.log")):
            if step is None or path.stem == step:
                logs[path.stem] = path.read_text(encoding="utf-8", errors="replace")
    return {"run_id": run_id, "events": found, "logs": logs}


def summary(run_id: str) -> dict:
    """The text of the run's summary.md."""
    path = _run_folder(run_id) / "summary.md"
    if not path.exists():
        raise OpsError(f"Run {run_id} has no summary yet.")
    return {"run_id": run_id, "summary": path.read_text(encoding="utf-8", errors="replace")}


def stop(run_id: str, who: str = "cli", project: str | None = None) -> dict:
    """Mark the run stopped and remove its containers (`project`, when given, must own the run)."""
    folder = _run_folder(run_id)
    if project is not None and folder.parent.name != project:
        raise common.NotFound(f"There is no run called '{run_id}' in {project}.")
    st = state.load(folder)
    if st["status"] in FINISHED:
        raise OpsError(f"Run {run_id} is already {st['status']}.")
    state.set_status(folder, "stopped")
    gates_core.close_questions(folder, "run stopped", who=who)
    adapters = common.make_adapters()
    removed = docker.cleanup_orphans(adapters.docker, run_id)
    notes = core.discard_branch(adapters, st["project"], run_id)
    events.emit("run.finished", project=st["project"], run=run_id, status="stopped", who=who)
    common.record_command(who, f"run stop {run_id}", st["project"], f"stopped run {run_id}")
    return {"run_id": run_id, "status": "stopped", "containers_removed": removed, "notes": notes}


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


def detail(project: str, run_id: str) -> dict:
    """One run: status plus the plan (frozen, or a preview when not started), title, preset, max_tries."""
    from phoenix9 import git as gitmod, summary
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
    return {**data, "plan": plan, "plan_frozen": frozen_plan, "title": facts["title"],
            "preset": facts["preset"], "max_tries": max_tries,
            "branch": gitmod.branch_name(run_id)}
