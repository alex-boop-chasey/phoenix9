"""Commands for `phoenix project`: list, show, edit, open, close, set-chat, new, templates, keys and services."""
import sys

from phoenix9 import project_services
from phoenix9.cli.output import problem, show, table
from phoenix9.ops import keys as keys_ops, projects
from phoenix9.ops.common import OpsError


def add(sub, common) -> None:
    """Register the project group."""
    group = sub.add_parser("project", help="projects").add_subparsers(dest="action", metavar="ACTION", required=True)
    p = group.add_parser("list", parents=[common], help="list projects, optionally searched and filtered")
    p.add_argument("--filter", default="", metavar="TEXT", help="only projects whose name or description has this text")
    p.add_argument("--status", default="all", help="all, run, fail, idle or need")
    p.add_argument("--owner", default="all", help="all, none (no repo) or a GitHub owner")
    p.add_argument("--sort", default="name", help="name, active or size")
    p.add_argument("--attention", action="store_true", help="put projects that need you first")
    p.set_defaults(func=list_)
    p = group.add_parser("show", parents=[common], help="show one project")
    p.add_argument("name")
    p.set_defaults(func=show_)
    p = group.add_parser("edit", parents=[common], help="change a project's description, profile or repo")
    p.add_argument("name")
    p.add_argument("--description", metavar="TEXT")
    p.add_argument("--profile")
    p.add_argument("--repo", metavar="O/N")
    p.set_defaults(func=edit_)
    p = group.add_parser("open", parents=[common], help="switch the project's chat on")
    p.add_argument("name")
    p.set_defaults(func=open_)
    p = group.add_parser("close", parents=[common], help="switch the project's chat off")
    p.add_argument("name")
    p.add_argument("--force", action="store_true", help="close even home or a project with chats open")
    p.add_argument("--yes", action="store_true", help="really switch it off")
    p.set_defaults(func=close_)
    p = group.add_parser("remove", parents=[common], help="take a project off Phoenix's list (keeps every file)")
    p.add_argument("name")
    p.add_argument("--yes", action="store_true", help="really remove it")
    p.set_defaults(func=remove_)
    p = group.add_parser("import", parents=[common], help="bring a removed project or an existing folder into Phoenix")
    p.add_argument("target", nargs="?", metavar="NAME|PATH")
    p.add_argument("--list", action="store_true", help="list what can be imported")
    p.set_defaults(func=import_)
    p = group.add_parser("set-chat", parents=[common], help="save the chat link (https://claude.ai/code/<id>)")
    p.add_argument("name")
    p.add_argument("url")
    p.set_defaults(func=set_chat_)
    p = group.add_parser("new", parents=[common], help="create a project")
    p.add_argument("name")
    p.add_argument("--description", default="", metavar="TEXT")
    p.add_argument("--profile")
    p.add_argument("--template", metavar="T", help="a menu template (see: phoenix project templates) or a GitHub OWNER/NAME")
    p.add_argument("--repo", metavar="O/N", help="copy this GitHub repo into code/")
    p.add_argument("--code", metavar="PATH", help="use code that already lives in this folder")
    p.add_argument("--new-repo", metavar="OWNER", help="make a private GitHub repo under OWNER")
    p.add_argument("--no-new-repo", action="store_true", help="do not make a GitHub repo")
    p.add_argument("--services", metavar="a,b", default="")
    p.add_argument("--keys-file", metavar="PATH", help="a TOML file of [[key]] name/value/secret rows")
    p.set_defaults(func=new_)
    group.add_parser("templates", parents=[common], help="the templates menu").set_defaults(func=templates_)
    p = group.add_parser("keys", parents=[common], help="a project's keys (secret values are never shown)")
    p.add_argument("name")
    p.add_argument("action", nargs="?", choices=("set", "remove"))
    p.add_argument("key", nargs="?", metavar="NAME")
    p.add_argument("--secret", action="store_true", help="with set: the value is secret")
    p.add_argument("--from-file", metavar="PATH", help="with set: read the value from this file (else stdin)")
    p.add_argument("--yes", action="store_true", help="with remove: really delete")
    p.set_defaults(func=keys_)
    p = group.add_parser("services", parents=[common], help="a project's services")
    p.add_argument("name")
    p.add_argument("--set", metavar="a,b", help="choose these services (empty text for none)")
    p.set_defaults(func=services_)


def _size(n) -> str:
    """Bytes in short words; '…' when not measured yet."""
    if n is None:
        return "…"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def list_(args) -> int:
    """List projects."""
    filtered = (args.filter, args.status, args.owner, args.sort, args.attention) != ("", "all", "all", "name", False)
    if filtered:
        r = projects.query(args.filter, args.status, args.owner, args.sort, args.attention)
        found = r["top"] + r["rest"]
    else:
        found = projects.list()
    text = table([[p["name"], p["state"], p["chats"], p["harness"], _size(p["size"]), p["last_used"]] for p in found],
                 ["project", "state", "chats", "harness", "size", "last used"]) if found else ("No projects match." if filtered else "No projects yet.")
    return show(args, found if not filtered or not args.json else r, text)


