"""The repair check: does a run's recorded state agree with itself, and with its worktree, settings, spec and server?"""
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from phoenix9 import atomic, gates, git, paths, resolve, runend, scrub, settings, state, status
from phoenix9.library import load_library
from phoenix9.repair.snapshot import worktree_of

REASON_LINES = 3
ENDED_TASK_OK = {"done": ("passed", "skipped"), "failed": gates.TASK_ENDED, "stopped": gates.TASK_ENDED}


@dataclass
class Finding:
    """One thing wrong in a run: a short code, plain words, the task it concerns and a hint for the fix."""
    code: str
    text: str
    task: int | None = None
    fix: dict = field(default_factory=dict)


def _tasks(st: dict):
    """The run's tasks as (number, task) pairs in number order."""
    return sorted(((int(n), t) for n, t in (st.get("tasks") or {}).items()), key=lambda x: x[0])


def _step_title(name: str) -> str:
    """A step's display title from the library (its name when the library cannot say)."""
    try:
        return load_library(paths.library()).step(name).title or name
    except Exception:  # noqa: BLE001 - a missing or broken library still leaves the name
        return name


def failed_steps(st: dict, title_of=None) -> list[dict]:
    """Every failed run-start or run-finish step line: {step, group, title, reasons} (first reason lines, scrubbed)."""
    title_of = title_of or _step_title
    out = []
    for x in st.get("steps") or []:
        if x.get("status") != "failed" or x.get("group") not in runend.RUN_GROUPS or x.get("task") is not None:
            continue
        lines = [ln.strip().removeprefix("The checks did not pass:").strip()
                 for ln in scrub.scrub(str(x.get("note") or "")).splitlines()]
        lines = [ln for ln in lines if ln][:REASON_LINES]
        name = x.get("step") or ""
        out.append({"step": name, "group": x.get("group"), "title": title_of(name) or name, "reasons": lines})
    return out


def check_statuses(run_dir: Path, st: dict) -> list[Finding]:
    """Run, task and step statuses must be known words."""
    return [Finding("bad-status", problem.capitalize() + ".", fix={"kind": "set-status"})
            for problem in state.status_problems(st)]


def _ended_mismatches(st: dict) -> list[Finding]:
    """An ended run must have no task or step line still going and no gate it waits on."""
    found = []
    allowed = ENDED_TASK_OK.get(st["status"], ())
    for n, t in _tasks(st):
        if t["status"] not in allowed:
            found.append(Finding("task-not-final", f"The run is {st['status']} but task {n} is still {t['status']}.",
                                 task=n, fix={"kind": "task-status", "task": n}))
    for i, x in enumerate(st.get("steps") or []):
        if x["status"] in ("pending", "running", "waiting"):
            found.append(Finding("step-not-final", f"The run is {st['status']} but step {x.get('step')} is still {x['status']}.",
                                 task=x.get("task"), fix={"kind": "step-line", "line": i}))
    if (st.get("current") or {}).get("gate"):
        found.append(Finding("ended-holds-gate", f"The run is {st['status']} but still points at question "
                             f"{st['current']['gate']}.", fix={"kind": "clear-gate"}))
    return found


def _live_mismatches(st: dict) -> list[Finding]:
    """A run that is not ended: waiting tasks and steps need a waiting run; running ones need a started run."""
    found, run = [], st["status"]
    for n, t in _tasks(st):
        if t["status"] == "waiting" and run != "waiting":
            found.append(Finding("task-waiting-run-not", f"Task {n} is waiting for a question but the run is {run}.",
                                 task=n, fix={"kind": "task-status", "task": n}))
        if t["status"] == "running" and run == "queued":
            found.append(Finding("task-running-run-queued", f"Task {n} is running but the run is only queued.",
                                 task=n, fix={"kind": "task-status", "task": n}))
    for i, x in enumerate(st.get("steps") or []):
        if x["status"] == "waiting" and run != "waiting":
            found.append(Finding("step-waiting-run-not", f"Step {x.get('step')} is waiting for a question but the "
                                 f"run is {run}.", task=x.get("task"), fix={"kind": "step-line", "line": i}))
        if x["status"] == "running" and run == "queued":
            found.append(Finding("step-running-run-queued", f"Step {x.get('step')} is running but the run is only "
                                 "queued.", task=x.get("task"), fix={"kind": "step-line", "line": i}))
    return found


def check_agreement(run_dir: Path, st: dict) -> list[Finding]:
    """The run status agrees with its tasks, step lines and current.gate."""
    if st.get("status") in gates.ENDED:
        return _ended_mismatches(st)
    return _live_mismatches(st) if st.get("status") in status.ACTIVE else []


def _attempt_numbers(run_dir: Path, n: int) -> list[int]:
    """The attempt folder numbers of task n, in order."""
    base = Path(run_dir) / "tasks" / str(n)
    if not base.is_dir():
        return []
    return sorted(int(m.group(1)) for p in base.iterdir() if p.is_dir() and (m := re.fullmatch(r"attempt-(\d+)", p.name)))


