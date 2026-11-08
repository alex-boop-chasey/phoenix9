"""The repair note steps: one function per step, and the registry the apply engine looks them up in."""
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import tomllib

from phoenix9 import (adapters as adapters_mod, atomic, checklock, failmodes, gates, git, paths, resolve, runend, scrub,
                      settings, spec as specmod, state, summary)
from phoenix9.library import load_library
from phoenix9.repair import snapshot
from phoenix9.runner import RunFailed, Runner


class StepRefused(Exception):
    """A step cannot be done; the message says why in plain words."""


@dataclass
class Context:
    """What a step is given: the run folder to change (a scratch copy in a dry run) and how it was asked."""
    run_dir: object
    dry: bool = False
    approve_unlock: bool = False
    who: str = "repair"


def _task(ctx, n: int) -> dict:
    """The state entry of task n, or refuse when the run has no such task."""
    task = (state.load(ctx.run_dir).get("tasks") or {}).get(str(n))
    if task is None:
        raise StepRefused(f"task {n} is not in this run")
    return task


def _unwaiting(ctx, n: int) -> None:
    """Refuse when task n waits on an open question (close the question first)."""
    if _task(ctx, n).get("gate"):
        raise StepRefused(f"task {n} is waiting on a question; close the question first")


def _skip_dependents(st: dict, n: int, why: str) -> list[int]:
    """Skip every unfinished task that needs task n, directly or through others; return their numbers."""
    tasks, skipped, todo = st["tasks"], [], [str(n)]
    while todo:
        cur = todo.pop()
        for key, t in sorted(tasks.items(), key=lambda kv: int(kv[0])):
            if cur in [str(d) for d in t.get("depends_on") or []] and key not in todo and int(key) not in skipped:
                if t.get("status") in ("pending", "running", "waiting"):
                    t.update(status="skipped", gate=None, note=why)
                    skipped.append(int(key))
                todo.append(key)
    return sorted(skipped)


def mark_done(ctx, n: int, why: str) -> str:
    """Mark task n passed, with the reason as its note and its flag cleared."""
    _unwaiting(ctx, n)
    state.update(ctx.run_dir, lambda s: s["tasks"][str(n)].update(
        status="passed", note=scrub.scrub(why), flagged="", gate=None, rerun=False))
    return f"task {n} is now done ({scrub.scrub(why)})"


def mark_skipped(ctx, n: int, why: str) -> str:
    """Mark task n skipped, and skip the unfinished tasks that depend on it."""
    _unwaiting(ctx, n)
    skipped = []

    def change(s):
        s["tasks"][str(n)].update(status="skipped", note=scrub.scrub(why), gate=None, rerun=False)
        skipped.extend(_skip_dependents(s, n, f"depends on task {n}, which was skipped"))
    state.update(ctx.run_dir, change)
    more = f"; also skipped task {', '.join(map(str, skipped))}" if skipped else ""
    return f"task {n} is now skipped ({scrub.scrub(why)}){more}"


def retry(ctx, n: int) -> str:
    """Put task n back to pending with rerun on, keeping its failures."""
    _unwaiting(ctx, n)
    state.update(ctx.run_dir, lambda s: s["tasks"][str(n)].update(status="pending", rerun=True, flagged=""))
    return f"task {n} will run again (its earlier failures are kept)"


def clear_failures(ctx, n: int) -> str:
    """Forget the failure reasons of task n."""
    count = len(_task(ctx, n).get("failures") or [])
    state.update(ctx.run_dir, lambda s: s["tasks"][str(n)].update(failures=[]))
    return f"cleared {count} failure(s) of task {n}"


def add_note(ctx, n: int, text: str) -> str:
    """Add a note to the failures of task n, which the next attempt reads."""
    line = "Note from the repair: " + scrub.scrub(text)
    _task(ctx, n)
    state.update(ctx.run_dir, lambda s: s["tasks"][str(n)].setdefault("failures", []).append(line))
    return f"added a note to task {n}"


