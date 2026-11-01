"""The runner: walks a run through the step plan (run-start, each task, run-finish), one step at a time.

It is a plain script. It trusts exit codes, files it wrote and reports it read itself; AI only ever
runs inside a step container (docs/architecture.md sections 4, 7 and 8).
"""
from __future__ import annotations

import re
import traceback
from pathlib import Path

from phoenix9 import atomic, events, gates, paths, scrub, settings, spec as spec_mod, state
from phoenix9 import claude as claude_mod
from phoenix9 import docker as docker_mod
from phoenix9.library import CodeError, Library, Step, load_code, load_library
from phoenix9.resolve import resolve
from phoenix9.stepctx import ProjectInfo, RunInfo, StepContext, StepInfo, StepResult, UsageLimit

FINAL = ("done", "failed", "stopped")
AI_KEYS = ("model", "fallback_models", "tools", "tools_denied", "mcp_servers", "claude_md", "skills",
           "max_turns", "timeout", "advisor")


class Runner:
    """Drives runs. `adapters` is the (real or fake) adapter set; `lib_root` holds steps/ and friends."""

    def __init__(self, adapters, lib_root):
        """Remember the adapters and load the step library."""
        self.adapters = adapters
        self.lib: Library = load_library(Path(lib_root))

    # ------------------------------------------------------------------ the whole run
    def drive(self, run_dir) -> str:
        """Run (or continue) one run until it is done, failed or waiting; return its status."""
        run_dir = Path(run_dir)
        st = state.load(run_dir)
        if st["status"] in FINAL or st["status"] == "waiting":
            return st["status"]
        state.set_status(run_dir, "running")
        project, run_id = st["project"], st["run_id"]
        try:
            setup = self._setup(run_dir, project, run_id)
        except Exception as err:  # bad settings or an impossible plan end the run, they do not crash it
            return self._finish(run_dir, project, run_id, "failed", scrub.scrub(str(err)))
        things = atomic.read_json(run_dir / "things.json", {})
        outcome = self._walk(run_dir, setup, things)
        if outcome == "waiting":
            return "waiting"
        status = "done" if outcome == "ok" else "failed"
        return self._finish(run_dir, project, run_id, status)

    def _finish(self, run_dir: Path, project: str, run_id: str, status: str, reason: str = "") -> str:
        """Set the final run status and emit run.finished."""
        state.set_status(run_dir, status)
        data = {"reason": reason} if reason else {}
        events.emit("run.finished", project=project, run=run_id, status=status, **data)
        return status

    def _setup(self, run_dir: Path, project: str, run_id: str) -> dict:
        """Load (or, on first drive, make and save) the frozen settings and the plan."""
        project_dir = paths.projects() / project
        sfile, pfile = run_dir / "settings.json", run_dir / "plan.json"
        values = atomic.read_json(sfile)
        if values is None:
            eff = settings.effective(project_dir, self.lib, atomic.read_json(run_dir / "overrides.json"))
            values = eff.values
            atomic.write_json(sfile, values)
        plan = atomic.read_json(pfile)
        if plan is None:
            enabled = {n: bool(t["on"]) for n, t in values.get("steps", {}).items()}
            plan = resolve(self.lib, enabled).to_json()
            atomic.write_json(pfile, plan)
        profile_name = values.get("profile") or ""
        profile = settings.load_profile(self.lib.root, profile_name) if profile_name else {}
        info = ProjectInfo(name=project, dir=project_dir, code_dir=project_dir / "code",
                           settings=values, profile=profile)
        return {"settings": values, "plan": plan, "project": info}

    def _spec_data(self, run_dir: Path, save: bool = True) -> dict:
        """spec.json, or (when no step made it) the spec parsed from the run's own copy (and saved)."""
        data = atomic.read_json(run_dir / "spec.json")
        if data is None:
            text = (run_dir / "spec.md").read_text(encoding="utf-8")
            data = spec_mod.to_json(spec_mod.parse(text))
            if save:
                atomic.write_json(run_dir / "spec.json", data)
        return data

    def _walk(self, run_dir: Path, setup: dict, things: dict) -> str:
        """Run-start steps, then every task, then run-finish steps. Returns ok | failed | waiting."""
        plan = setup["plan"]["groups"]
        failed = False
        start_ok = True
        for name in plan["run-start"]:
            result = self._do_step(run_dir, setup, things, "run-start", name, None)
            if result == "waiting":
                return "waiting"
            if result == "failed":
                start_ok = False
                break
        spec_data = self._spec_data(run_dir) if start_ok else {"tasks": []}
        if not start_ok:
            self._skip_all(run_dir, state.load(run_dir))
            return "failed"
        parsed = spec_mod.from_json(spec_data)
        for task in spec_mod.order(parsed):
            outcome = self._do_task(run_dir, setup, things, spec_data, task)
            if outcome == "waiting":
                return "waiting"
            failed = failed or outcome != "passed"
        for name in plan["run-finish"]:
            result = self._do_step(run_dir, setup, things, "run-finish", name, None)
            if result == "waiting":
                return "waiting"
            failed = failed or result == "failed"
        return "failed" if failed else "ok"

    def _skip_all(self, run_dir: Path, st: dict) -> None:
        """After a failed start: mark every unfinished task skipped."""
        for n, t in st["tasks"].items():
            if t["status"] in ("pending", "running"):
                state.set_task(run_dir, int(n), status="skipped")

    # ------------------------------------------------------------------ tasks
    def _do_task(self, run_dir: Path, setup: dict, things: dict, spec_data: dict, task) -> str:
        """Run one task's step group once. Returns passed | failed | skipped | waiting."""
        st = state.load(run_dir)
        n = task.number
        current = st["tasks"].get(str(n), {}).get("status", "pending")
        if current in ("passed", "failed", "skipped"):
            return current
        project, run_id = st["project"], st["run_id"]
        blocked = [d for d in task.depends_on if st["tasks"].get(str(d), {}).get("status") in ("failed", "skipped")]
        if blocked:
            reason = "Task " + ", ".join(str(d) for d in blocked) + " did not pass, so this task was skipped."
            state.set_task(run_dir, n, status="skipped", failures=[reason])
            events.emit("task.finished", project=project, run=run_id, task=n, status="skipped")
            return "skipped"
        if current == "pending":
            events.emit("task.started", project=project, run=run_id, task=n, title=task.title)
        state.set_task(run_dir, n, status="running", tries=1)
        task_data = next(t for t in spec_data["tasks"] if t["number"] == n)
        for name in setup["plan"]["groups"]["task"]:
            result = self._do_step(run_dir, setup, things, "task", name, task_data)
            if result == "waiting":
                return "waiting"
            if result == "failed":
                return self._fail_task(run_dir, project, run_id, n)
        state.set_task(run_dir, n, status="passed")
        events.emit("task.finished", project=project, run=run_id, task=n, status="passed")
        return "passed"

    def _fail_task(self, run_dir: Path, project: str, run_id: str, n: int) -> str:
        """Mark the task failed (its dependents are skipped when the loop reaches them)."""
        line = next((x for x in reversed(state.load(run_dir)["steps"]) if x["task"] == n and x["status"] == "failed"), {})
        state.set_task(run_dir, n, status="failed")
        events.emit("task.finished", project=project, run=run_id, task=n, status="failed", note=line.get("note", ""))
        return "failed"

    # ------------------------------------------------------------------ one step
    def _do_step(self, run_dir: Path, setup: dict, things: dict, group: str, name: str, task: dict | None) -> str:
        """Run one step with its state line and events. Returns passed | failed | skipped | waiting."""
        st = state.load(run_dir)
        project, run_id = st["project"], st["run_id"]
        number = task["number"] if task else None
        index = next((i for i, x in enumerate(st["steps"])
                      if (x["group"], x["task"], x["step"]) == (group, number, name)), None)
        if index is not None and st["steps"][index]["status"] in ("passed", "skipped"):
            return st["steps"][index]["status"]
        if index is None:
            index = state.add_step_line(run_dir, group, number, name, "running")
        else:
            state.set_step_line(run_dir, index, status="running", finished=None, note="")
        state.update(run_dir, lambda s: s.__setitem__("current", {"group": group, "task": number, "step": name, "attempt": 1}))
        events.emit("run.step.started", project=project, run=run_id, task=number, step=name, group=group)
        step = self.lib.step(name)
        ctx = self._context(run_dir, setup, things, step, task)
        result = self._call(ctx, step)
        if result.status == "gate":
            return self._open_gate(run_dir, index, step, number, result)
        status = {"pass": "passed", "fail": "failed", "skip": "skipped"}[result.status]
        note = "; ".join(result.reasons)
        if status == "failed" and number is not None:
            self._add_failures(run_dir, number, result.reasons)
        if result.produces:
            things.update(result.produces)
            atomic.write_json(run_dir / "things.json", things)
        state.set_step_line(run_dir, index, status=status, note=scrub.scrub(note))
        events.emit("run.step.finished", project=project, run=run_id, task=number, step=name, status=status,
                    reasons=[scrub.scrub(r) for r in result.reasons])
        return status

    def _add_failures(self, run_dir: Path, n: int, reasons: list[str]) -> None:
        """Remember why a task step failed (fed to later attempts and shown to Alex)."""
        def change(s):
            s["tasks"][str(n)]["failures"].extend(scrub.scrub(r) for r in reasons)
        state.update(run_dir, change)

    def _open_gate(self, run_dir: Path, index: int, step: Step, task: int | None, result: StepResult) -> str:
        """Open the gate the step asked for; the run waits (answers are handled later)."""
        spec = dict(result.gate or {})
        gate = gates.open_gate(
            run_dir, kind=spec.get("kind", "step"), title=spec.get("title", step.title),
            why=spec.get("why", "; ".join(result.reasons) or f"{step.title} needs you."),
            task=task, step=step.name, links=spec.get("links", ()), actions=spec.get("actions"),
            flags=spec.get("flags", ()))
        state.set_step_line(run_dir, index, note=f"waiting for gate {gate['id']}")
        return "waiting"

    def _call(self, ctx: StepContext, step: Step) -> StepResult:
        """Call the step's code, turning any crash or broken import into a failed result."""
        try:
            if step.kind == "gate":
                return StepResult("gate", gate={"title": step.title, "why": step.description})
            code = load_code(self.lib, step)
            if step.kind == "ai":
                return run_ai_step(ctx, code)
            if code is None or not hasattr(code, "run"):
                return StepResult("fail", [f"{step.title} has no run.py to run."])
            result = code.run(ctx)
            if not isinstance(result, StepResult):
                return StepResult("fail", [f"{step.title} did not return a StepResult."])
            return result
        except CodeError as err:
            return StepResult("fail", [str(err)])
        except UsageLimit:
            raise
        except Exception as err:
            ctx.log(traceback.format_exc())
            return StepResult("fail", [f"{step.title} crashed: {type(err).__name__}: {err}"])

    # ------------------------------------------------------------------ context and things
    def _context(self, run_dir: Path, setup: dict, things: dict, step: Step, task: dict | None) -> StepContext:
        """Build the StepContext: provided things, produced things and fallbacks for every need."""
        st = state.load(run_dir)
        project, run_id = st["project"], st["run_id"]
        info: ProjectInfo = setup["project"]
        work = paths.work(project, run_id)
        worktree = work if work.is_dir() else None
        spec_data = self._spec_data(run_dir, save=False)
        number = task["number"] if task else None
        failures = st["tasks"].get(str(number), {}).get("failures", []) if task else []
        provided = {"spec": spec_data, "task": task, "worktree": str(worktree) if worktree else "",
                    "failures": list(failures)}
        visible = dict(things)
        for need, source in setup["plan"]["sources"].get(step.name, {}).items():
            if source == "provided":
                visible[need] = provided.get(need)
            elif source.startswith("fallback:"):
                visible[need] = source.split(":", 1)[1]
            else:
                visible[need] = things.get(need, "")
        values = setup["settings"].get("steps", {}).get(step.name, {})
        ai = {k: values[k] for k in AI_KEYS if k in values} if step.kind == "ai" else {}
        own = {k: v for k, v in values.items() if k != "on" and k not in ai}
        logfile = run_dir / "logs" / f"{step.name}.log"

        def emit(type: str, **data):
            return events.emit(type, project=project, run=run_id, task=number, step=step.name, **data)

        def log(text: str) -> None:
            logfile.parent.mkdir(parents=True, exist_ok=True)
            with open(logfile, "a", encoding="utf-8") as f:
                f.write(scrub.scrub(text).rstrip("\n") + "\n")

        return StepContext(
            project=info, run=RunInfo(id=run_id, folder=run_dir, spec=spec_data),
            step=StepInfo(name=step.name, kind=step.kind, folder=step.folder, settings=own, ai=ai,
                          produces=step.produces),
            task=task, attempt=1, worktree=worktree, things=visible, adapters=self.adapters,
            emit=emit, log=log)


