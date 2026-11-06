"""The runner: walks a run through the step plan (run-start, each task, run-finish), one step at a time.

It is a plain script. It trusts exit codes, files it wrote and reports it read itself; AI only ever
runs inside a step container (docs/architecture.md sections 4, 7 and 8).

How it is shaped (a small state machine, every state kept in state.json so a restart picks up exactly
where it stopped):

- Every `drive()` walks the run from the top. Anything already finished is passed over, so walking is
  safe to repeat. The walk stops at the first thing that waits (an open gate) and `drive()` returns
  "waiting". The runner never blocks: the service loop (watch.py) drives the run again once the gate
  it waits on (`current.gate`) is answered.
- Two kinds of things hold a gate, and each checks its own gate's answer when the walk reaches it:
  a **step line** (the step returned status "gate"; line status "waiting", line `gate`) and a
  **task** (a human task, or an escalation after the last try; task `gate`). What each answer does is
  written once, in STEP_ANSWERS and TASK_ANSWERS below. A new gate kind returned by a step needs no
  runner change: it is a step gate.
- A task runs attempts (tries = the attempt being worked on). An attempt is the task-level steps in
  plan order; it ends at the first failed step (the worktree is reset to `attempt_base`) or when all
  pass. tasks/<n>/attempt-<k>/result.json marks it over. failmodes.py decides what comes after a
  failed attempt (retry, fail and carry on, or escalate).
- Run-level steps get no retries and no on_failure mode: a failed start step ends the run (failed),
  a failed finish step makes the run failed but the other finish steps still run. A run-level step
  that wants Alex returns a gate (any kind, e.g. escalation with acknowledged / skip / stop).
"""
from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from pathlib import Path

from phoenix9 import atomic, events, failmodes, gates, hold, paths, scrub, settings, spec as spec_mod, state
from phoenix9 import claude as claude_mod
from phoenix9 import reports, runend, runs as runs_mod, summary
from phoenix9 import keys as keys_mod
from phoenix9.aistep import checks_text, project_domains, render_prompt, task_text
from phoenix9 import docker as docker_mod, stepproxy
from phoenix9.ops.common import OpsError
from phoenix9.library import CodeError, Library, Step, load_code, load_library
from phoenix9.resolve import resolve
from phoenix9.stepctx import ProjectInfo, RunInfo, StepContext, StepInfo, StepResult, UsageLimit

FINAL = ("done", "failed", "stopped")
TASK_FINAL = ("passed", "failed", "skipped")
AI_KEYS = ("model", "fallback_models", "tools", "tools_denied", "mcp_servers", "claude_md", "skills",
           "max_turns", "timeout", "advisor")

# What an answer does to a gate a STEP opened (any kind: step, plan, merge, deploy, escalation, ...).
#   passed  = the step counts as passed with what it said it produces
#   again   = call the same step again with ctx.answer (the note is added to the task's failures)
#   skipped = step skipped; for a task step the whole task is skipped (and its dependents)
#   stopped = the run is stopped
#   failed  = Alex has seen it; the step stays failed and the normal failure handling goes on
#   any action not listed here (a new gate kind's own action) = again, but nothing is added to failures
STEP_ANSWERS = {"approve": "passed", "back": "again", "skip": "skipped", "stop": "stopped",
                "acknowledged": "failed"}

# What an answer does to a gate a TASK holds (opened by the runner itself), by gate kind.
#   rerun = run exactly one more attempt (after committing any outside fix); failmodes.acknowledge
#           sets the task's `rerun` flag and starting that attempt clears it
TASK_ANSWERS = {
    "human-task": {"approve": "passed", "skip": "skipped", "stop": "stopped"},
    "escalation": {"acknowledged": "rerun", "skip": "skipped", "stop": "stopped"},
}


class RunFailed(Exception):
    """The run cannot go on; the message is the reason shown to Alex."""


@dataclass
class Outcome:
    """How one step call ended, as the walk sees it.

    status: passed | failed | skipped | waiting | stopped | dropped (Alex skipped the whole task)
    """
    status: str
    reasons: list = field(default_factory=list)


