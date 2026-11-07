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
    c = cmds.add_parser("catch-up", parents=[common_parser], help="set up chats for existing projects that have none")
    c.add_argument("--all", action="store_true", help="really do it (without it, only list what would be done)")
    c.set_defaults(func=run_catch_up)
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


def run_catch_up(args) -> int:
    """List the projects missing a chat; with --all set each up, one at a time."""
    say = None if args.json else (lambda r: print("%s: %s" % (r["project"], r["message"]), flush=True))
    data = chat.catch_up(args.who, args.all, say)
    if args.all:
        text = "Set up %d chat(s); %d failed." % (len(data["results"]) - data["failed"], data["failed"]) if data["todo"] else "Every project already has a chat."
    elif data["todo"]:
        text = "These projects have no chat yet:\n%s\nRun again with --all to set them up." % "\n".join("  " + n for n in data["todo"])
    else:
        text = "Every project already has a chat."
    show(args, data, text)
    return 1 if data["failed"] else 0