# ---------------------------------------------------------------------- worktree steps
QUIET = SimpleNamespace(notify=SimpleNamespace(send=lambda text: None), git=git)


def _work(ctx) -> Path:
    """The run's worktree, or refuse when it is gone (rebuild the worktree is the step for that)."""
    work = snapshot.worktree_of(ctx.run_dir)
    if not work.is_dir():
        raise StepRefused("the worktree is gone; use 'rebuild the worktree' first")
    return work


def _snapshot_number(ctx) -> int:
    """The number of the snapshot taken for this repair (the newest one)."""
    return max(snapshot._numbers(Path(ctx.run_dir)), default=1)


def _hard_reset(work: Path, sha: str) -> None:
    """Reset the worktree hard to sha and drop untracked files, but keep env files (undo cannot bring them back)."""
    git.git(work, "reset", "-q", "--hard", sha)
    git.git(work, "clean", "-fdq", "-e", ".env*")


def _env_task(ctx) -> int | None:
    """The task env files are filed under: the current task, else the first failed one, else the first."""
    st = state.load(ctx.run_dir)
    tasks = st.get("tasks") or {}
    current = (st.get("current") or {}).get("task")
    if current is not None and str(current) in tasks:
        return int(current)
    failed = sorted(int(k) for k, t in tasks.items() if t.get("status") == "failed")
    return failed[0] if failed else min(map(int, tasks), default=None)


def _moved_text(moved: list[str], task: int) -> str:
    """Plain words for the env files moved out of the worktree."""
    return f"; moved env file(s) {', '.join(moved)} to tasks/{task}/outside-env/" if moved else ""


def redo(ctx, n: int) -> str:
    """Put task n and every later task back to pending (tries 0, failures cleared), move their attempts aside
    and reset the worktree to the commit task n started from."""
    tasks = (state.load(ctx.run_dir).get("tasks") or {})
    _task(ctx, n)
    later = sorted(int(k) for k in tasks if int(k) >= n)
    for k in later:
        _unwaiting(ctx, k)
    base = tasks[str(n)].get("attempt_base")
    if not base:
        raise StepRefused(f"task {n} has no recorded start commit, so its work cannot be reset")
    work = None if ctx.dry else _work(ctx)
    keep = ("title", "depends_on", "escalations")

    def change(s):
        for k in later:
            t = s["tasks"][str(k)]
            fresh = state.new_task()
            fresh.update({f: t[f] for f in keep if f in t})
            if k == n:
                fresh["attempt_base"] = base
            t.clear()
            t.update(fresh)
        s["steps"] = [x for x in s["steps"] if x.get("task") is None or x["task"] < n]
        if (s.get("current") or {}).get("task") in later:
            s["current"].update(task=None, step=None, attempt=None, gate=None)
    state.update(ctx.run_dir, change)
    number = _snapshot_number(ctx)
    for k in later:
        for folder in sorted((Path(ctx.run_dir) / "tasks" / str(k)).glob("attempt-*")):
            snapshot.move_to_removed(ctx.run_dir, number, folder)
    if work is not None:
        _hard_reset(work, base)
    names = ", ".join(map(str, later))
    return f"task {names} will start again from scratch" + ("" if work else " (the worktree is not touched in a dry run)")


def keep_hand_fix(ctx, message: str) -> str:
    """Commit the uncommitted worktree changes as an outside fix and start the current task from that commit."""
    task = _env_task(ctx)
    if task is None:
        raise StepRefused("this run has no tasks")
    if ctx.dry:
        return f"would commit the hand fix with message \"{scrub.scrub(message)}\""
    work = _work(ctx)
    moved = failmodes.move_env_out(QUIET, ctx.run_dir, work, task)
    extra = _moved_text(moved, task)
    if not git.pending_paths(work, skip_env=True):
        return "the worktree has no changes to keep" + extra
    if git.scan_secrets(git.diff_text(work, "HEAD")):
        raise StepRefused("the worktree changes look like they hold a secret; take it out first")
    run_id = state.load(ctx.run_dir)["run_id"]
    sha = git.commit(work, scrub.scrub(message), {"Phoenix-Run": run_id, "Phoenix-Task": str(task),
                                                  "Phoenix-Fix-By": "repair"}, skip_env=True)
    state.update(ctx.run_dir, lambda s: s["tasks"][str(task)].update(attempt_base=sha))
    return f"committed the hand fix as {sha[:10]}; task {task} now starts from it{extra}"