class Runner:
    """Drives runs. `adapters` is the (real or fake) adapter set; `lib_root` holds steps/ and friends."""

    def __init__(self, adapters, lib_root):
        """Remember the adapters and load the step library."""
        self.adapters = adapters
        self.lib: Library = load_library(Path(lib_root))
        self._ending = False

    # ------------------------------------------------------------------ the whole run
    def drive(self, run_dir) -> str:
        """Run (or continue) one run until it is done, failed, stopped or waiting; return its status.

        The run lock is held the whole time, so a stop from outside cannot change the run under the
        walk (it leaves a stop request instead). When someone else holds the lock, nothing is done."""
        run_dir = Path(run_dir)
        held = runend.lock(run_dir)
        try:
            held.__enter__()
        except TimeoutError:
            return state.load(run_dir)["status"]
        try:
            return self._drive(run_dir)
        finally:
            held.__exit__()

    def _drive(self, run_dir: Path) -> str:
        st = state.load(run_dir)
        if st["status"] in FINAL:
            return st["status"]
        asked = runend.stop_requested(run_dir)
        if asked is not None:
            return self._end(run_dir, "stopped", who=asked.get("who") or "cli")
        if st["status"] == "waiting":
            gate_id = (st.get("current") or {}).get("gate") or adopt_gate(run_dir)
            if gate_id and gates.current_answer(run_dir) is None:
                self.check_waiting(run_dir)
                return "waiting"
        state.set_status(run_dir, "running")
        project, run_id = st["project"], st["run_id"]
        try:
            setup = self._setup(run_dir, project, run_id)
        except Exception as err:  # bad settings or an impossible plan end the run, they do not crash it
            return self._finish(run_dir, project, run_id, "failed", scrub.scrub(str(err)))
        things = atomic.read_json(run_dir / "things.json", {})
        while True:
            try:
                outcome = self._walk(run_dir, setup, things)
            except RunFailed as err:
                self._skip_all(run_dir, state.load(run_dir))
                return self._finish(run_dir, project, run_id, "failed", scrub.scrub(str(err)))
            if outcome != "waiting" or gates.current_answer(run_dir) is None:
                break
            state.set_status(run_dir, "running")   # answered at once (e.g. by the project chat)
        if outcome == "waiting":
            self.check_waiting(run_dir)
            return "waiting"
        if outcome == "stopped":
            return self._stop(run_dir, setup, things)
        return self._finish(run_dir, project, run_id, "failed" if outcome == "failed" else "done")

    def stop_now(self, run_dir, who: str = "cli", wait: float = runend.LOCK_WAIT_S) -> dict:
        """Stop a run the runner is not walking, the same clean way as a `stop` answer, under the run lock.
        Raises TimeoutError when the lock is busy (the runner is walking it: leave a stop request)."""
        run_dir = Path(run_dir)
        with runend.lock(run_dir, wait=wait):
            st = state.load(run_dir)
            if st["status"] in FINAL:
                return {"status": st["status"], "notes": []}
            return self._end_run(run_dir, "stopped", who=who)

    def check_waiting(self, run_dir) -> None:
        """Called for a waiting run with no answer yet (here and by the service loop each round).
        A waiting run holding no gate (a crash right after a gate was opened) adopts it first."""
        if not (state.load(Path(run_dir)).get("current") or {}).get("gate"):
            adopt_gate(run_dir)
        failmodes.watch_delegate(self, Path(run_dir))

    def _end_run(self, run_dir: Path, status: str, reason: str = "", who: str = "phoenix",
                 setup: dict | None = None, things: dict | None = None) -> dict:
        """End the run through runend.end_run; a stop still runs the finish steps marked `after_stop`."""
        def after_stop():
            nonlocal setup, things
            if setup is None:
                if atomic.read_json(run_dir / "plan.json") is None:
                    return                     # never started: no finish steps to run
                st = state.load(run_dir)
                try:
                    setup = self._setup(run_dir, st["project"], st["run_id"])
                except Exception:              # noqa: BLE001 - a broken setup must not block the stop
                    return
            if things is None:
                things = atomic.read_json(run_dir / "things.json", {})
            self._ending = True
            try:
                for name in setup["plan"]["groups"]["run-finish"]:
                    if self._step_settings(setup, name).get("after_stop"):
                        self._do_step(run_dir, setup, things, "run-finish", name, None)
            finally:
                self._ending = False
        return runend.end_run(run_dir, status, reason=reason, who=who, adapters=self.adapters,
                              after_stop=after_stop, lib_root=self.lib.root)

    def _end(self, run_dir: Path, status: str, reason: str = "", who: str = "phoenix",
             setup: dict | None = None, things: dict | None = None) -> str:
        return self._end_run(run_dir, status, reason, who, setup, things)["status"]

    def _finish(self, run_dir: Path, project: str, run_id: str, status: str, reason: str = "") -> str:
        """End the run done or failed (runend.end_run never changes a run that already ended)."""
        return self._end(run_dir, status, reason)

    def _stop(self, run_dir: Path, setup: dict, things: dict, who: str = "phoenix") -> str:
        """Alex answered stop (or asked for a stop): unfinished tasks are skipped, only finish steps marked
        `after_stop = true` (Notify) still run, the branch is discarded, and the run ends `stopped`."""
        return self._end(run_dir, "stopped", who=who, setup=setup, things=things)

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
        if not profile_name and any(r.get("kind") == "ai" for r in plan.get("steps", [])):
            raise RunFailed(settings.no_profile_message(project))   # an AI step would launch docker with no image
        profile = settings.load_profile(self.lib.root, profile_name) if profile_name else {}
        info = ProjectInfo(name=project, dir=project_dir, code_dir=project_dir / "code",
                           settings=values, profile=profile)
        return {"settings": values, "plan": plan, "project": info}

    @staticmethod
    def _step_settings(setup: dict, name: str) -> dict:
        """The step's effective settings for this run (its [settings] keys, `on`, and ai keys)."""
        return setup["settings"].get("steps", {}).get(name, {})

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
        """Run-start steps, then every task, then run-finish steps. Returns ok | failed | waiting | stopped."""
        plan = setup["plan"]["groups"]
        for name in plan["run-start"]:
            out = self._do_step(run_dir, setup, things, "run-start", name, None)
            if out.status in ("waiting", "stopped"):
                return out.status
            if out.status == "failed":
                self._skip_all(run_dir, state.load(run_dir))
                return "failed"
        spec_data = self._spec_data(run_dir)
        if not spec_data.get("tasks"):
            raise RunFailed("No plan: the brief has no tasks and the plan was skipped")
        for task in spec_mod.order(spec_mod.from_json(spec_data)):
            self._hold_point(run_dir)
            outcome = self._run_task(run_dir, setup, things, spec_data, task)
            if outcome in ("waiting", "stopped"):
                return outcome
        failed = any(t["status"] == "failed" for t in state.load(run_dir)["tasks"].values())
        self._hold_point(run_dir)
        for name in plan["run-finish"]:
            out = self._do_step(run_dir, setup, things, "run-finish", name, None)
            if out.status in ("waiting", "stopped"):
                return out.status
            failed = failed or out.status == "failed"
        return "failed" if failed else "ok"

    def _hold_point(self, run_dir: Path) -> None:
        """A task boundary: while an update asks for a hold, mark the run held and wait here (blocks drive())."""
        if not hold.hold_requested():
            if (state.load(run_dir).get("current") or {}).get("held"):   # left over from a restart
                state.update(run_dir, lambda s: s.setdefault("current", {}).__setitem__("held", False))
            return
        st = state.update(run_dir, lambda s: s.setdefault("current", {}).__setitem__("held", True))
        events.emit("run.held", project=st["project"], run=st["run_id"],
                    why=(hold.hold_info() or {}).get("why", ""))
        while hold.hold_requested():
            self.adapters.clock.sleep(5)
        state.update(run_dir, lambda s: s.setdefault("current", {}).__setitem__("held", False))

    def _skip_all(self, run_dir: Path, st: dict) -> None:
        """After a failed start: mark every unfinished task skipped."""
        for n, t in st["tasks"].items():
            if t["status"] in ("pending", "running"):
                state.set_task(run_dir, int(n), status="skipped")

    # ------------------------------------------------------------------ tasks
    def _run_task(self, run_dir: Path, setup: dict, things: dict, spec_data: dict, task) -> str:
        """Bring one task as far as it can go. Returns passed | failed | skipped | waiting | stopped."""
        n = task.number
        st = state.load(run_dir)
        t = st["tasks"].get(str(n)) or state.set_task(run_dir, n)["tasks"][str(n)]
        if t["status"] in TASK_FINAL:
            return t["status"]
        blocked = [d for d in task.depends_on
                   if st["tasks"].get(str(d), {}).get("status") in ("failed", "skipped")]
        if blocked:
            what = "failed" if st["tasks"][str(blocked[0])]["status"] == "failed" else "was skipped"
            failmodes.skip_task(run_dir, n, f"depends on task {blocked[0]}, which {what}")
            return "skipped"
        if t["status"] == "pending":
            events.emit("task.started", project=st["project"], run=st["run_id"], task=n, title=task.title)
        if t.get("gate"):
            outcome = self._answer_task_gate(run_dir, n, t["gate"])
            if outcome != "rerun":
                return outcome
        elif task.for_you:
            return self._open_human_gate(run_dir, spec_data, n)
        return self._attempts(run_dir, setup, things, spec_data, n)

    def _open_human_gate(self, run_dir: Path, spec_data: dict, n: int) -> str:
        """A `For you: yes` task: no task steps; Alex does it and answers approve / skip / stop."""
        task = next(t for t in spec_data["tasks"] if t["number"] == n)
        done = "\n".join(f"- {c['text']}" for c in task.get("done_when", []))
        why = "\n".join(x for x in (f"Task {n}: {task['title']}", task.get("goal", ""),
                                    f"Done when:\n{done}" if done else "") if x)
        _open_gate(run_dir, ("task", n), kind="human-task", title=f"Task {n} is for you: {task['title']}",
                   why=why, task=n, actions=["approve", "skip", "stop"])
        return "waiting"

    def _answer_task_gate(self, run_dir: Path, n: int, gate_id: str) -> str:
        """The task waits on its own gate: act on the answer if there is one (TASK_ANSWERS).
        Returns waiting | passed | skipped | stopped | rerun."""
        answer = gates.poll(run_dir, gate_id)
        if answer is None:
            return "waiting"
        kind = (gates.read(run_dir, gate_id) or {}).get("kind", "")
        move = TASK_ANSWERS.get(kind, {}).get(answer["action"])
        who = answer.get("who", "cli")
        if move is None:
            raise ValueError(f"gate {gate_id} ({kind}) cannot take the answer {answer['action']!r}")
        if move == "rerun":
            failmodes.acknowledge(self, run_dir, n, answer)
            return "rerun"
        failmodes.stop_delegate(self, state.load(run_dir), n, answer)
        state.update(run_dir, lambda s: s["current"].__setitem__("gate", None))
        if move == "passed":
            failmodes._finish_task(run_dir, n, "passed", note=f"done by {who}")
        elif move == "skipped":
            failmodes.skip_task(run_dir, n, f"skipped by {who}")
        return move

    def _attempts(self, run_dir: Path, setup: dict, things: dict, spec_data: dict, n: int) -> str:
        """Run attempts until the task passes, waits, or failmodes says stop trying."""
        task_data = next(t for t in spec_data["tasks"] if t["number"] == n)
        max_tries = setup["settings"].get("max_tries", 1)
        while True:
            # Decide at the top, from files only, so a restart at any point makes the same choice.
            t = state.load(run_dir)["tasks"][str(n)]
            k = t.get("tries", 0)
            last = failmodes.attempt_result(run_dir, n, k) if k else None
            if last is not None and last["status"] == "passed":
                failmodes._finish_task(run_dir, n, "passed")
                return "passed"
            if last is not None and not t.get("rerun") and not failmodes.should_retry(run_dir, n, max_tries):
                return failmodes.after_last_try(self, run_dir, n, last.get("reasons") or [])
            if k == 0 or last is not None:
                k += 1                                # the last attempt is over: start the next one
                state.set_task(run_dir, n, tries=k, rerun=False, status="running")
            else:
                state.set_task(run_dir, n, status="running")   # attempt k was cut short: go on with it
            out = self._run_attempt(run_dir, setup, things, task_data, k)
            if out.status in ("waiting", "stopped"):
                return out.status
            if out.status == "dropped":
                failmodes.skip_task(run_dir, n, "skipped by an answer to a gate")
                return "skipped"
            # passed or failed: attempt k's result.json is written; the top of the loop decides.

    def _run_attempt(self, run_dir: Path, setup: dict, things: dict, task: dict, k: int) -> Outcome:
        """Attempt k: the task steps in plan order. `once` steps run until they have passed once;
        after them the worktree's commit is recorded as attempt_base. A failed step ends the
        attempt and the worktree goes back to attempt_base."""
        n = task["number"]
        names = setup["plan"]["groups"]["task"]
        once = {x for x in names if self._step_settings(setup, x).get("once")}
        worktree = self._worktree(run_dir)
        start_head = self.adapters.git.head(worktree) if worktree else None
        based = False
        for name in names:
            if name in once and self._passed_before(run_dir, n, name, k):
                continue
            if name not in once and not based:
                based = True
                if self._line_index(state.load(run_dir), "task", n, name, k) is None and worktree:
                    state.set_task(run_dir, n, attempt_base=self.adapters.git.head(worktree))
            out = self._do_step(run_dir, setup, things, "task", name, task, k)
            if out.status == "failed":
                self._end_attempt(run_dir, n, k, out.reasons, worktree, start_head)
                return out
            if out.status in ("waiting", "stopped", "dropped"):
                return out
        failmodes.write_attempt_result(run_dir, n, k, "passed", [])
        return Outcome("passed")

    def _end_attempt(self, run_dir: Path, n: int, k: int, reasons, worktree, start_head) -> None:
        """A failed attempt is thrown away: reset the worktree, then record that the attempt is over."""
        base = state.load(run_dir)["tasks"][str(n)].get("attempt_base") or start_head
        if worktree and base:
            self.adapters.git.reset_attempt(worktree, base)
        failmodes.write_attempt_result(run_dir, n, k, "failed", reasons)

    def _worktree(self, run_dir: Path) -> Path | None:
        st = state.load(run_dir)
        work = paths.work(st["project"], st["run_id"])
        return work if work.is_dir() else None

    @staticmethod
    def _line_index(st: dict, group: str, task: int | None, name: str, attempt: int | None) -> int | None:
        return next((i for i, x in enumerate(st["steps"])
                     if (x["group"], x["task"], x["step"], x.get("attempt")) == (group, task, name, attempt)), None)

    @staticmethod
    def _passed_before(run_dir: Path, n: int, name: str, k: int) -> bool:
        """True when a `once` step already passed for this task in an earlier attempt."""
        return any(x["task"] == n and x["step"] == name and x["status"] == "passed"
                   and (x.get("attempt") or 0) < k for x in state.load(run_dir)["steps"])

    # ------------------------------------------------------------------ one step
    def _do_step(self, run_dir: Path, setup: dict, things: dict, group: str, name: str,
                 task: dict | None, attempt: int | None = None) -> Outcome:
        """Run one step (or act on the answer to the gate it opened) with its state line and events."""
        st = state.load(run_dir)
        project, run_id = st["project"], st["run_id"]
        number = task["number"] if task else None
        index = self._line_index(st, group, number, name, attempt)
        line = st["steps"][index] if index is not None else None
        if line and line["status"] in ("passed", "skipped"):
            return Outcome(line["status"])
        if line and line["status"] == "waiting":
            out = self._handle_gate(run_dir, setup, things, index, line, number)
            if out is not None:
                return out
            line = state.load(run_dir)["steps"][index]
        if index is None:
            index = state.add_step_line(run_dir, group, number, name, "running", attempt=attempt)
        else:
            state.set_step_line(run_dir, index, status="running", finished=None, note="")
        state.update(run_dir, lambda s: s.__setitem__(
            "current", {"group": group, "task": number, "step": name, "attempt": attempt or 1, "gate": None}))
        events.emit("run.step.started", project=project, run=run_id, task=number, step=name, group=group)
        step = self.lib.step(name)
        ctx = self._context(run_dir, setup, things, step, task, attempt or 1, _ctx_answer(line))
        result = self._call_with_proxies(ctx, step)
        if result.status == "gate":
            return self._open_step_gate(run_dir, index, step, number, result)
        status = {"pass": "passed", "fail": "failed", "skip": "skipped"}[result.status]
        self._record(run_dir, things, index, number, name, status, result.reasons, result.produces)
        return Outcome(status, list(result.reasons))

    def _on_approved(self, run_dir: Path, setup: dict, things: dict, name: str, number, produces: dict) -> dict:
        """Call the step's optional on_approved(ctx, produces) hook; its returned dict goes on the finished event."""
        step = self.lib.step(name)
        try:
            code = load_code(self.lib, step)
            if code is None or not hasattr(code, "on_approved"):
                return {}
            task = state.load(run_dir)["tasks"].get(str(number)) if number is not None else None
            ctx = self._context(run_dir, setup, things, step, None if task is None else {"number": number, **task})
            return dict(code.on_approved(ctx, produces) or {})
        except Exception as err:     # a broken hook ends the run with a reason instead of crashing the runner
            first = (str(err).strip().splitlines() or [""])[0]
            raise RunFailed(f"{step.title} could not use the approved result: {type(err).__name__}: {first}")

    def _record(self, run_dir: Path, things: dict, index: int, number, name: str, status: str,
                reasons, produces, **extra) -> None:
        """Write a finished step: things it produced, its state line, failures and the event."""
        st = state.load(run_dir)
        if status == "failed" and number is not None:
            self._add_failures(run_dir, number, reasons)
        if produces:
            things.update(produces)
            atomic.write_json(run_dir / "things.json", things)
        state.set_step_line(run_dir, index, status=status, note=scrub.scrub("; ".join(reasons)))
        events.emit("run.step.finished", project=st["project"], run=st["run_id"], task=number, step=name,
                    status=status, reasons=[scrub.scrub(r) for r in reasons], **extra)

    def _add_failures(self, run_dir: Path, n: int, reasons: list[str]) -> None:
        """Remember why a task step failed (fed to later attempts and shown to Alex)."""
        def change(s):
            s["tasks"][str(n)]["failures"].extend(scrub.scrub(r) for r in reasons)
        state.update(run_dir, change)

    def _open_step_gate(self, run_dir: Path, index: int, step: Step, task: int | None,
                        result: StepResult) -> Outcome:
        """Open the gate the step asked for. The line keeps what the step said (produces, reasons)
        so the answer can be acted on after a restart."""
        spec = dict(result.gate or {})
        _open_gate(run_dir, ("line", index), extra={"produces": dict(result.produces),
                                                    "reasons": list(result.reasons)},
                   kind=spec.get("kind", "step"), title=spec.get("title", step.title),
                   why=spec.get("why", "; ".join(result.reasons) or f"{step.title} needs you."),
                   task=task, step=step.name, links=spec.get("links", ()), actions=spec.get("actions"),
                   flags=spec.get("flags", ()))
        return Outcome("waiting")

    def _handle_gate(self, run_dir: Path, setup: dict, things: dict, index: int, line: dict, number) -> Outcome | None:
        """The step's gate: no answer yet = still waiting; else act on it (STEP_ANSWERS).
        Returns None when the step must be called again: `back`, or an action the table does not
        know (a new gate kind's own action), which re-calls the step with ctx.answer and adds
        nothing to the failures."""
        answer = gates.poll(run_dir, line["gate"])
        if answer is None:
            return Outcome("waiting")
        move = STEP_ANSWERS.get(answer["action"], "again")
        who, note = answer.get("who", "cli"), (answer.get("note") or "").strip()
        state.update(run_dir, lambda s: s["current"].__setitem__("gate", None))
        if move == "again":
            if answer["action"] == "back" and number is not None and note:
                self._add_failures(run_dir, number, [f"Sent back by {who}: {note}"])

            def keep(s):
                ln = s["steps"][index]
                ln["answers"] = list(ln.get("answers") or [])
                if not ln["answers"] or ln["answers"][-1] != answer:    # a restart may get here twice
                    ln["answers"].append(answer)
            state.update(run_dir, keep)
            return None
        name = line["step"]
        if move == "passed":
            produces = line.get("produces") or {}
            extra = self._on_approved(run_dir, setup, things, name, number, produces)
            things.update(atomic.read_json(run_dir / "things.json", {}))   # a hook (Merge) may have recorded a thing
            self._record(run_dir, things, index, number, name, "passed", [], produces, **extra)
            state.set_step_line(run_dir, index, note=f"approved by {who}")
            return Outcome("passed")
        if move == "failed":
            reasons = line.get("reasons") or [(gates.read(run_dir, line["gate"]) or {}).get("why", "")]
            self._record(run_dir, things, index, number, name, "failed", reasons, {})
            return Outcome("failed", list(reasons))
        self._record(run_dir, things, index, number, name, "skipped", [f"{move} by {who}"], {})
        if move == "stopped":
            return Outcome("stopped")
        return Outcome("dropped" if number is not None else "skipped")

    def _call_with_proxies(self, ctx: StepContext, step: Step) -> StepResult:
        """Run the step with the key proxies its step.toml asks for; they are always stopped afterwards."""
        if not step.proxy:
            return self._call(ctx, step)
        bind = self.adapters.docker.bridge_gateway() if step.kind == "ai" else stepproxy.HOST_BIND
        try:
            with stepproxy.step_proxies(ctx, step, bind):
                return self._call(ctx, step)
        except OpsError as err:
            return StepResult("fail", [str(err)])

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
            first = (str(err).strip().splitlines() or [""])[0]
            return StepResult("fail", [f"step {step.name} crashed: {type(err).__name__}: {first}"])

    # ------------------------------------------------------------------ context and things
    def _context(self, run_dir: Path, setup: dict, things: dict, step: Step, task: dict | None,
                 attempt: int = 1, answer: dict | None = None) -> StepContext:
        """Build the StepContext: provided things, produced things and fallbacks for every need."""
        st = state.load(run_dir)
        project, run_id = st["project"], st["run_id"]
        info: ProjectInfo = setup["project"]
        scrub.add_secrets(keys_mod.secret_values(project))    # project keys never reach a log
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

        ctx = StepContext(
            project=info, run=RunInfo(id=run_id, folder=run_dir, spec=spec_data),
            step=StepInfo(name=step.name, kind=step.kind, folder=step.folder, settings=own, ai=ai,
                          produces=step.produces),
            task=task, attempt=attempt, worktree=worktree, things=visible, adapters=self.adapters,
            emit=emit, log=log, answer=answer)
        for need, source in setup["plan"]["sources"].get(step.name, {}).items():
            if source.startswith("fallback:") and need in reports.FALLBACK_VALUES:
                ctx.things[need] = reports.FALLBACK_VALUES[need](ctx)    # fallback-value hook
        return ctx


