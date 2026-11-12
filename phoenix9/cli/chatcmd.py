"""The `phoenix chat` commands: status, open, sleep or forget a project's chat."""
import argparse
import sys
import time

from phoenix9.cli.output import problem, show, table
from phoenix9.ops import chat

WORDS = {"none": "No chat yet", "asleep": "Asleep", "waking": "Waking", "awake": "Awake",
         "working": "Awake, working", "unknown": "Can't tell"}


def add(sub, common_parser) -> None:
    """Register the chat group."""
    p = sub.add_parser("chat", parents=[common_parser], help="project chats: status, open, sleep, forget")
    cmds = p.add_subparsers(dest="chat_cmd", metavar="COMMAND", title="commands")
    t = cmds.add_parser("status", parents=[common_parser], help="show one project's chat, or every project's")
    t.add_argument("project", nargs="?", help="the project (leave out for all)")
    t.set_defaults(func=run_status)
    o = cmds.add_parser("open", parents=[common_parser], help="open a project's chat, waking it if asleep")
    o.add_argument("project", help="the project")
    o.set_defaults(func=run_open)
    s = cmds.add_parser("sleep", parents=[common_parser], help="ask the chat to wrap up, then stop it (nothing is lost)")
    s.add_argument("project", help="the project")
    s.set_defaults(func=run_sleep)
    f = cmds.add_parser("forget", parents=[common_parser],
                        help="stop the chat and forget its saved conversation (needs --yes)")
    f.add_argument("project", help="the project")
    f.add_argument("--yes", action="store_true", help="confirm that you mean it")
    f.set_defaults(func=run_forget)
    # Old name, kept so scripts don't break; no help= so it is not listed.
    off = cmds.add_parser("off", parents=[common_parser])
    off.add_argument("project", help="the project")
    off.add_argument("--yes", action="store_true", help=argparse.SUPPRESS)
    off.set_defaults(func=run_off)
    p.set_defaults(func=lambda args: (p.print_help(), 0)[1])


def ago(when, now: float | None = None) -> str:
    """A time as plain words: 'just now', '5 min ago', '2 h ago', '3 days ago', or 'never'."""
    if not when:
        return "never"
    seconds = max(0.0, (time.time() if now is None else now) - when)
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return "%d min ago" % (seconds // 60)
    if seconds < 86400:
        return "%d h ago" % (seconds // 3600)
    days = int(seconds // 86400)
    return "%d day%s ago" % (days, "" if days == 1 else "s")


def run_status(args) -> int:
    """Print one project's chat state and links, or a table of every project's chat."""
    if args.project:
        data = chat.chat_state(args.project)
        parts = [WORDS.get(data["state"], data["state"]), "last active " + ago(data.get("last_active"))]
        if data.get("web_url"):
            parts += ["Web: " + data["web_url"], "App: " + data["app_url"]]
        return show(args, data, "%s: %s" % (args.project, " · ".join(parts)))
    data = chat.status_all()
    rows = [[r["name"], WORDS.get(r["state"], r["state"]), ago(r.get("last_active"))] for r in data["projects"]]
    text = table(rows, ["Project", "Chat", "Last active"]) if rows else "No projects yet."
    if data["unlisted"]:
        text += "\n\nChats running for projects that are not listed:\n" + "\n".join(
            "  claude-rc-chat@" + n for n in data["unlisted"])
    return show(args, data, text)


def run_open(args) -> int:
    """Open the chat and print its links."""
    data = chat.open_chat(args.project, args.who)
    text = "%s\nWeb: %s\nApp: %s" % (data["message"], data["web_url"], data["app_url"])
    return show(args, data, text)


def run_sleep(args) -> int:
    """Wrap up and sleep the chat."""
    data = chat.sleep_chat(args.project, args.who)
    return show(args, data, data["message"])


def run_forget(args) -> int:
    """Forget the saved chat (needs --yes)."""
    if not args.yes:
        return problem(args, "This stops %s's chat and forgets its saved conversation; pressing Chat then starts a "
                             "fresh one. Run it again with --yes to do it." % args.project)
    data = chat.forget_chat(args.project, args.who)
    return show(args, data, data["message"])


def run_off(args) -> int:
    """Old name for sleep: say the new name, then sleep the chat."""
    print("off is now: phoenix chat sleep", file=sys.stderr)
    return run_sleep(args)