def _on_branch_or_main(work: Path, run_id: str, sha: str) -> bool:
    """True when the commit is part of phoenix/<run> or of main."""
    for ref in (git.branch_name(run_id), git.MAIN):
        if git.run_git(work, "merge-base", "--is-ancestor", sha, f"refs/heads/{ref}", check=False).returncode == 0:
            return True
    return False


def _lost_bases(ctx, work: Path) -> list[int]:
    """Tasks whose attempt_base the worktree no longer contains."""
    lost = []
    for k, t in sorted((state.load(ctx.run_dir).get("tasks") or {}).items(), key=lambda kv: int(kv[0])):
        base = t.get("attempt_base")
        if base and git.run_git(work, "merge-base", "--is-ancestor", base, "HEAD", check=False).returncode != 0:
            lost.append(int(k))
    return lost


def reset_worktree(ctx, sha: str) -> str:
    """Reset the worktree to a commit of phoenix/<run> or main; name the tasks whose start commit is then gone."""
    work = _work(ctx)
    found = git.run_git(work, "rev-parse", "--verify", "-q", f"{sha}^{{commit}}", check=False)
    if found.returncode != 0:
        raise StepRefused(f"{sha} is not a commit of this project")
    full = found.stdout.decode().strip()
    if not _on_branch_or_main(work, Path(ctx.run_dir).name, full):
        raise StepRefused(f"{sha} is not a commit on {git.branch_name(Path(ctx.run_dir).name)} or main")
    if ctx.dry:
        return f"would reset the worktree to {full[:10]}"
    _hard_reset(work, full)
    lost = _lost_bases(ctx, work)
    tail = (f"; task {', '.join(map(str, lost))} no longer has its start commit (redo it, or the check fails)"
            if lost else "")
    return f"reset the worktree to {full[:10]}{tail}"


def rebuild_worktree(ctx) -> str:
    """Remove the worktree and make it again from the branch; uncommitted and untracked files are dropped."""
    run_dir = Path(ctx.run_dir)
    if ctx.dry:
        return "would rebuild the worktree from its branch"
    work, code = snapshot.worktree_of(run_dir), snapshot.code_dir_of(run_dir)
    moved, task = [], _env_task(ctx)
    if work.is_dir() and task is not None:
        moved = failmodes.move_env_out(QUIET, run_dir, work, task)
    try:
        git.remove_worktree(code, work)
        git.make_worktree(code, run_dir.name, work)
    except git.GitError as e:
        raise StepRefused(f"the worktree could not be rebuilt: {scrub.scrub(str(e))}") from e
    return "rebuilt the worktree from its branch (uncommitted and untracked files were dropped)" + (
        _moved_text(moved, task) if moved else "")


FORBIDDEN_TOP = ("domains", "services", "safety_files", "keys", "secrets", "images", "docker")
FORBIDDEN_KEYS = ("diff.allow_extra",)
PROTECTED_STEPS = ("diff-rules", "secret-scan")


def _lib():
    """The step library of the running copy."""
    return load_library(paths.library())


def _forbidden_key(key: str) -> str | None:
    """Why a settings key can never be changed by a repair, or None."""
    top = key.split(".")[0]
    if top in FORBIDDEN_TOP or key in FORBIDDEN_KEYS:
        return f"'{key}' is a safety setting; a repair never changes it. Change it in Settings yourself."
    if any(word in key.lower() for word in ("tool", "mcp")):
        return f"'{key}' changes what the agent may use; a repair never changes it. Change it in Settings yourself."
    parts = key.split(".")
    if len(parts) >= 2 and parts[0] == "steps":
        guard = _lib()
        if parts[1] in PROTECTED_STEPS or (guard.has_step(parts[1]) and guard.step(parts[1]).safety):
            return f"'{key}' belongs to step {parts[1]}, which guards the run; a repair never changes it."
    return None


