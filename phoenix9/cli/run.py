"""Commands for `phoenix run`: start, status, list, log, stop."""
import time

from phoenix9.cli.output import problem, show, table
from phoenix9.ops import runs

FINISHED = ("done", "failed", "stopped")


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


def stop(args) -> int:
    """Stop a run (needs --yes)."""
    if not args.yes:
        return problem(args, f"This stops run {args.run_id} and removes its containers. "
                             "Add --yes to go ahead.")
    r = runs.stop(args.run_id, who=args.who)
    return show(args, r, f"Stopped run {r['run_id']}.")
