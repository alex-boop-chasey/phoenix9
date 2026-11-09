"""The `phoenix agent` commands: brief, status, send and read for the Phoenix agent chat."""
from phoenix9 import scrub
from phoenix9.cli.output import problem, show
from phoenix9.ops import agent, common


def stop_words(stopped: int) -> str:
    """The plain sentence for what Stop did."""
    if stopped:
        return "Stopped %d running command%s. The agent has been told to stop." % (stopped, "" if stopped == 1 else "s")
    return "Nothing was running; the agent has been told to stop."


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
    x = cmds.add_parser("restart", parents=[common_parser], help="restart the agent's service (needs --yes)")
    x.add_argument("--yes", action="store_true", help="confirm that you mean it")
    x.set_defaults(func=run_restart)
    t = cmds.add_parser("stop", parents=[common_parser], help="end the command the agent is running and tell it to stop")
    t.set_defaults(func=run_stop)
    n = cmds.add_parser("new", parents=[common_parser], help="start a fresh conversation with the agent (needs --yes)")
    n.add_argument("--yes", action="store_true", help="confirm that you mean it")
    n.set_defaults(func=run_new)
    w = cmds.add_parser("watch", parents=[common_parser], help="check once that the agent is running; restart it if not")
    w.set_defaults(func=run_watch)
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


def run_watch(args) -> int:
    """Run one watchdog check on the agent."""
    from phoenix9 import adapters, agentwatch
    common.record_command(args.who, "agent watch")
    result = agentwatch.check_once(adapters.real())
    return show(args, {"result": result}, "Agent watchdog: %s." % result)


def run_restart(args) -> int:
    """Restart the agent's systemd service."""
    if not args.yes:
        return problem(args, "This restarts the Phoenix agent's service; a reply it is writing is cut off. "
                             "Add --yes to go ahead.")
    data = agent.restart(args.who)
    return show(args, data, "Asked systemd to restart %s." % data["unit"])


def run_stop(args) -> int:
    """End the agent's running command and tell it to stop."""
    try:
        data = agent.stop(args.who)
    except common.OpsError as err:
        return problem(args, str(err))
    return show(args, data, stop_words(data["stopped"]))


def run_new(args) -> int:
    """Ask the agent to save its notes, then start a fresh conversation."""
    if not args.yes:
        return problem(args, "This asks the agent to save its notes, waits for it to finish (a few minutes at most), "
                             "then ends the current conversation and starts a new one. Add --yes to go ahead.")
    try:
        data = agent.new_conversation(args.who)
    except common.OpsError as err:
        return problem(args, str(err))
    notes = "The agent was asked to save its notes first." if data["notes_asked"] else "The agent was off, so it was just started."
    return show(args, data, "A new conversation has started. %s (Waited %d seconds.)" % (notes, data["waited_seconds"]))