def _enabled(values: dict) -> dict:
    """The on/off map of the steps in a run's settings."""
    return {n: bool(t["on"]) for n, t in (values.get("steps") or {}).items() if isinstance(t, dict) and "on" in t}


def _plan_of(lib, values: dict) -> dict:
    """The plan the resolver makes of these settings, as plain data; refuse when it cannot be made."""
    try:
        return resolve.resolve(lib, _enabled(values)).to_json()
    except resolve.ResolveError as err:
        raise StepRefused(f"the steps cannot work like that: {err}") from None


def _guard_step_off(lib, old: dict, new: dict, name: str) -> None:
    """Refuse switching a step off when it always runs, guards the run, or a safety step needs it."""
    if not lib.has_step(name):
        raise StepRefused(f"there is no step called '{name}'")
    step = lib.step(name)
    if step.default == "always" or name in PROTECTED_STEPS or step.safety:
        raise StepRefused(f"step {name} can never be switched off by a repair")
    lost = [r["name"] for r in old["steps"] if r["safety"] and r["on"]
            and not next(n for n in new["steps"] if n["name"] == r["name"])["on"]]
    if lost:
        raise StepRefused(f"step {name} is needed by safety step {lost[0]}")


def _freeze(ctx, plan: bool = False, key: str | None = None) -> None:
    """Record in repairs/frozen.json that a repair set the plan or a setting, so the check accepts it."""
    path = Path(ctx.run_dir) / snapshot.FROZEN
    data = atomic.read_json(path) or {}
    data["plan"] = bool(data.get("plan")) or plan
    keys = list(data.get("settings") or [])
    if key and key not in keys:
        keys.append(key)
    data["settings"] = keys
    atomic.write_json(path, data)


def _parse_toml_value(text: str):
    """The value written as TOML text, or refuse."""
    try:
        return tomllib.loads(f"v = {text}")["v"]
    except (tomllib.TOMLDecodeError, KeyError):
        raise StepRefused(f"'{text}' is not a value I can read (write it as TOML, for example 4, true or \"text\")") from None


def _leaves(key: str, value) -> dict:
    """The dotted leaf keys a value would set (a table value sets every key inside it)."""
    flat = settings._flatten({key: value})
    if not flat:
        raise StepRefused(f"'{key}' needs a value")
    return flat


def _check_leaf(lib, specs: dict, old_values: dict, path: str, value) -> None:
    """Refuse one leaf key that is forbidden, unknown, wrongly typed, or shrinks the diff deny list."""
    why = _forbidden_key(path)
    if why:
        raise StepRefused(why)
    if path not in specs:
        raise StepRefused(f"'{path}' is not a setting a repair can set")
    problems = settings._leaf_problems(path, value, specs[path], "this run")
    if problems:
        raise StepRefused("; ".join(problems))
    if path == "diff.deny_extra":
        have = settings._flatten(old_values).get(path) or []
        missing = [x for x in have if x not in value]
        if missing:
            raise StepRefused(f"diff.deny_extra can only grow; '{missing[0]}' would be dropped")


def set_setting(ctx, key: str, value: str) -> str:
    """Set one setting for this run in settings.json and make plan.json again from the settings."""
    lib, run_dir = _lib(), Path(ctx.run_dir)
    old_values = atomic.read_json(run_dir / "settings.json") or {}
    leaves = _leaves(key, _parse_toml_value(value))
    specs = settings.all_specs(lib)
    for path, val in leaves.items():
        _check_leaf(lib, specs, old_values, path, val)
    flat = {**settings._flatten(old_values), **leaves}
    new_values = settings._unflatten(flat)
    old_plan, new_plan = _plan_of(lib, old_values), _plan_of(lib, new_values)
    for path, val in leaves.items():
        parts = path.split(".")
        if parts[0] == "steps" and parts[-1] == "on" and not val:
            _guard_step_off(lib, old_plan, new_plan, parts[1])
    lost = [r["name"] for r in old_plan["steps"] if r["safety"] and r["on"]
            and not next(n for n in new_plan["steps"] if n["name"] == r["name"])["on"]]
    if lost:
        raise StepRefused(f"that would switch off safety step {lost[0]}")
    atomic.write_json(run_dir / "settings.json", new_values)
    atomic.write_json(run_dir / "plan.json", new_plan)
    for path in leaves:
        _freeze(ctx, plan=True, key=path)
    return f"set {key} = {value} for this run and made the plan again"


