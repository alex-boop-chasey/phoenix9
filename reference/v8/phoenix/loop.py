"""The loop that takes a run through its plan, one step at a time.

For each step: skip it when it is the owner's job (`For you: yes`) or when a
step it depends on did not pass. Otherwise get its checks written and locked
and run them once on the branch head (the red check). Then up to `max_tries`
times: a fresh workspace, one builder session in a firewalled container,
bring the files back (snapshot, with the lock check and the secret scan),
commit them as a candidate, and run the checks on that commit. A pass keeps
the commit; a fail throws it away and the next try gets the feedback.

run.json is rewritten after every change. After a crash or restart the loop
picks up where it was: the steps that passed are read back from the git
trailers in Phoenix's own clone (git wins over run.json), the step that was
in progress starts again from scratch, and leftover workspaces and
containers are removed.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from phoenix import checks, claude, config, docker, runs, verify
from phoenix import git as pgit
from phoenix import plan as pplan
from phoenix.log import log
from phoenix.state import atomic_write

BUILDER_ROLE = "builder"
BUILDER_MAX_TURNS = 200
PROBE_ROLE = "probe"
PROBE_TIMEOUT_MIN = 5
PROMPT_TEMPLATE = Path(__file__).resolve().parent.parent / "prompts" / "builder.md"
GIT_LOG_LINES = 200
EARLY_END = ("crashed", "timed_out", "no_output")       # session kinds that count as a failed try at once
FINAL_STATUSES = ("passed", "failed", "blocked", "for_you")
USER_PROMPT = ("Build Step {n}: {title}, following the instructions you were given. "
               "Before you finish, run the check command yourself. "
               "End with `STEP DONE` or `STEP BLOCKED: <reason>` on the last line.\n")


class Paused(Exception):
    """Claude's usage limit did not lift within the allowed wait; the run is paused."""


@dataclass
class Tools:
    """The outside pieces the loop uses. Tests swap them for fakes."""

    write_checks: Callable = checks.write_checks
    lock: Callable = checks.lock
    red_check: Callable = checks.red_check
    builder: Callable = docker.run_claude_container
    verify: Callable = verify.verify_step
    wait_for_limit: Callable = claude.wait_for_limit
    probe: Callable | None = None                      # None = a tiny real Claude session (probe_session)
    now: Callable = field(default=lambda: datetime.now(timezone.utc))
    sleep: Callable = time.sleep
    cleanup_orphans: Callable = docker.cleanup_orphans


# ------------------------------------------------------------- run.json helpers
def step_entry(record: dict, number: int) -> dict:
    """Return one step's entry in a run.json record (an empty dict when it has none yet)."""
    return next((e for e in record.get("steps", []) if isinstance(e, dict) and e.get("number") == number), {})


def note_step(run_id: str, number: int, **fields) -> None:
    """Set fields on one step's entry in run.json and save it (atomic write)."""
    checks.note_step(run_id, number, **fields)


def note_run(run_id: str, **fields) -> dict:
    """Set top-level fields in run.json and save it (atomic write). Returns the record."""
    record = runs.load_run(run_id)
    record.update(fields)
    runs.save_run(record)
    return record


def step_status(run_id: str, number: int) -> str:
    """Return a step's status as run.json has it now."""
    return step_entry(runs.load_run(run_id), number).get("status", "pending")


# ------------------------------------------------------------- the builder's prompt
def git_log(repo: str, base_sha: str) -> str:
    """Return `git log --oneline base..HEAD` of Phoenix's clone (newest first, capped)."""
    if not base_sha:
        return "(no commits yet)"
    lines = pgit.git(pgit.clone_dir(repo), "log", "--oneline", f"{base_sha}..HEAD").splitlines()
    if len(lines) > GIT_LOG_LINES:
        lines = lines[:GIT_LOG_LINES] + [f"... and {len(lines) - GIT_LOG_LINES} older commits"]
    return "\n".join(lines) or "(no commits yet)"