# ---------------------------------------------------------------------- gates held by the run
def _open_gate(run_dir, holder: tuple, *, extra: dict | None = None, **fields) -> dict:
    """Open a gate (gates.open_gate takes `fields`) and, in ONE state update, record who holds it:
    holder ("task", n) sets the task's `gate`; ("line", index) sets that step line's `gate` and
    status waiting. `extra` fields go onto the holder too. current.gate is set either way."""
    gate = gates.open_gate(run_dir, **fields)

    def change(s):
        if holder[0] == "task":
            s["tasks"][str(holder[1])].update(gate=gate["id"], **(extra or {}))
            s["current"]["task"] = holder[1]
        else:
            s["steps"][holder[1]].update(status="waiting", gate=gate["id"],
                                         note=f"waiting for gate {gate['id']}", **(extra or {}))
        s["current"]["gate"] = gate["id"]
    state.update(Path(run_dir), change)
    return gate


def adopt_gate(run_dir) -> str | None:
    """A waiting run whose current.gate is empty (a crash right after the gate file was written):
    take the newest unanswered gate in gates/ and hold it again, by its task or (when the gate names
    a step) by that step's latest line. Returns the gate id, or None when there is none."""
    run_dir = Path(run_dir)
    found = []
    for f in (run_dir / "gates").glob("*.json"):
        if f.name.endswith(".answer.json") or gates.poll(run_dir, f.stem) is not None:
            continue
        g = atomic.read_json(f)
        if g:
            found.append((int(g["id"].rsplit(".", 1)[1]), g))
    if not found:
        return None
    gate = max(found, key=lambda x: x[0])[1]

    def change(s):
        if gate.get("step"):
            index = max((i for i, x in enumerate(s["steps"])
                         if x["step"] == gate["step"] and x["task"] == gate.get("task")), default=None)
            if index is not None:
                s["steps"][index].update(status="waiting", gate=gate["id"],
                                         note=f"waiting for gate {gate['id']}")
        elif gate.get("task") is not None and str(gate["task"]) in s["tasks"]:
            s["tasks"][str(gate["task"])].update(gate=gate["id"], status="waiting")
            s["current"]["task"] = gate["task"]
        s["current"]["gate"] = gate["id"]
    state.update(run_dir, change)
    return gate["id"]