def turn_off_step(ctx, name: str) -> str:
    """Take one step out of this run's plan (never diff-rules, secret-scan or a step a safety rule needs)."""
    lib, run_dir = _lib(), Path(ctx.run_dir)
    values = atomic.read_json(run_dir / "settings.json") or {}
    old_plan = _plan_of(lib, values)
    if lib.has_step(name) and not next((r["on"] for r in old_plan["steps"] if r["name"] == name), False):
        raise StepRefused(f"step {name} is already off in this run")
    new_values = settings._unflatten({**settings._flatten(values), f"steps.{name}.on": False})
    new_plan = _plan_of(lib, new_values)
    _guard_step_off(lib, old_plan, new_plan, name)
    atomic.write_json(run_dir / "settings.json", new_values)
    atomic.write_json(run_dir / "plan.json", new_plan)
    _freeze(ctx, plan=True, key=f"steps.{name}.on")
    return f"turned off step {name} for this run"


def _notes_file(run_dir: Path, path: str) -> Path:
    """The spec file under the project's notes/, or refuse when it is anywhere else."""
    notes = (paths.projects() / run_dir.parent.name / "notes").resolve()
    target = Path(path)
    target = (target if target.is_absolute() else notes.parent / target).resolve()
    if not target.is_relative_to(notes) or not target.is_file():
        raise StepRefused(f"the spec must be a file inside the project's notes/ folder: {path}")
    return target


def _merged_tasks(old: dict, new_spec) -> dict:
    """The state tasks after a spec swap: same number and title keeps its entry, new are pending; refuse lost work."""
    out = {}
    for t in new_spec.tasks:
        have = old.get(str(t.number))
        if have is not None and have.get("title") == t.title:
            out[str(t.number)] = dict(have, depends_on=list(t.depends_on))
        elif have is not None and have.get("status") != "pending":
            raise StepRefused(f"task {t.number} is {have.get('status')} here as '{have.get('title')}'; "
                              f"the new spec calls it '{t.title}'")
        else:
            out[str(t.number)] = state.new_task(t.title, t.depends_on)
    kept = [n for n, have in old.items() if n not in out and have.get("status") != "pending"]
    if kept:
        raise StepRefused(f"task {kept[0]} is not in the new spec but has already been worked on")
    return out


def replace_spec(ctx, path: str) -> str:
    """Swap the run's spec for a file from the project's notes/, keeping the progress of matching tasks."""
    run_dir = Path(ctx.run_dir)
    file = _notes_file(run_dir, path)
    text = file.read_text(encoding="utf-8")
    problems = specmod.check(text)
    if problems:
        raise StepRefused("the new spec does not parse: " + "; ".join(problems[:3]))
    new_spec = specmod.parse(text)
    merged = _merged_tasks(state.load(run_dir).get("tasks") or {}, new_spec)
    atomic.write_text(run_dir / "spec.md", text)
    atomic.write_json(run_dir / "spec.json", specmod.to_json(new_spec))

    def change(st):
        st["tasks"] = merged
    state.update(run_dir, change)
    return f"replaced the spec with {file.name} ({len(merged)} tasks)"


