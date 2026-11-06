"""Commands for `phoenix run`: start, status, list, log, stop, discard."""
import time

from phoenix9.cli.output import problem, show, table
from phoenix9.ops import runs

FINISHED = ("done", "failed", "stopped")
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
    p = group.add_parser("status", parents=[common], help="show how a run is going")
    p.add_argument("run_id")
    p.add_argument("--watch", action="store_true", help="keep printing new events until the run stops")
    p.set_defaults(func=status)
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


def discard(args) -> int:
    """Discard a failed or stopped run's work (needs --yes)."""
    if not args.yes:
        return problem(args, f"This deletes run {args.run_id}'s worktree and branch, here and on GitHub. "
                             "Add --yes to go ahead.")
    r = runs.discard(args.run_id, who=args.who, force=args.force)
    words = f"Discarded the work of run {r['run_id']}."
    return show(args, r, "\n".join([words, *(f"Note: {n}" for n in r["notes"])]))