def show_(args) -> int:
    """Show one project."""
    p = projects.show(args.name)
    chat = p["chat"]
    lines = [p["name"], f"  path: {p['path']}", f"  about: {p['description'] or '(none)'}",
             f"  repo: {p['repo'] or '(none)'}", f"  profile: {p['profile'] or '(none)'}",
             f"  services: {', '.join(p['services']) or '(none)'}", f"  size: {_size(p['size'])}",
             f"  chat server: {p['state']} ({p['chats']} chats open), last used {p['last_used']}",
             f"  chat link: {chat['url'] or '(none yet)'}", f"  harness: {p['harness']}",
             f"  VS Code: {p['vscode_url']}"]
    if p["gates"]:
        lines += ["  needs you:"] + [f"    {g['id']}: {g['title']}" for g in p["gates"]]
    if p["changelog"]:
        lines += ["  recent changes:"] + [f"    {x}" for x in p["changelog"]]
    return show(args, p, "\n".join(lines))


def edit_(args) -> int:
    """Change a project's description, profile or repo."""
    r = projects.edit(args.name, args.who, args.description, args.profile, args.repo)
    return show(args, r, f"Changed {', '.join(r['changed'])} for {args.name}.")


def open_(args) -> int:
    """Switch a project's chat on."""
    r = projects.open_(args.name, args.who)
    return show(args, r, f"{args.name} is already on." if r["already"] else
                f"{args.name} is on. It shows up in the Claude app in a few seconds; start a chat there.")


def close_(args) -> int:
    """Switch a project's chat off (needs --yes)."""
    if not args.yes:
        return problem(args, f"This switches {args.name}'s chat off. Run it again with --yes to do it.")
    r = projects.close(args.name, args.who, args.force)
    return show(args, r, f"{args.name} is already off." if r["already"] else
                f"{args.name} is off. It won't start at boot; phoenix project open {args.name} turns it back on.")


def remove_(args) -> int:
    """Remove a project from Phoenix (needs --yes); nothing is deleted."""
    if not args.yes:
        return problem(args, f"This takes {args.name} off Phoenix's list and out of the Claude app. "
                             "Its files stay. Run it again with --yes to do it.")
    r = projects.remove(args.name, args.who)
    return show(args, r, f"Removed {args.name} from Phoenix. {r['kept']} "
                         f"Bring it back with: phoenix project import {args.name}")


def import_(args) -> int:
    """Import a project, or list what can be imported."""
    if args.list or not args.target:
        found = projects.import_candidates()
        rows = [[c["name"], c["path"], c["repo"] or "(none)", f"removed on {c['removed_on']}" if c["removed_on"] else "not listed"]
                for c in found]
        return show(args, found, table(rows, ["name", "path", "repo", "status"]) if rows else "Nothing to import.")
    r = projects.import_(args.target, args.who)
    return show(args, r, f"Imported {r['name']}. Its chat is on and shows up in the Claude app in a few seconds.")


def set_chat_(args) -> int:
    """Save the project's chat link."""
    r = projects.set_chat(args.name, args.url, args.who)
    return show(args, r, f"Saved the chat link for {args.name}.")


def new_(args) -> int:
    """Create a project, printing one line per creation step."""
    opts = {"name": args.name, "description": args.description, "profile": args.profile, "template": args.template,
            "repo": args.repo, "code": args.code, "new_repo": args.new_repo, "no_new_repo": args.no_new_repo,
            "services": [x.strip() for x in args.services.split(",") if x.strip()], "keys_file": args.keys_file}
    say = None if args.json else (lambda line: print(f"- {line}"))
    r = projects.new(opts, args.who, say)
    return show(args, r, f"Created {r['path']}")


def templates_(args) -> int:
    """List the templates menu."""
    menu = projects.templates_menu()
    text = table([[t["name"], t["title"], t["profile"], t["kind"]] for t in menu],
                 ["template", "title", "profile", "kind"]) if menu else "No templates."
    return show(args, menu, text)


def _value(args) -> str:
    """The key value from --from-file or stdin (one trailing newline dropped); never from an argument."""
    if args.from_file:
        try:
            text = open(args.from_file, encoding="utf-8").read()
        except OSError as err:
            raise OpsError(f"Cannot read {args.from_file}: {err.strerror}") from None
    else:
        text = sys.stdin.read()
    return text[:-1] if text.endswith("\n") else text


def keys_(args) -> int:
    """List, set or remove a project's keys."""
    if args.action is None:
        rows = keys_ops.list_(args.name, args.who)
        shown = [[r["name"], "secret" if r["secret"] else "plain",
                  ("••••••" if r["secret"] else r["value_if_not_secret"]) if r["has_value"] else "(empty)"] for r in rows]
        return show(args, rows, table(shown, ["key", "kind", "value"]) if rows else "No keys yet.")
    if not args.key:
        return problem(args, "Say which key, for example: phoenix project keys NAME set API_KEY --secret", 2)
    if args.action == "set":
        r = keys_ops.set_(args.name, args.key, _value(args), args.secret, args.who)
        return show(args, r, f"Saved {args.key} for {args.name}.")
    if not args.yes:
        return problem(args, f"This deletes the key {args.key}. Run it again with --yes to do it.")
    r = keys_ops.remove(args.name, args.key, args.who)
    return show(args, r, f"Removed {args.key} from {args.name}.")


def services_(args) -> int:
    """List the project's services, or choose them with --set."""
    if args.set is not None:
        names = [n.strip() for n in args.set.split(",") if n.strip()]
        r = project_services.set_services(args.name, names, args.who)
        return show(args, r, f"{args.name} now uses: {', '.join(names) or 'no services'}.")
    r = project_services.overview(args.name)
    text = (f"Chosen: {', '.join(r['chosen']) or '(none)'}\nAvailable: "
            + ", ".join(f"{a['name']} ({a['title']})" for a in r["available"]))
    return show(args, r, text)
