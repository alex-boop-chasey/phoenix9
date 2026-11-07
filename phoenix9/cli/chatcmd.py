"""The `phoenix chat` commands: open a project's chat."""
from phoenix9.cli.output import show
from phoenix9.ops import chat


def add(sub, common_parser) -> None:
    """Register the chat group."""
    p = sub.add_parser("chat", parents=[common_parser], help="project chats: open")
    cmds = p.add_subparsers(dest="chat_cmd", metavar="COMMAND", title="commands")
    o = cmds.add_parser("open", parents=[common_parser], help="open (start if needed) a project's chat")
    o.add_argument("project", help="the project")
    o.set_defaults(func=run_open)
    p.set_defaults(func=lambda args: (p.print_help(), 0)[1])


def run_open(args) -> int:
    """Open the chat and print its links."""
    data = chat.open_chat(args.project, args.who)
    text = "%s\nWeb: %s\nApp: %s" % (data["message"], data["web_url"], data["app_url"])
    return show(args, data, text)
