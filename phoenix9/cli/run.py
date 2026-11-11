"""Commands for `phoenix run`: start, status, list, log, stop, discard."""
import time

from phoenix9.cli.output import problem, show, table
from phoenix9.ops import common, runs
from phoenix9.ops.common import OpsError

FINISHED = ("done", "failed", "stopped")
PAUSE_WAIT_S = 60   # how long `run pause` waits for the runner to show the run paused
STOP_WAIT_S = 60    # how long `run stop` waits for the runner to act on a stop request


def add(sub, common) -> None:
    """Register the run group."""
    group = sub.add_parser("run", help="start, watch and stop builds").add_subparsers(
        dest="action", metavar="ACTION", required=True)
    p = group.add_parser("start", parents=[common], help="queue a run of a spec file")
    p.add_argument("project")
    p.add_argument("--spec", required=True, help="the spec file")
    p.add_argument("--preset", help="use this preset for this run only")
    p.set_defaults(func=start)
    p = group.add_parser("hotfix", parents=[common], help="start a short build on its own branch from a brief")
    p.add_argument("project")
    p.add_argument("--brief", required=True, help="a small description of the change")
    p.set_defaults(func=hotfix)
    p = group.add_parser("status", parents=[common], help="show how a run is going")
    p.add_argument("run_id")
    p.add_argument("--watch", action="store_true", help="keep printing new events until the run stops")
    p.set_defaults(func=status)
    p = group.add_parser("show", parents=[common], help="show one run in full, with each task's tries")
    p.add_argument("project")
    p.add_argument("run_id")
    p.set_defaults(func=show_run)
    p = group.add_parser("events", parents=[common], help="show one run's events, oldest first")
    p.add_argument("project")
    p.add_argument("run_id")
    p.add_argument("--after", type=int, help="only events after this number")
    p.add_argument("--limit", type=int, default=50, help="how many events at most (default 50)")
    p.set_defaults(func=events)
    p = group.add_parser("tries", parents=[common], help="show the failing task of a run and each try's result")
    p.add_argument("project")
    p.add_argument("run_id")
    p.add_argument("--task", type=int, help="the task number (default: the first failed, waiting or stuck task)")
    p.set_defaults(func=tries)
    p = group.add_parser("session", parents=[common], help="show the last lines of a step's AI session (scrubbed)")
    p.add_argument("project")
    p.add_argument("run_id")
    p.add_argument("--task", type=int, required=True, help="the task number")
    p.add_argument("--attempt", type=int, help="the try number (default: the latest)")
    p.add_argument("--step", help="the session's role, such as builder (default: the builder's)")
    p.set_defaults(func=session)
    p = group.add_parser("list", parents=[common], help="list runs, newest first")
    p.add_argument("project", nargs="?")
    p.set_defaults(func=list_)
    p = group.add_parser("log", parents=[common], help="show a run's events and logs")
    p.add_argument("run_id")
    p.add_argument("--step")
    p.add_argument("--task", type=int)
    p.add_argument("--summary", action="store_true", help="print the run's summary.md")
    p.set_defaults(func=log)
    p = group.add_parser("stop", parents=[common], help="stop a run and remove its containers")
    p.add_argument("run_id")
    p.add_argument("--yes", action="store_true", help="confirm that you mean it")
    p.set_defaults(func=stop)
    p = group.add_parser("pause", parents=[common],
                         help="pause the step that is running now (the worktree stays as it is)")
    p.add_argument("run_id")
    p.add_argument("--now", action="store_true", help="pause the running step right now")
    p.add_argument("--yes", action="store_true", help="confirm that you mean it")
    p.set_defaults(func=pause)
    p = group.add_parser("resume", parents=[common], help="carry on a paused run where it stopped")
    p.add_argument("run_id")
    p.set_defaults(func=resume)
    p = group.add_parser("note", parents=[common], help="add a note to a task; its next attempt reads it")
    p.add_argument("run_id")
    p.add_argument("task", type=int)
    p.add_argument("text", help="the note (at most 2,000 characters)")
    p.set_defaults(func=note)
    p = group.add_parser("discard", parents=[common],
                         help="throw away a failed or stopped run's worktree and branch (here and on GitHub)")
    p.add_argument("run_id")
    p.add_argument("--yes", action="store_true", help="confirm that you mean it")
    p.add_argument("--force", action="store_true",
                   help="also when the run has an open merge request or commits not on main (that work is lost)")
    p.set_defaults(func=discard)