def _attempt_findings(run_dir: Path, n: int, tries: int, have: list[int]) -> list[Finding]:
    """Attempt folders must be 1..tries (the newest may be missing: tries moves one ahead of the folder)."""
    if have in (list(range(1, tries + 1)), list(range(1, tries))):
        return []
    return [Finding("tries-mismatch", f"Task {n} says it is on try {tries} but its attempt folders are "
                    f"{have or 'missing'}.", task=n, fix={"kind": "tries", "task": n, "folders": have})]


def _result_findings(run_dir: Path, n: int, tries: int, have: list[int]) -> list[Finding]:
    """Every attempt below `tries` must have a readable result.json that names its own attempt."""
    found = []
    for k in (k for k in have if k < tries):
        result = atomic.read_json(Path(run_dir) / "tasks" / str(n) / f"attempt-{k}" / "result.json")
        if not isinstance(result, dict):
            found.append(Finding("attempt-no-result", f"Task {n} attempt {k} is over but has no result.json.",
                                 task=n, fix={"kind": "attempt-result", "task": n, "attempt": k}))
        elif result.get("attempt", k) != k:
            found.append(Finding("attempt-wrong-result", f"Task {n} attempt {k} has a result.json for attempt "
                                 f"{result['attempt']}.", task=n, fix={"kind": "attempt-result", "task": n, "attempt": k}))
    return found


def check_tries(run_dir: Path, st: dict) -> list[Finding]:
    """Per task, `tries` matches the attempt folders and their result.json files."""
    found = []
    for n, t in _tasks(st):
        tries, have = int(t.get("tries", 0)), _attempt_numbers(run_dir, n)
        problems = _attempt_findings(run_dir, n, tries, have)
        found += problems or _result_findings(run_dir, n, tries, have)
    return found


def check_one_running(run_dir: Path, st: dict) -> list[Finding]:
    """At most one step line in the run is running."""
    running = [x for x in st.get("steps") or [] if x.get("status") == "running"]
    if len(running) < 2:
        return []
    names = ", ".join(str(x.get("step")) for x in running)
    return [Finding("many-running", f"{len(running)} step lines say running at once ({names}); only one can.",
                    fix={"kind": "step-line"})]


def check_questions(run_dir: Path, st: dict) -> list[Finding]:
    """The open questions are exactly the ones the run waits on."""
    found = [Finding("orphan-question", f"Question {g['id']} is unanswered but nothing waits on it.",
                     task=g.get("task"), fix={"kind": "close-question", "gate": g["id"]})
             for g in gates.orphans(run_dir)]
    if st.get("status") != "waiting":
        return found
    every = gates.run_gates(run_dir)
    open_ids = {g["id"] for g in every if g["state"] == "open"}
    answered_held = [g for g in every if g["state"] == "answered" and gates.held(st, g["id"])]
    if status.carrying_on(st, open_ids) and not answered_held:
        found.append(Finding("waiting-no-question", "The run is waiting but no open question is waiting for an answer.",
                             fix={"kind": "run-status"}))
    return found


def _worktree_expected(st: dict) -> bool:
    """A run that has not started, or is finished and merged, may have no worktree."""
    return st.get("status") not in ("queued", "done")


def _tree_findings(work: Path, run_id: str) -> list[Finding]:
    """The worktree is on the run's branch."""
    branch = git.run_git(work, "rev-parse", "--abbrev-ref", "HEAD", check=False).stdout.decode().strip()
    want = git.branch_name(run_id)
    if branch == want:
        return []
    return [Finding("worktree-wrong-branch", f"The worktree is on '{branch or 'no branch'}', not on {want}.",
                    fix={"kind": "worktree-branch"})]


def _base_findings(work: Path, st: dict) -> list[Finding]:
    """Every task's attempt_base is a commit the worktree contains."""
    found = []
    for n, t in _tasks(st):
        base = t.get("attempt_base")
        if base and git.run_git(work, "merge-base", "--is-ancestor", base, "HEAD", check=False).returncode != 0:
            found.append(Finding("base-not-in-worktree", f"Task {n} starts from commit {str(base)[:10]}, which the "
                                 "worktree does not contain.", task=n, fix={"kind": "attempt-base", "task": n}))
    return found


def _env_findings(work: Path) -> list[Finding]:
    """No .env-style file sits in the worktree."""
    found = []
    for root, dirs, files in os.walk(work):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in files:
            if git.is_env_file(name):
                rel = (Path(root) / name).relative_to(work).as_posix()
                found.append(Finding("env-file", f"The worktree holds an env file ({rel}).",
                                     fix={"kind": "env-file", "path": rel}))
    return found


