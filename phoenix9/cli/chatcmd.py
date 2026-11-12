"""The `phoenix chat` commands: open, sleep or turn off a project's chat."""
from phoenix9.cli.output import problem, show
from phoenix9.ops import chat


def add(sub, common_parser) -> None:
    """Register the chat group."""
    p = sub.add_parser("chat", parents=[common_parser], help="project chats: open, sleep, off")
    cmds = p.add_subparsers(dest="chat_cmd", metavar="COMMAND", title="commands")
    o = cmds.add_parser("open", parents=[common_parser], help="open (start if needed) a project's chat")
    o.add_argument("project", help="the project")
    o.set_defaults(func=run_open)
    s = cmds.add_parser("sleep", parents=[common_parser], help="ask the chat to wrap up, then let it sleep")
    s.add_argument("project", help="the project")
    s.set_defaults(func=run_sleep)
    f = cmds.add_parser("off", parents=[common_parser], help="stop and disable a project's chat (needs --yes)")
    f.add_argument("project", help="the project")
    f.add_argument("--yes", action="store_true", help="confirm that you mean it")
    f.set_defaults(func=run_off)
    p.set_defaults(func=lambda args: (p.print_help(), 0)[1])


def run_open(args) -> int:
    """Open the chat and print its links."""
    data = chat.open_chat(args.project, args.who)
    text = "%s\nWeb: %s\nApp: %s" % (data["message"], data["web_url"], data["app_url"])
    return show(args, data, text)


def run_sleep(args) -> int:
    """Wrap up and sleep the chat."""
    data = chat.sleep_chat(args.project, args.who)
    return show(args, data, data["message"])


def run_off(args) -> int:
    """Turn the chat off (needs --yes)."""
    if not args.yes:
        return problem(args, "This stops %s's chat and turns it off. Run it again with --yes to do it." % args.project)
    data = chat.off_chat(args.project, args.who)
    return show(args, data, data["message"])