# ---------------------------------------------------------------------- AI steps
def _task_text(task: dict | None) -> str:
    """The task as plain text for a prompt."""
    if not task:
        return ""
    lines = [f"Task {task['number']}: {task['title']}", "", task.get("goal", "")]
    return "\n".join(lines).strip()


def _checks_text(ctx: StepContext) -> str:
    """The 'Done when' bullets of the task (or the produced checks) as a list."""
    checks = ctx.things.get("checks")
    if checks and checks != "spec-done-when":
        return str(checks)
    done = (ctx.task or {}).get("done_when", [])
    return "\n".join(f"- {c['text']}" for c in done)


def render_prompt(template: str, values: dict) -> str:
    """Fill {{placeholders}} in a prompt; names that are not known stay as written."""
    return re.sub(r"\{\{\s*([\w-]+)\s*\}\}", lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), template)


def run_ai_step(ctx: StepContext, code=None) -> StepResult:
    """Run one AI step: fill the prompt, run a Claude session in a container, then judge it from files."""
    if ctx.worktree is None:
        return StepResult("fail", ["There is no worktree for the AI session to work in."])
    folder = Path(ctx.step.folder)
    prompt_file = folder / "prompt.md"
    if not prompt_file.is_file():
        return StepResult("fail", [f"{ctx.step.name} has no prompt.md."])
    values = {k: (v if isinstance(v, str) else ("\n".join(map(str, v)) if isinstance(v, list) else str(v)))
              for k, v in ctx.things.items() if v is not None}
    values.update({"task": _task_text(ctx.task), "checks": _checks_text(ctx),
                   "spec_title": ctx.run.spec.get("title", "")})
    if code is not None and hasattr(code, "before"):
        values.update({k: str(v) for k, v in (code.before(ctx) or {}).items()})
    number = ctx.task["number"] if ctx.task else 0
    attempt_dir = ctx.run.folder / "tasks" / str(number) / f"attempt-{ctx.attempt}"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    out_prompt = attempt_dir / f"{ctx.step.name}-prompt.md"
    out_prompt.write_text(render_prompt(prompt_file.read_text(encoding="utf-8"), values), encoding="utf-8")
    profile = ctx.project.profile
    domains = docker_mod.write_domains_file(ctx.project.name, profile.get("allowed_domains", ()),
                                            ctx.project.settings.get("allowed_domains", ()))
    mount_dir = ctx.run.folder / "spec-mount"
    mount_dir.mkdir(exist_ok=True)
    if not (mount_dir / "spec.md").exists():
        atomic.write_text(mount_dir / "spec.md", (ctx.run.folder / "spec.md").read_text(encoding="utf-8"), mode=0o444)
    session = ctx.adapters.claude.launch(
        ctx.adapters.docker, ai=ctx.step.ai, project=ctx.project.name, run_id=ctx.run.id, task=number,
        attempt=ctx.attempt, role=ctx.step.name, image=profile.get("image", ""), workspace=ctx.worktree,
        prompt_file=out_prompt, step_dir=folder, project_dir=ctx.project.dir, spec_dir=mount_dir,
        domains_file=domains)
    claude_mod.record_usage(ctx.run.folder, session, attempt_dir)
    ctx.log(f"session ended: {session.kind}")
    if session.kind == "rate_limited":
        raise UsageLimit(session)
    if code is not None and hasattr(code, "after"):
        return code.after(ctx, session)
    if session.kind == "ok":
        return StepResult("pass")
    return StepResult("fail", [f"The AI session ended without finishing ({session.kind})."])