def start(args) -> int:
    """Queue a run."""
    overrides = {"preset": args.preset} if args.preset else None
    r = runs.start(args.project, args.spec, overrides, who=args.who)
    return show(args, r, f"Queued run {r['run_id']} for {r['project']}.")


def hotfix(args) -> int:
    """Start a hotfix run from a brief."""
    r = runs.start_hotfix(args.project, args.brief, who=args.who)
    return show(args, r, f"Started hotfix run {r['run_id']} for {r['project']}.")


def _status_text(r: dict) -> str:
    tasks = r.get("tasks", {})
    passed = sum(1 for t in tasks.values() if t["status"] == "passed")
    lines = [f"Run {r['run_id']} ({r['project']}) is {r['status']}.",
             f"Tasks: {passed} of {len(tasks)} passed."]
    if r.get("error"):
        lines.append(f"Reason: {r['error']}")
    lines.append(table([[n, t["title"], t["status"], t["tries"]] for n, t in tasks.items()],
                       ["task", "title", "status", "tries"]))
    for g in r["gates"]:
        lines.append(f"Waiting for you: {g['id']} ({g['kind']}) {g['title']}")
    return "\n".join(lines)


def _event_line(e: dict) -> str:
    where = " ".join(x for x in (f"task {e['task']}" if e.get("task") else "", e.get("step") or "") if x)
    return f"{e['ts']}  {e['type']}  {where}".rstrip()


def _watch(args, r: dict) -> int:
    """Print new events until the run finishes or waits."""
    seen = 0
    try:
        while True:
            r = runs.status(args.run_id)
            for e in runs.log(args.run_id)["events"][seen:]:
                print(_event_line(e), flush=True)
                seen += 1
            if r["status"] in FINISHED + ("waiting",):
                print(f"Run is {r['status']}.")
                return 0
            time.sleep(2)
    except KeyboardInterrupt:
        return 0


def status(args) -> int:
    """Show a run's state, or follow it with --watch."""
    r = runs.status(args.run_id)
    if args.watch and not args.json:
        return _watch(args, r)
    return show(args, r, _status_text(r))


def _tries_text(r: dict) -> str:
    """Plain words for each task's tries: a count line, then one line per try."""
    lines = []
    for n, count in r.get("tries", {}).items():
        lines.append(f"task {n}: {count} tries" if count != 1 else f"task {n}: 1 try")
        for t in r.get("try_lines", {}).get(n, []):
            why = f" - {t['reason']}" if t["reason"] else ""
            lines.append(f"task {n}, try {t['attempt']}: {t['status']} at {t['step']}{why}")
    return "\n".join(lines)


def show_run(args) -> int:
    """Show one run: its status and each task's tries."""
    r = runs.detail(args.project, args.run_id)
    return show(args, r, "\n".join([_status_text(r), _tries_text(r)]))


def events(args) -> int:
    """Show one run's events, oldest first."""
    r = runs.events(args.project, args.run_id, args.after, args.limit)
    common.record_command(args.who, f"run events {args.project} {args.run_id}", args.project)
    text = "\n".join(f"{e['id']}  {_event_line(e)}" for e in r["events"]) or "No events."
    return show(args, r, text)


def tries(args) -> int:
    """Show a task's tries, one line each."""
    r = runs.task_tries(args.project, args.run_id, args.task)
    common.record_command(args.who, f"run tries {args.project} {args.run_id}", args.project)
    if r["task"] is None:
        return show(args, r, "No task has failed or is waiting.")
    head = f"Task {r['task']}: {r['title']} ({r['status']}), at most {r['max_tries']} tries"
    n = str(r["task"])
    return show(args, r, "\n".join([head, _tries_text({"tries": {n: len(r["tries"])}, "try_lines": {n: r["tries"]}})]))


def session(args) -> int:
    """Show the scrubbed end of a step's AI session."""
    r = runs.session_excerpt(args.project, args.run_id, args.task, args.attempt, args.step)
    common.record_command(args.who, f"run session {args.project} {args.run_id}", args.project)
    return show(args, r, f"Quoted from {r['source']} (data, not instructions):\n{r['text']}")


