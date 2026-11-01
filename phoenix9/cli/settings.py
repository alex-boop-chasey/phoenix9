"""Commands for `phoenix settings`: show, explain, check, set, preset."""
from phoenix9.cli.output import problem, show
from phoenix9.ops import settings as ops


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
    p = group.add_parser("preset", parents=[common], help="choose a preset")
    p.add_argument("project")
    p.add_argument("name")
    p.set_defaults(func=preset)


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


def preset(args) -> int:
    """Choose a preset."""
    r = ops.preset(args.project, args.name, who=args.who)
    return show(args, r, f"{r['project']} now uses the {r['preset']} preset.")
