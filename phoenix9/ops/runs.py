"""Ops for runs: start, status, list, log and stop."""
from pathlib import Path

from phoenix9 import atomic, docker, events, gates as gates_core, runs as core, settings, spec, state
from phoenix9.ops import common
from phoenix9.ops.common import OpsError

FINISHED = ("done", "failed", "stopped")


def _run_folder(run_id: str) -> Path:
    folder = core.find_run(run_id)
    if folder is None:
        raise OpsError(f"There is no run called '{run_id}'.")
    return folder


def start(project: str, spec_path, overrides: dict | None = None, who: str = "cli") -> dict:
    """Queue a new run of a spec in a project and return its id."""
    folder = common.project_dir(project)
    try:
        text = Path(spec_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as err:
        raise OpsError(f"I cannot read the spec file {spec_path}: {err.strerror or err}.") from None
    problems = spec.check(text)
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
        run_dir = core.create_run(project, Path(spec_path), overrides)
    except (ValueError, OSError) as err:
        raise OpsError(f"I could not start the run: {err}") from None
    run_id = run_dir.name
    common.record_command(who, f"run start {project}", project, f"started run {run_id}")
    return {"run_id": run_id, "project": project, "status": "queued", "folder": str(run_dir)}


def status(run_id: str) -> dict:
    """The run's state plus its open questions and last few events."""
    folder = _run_folder(run_id)
    st = state.load(folder)
    open_gates = [g for g in gates_core.list_gates(st["project"]) if g["run"] == run_id]
    return {**st, "gates": open_gates, "recent_events": events.tail(folder / "events.jsonl", 5)}


def list_(project: str | None = None) -> list:
    """Summaries of runs (one project or all), newest first."""
    if project:
        common.project_dir(project)
    return core.list_runs(project)


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


def stop(run_id: str, who: str = "cli") -> dict:
    """Mark the run stopped and remove its containers."""
    folder = _run_folder(run_id)
    st = state.load(folder)
    if st["status"] in FINISHED:
        raise OpsError(f"Run {run_id} is already {st['status']}.")
    state.set_status(folder, "stopped")
    removed = docker.cleanup_orphans(common.make_adapters().docker, run_id)
    events.emit("run.finished", project=st["project"], run=run_id, status="stopped", who=who)
    common.record_command(who, f"run stop {run_id}", st["project"], f"stopped run {run_id}")
    return {"run_id": run_id, "status": "stopped", "containers_removed": removed}


list = list_