def render_prompt(plan: pplan.Plan, step: pplan.Step, check_cmd: str, log_text: str,
                  feedback: str, try_no: int, max_tries: int) -> str:
    """Fill in prompts/builder.md for one try of one step."""
    bullets = "\n".join(f"{i}. {b}" for i, b in enumerate(step.done_when, 1))
    if feedback:
        fb = f"This is try {try_no} of {max_tries}. The previous try failed. Phoenix said:\n\n```\n{feedback}\n```"
    else:
        fb = f"None: this is try {try_no} of {max_tries}."
    values = {
        "about": plan.about.strip() or "(none)",
        "every_step": plan.every_step.strip() or "(none)",
        "step_number": str(step.number),
        "step_title": step.title,
        "step_description": step.description.strip() or "(no description)",
        "done_when": bullets or "(none)",
        "step_folder": checks.step_folder(step.number),
        "check_command": check_cmd,
        "git_log": log_text,
        "feedback": fb,
    }
    text = PROMPT_TEMPLATE.read_text()
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def last_line(text: str) -> str:
    """Return the builder's last non-empty line (only logged: what the builder says never counts)."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return lines[-1][:300] if lines else ""


# ------------------------------------------------------------- usage limits
def probe_session(run_id: str, settings: dict) -> claude.Result:
    """Run a tiny Claude session to see whether the usage limit has lifted."""
    folder = pgit.work_root() / f"{run_id}-{PROBE_ROLE}"
    pgit.rmtree(folder)
    folder.mkdir(parents=True)
    prompt = runs.run_dir(run_id) / "prompts" / f"{PROBE_ROLE}.md"
    atomic_write(prompt, "Reply with the single word OK.\n")
    try:
        result = docker.run_claude_container(run_id, PROBE_ROLE, 0, PROBE_ROLE, folder, prompt, [], None,
                                             PROBE_TIMEOUT_MIN, max_turns=1, settings=settings)
        claude.record_usage(run_id, result, role=PROBE_ROLE)
        return result
    finally:
        pgit.remove_workspace(folder)


def wait_out_limit(run_id: str, result: claude.Result, tools: Tools, s: dict) -> None:
    """Wait for Claude's usage limit to lift (Step 3's wait_for_limit). Raise Paused when it does not."""
    log(run_id, f"usage limit reached; waiting (resets at {result.resets_at or 'unknown'})")
    probe = tools.probe or (lambda: probe_session(run_id, s))
    if not tools.wait_for_limit(result, probe, tools.now, tools.sleep,
                                probe_min=s["usage_probe_min"], max_wait_h=s["usage_max_wait_h"]):
        raise Paused(f"the usage limit did not lift within {s['usage_max_wait_h']} hours")
    log(run_id, "usage limit lifted; repeating the same try")


# ------------------------------------------------------------- checks (once per step)
def prepare_checks(run: dict, step: pplan.Step, tools: Tools, s: dict) -> bool:
    """Write and lock the step's checks, then run the red check. False = the step has no checks.

    Done once per step. After a restart, checks already committed for the
    step are kept (locked if the lock commit was not made yet) and the red
    check is not repeated when run.json already has its result.
    """
    run_id, repo, n = run["run_id"], run["repo"], step.number
    clone = pgit.clone_dir(repo)
    files = checks.step_check_files(clone, n)
    if not files:
        paths = tools.write_checks(run, step, settings=s)
        tools.lock(repo, n, [str(p) for p in paths])
    elif any(f not in checks.read_manifest(clone) for f in files):
        tools.lock(repo, n, files)
    if step_entry(runs.load_run(run_id), n).get("red_check"):
        return True
    return tools.red_check(run, step, settings=s)


# ------------------------------------------------------------- one try
def builder_mounts(run_id: str, n: int, try_no: int) -> list[docker.Mount]:
    """The test configs and a scratch report folder, so the builder can run the exact check command."""
    out_dir = config.paths().runs / run_id / "3-product" / "reports" / f"{n}-{try_no}-{BUILDER_ROLE}"
    pgit.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    docker.hand_to_agent(out_dir)
    return checks.check_mounts(out_dir)


def one_try(run: dict, plan: pplan.Plan, step: pplan.Step, try_no: int, feedback: str,
            tools: Tools, s: dict) -> tuple[str, object]:
    """Run one builder try. Returns ("rate_limited", Result), ("failed", feedback) or ("passed", sha).

    A failed try leaves Phoenix's clone exactly where it was before the try.
    """
    run_id, repo, n = run["run_id"], run["repo"], step.number
    clone = pgit.clone_dir(repo)
    env_file = checks.project_env_file(repo)
    has_spec = any(f.endswith(".spec.ts") for f in checks.step_check_files(clone, n))
    prompts = runs.run_dir(run_id) / "prompts"
    system_file = prompts / f"{n}-{try_no}-{BUILDER_ROLE}-system.md"
    user_file = prompts / f"{n}-{try_no}-{BUILDER_ROLE}.md"
    atomic_write(system_file, render_prompt(plan, step, checks.check_command(n, has_spec),
                                            git_log(repo, run.get("base_sha", "")), feedback,
                                            try_no, s["max_tries"]))
    atomic_write(user_file, USER_PROMPT.format(n=n, title=step.title))
    before = pgit.head(clone)
    workspace = pgit.fresh_workspace(repo, run_id, n, try_no)
    try:
        result = tools.builder(run_id, n, try_no, BUILDER_ROLE, workspace, user_file,
                               [env_file] if env_file else [], checks.domains_file(repo),
                               s["builder_timeout_min"], no_output_timeout_min=s["no_output_timeout_min"],
                               max_turns=BUILDER_MAX_TURNS, system_prompt_file=system_file,
                               mounts=builder_mounts(run_id, n, try_no), settings=s)
        claude.record_usage(run_id, result, role=BUILDER_ROLE, step=n, try_no=try_no)
        log(run_id, f"step {n}: builder try {try_no} ended '{result.kind}': {last_line(result.text)}")
        if result.kind == "rate_limited":
            return "rate_limited", result
        if result.kind in EARLY_END:
            return "failed", (f"The builder session ended before it finished ({result.kind}). "
                              f"End of its output:\n{result.text[-1000:]}")
        try:
            pgit.snapshot(workspace, repo, locked=(checks.CHECKS_ROOT + "/",), env_file=env_file)
        except pgit.Rejected as e:
            pgit.clean(clone)
            log(run_id, f"step {n}: Phoenix refused the changes of try {try_no}: {e.reasons[0] if e.reasons else ''}")
            return "failed", "Phoenix refused all of the changes:\n" + "\n".join(f"- {r}" for r in e.reasons)
    finally:
        pgit.remove_workspace(workspace)
    sha = pgit.commit_step(repo, run_id, n, f"Step {n}: {step.title}")
    note_step(run_id, n, candidate=sha, head_before=before)
    verdict = tools.verify(run, step, sha, try_no=try_no, settings=s)
    if verdict.ok:
        return "passed", sha
    pgit.git(clone, "reset", "-q", "--hard", before)
    log_path = config.paths().runs / run_id / "logs" / f"{n}-{try_no}-{verify.ROLE}.txt"
    return "failed", verify.feedback(verdict, log_path, env_file)


# ------------------------------------------------------------- one step
def fail_step(run_id: str, plan: pplan.Plan, step: pplan.Step, reason: str) -> None:
    """Mark a step failed with its reason, and every step that depends on it blocked."""
    note_step(run_id, step.number, status="failed", reason=reason, candidate=None, head_before=None)
    log(run_id, f"step {step.number}: failed: {reason}")
    for dep in pplan.dependents_of(plan, step.number):
        if step_status(run_id, dep.number) not in ("passed", "for_you"):
            note_step(run_id, dep.number, status="blocked", reason=f"step {step.number} failed")
            log(run_id, f"step {dep.number}: blocked (step {step.number} failed)")


def run_step(run: dict, step: pplan.Step, *, plan: pplan.Plan | None = None, tools: Tools | None = None,
             settings: dict | None = None) -> str:
    """Take one step from start to `passed`, `failed`, `blocked` or `for_you`. Returns the status.

    Raises Paused when Claude's usage limit does not lift in time.
    """
    tools = tools or Tools()
    s = settings or config.load()
    plan = plan or checks.load_plan(run)
    run_id, n = run["run_id"], step.number
    if step.for_you:
        note_step(run_id, n, status="for_you", reason="For you: the owner does this step by hand")
        log(run_id, f"step {n}: for you (skipped)")
        return "for_you"
    waiting = [d for d in step.depends_on if step_status(run_id, d) != "passed"]
    if waiting:
        reason = "depends on step " + ", ".join(map(str, waiting)) + ", which did not pass"
        note_step(run_id, n, status="blocked", reason=reason)
        log(run_id, f"step {n}: blocked ({reason})")
        return "blocked"
    note_step(run_id, n, status="running", tries=0, reason="")
    try:
        ready = prepare_checks(run, step, tools, s)
    except (checks.CannotCheck, checks.CheckWriterFailed, checks.LockBroken, pgit.GitError, ValueError) as e:
        fail_step(run_id, plan, step, f"checks: {e}")
        return "failed"
    if not ready:
        fail_step(run_id, plan, step, "the step has no checks")
        return "failed"
    feedback, try_no = "", 1
    while try_no <= s["max_tries"]:
        note_step(run_id, n, tries=try_no)
        outcome, detail = one_try(run, plan, step, try_no, feedback, tools, s)
        if outcome == "rate_limited":
            wait_out_limit(run_id, detail, tools, s)
            continue                                       # the same try again; the wait is not a try
        if outcome == "passed":
            note_step(run_id, n, status="passed", commit=detail, reason="", candidate=None, head_before=None)
            log(run_id, f"step {n}: passed on try {try_no} ({detail[:12]})")
            return "passed"
        feedback = detail
        atomic_write(runs.run_dir(run_id) / "prompts" / f"{n}-{try_no}-feedback.md", feedback + "\n")
        note_step(run_id, n, reason=feedback.splitlines()[0][:300], candidate=None, head_before=None)
        try_no += 1
    fail_step(run_id, plan, step, step_entry(runs.load_run(run_id), n).get("reason") or "failed")
    return "failed"


# ------------------------------------------------------------- the whole plan
def reset_candidate(repo: str, number: int, base_sha: str) -> None:
    """Throw away any commit of step `number` at the top of the branch (a candidate that was never judged)."""
    clone = pgit.clone_dir(repo)
    fmt = f"%(trailers:key={pgit.TRAILER_STEP},valueonly)"
    while pgit.head(clone) != base_sha:
        trailer = pgit.git(clone, "log", "-1", f"--format={fmt}", "HEAD").strip()
        if trailer != str(number):
            return
        pgit.git(clone, "reset", "-q", "--hard", "HEAD~1")


def remove_leftovers(run_id: str, tools: Tools) -> None:
    """Remove the run's leftover workspaces (cache/work/<run>-*) and containers."""
    root = pgit.work_root()
    if root.is_dir():
        for p in root.iterdir():
            if p.name.startswith(f"{run_id}-"):
                pgit.remove_workspace(p)
    n = tools.cleanup_orphans(run_id)
    if n:
        log(run_id, f"removed {n} leftover container(s)")


