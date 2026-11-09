"""The `phoenix edit` commands: start, list, heartbeat, finish and abandon a quick edit."""
from phoenix9 import edits
from phoenix9.cli.output import problem, show, table
from phoenix9.ops import common


def add(sub, common_parser) -> None:
    """Register the edit group."""
    p = sub.add_parser("edit", parents=[common_parser], help="quick edits in a branch copy of a project")
    cmds = p.add_subparsers(dest="edit_cmd", metavar="COMMAND", title="commands")
    c = cmds.add_parser("start", parents=[common_parser], help="start a quick edit and print its folder")
    c.add_argument("project")
    c.add_argument("--title", required=True, help="what the edit is for")
    c.set_defaults(func=run_start)
    c = cmds.add_parser("list", parents=[common_parser], help="list quick edits")
    c.add_argument("--project", help="only this project")
    c.set_defaults(func=run_list)
    c = cmds.add_parser("heartbeat", parents=[common_parser], help="say work is going on in a quick edit")
    c.add_argument("id")
    c.set_defaults(func=run_heartbeat)
    c = cmds.add_parser("abandon", parents=[common_parser], help="remove a quick edit's folder and branch")
    c.add_argument("id")
    c.add_argument("--yes", action="store_true", help="confirm (this throws the work away)")
    c.set_defaults(func=run_abandon)
    c = cmds.add_parser("finish", parents=[common_parser], help="check a quick edit, push it and open a merge request")
    c.add_argument("id")
    c.add_argument("--message", help="the commit message (default: the edit's title)")
    c.set_defaults(func=run_finish)
    p.set_defaults(func=lambda args: (p.print_help(), 0)[1])


def run_start(args) -> int:
    """Start a quick edit and print its folder."""
    common.project_dir(args.project)
    try:
        rec = edits.start(args.project, args.title, args.who)
    except edits.EditError as err:
        return problem(args, str(err))
    common.record_command(args.who, f"edit start {args.project}", args.project)
    return show(args, rec, rec["folder"])


def run_list(args) -> int:
    """List quick edits."""
    common.record_command(args.who, "edit list", args.project)
    found = edits.list_edits(args.project)
    rows = [[e["id"], e["project"], e["status"], e["last_activity"], e["title"]] for e in found]
    text = table(rows, ["ID", "PROJECT", "STATUS", "LAST ACTIVITY", "TITLE"]) if rows else "No quick edits."
    return show(args, {"edits": found}, text)


def run_heartbeat(args) -> int:
    """Record a heartbeat for a quick edit."""
    try:
        rec = edits.heartbeat(args.id)
    except edits.EditError as err:
        return problem(args, str(err))
    common.record_command(args.who, f"edit heartbeat {args.id}", rec["project"])
    return show(args, rec, f"ok {rec['last_activity']}")


def run_finish(args) -> int:
    """Check, commit, push and open a merge request for a quick edit."""
    try:
        rec = edits.finish(args.id, args.message, who=args.who)
    except edits.EditError as err:
        return problem(args, str(err))
    common.record_command(args.who, f"edit finish {args.id}", rec["project"])
    return show(args, rec, f"Finished {args.id}. Merge request: {rec['pr']}")


def run_abandon(args) -> int:
    """Remove a quick edit's worktree and branch (needs --yes)."""
    if not args.yes:
        return problem(args, f"This throws away the quick edit {args.id}. Run again with --yes to do it.")
    try:
        rec = edits.abandon(args.id, args.who)
    except edits.EditError as err:
        return problem(args, str(err))
    common.record_command(args.who, f"edit abandon {args.id}", rec["project"])
    return show(args, rec, f"Abandoned {args.id}.")
