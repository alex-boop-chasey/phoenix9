"""Commands for `phoenix steps list`, `phoenix profiles list` and `phoenix presets list`."""
from phoenix9.cli.output import show, table
from phoenix9.ops import library


def add(sub, common) -> None:
    """Register the steps, profiles and presets groups."""
    for name, func, help_ in (("steps", steps, "the build steps"), ("profiles", profiles, "project profiles"),
                              ("presets", presets, "presets")):
        group = sub.add_parser(name, help=help_).add_subparsers(dest="action", metavar="ACTION", required=True)
        group.add_parser("list", parents=[common], help=f"list {name}").set_defaults(func=func)


def _problems(r: dict) -> str:
    return "".join(f"\nProblem: {p}" for p in r.get("problems", []))


def steps(args) -> int:
    """List steps."""
    r = library.steps()
    text = table([[s["name"], s["group"], s["kind"], s["default"], s["title"]] for s in r["steps"]],
                 ["step", "group", "kind", "default", "title"])
    return show(args, r, text + _problems(r))


def profiles(args) -> int:
    """List profiles."""
    r = library.profiles()
    text = table([[p["name"], p["image"], p["title"]] for p in r["profiles"]], ["profile", "image", "title"])
    return show(args, r, text + _problems(r))


def presets(args) -> int:
    """List presets."""
    r = library.presets()
    return show(args, r, table([[p["name"], p["title"]] for p in r["presets"]], ["preset", "title"]))
