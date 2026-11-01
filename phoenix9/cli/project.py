"""Commands for `phoenix project`: list, show, keys and services."""
import sys

from phoenix9 import project_services
from phoenix9.cli.output import problem, show, table
from phoenix9.ops import keys as keys_ops, projects
from phoenix9.ops.common import OpsError


def add(sub, common) -> None:
    """Register the project group."""
    group = sub.add_parser("project", help="projects").add_subparsers(dest="action", metavar="ACTION", required=True)
    group.add_parser("list", parents=[common], help="list projects").set_defaults(func=list_)
    p = group.add_parser("show", parents=[common], help="show one project")
    p.add_argument("name")
    p.set_defaults(func=show_)
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


def list_(args) -> int:
    """List projects."""
    found = projects.list()
    text = table([[p["name"], "yes" if p["has_phoenix_toml"] else "no", p["description"][:60]] for p in found],
                 ["project", "phoenix.toml", "about"]) if found else "No projects yet."
    return show(args, found, text)


def show_(args) -> int:
    """Show one project."""
    p = projects.show(args.name)
    text = (f"{p['name']}\n  path: {p['path']}\n  about: {p['description'] or '(none)'}\n"
            f"  repo: {p['repo'] or '(none)'}\n  phoenix.toml: {'yes' if p['has_phoenix_toml'] else 'no'}")
    return show(args, p, text)


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