def sync_steps(run_id: str, plan: pplan.Plan, passed: set[int], current: int | None) -> None:
    """Make run.json's steps match the plan and git: one entry per step, git's passes win.

    The step that was in progress (`current`) is set back to not started.
    """
    record = runs.load_run(run_id)
    old = {e.get("number"): e for e in record.get("steps", []) if isinstance(e, dict)}
    entries = []
    for step in pplan.plan_order(plan):
        e = old.get(step.number, {})
        e.update(number=step.number, title=step.title)
        e.setdefault("status", "pending")
        e.setdefault("tries", 0)
        e.setdefault("reason", "")
        if step.number in passed:
            e.update(status="passed", reason="")
        elif e["status"] == "passed" or step.number == current:
            e.update(status="pending", tries=0, reason="", commit=None)
        e.update(candidate=None, head_before=None)
        entries.append(e)
    record["steps"] = entries
    runs.save_run(record)


def start(run_id: str, plan: pplan.Plan, tools: Tools) -> dict:
    """Get the run branch ready (new run or restart) and bring run.json in line with git."""
    record = runs.load_run(run_id)
    resuming = record.get("status") in ("running", "paused")
    if resuming:
        log(run_id, f"resuming run (was {record['status']}, step {record.get('current_step')})")
        remove_leftovers(run_id, tools)
    repo = record["repo"]
    docker.write_domains_file(plan)
    base = pgit.start_branch(repo, run_id)
    if not record.get("base_sha"):
        record = note_run(run_id, base_sha=base, branch=pgit.branch_name(run_id))
    pgit.commit_plan(repo, run_id, Path(record["plan_path"]))
    current = record.get("current_step") if resuming else None
    if current is not None:
        reset_candidate(repo, int(current), record["base_sha"])
    passed = set(pgit.passed_steps(repo, record["base_sha"]))
    sync_steps(run_id, plan, passed, current)
    return note_run(run_id, status="running")


