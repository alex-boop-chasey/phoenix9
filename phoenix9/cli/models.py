"""Commands for `phoenix models`: show and change Phoenix's default models for the AI steps."""
from phoenix9.cli.output import show
from phoenix9.ops import app


def add(sub, common) -> None:
    """Register the models group."""
    group = sub.add_parser("models", help="Phoenix's default models for the AI steps").add_subparsers(
        dest="action", metavar="ACTION", required=True)
    p = group.add_parser("list", parents=[common], help="each AI step's model and fallbacks")
    p.set_defaults(func=list_)
    p = group.add_parser("set", parents=[common], help="choose the default model for one AI step")
    p.add_argument("step")
    p.add_argument("model")
    p.add_argument("--fallback", action="append", default=[], metavar="MODEL", help="a fallback model; up to two")
    p.set_defaults(func=set_)


def list_(args) -> int:
    """List the default models."""
    rows = app.default_models()
    text = "\n".join(f"{n}: {r['model']}" + (f" (then {', '.join(r['fallback_models'])})" if r["fallback_models"] else "")
                     for n, r in rows.items())
    return show(args, rows, text)


def set_(args) -> int:
    """Save the default model for one step."""
    r = app.set_default_models({args.step: {"model": args.model, "fallback_models": args.fallback}}, who=args.who)
    return show(args, r, f"Saved the default model for {args.step}.")
