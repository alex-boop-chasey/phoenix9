"""Commands for `phoenix keys`: audit of every secrets file and project key (names only)."""
from phoenix9.cli.output import show, table
from phoenix9.ops import keys as ops


def add(sub, common) -> None:
    """Register the keys group."""
    group = sub.add_parser("keys", help="account and project keys audit").add_subparsers(
        dest="action", metavar="ACTION", required=True)
    p = group.add_parser("audit", parents=[common], help="which keys exist, where they are used, and problems")
    p.set_defaults(func=audit)


def _text(data: dict) -> str:
    """The audit as three short sections."""
    g = [[r["file"], ", ".join(r["names"]) or "-", r["used_by"], r["modified"], r["mode"]] for r in data["global"]]
    p = [[r["project"], r["name"], "yes" if r["secret"] else "no", "yes" if r["set"] else "no", r["used"],
          r["last_touched"], r["service"] or "-"] for r in data["projects"]]
    problems = "\n".join(f"- {x}" for x in data["problems"]) or "No problems found."
    return ("Account keys\n" + (table(g, ["FILE", "KEYS", "USED BY", "MODIFIED", "MODE"]) if g else "None.")
            + "\n\nProject keys\n"
            + (table(p, ["PROJECT", "KEY", "SECRET", "SET", "USED", "LAST TOUCHED", "SERVICE"]) if p else "None.")
            + "\n\nProblems\n" + problems)


def audit(args) -> int:
    """Print the keys audit."""
    data = ops.audit()
    return show(args, data, _text(data))