def run_plan(run_id: str, *, tools: Tools | None = None, settings: dict | None = None) -> str:
    """Take a run through every step of its plan, in order. Returns the run's final status.

    `done` when no step failed or was blocked, `failed` otherwise, `paused`
    when Claude's usage limit did not lift in time (run it again later).
    Anything unexpected is raised and run.json stays `running`, so the next
    start resumes.
    """
    tools = tools or Tools()
    s = settings or config.load()
    record = runs.load_run(run_id)
    if record.get("status") in ("done", "failed"):
        return record["status"]
    plan = checks.load_plan(record)
    problems = pplan.check(plan)
    if problems:
        log(run_id, "the plan has problems: " + "; ".join(problems))
        note_run(run_id, status="failed")
        return "failed"
    record = start(run_id, plan, tools)
    for step in pplan.plan_order(plan):
        if step_status(run_id, step.number) in FINAL_STATUSES:
            continue
        record = note_run(run_id, current_step=step.number)
        try:
            run_step(record, step, plan=plan, tools=tools, settings=s)
        except Paused as e:
            log(run_id, f"run paused: {e}")
            note_run(run_id, status="paused")
            return "paused"
    statuses = [step_status(run_id, st.number) for st in plan.steps]
    final = "failed" if any(x in ("failed", "blocked") for x in statuses) else "done"
    note_run(run_id, status=final, current_step=None)
    log(run_id, f"run {final}")
    return final


def status_lines(run_id: str) -> list[str]:
    """Return one line per step: number, title, status, tries, reason."""
    lines = []
    for e in runs.load_run(run_id).get("steps", []):
        if not isinstance(e, dict):
            continue
        reason = (e.get("reason") or "").replace("\n", " ")
        lines.append(f"{e.get('number', '?'):>2}  {e.get('title', '')}  {e.get('status', 'pending')}  "
                     f"tries {e.get('tries', 0)}  {reason}".rstrip())
    return lines