def close_question(ctx, id: str, action: str) -> str:
    """Answer (or, with 'closed', close) one question of this run the normal way."""
    run_dir = Path(ctx.run_dir)
    gate = gates.read(run_dir, id)
    if gate is None or gate.get("run") != run_dir.name:
        raise StepRefused(f"question {id} is not a question of this run")
    if action == "closed":
        if ctx.dry:
            return f"would close question {id}"
        if not gates.close_questions(run_dir, "closed by a repair", who=ctx.who, only=id):
            raise StepRefused(f"question {id} is already answered or closed")
        return f"closed question {id}"
    try:
        project_settings = settings.load_project(paths.projects() / run_dir.parent.name)
    except settings.SettingsError:
        project_settings = {}
    if not gates.may_answer(gate, ctx.who, project_settings):
        raise StepRefused(f"'{ctx.who}' may not answer {gate['kind']} questions here")
    if action not in gate["actions"]:
        raise StepRefused(f"'{action}' is not allowed for question {id}; use one of {', '.join(gate['actions'])}")
    if not any(g["id"] == id and g["state"] == "open" for g in gates.run_gates(run_dir)):
        raise StepRefused(f"question {id} is not open (the run is not waiting on it)")
    if ctx.dry:
        return f"would answer question {id} with {action}"
    try:
        gates.answer(id, action, note="answered by a repair", who=ctx.who)
    except (gates.NotOpen, ValueError) as err:
        raise StepRefused(str(err)) from None
    return f"answered question {id} with {action}"


# ---------------------------------------------------------------------- rewrite checks, rerun finish step
UNLOCK_REFUSED = "needs Alex's approval: it unlocks checks"
BUILD_STEPS = ("builder", "reviewer")


def _project_settings(run_dir: Path) -> dict:
    """The project's own settings, or nothing when they cannot be read."""
    try:
        return settings.load_project(paths.projects() / run_dir.parent.name)
    except settings.SettingsError:
        return {}


def _may_unlock(ctx) -> bool:
    """True when the unlock is approved and the asker may answer an escalation question of this project."""
    return bool(ctx.approve_unlock) and gates.may_answer({"kind": "escalation"}, ctx.who, _project_settings(Path(ctx.run_dir)))


def _objections(ctx, n: int, locked: list[str]) -> list[str]:
    """The failure and step-line reasons of task n that give the checks as the cause (SPEC_PROBLEM or a locked file)."""
    st = state.load(ctx.run_dir)
    texts = list(_task(ctx, n).get("failures") or [])
    texts += [x.get("note") or "" for x in st.get("steps") or []
              if x.get("task") == n and x.get("step") in BUILD_STEPS]
    names = [p for f in locked for p in (f, f.rsplit("/", 1)[-1])]
    return [t for t in texts if t and ("SPEC_PROBLEM" in t or any(name in t for name in names))]


def _locked_files(ctx, n: int) -> tuple[str, list[str]]:
    """The folder and the files in task n's checklock manifest (empty when the task has none)."""
    data = atomic.read_json(Path(ctx.run_dir) / "tasks" / str(n) / "checks.lock.json") or {}
    return data.get("dir", ""), sorted(data.get("files") or {})


def _once_steps(ctx) -> set[str]:
    """The task steps this run's settings mark `once`."""
    values = atomic.read_json(Path(ctx.run_dir) / "settings.json") or {}
    return {name for name, conf in (values.get("steps") or {}).items() if isinstance(conf, dict) and conf.get("once")}