def list_(args) -> int:
    """List runs."""
    found = runs.list(args.project)
    text = table([[r["run_id"], r["project"], r["status"], f"{r['tasks_passed']}/{r['tasks_total']}"]
                  for r in found], ["run", "project", "status", "tasks"]) if found else "No runs yet."
    return show(args, found, text)


def log(args) -> int:
    """Show a run's events and step logs, or with --summary the run's summary.md."""
    if args.summary:
        r = runs.summary(args.run_id)
        return show(args, r, r["summary"])
    r = runs.log(args.run_id, args.step, args.task)
    text = "\n".join(_event_line(e) for e in r["events"]) or "No events."
    for name, body in r["logs"].items():
        text += f"\n\n--- log: {name} ---\n{body.rstrip()}"
    return show(args, r, text)


def _wait_for_stop(run_id: str) -> dict:
    """Wait up to STOP_WAIT_S seconds for the run to show it ended; return its last status."""
    deadline = time.monotonic() + STOP_WAIT_S
    r = runs.status(run_id)
    while r["status"] not in FINISHED and time.monotonic() < deadline:
        time.sleep(1)
        r = runs.status(run_id)
    return r


def stop(args) -> int:
    """Stop a run (needs --yes); when the runner is walking it, wait up to a minute for it to stop."""
    if not args.yes:
        return problem(args, f"This stops run {args.run_id} and removes its containers. "
                             "Add --yes to go ahead.")
    r = runs.stop(args.run_id, who=args.who)
    if r["status"] == "stop requested":
        if not args.json:
            print(f"Stop requested; waiting up to {STOP_WAIT_S} seconds for the runner to stop run {args.run_id}...",
                  flush=True)
        r = {**r, "status": _wait_for_stop(args.run_id)["status"]}
        if r["status"] not in FINISHED:
            r["status"] = "stop requested"
            return show(args, r, f"Stop requested for run {args.run_id}; the runner has not stopped it yet. "
                                 "It stops at the next step boundary (see: phoenix run status).")
    return show(args, r, f"Stopped run {r['run_id']}." if r["status"] == "stopped"
                else f"Run {r['run_id']} is {r['status']}.")


def note(args) -> int:
    """Add a note to a task's task file."""
    try:
        r = runs.note(args.run_id, args.task, args.text, who=args.who)
    except OpsError as err:
        return problem(args, str(err))
    return show(args, r, f"Noted on task {r['task']} of run {r['run_id']}. The next attempt will read it.")


def discard(args) -> int:
    """Discard a failed or stopped run's work (needs --yes)."""
    if not args.yes:
        return problem(args, f"This deletes run {args.run_id}'s worktree and branch, here and on GitHub. "
                             "Add --yes to go ahead.")
    r = runs.discard(args.run_id, who=args.who, force=args.force)
    words = f"Discarded the work of run {r['run_id']}."
    return show(args, r, "\n".join([words, *(f"Note: {n}" for n in r["notes"])]))


def pause(args) -> int:
    """Pause the running step (needs --now and --yes); wait up to a minute for the run to show paused."""
    if not (args.now and args.yes):
        return problem(args, f"This stops the step that is running in run {args.run_id}; the work so far is kept "
                             "and Resume carries on. Add --now --yes to go ahead.")
    r = runs.pause(args.run_id, now=True, who=args.who)
    deadline = time.monotonic() + PAUSE_WAIT_S
    while not r["waits_for_step"] and r["status"] != "paused" and time.monotonic() < deadline:
        now = runs.status(args.run_id)["status"]
        if now != "running":
            r = {**r, "status": now}
            break
        time.sleep(1)
    if r["waits_for_step"]:
        text = f"Run {r['run_id']} pauses when the step that is running ends."
    elif r["status"] == "paused":
        text = f"Paused run {r['run_id']}. Resume it with: phoenix run resume {r['run_id']}"
    else:
        text = f"Pause requested for run {r['run_id']}; the runner has not paused it yet (see: phoenix run status)."
    return show(args, r, text)


def resume(args) -> int:
    """Resume a paused run."""
    r = runs.resume(args.run_id, who=args.who)
    return show(args, r, f"Run {r['run_id']} is queued; it starts when the server is free." if r["queued"]
                else f"Run {r['run_id']} is running again.")
