"""Printing helpers shared by all commands: JSON or plain words, and simple aligned columns."""
import json
import sys


def show(args, data, text: str = "") -> int:
    """Print data as JSON when --json was given, else the plain text; returns exit code 0."""
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True))
    elif text:
        print(text.rstrip("\n"))
    return 0


def problem(args, message: str, code: int = 1) -> int:
    """Print a refusal or problem in plain words (JSON error object with --json) and return the code."""
    if args.json:
        print(json.dumps({"ok": False, "error": message}))
    else:
        print(message, file=sys.stderr)
    return code


def table(rows: list[list[str]], headers: list[str]) -> str:
    """Rows as left-aligned columns under a header line."""
    grid = [headers] + [[str(c) for c in row] for row in rows]
    widths = [max(len(r[i]) for r in grid) for i in range(len(headers))]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in grid)
