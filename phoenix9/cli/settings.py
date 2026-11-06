"""Commands for `phoenix settings`: show, explain, check, set, add, remove, preset, and `global` (show, set, migrate)."""
from phoenix9.cli.output import problem, show
from phoenix9.ops import app, settings as ops


def add(sub, common) -> None:
    """Register the settings group."""
    group = sub.add_parser("settings", help="a project's settings").add_subparsers(
        dest="action", metavar="ACTION", required=True)
    for name, func, help_ in (("show", show_, "every setting and where it came from"),
                              ("explain", explain, "the plan in plain words"),
                              ("check", check, "look for mistakes in phoenix.toml")):
        p = group.add_parser(name, parents=[common], help=help_)
        p.add_argument("project")
        p.set_defaults(func=func)
    p = group.add_parser("set", parents=[common], help="change one setting")
    p.add_argument("project")
    p.add_argument("assignment", metavar="key=value")
    p.set_defaults(func=set_)
    for name, help_ in (("add", "add one item to a list setting (safety_files, services...)"),
                        ("remove", "take one item out of a list setting")):
        p = group.add_parser(name, parents=[common], help=help_)
        p.add_argument("project")
        p.add_argument("key", help="a list setting, e.g. safety_files")
        p.add_argument("item")
        p.set_defaults(func=change_list, add=name == "add")
    p = group.add_parser("preset", parents=[common], help="choose a preset")
    p.add_argument("project")
    p.add_argument("name")
    p.set_defaults(func=preset)
    glob = group.add_parser("global", help="Phoenix's own settings (dashboard addresses)").add_subparsers(
        dest="global_action", metavar="ACTION", required=True)
    p = glob.add_parser("show", parents=[common], help="the dashboard addresses")
    p.set_defaults(func=global_show)
    p = glob.add_parser("set", parents=[common],
                        help="set dashboard_url, allowed_origins (comma list) or vscode_url (empty = not set)")
    p.add_argument("assignments", nargs="+", metavar="key=value")
    p.set_defaults(func=global_set)
    p = glob.add_parser("migrate", parents=[common],
                        help="one time: allowed_origins = api.env's origins + the dashboard's (nothing once set)")
    p.set_defaults(func=global_migrate)


def _flat(values: dict, prefix: str = "") -> list[tuple[str, object]]:
    out = []
    for key, value in values.items():
        if isinstance(value, dict):
            out += _flat(value, f"{prefix}{key}.")
        else:
            out.append((f"{prefix}{key}", value))
    return out


def show_(args) -> int:
    """Show effective settings."""
    r = ops.show(args.project)
    text = "\n".join(f"{k} = {v!r}  (from {r['source'].get(k, '?')})" for k, v in _flat(r["values"]))
    return show(args, r, text)


def explain(args) -> int:
    """Explain the plan."""
    r = ops.explain(args.project)
    return show(args, r, r["text"])


def check(args) -> int:
    """Check phoenix.toml; exit 1 when there are problems."""
    r = ops.check(args.project)
    show(args, r, "The settings are fine." if r["ok"] else
         "The settings have problems:\n" + "\n".join(f"- {p}" for p in r["problems"]))
    return 0 if r["ok"] else 1


def set_(args) -> int:
    """Set key=value."""
    key, sep, value = args.assignment.partition("=")
    if not sep or not key:
        return problem(args, "Say it as key=value, for example steps.builder.max_turns=30.", 2)
    r = ops.set(args.project, key.strip(), value, who=args.who)
    return show(args, r, f"Set {r['key']} in {r['project']}.")


def change_list(args) -> int:
    """Add an item to, or remove it from, a list setting."""
    r = ops.change_list(args.project, args.key, args.item, args.add, who=args.who)
    words = (f"Added {r['item']} to {r['key']} in {r['project']}." if args.add
             else f"Removed {r['item']} from {r['key']} in {r['project']}.")
    return show(args, r, words)


def preset(args) -> int:
    """Choose a preset."""
    r = ops.preset(args.project, args.name, who=args.who)
    return show(args, r, f"{r['project']} now uses the {r['preset']} preset.")


def _addresses_text(values: dict) -> str:
    return "\n".join([f"dashboard_url = {values['dashboard_url']}",
                      f"allowed_origins = {', '.join(values['allowed_origins'])}",
                      f"vscode_url = {values['vscode_url'] or '(not set)'}"])


def global_show(args) -> int:
    """Show the dashboard addresses."""
    view = app.global_view()
    return show(args, {"addresses": view["addresses"]}, _addresses_text(view["addresses"]))


def global_set(args) -> int:
    """Set dashboard addresses from key=value pairs (the API restarts when the allowed origins change)."""
    changes = {}
    for item in args.assignments:
        key, sep, value = item.partition("=")
        if not sep or not key.strip():
            return problem(args, "Say it as key=value, for example vscode_url=https://code.example.com/.", 2)
        changes[key.strip()] = value
    r = app.set_addresses(changes, who=args.who)
    return show(args, r, _addresses_text(r["values"]) + f"\nAPI restart {r['api_restart']}.")


def global_migrate(args) -> int:
    """Run the one-time move to the address settings."""
    r = app.migrate_addresses(args.who)
    words = "Moved the allowed origins into the settings." if r["migrated"] else "Already done; nothing changed."
    return show(args, r, words + "\n" + _addresses_text(r["values"]))