def _remove_checks(ctx, n: int, files: list[str]) -> str | None:
    """Take the locked check files out of the worktree with one commit; return the new head (None if nothing changed)."""
    work = _work(ctx)
    git.run_git(work, "rm", "-rq", "--ignore-unmatch", "--", *files, check=False)
    for rel in files:
        (work / rel).unlink(missing_ok=True)
    if git.run_git(work, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return None
    git.git(work, *git.IDENT, "commit", "-q", "--no-verify", "-m",
            f"Remove the checks of task {n} (repair)\n\nPhoenix-Run: {Path(ctx.run_dir).name}\nPhoenix-Task: {n}\n")
    return git.head(work)


def rewrite_checks(ctx, n: int, why: str) -> str:
    """Throw away the locked checks of task n so Check-writer and Red check run again on resume (needs approval)."""
    task = _task(ctx, n)
    folder, files = _locked_files(ctx, n)
    if not _objections(ctx, n, files):
        raise StepRefused(f"task {n} has no SPEC_PROBLEM and no failure naming its locked checks; "
                          "the checks are not the problem")
    if not _may_unlock(ctx):
        raise StepRefused(UNLOCK_REFUSED)
    once = _once_steps(ctx)
    objection = scrub.scrub(why)
    if ctx.dry:
        return f"would remove the locked checks of task {n} and run the check writer again"
    head = _remove_checks(ctx, n, files) if files else None
    (Path(ctx.run_dir) / "tasks" / str(n) / "checks.lock.json").unlink(missing_ok=True)

    def change(s):
        t = s["tasks"][str(n)]
        t.update(status="pending", tries=0, flagged="", gate=None, rerun=False, check_objection=objection)
        if head:
            t["attempt_base"] = head
        s["steps"] = [x for x in s["steps"]
                      if not (x.get("task") == n and x.get("step") in once and x.get("status") == "passed")]
        for other in s["tasks"].values():
            if other.get("status") == "skipped" and (other.get("note") or "").startswith(f"depends on task {n}"):
                other.update(status="pending", note="")
    state.update(ctx.run_dir, change)
    return (f"removed the locked checks of task {n} ({len(files)} file(s)); task {n} is pending and the check "
            f"writer sees your objection: {objection}")


def make_runner() -> Runner:
    """The runner a repair uses to run one step; tests put a fake in its place."""
    return Runner(adapters_mod.real(), paths.library())


def rerun_finish(ctx, name: str) -> str:
    """Run one finish step again on a failed run, add its line and work out the run's status from the finish steps."""
    st = state.load(ctx.run_dir)
    if st.get("status") != "failed":
        raise StepRefused("a finish step can only run again on a failed run")
    plan = atomic.read_json(Path(ctx.run_dir) / "plan.json") or {}
    if name not in (plan.get("groups") or {}).get("run-finish", []):
        raise StepRefused(f"'{name}' is not a finish step of this run")
    _work(ctx)
    if ctx.dry:
        return f"would run finish step {name} again"
    try:
        status, outcome = make_runner().rerun_finish_step(Path(ctx.run_dir), name)
    except RunFailed as err:
        raise StepRefused(f"finish step {name} cannot be run: {err}") from None
    if status == "done":
        summary.refresh(Path(ctx.run_dir), paths.library())
    words = {"passed": "passed", "failed": "failed", "skipped": "was skipped", "waiting": "opened a question"}
    return f"finish step {name} {words.get(outcome, outcome)}; the run is now {status}"


def resume_run(ctx) -> str:
    """Put the run back to running (or queued if it never started) so the runner carries on; the run lock is held."""
    from phoenix9.repair import resume
    if ctx.dry:
        why = resume.refusal(ctx.run_dir)
        if why:
            raise StepRefused(why)
        return "would resume the run"
    try:
        status = resume.resume_locked(ctx.run_dir, ctx.who)
    except resume.RepairRefused as err:
        raise StepRefused(str(err)) from None
    return f"the run is {status} and the runner carries on from the first unfinished task"


STEPS = {"resume": resume_run, "redo": redo, "keep-hand-fix": keep_hand_fix, "reset-worktree": reset_worktree,
         "rebuild-worktree": rebuild_worktree, "mark-done": mark_done, "mark-skipped": mark_skipped, "retry": retry,
         "clear-failures": clear_failures, "add-note": add_note, "set-setting": set_setting,
         "turn-off-step": turn_off_step, "replace-spec": replace_spec, "close-question": close_question,
         "rewrite-checks": rewrite_checks, "rerun-finish": rerun_finish}


def run_step(ctx, step) -> str:
    """Do one parsed step; refuse the ones that are not built yet. Returns what it changed, in words."""
    fn = STEPS.get(step.kind)
    if fn is None:
        raise StepRefused(f"'{step.text}' is not supported yet")
    return fn(ctx, **step.args)