def _ctx_answer(line: dict | None) -> dict | None:
    """ctx.answer for a re-called step: the latest answer, plus "notes" = every back note in order."""
    answers = (line or {}).get("answers") or []
    if not answers:
        return None
    notes = [a.get("note", "") for a in answers if a.get("action") == "back"]
    return {**answers[-1], "notes": notes}


# ---------------------------------------------------------------------- AI steps
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
    values.update({"task": task_text(ctx.task), "checks": checks_text(ctx),
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
                                            project_domains(ctx))
    mount_dir = ctx.run.folder / "spec-mount"
    mount_dir.mkdir(exist_ok=True)
    if not (mount_dir / "spec.md").exists():
        atomic.write_text(mount_dir / "spec.md", (ctx.run.folder / "spec.md").read_text(encoding="utf-8"), mode=0o444)
    extra = code.mounts(ctx) if code is not None and hasattr(code, "mounts") else {}
    extra_mounts = list(extra.get("extra_mounts") or [])
    allow_file = stepproxy.write_allow_file(ctx, ctx.proxies)
    if allow_file:
        extra_mounts.append(docker_mod.Mount(allow_file, docker_mod.ALLOWED_PROXY_MOUNT))
    docker_mod.hand_writable_mounts(ctx.adapters.docker, extra_mounts)  # e.g. the planner's /out
    with keys_mod.env_file(ctx.project.name) as key_file:
        session = ctx.adapters.claude.launch(
            ctx.adapters.docker, ai=ctx.step.ai, project=ctx.project.name, run_id=ctx.run.id, task=number,
            attempt=ctx.attempt, role=ctx.step.name, image=profile.get("image", ""), workspace=ctx.worktree,
            prompt_file=out_prompt, step_dir=folder, project_dir=ctx.project.dir, spec_dir=mount_dir,
            domains_file=domains, workspace_ro=bool(extra.get("workspace_ro")),
            extra_mounts=extra_mounts, env_files=[key_file] if key_file else [],
            extra_env=stepproxy.container_env(ctx.proxies))
    claude_mod.record_usage(ctx.run.folder, session, attempt_dir)
    ctx.log(f"session ended: {session.kind}")
    if session.kind == "rate_limited":
        raise UsageLimit(session)
    if code is not None and hasattr(code, "after"):
        return code.after(ctx, session)
    if session.kind == "ok":
        return StepResult("pass")
    return StepResult("fail", [f"The AI session ended without finishing ({session.kind})."])
