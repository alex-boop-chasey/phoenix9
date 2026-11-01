"""Commands for `phoenix project`: list and show (read-only for now)."""
from phoenix9.cli.output import show, table
from phoenix9.ops import projects


def add(sub, common) -> None:
    """Register the project group."""
    group = sub.add_parser("project", help="projects").add_subparsers(dest="action", metavar="ACTION", required=True)
    group.add_parser("list", parents=[common], help="list projects").set_defaults(func=list_)
    p = group.add_parser("show", parents=[common], help="show one project")
    p.add_argument("name")
    p.set_defaults(func=show_)


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