def check_worktree(run_dir: Path, st: dict) -> list[Finding]:
    """The worktree exists, is on phoenix/<run>, contains every attempt_base and holds no env file."""
    work = worktree_of(run_dir)
    if not (work / ".git").exists():
        if not _worktree_expected(st):
            return []
        return [Finding("worktree-missing", f"The worktree for this run is missing ({work}).",
                        fix={"kind": "worktree-missing"})]
    try:
        return _tree_findings(work, run_dir.name) + _base_findings(work, st) + _env_findings(work)
    except git.GitError as err:
        return [Finding("worktree-unreadable", f"Git cannot read the worktree: {err}", fix={"kind": "worktree-missing"})]


def _plan_findings(run_dir: Path, values: dict, lib) -> list[Finding]:
    """plan.json equals what the resolver makes of the frozen settings (unless a repair froze it)."""
    if (run_dir / "repairs" / "frozen.json").is_file():
        return []
    plan = atomic.read_json(run_dir / "plan.json")
    if plan is None:
        return []
    try:
        enabled = {n: bool(t["on"]) for n, t in (values.get("steps") or {}).items()}
        want = json.loads(json.dumps(resolve.resolve(lib, enabled).to_json()))
    except (resolve.ResolveError, KeyError, TypeError) as err:
        return [Finding("settings-no-plan", f"The settings cannot make a plan: {err}", fix={"kind": "plan"})]
    if plan != want:
        return [Finding("plan-differs", "plan.json is not what the settings in settings.json make.",
                        fix={"kind": "plan"})]
    return []


def check_settings(run_dir: Path, st: dict) -> list[Finding]:
    """settings.json is valid, and plan.json is what the resolver makes of it."""
    values = atomic.read_json(run_dir / "settings.json")
    if values is None:
        return [] if not (run_dir / "settings.json").exists() else [
            Finding("settings-bad", "settings.json cannot be read.", fix={"kind": "settings"})]
    lib = load_library(paths.library())
    problems = settings.validate(values, settings.all_specs(lib), "settings.json")
    if problems:
        return [Finding("settings-bad", "settings.json is not valid: " + "; ".join(problems), fix={"kind": "settings"})]
    return _plan_findings(run_dir, values, lib)


def check_spec(run_dir: Path, st: dict) -> list[Finding]:
    """spec.json lists the same tasks (numbers, titles, depends_on) as the state."""
    data = atomic.read_json(run_dir / "spec.json")
    if data is None or "tasks" not in data:
        return []
    try:
        spec = {int(t["number"]): (t["title"], sorted(t["depends_on"])) for t in data["tasks"]}
    except (KeyError, TypeError, ValueError):
        return [Finding("spec-bad", "spec.json has tasks that cannot be read.", fix={"kind": "spec"})]
    have = {n: (t.get("title"), sorted(t.get("depends_on") or [])) for n, t in _tasks(st)}
    found = []
    for n in sorted(set(spec) | set(have)):
        if n not in spec or n not in have:
            where = "spec.json" if n not in spec else "the run state"
            found.append(Finding("spec-task-missing", f"Task {n} is missing from {where}.", task=n, fix={"kind": "spec"}))
        elif spec[n] != have[n]:
            found.append(Finding("spec-task-differs", f"Task {n} differs between spec.json and the run state "
                                 "(title or depends_on).", task=n, fix={"kind": "spec"}))
    return found


def _running_elsewhere(run_dir: Path) -> list[str]:
    """The ids of other runs on the server whose state says running."""
    root = paths.runs()
    others = []
    for proj in sorted(root.iterdir()) if root.is_dir() else []:
        for d in sorted(proj.iterdir()) if proj.is_dir() else []:
            if d.is_dir() and d != run_dir and (atomic.read_json(d / "state.json") or {}).get("status") == "running":
                others.append(d.name)
    return others


def check_server(run_dir: Path, st: dict, as_run: Path | None = None) -> list[Finding]:
    """At most one run is running on the whole server (as_run: the real folder when run_dir is a scratch copy)."""
    if st.get("status") != "running":
        return []
    others = _running_elsewhere(Path(as_run) if as_run else run_dir)
    if not others:
        return []
    return [Finding("many-runs-running", "Another run is running on the server too (" + ", ".join(others)
                    + "); only one can.", fix={"kind": "run-status"})]


CHECKS = (check_statuses, check_agreement, check_tries, check_one_running, check_questions,
          check_worktree, check_settings, check_spec, check_server)


def run_checks(run_dir, as_run=None) -> list[Finding]:
    """Run every state invariant on one run folder and return all findings (empty = healthy).

    as_run: the real run folder when run_dir is a scratch copy of it, so the copy is not "another run"."""
    run_dir = Path(run_dir)
    st = state.load(run_dir) or {}
    found = check_statuses(run_dir, st)
    if found:
        return found                    # the other checks need known statuses
    for check in CHECKS[1:]:
        found += check(run_dir, st, as_run) if check is check_server else check(run_dir, st)
    return found
