"""The `phoenix plan` commands: start, status, continue and list planning sessions."""
from phoenix9 import chat, plans
from phoenix9.cli.output import problem, show, table
from phoenix9.ops import common


def add(sub, common_parser) -> None:
    """Register the plan group."""
    p = sub.add_parser("plan", parents=[common_parser], help="planning sessions that write a spec for a project")
    cmds = p.add_subparsers(dest="plan_cmd", metavar="COMMAND", title="commands")
    c = cmds.add_parser("start", parents=[common_parser], help="start a planning session (runs until it ends)")
    c.add_argument("project")
    c.add_argument("--brief", required=True, help="what to plan")
    c.add_argument("--model", help="the model (default: setting plan.model)")
    c.set_defaults(func=run_start)
    c = cmds.add_parser("status", parents=[common_parser], help="show one planning session")
    c.add_argument("id")
    c.set_defaults(func=run_status)
    c = cmds.add_parser("continue", parents=[common_parser], help="resume the session after the answers are filled in")
    c.add_argument("id")
    c.set_defaults(func=run_continue)
    c = cmds.add_parser("list", parents=[common_parser], help="list planning sessions")
    c.add_argument("--project", help="only this project")
    c.set_defaults(func=run_list)
    p.set_defaults(func=lambda args: (p.print_help(), 0)[1])


def _summary(rec: dict) -> str:
    return f"{rec['id']}: {rec['status']}" + (f" - {rec['report']}" if rec.get("report") else "")


def run_start(args) -> int:
    """Start a planning session."""
    common.project_dir(args.project)
    common.record_command(args.who, f"plan start {args.project}", args.project)
    try:
        rec = chat.plan_start(args.project, args.brief, args.model, who=args.who)
    except plans.PlanError as err:
        return problem(args, str(err))
    return show(args, rec, _summary(rec))


def run_status(args) -> int:
    """Show one planning session."""
    try:
        rec = plans.load(args.id)
    except plans.PlanError as err:
        return problem(args, str(err))
    return show(args, rec, _summary(rec))


def run_continue(args) -> int:
    """Resume a planning session."""
    try:
        rec = chat.plan_continue(args.id, who=args.who)
    except plans.PlanError as err:
        return problem(args, str(err))
    common.record_command(args.who, f"plan continue {args.id}", rec["project"])
    return show(args, rec, _summary(rec))


def run_list(args) -> int:
    """List planning sessions."""
    common.record_command(args.who, "plan list", args.project)
    found = plans.list_plans(args.project)
    rows = [[r["id"], r["project"], r["status"], str(r.get("open_questions") if r.get("open_questions") is not None else "-"),
             r["brief"][:50]] for r in found]
    text = table(rows, ["ID", "PROJECT", "STATUS", "OPEN", "BRIEF"]) if rows else "No planning sessions."
    return show(args, {"plans": found}, text)
