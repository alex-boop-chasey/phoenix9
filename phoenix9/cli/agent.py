"""The `phoenix agent` commands: brief, status, send and read for the Phoenix agent chat."""
from phoenix9 import scrub
from phoenix9.cli.output import problem, show
from phoenix9.ops import agent, common


def add(sub, common_parser) -> None:
    """Register the agent group."""
    p = sub.add_parser("agent", parents=[common_parser], help="the Phoenix agent chat: brief, status, send, read")
    cmds = p.add_subparsers(dest="agent_cmd", metavar="COMMAND", title="commands")
    b = cmds.add_parser("brief", parents=[common_parser], help="short summary of all projects for the agent")
    b.set_defaults(func=run_brief)
    s = cmds.add_parser("status", parents=[common_parser], help="is the agent awake, busy or idle")
    s.set_defaults(func=run_status)
    m = cmds.add_parser("send", parents=[common_parser], help="post a message to the agent")
    m.add_argument("text", help="the message")
    m.add_argument("--page", help="the panel page this is about")
    m.add_argument("--project", help="the project this is about")
    m.add_argument("--run", help="the run this is about")
    m.set_defaults(func=run_send)
    r = cmds.add_parser("read", parents=[common_parser], help="read the agent's conversation as plain lines")
    r.add_argument("--after", type=int, default=0, help="only items after this line number")
    r.add_argument("--tail", type=int, help="only the last N items")
    r.set_defaults(func=run_read)
    p.set_defaults(func=lambda args: (p.print_help(), 0)[1])


def run_brief(args) -> int:
    """Print the brief."""
    common.record_command(args.who, "agent brief")
    data = agent.brief()
    return show(args, data, data["text"])


def run_status(args) -> int:
    """Print the agent's state."""
    common.record_command(args.who, "agent status")
    data = agent.status()
    name = data.get("name")
    text = "The agent is %s%s." % (data["state"], " (%s)" % name if name and data["state"] != "asleep" else "")
    return show(args, data, text)


def run_send(args) -> int:
    """Send a message to the agent."""
    context = {"page": args.page, "project": args.project, "run": args.run}
    try:
        data = agent.send(args.text, {k: v for k, v in context.items() if v}, args.who)
    except common.OpsError as err:
        return problem(args, str(err))
    return show(args, data, "Sent to the agent.")


def _item_line(item: dict) -> str:
    """One panel item as a plain line."""
    text = item.get("text") or item.get("markdown") or item.get("title") or item.get("name") or ""
    return scrub.scrub("%s %s: %s" % (item.get("line"), item.get("type"),
                                      str(text).replace("\n", " ")))


def run_read(args) -> int:
    """Print the agent's recent conversation items."""
    common.record_command(args.who, "agent read")
    data = agent.messages(args.after, 100000)
    if args.tail is not None:
        data["items"] = data["items"][-args.tail:] if args.tail > 0 else []
    return show(args, data, "\n".join(_item_line(i) for i in data["items"]) or "Nothing to read.")
