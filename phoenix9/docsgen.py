"""Writes reference files (commands, settings, steps, pages, cards) from the code itself, into a folder you name."""
import argparse
import hashlib
import tomllib
from pathlib import Path

from phoenix9 import __version__, cards, paths, routes, settings
from phoenix9.library import load_library

FILES = ("commands.md", "settings.md", "steps.md", "pages.md", "cards.md")
HIDDEN_FLAGS = ("-h", "--help", "--json", "--who")

PAGE_TEXT = {
    "projects": "The home page: every project as a row with its status, owner and what needs Alex.",
    "new": "The new-project wizard: name, owner, template and first spec.",
    "p/<name>/overview": "One project: its state, open gates (Needs you) and recent builds.",
    "p/<name>/build": "One project's builds: start a build, follow a run's steps and tasks; `wizard` opens a slide of the build wizard (1 to 7).",
    "p/<name>/logs": "One project's logs and run documents; `run`, `step`, `task`, `kind` and `log` pick what to show.",
    "p/<name>/settings": "One project's settings (sections: project, build); `key` jumps to one setting.",
    "settings": "Phoenix's own settings (sections: services, models, updates, addresses).",
    "doc": "The document viewer: one notes or research document; `path` is its id, like notes:<project>/<file>.md.",
}


def _flag_line(action: argparse.Action) -> str:
    """One bullet for an argument: its names, value shape, default and help."""
    if action.option_strings:
        name = ", ".join(action.option_strings)
        if action.nargs != 0:
            name += f" {(action.metavar or action.dest).upper()}"
    else:
        name = f"<{action.metavar or action.dest}>"
    extra = ""
    if action.option_strings and action.default not in (None, False, argparse.SUPPRESS):
        extra = f" (default {action.default})"
    return f"- `{name}`{extra}: {action.help or ''}".rstrip(": ").rstrip()


def _args_of(parser: argparse.ArgumentParser) -> list[str]:
    """The bullets for a parser's own arguments, without the shared ones."""
    out = []
    for a in parser._actions:
        if isinstance(a, (argparse._SubParsersAction, argparse._HelpAction)):
            continue
        if any(o in HIDDEN_FLAGS for o in a.option_strings):
            continue
        out.append(_flag_line(a))
    return out


def _walk(parser: argparse.ArgumentParser, path: str, out: list[str], depth: int) -> None:
    """Add a section for every command below this parser."""
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        helps = {a.dest: a.help for a in action._choices_actions}
        for name, sub in action.choices.items():
            if name not in helps:       # a hidden old name (no help text), e.g. `phoenix chat off`
                continue
            full = f"{path} {name}".strip()
            out.append(f"{'#' * depth} `phoenix {full}`")
            out.append("")
            if helps.get(name):
                out += [helps[name], ""]
            lines = _args_of(sub)
            out += lines + ([""] if lines else [])
            _walk(sub, full, out, depth + 1)


def commands_body() -> str:
    """Every phoenix group and command with its flags, read from argparse."""
    from phoenix9.__main__ import build_parser
    out = ["# Phoenix commands", "",
           "Every command takes `--json` (machine-readable answer) and `--who NAME` (who is running it).",
           "Destructive commands need `--yes`.", ""]
    _walk(build_parser(), "", out, 2)
    return "\n".join(out)


def _show(value) -> str:
    """A default value as short text."""
    if value is None:
        return "(none)"
    if isinstance(value, bool):
        return "true" if value else "false"
    return repr(value) if isinstance(value, str) else str(value)


def _spec_rows(specs: dict) -> list[str]:
    """Table rows for settings specs."""
    rows = []
    for key, s in specs.items():
        kind = " or ".join(t.__name__ for t in s.type) if isinstance(s.type, tuple) else s.type.__name__
        if s.item_type:
            kind += f" of {s.item_type.__name__}"
        rows.append(f"| `{key}` | {kind} | {_show(s.default)} | {', '.join(map(str, s.choices))} |")
    return rows


def _preset_steps(lib, name: str) -> list[str]:
    """The steps a preset runs, in run order."""
    own = settings.load_preset(lib.root, name).get("steps", {})
    on = []
    for step in lib.steps:
        value = own.get(step.name, {}).get("on", step.default != "off")
        if step.default == "always" or value:
            on.append(step.name)
    return on


def settings_body(lib_root: Path) -> str:
    """phoenix.toml keys, defaults, layers, presets and profiles."""
    lib = load_library(lib_root)
    head = "| Key | Type | Default | Allowed |\n| --- | --- | --- | --- |"
    out = ["# Settings (phoenix.toml)", "",
           "Change with `phoenix settings`. Unknown keys are errors.", "",
           "## Layer order", "",
           "Lowest first; a later layer wins: " + " < ".join(settings.LAYERS) + ".", "",
           "## Project keys", "", head, *_spec_rows(settings.PROJECT_SCHEMA), "",
           "## AI keys (under `steps.<name>` for every ai step)", "", head, *_spec_rows(settings.AI_SCHEMA), "",
           "## Step keys (`steps.<name>.<key>`)", "", head,
           *_spec_rows({k: v for k, v in settings.step_specs(lib).items() if k not in
                        {f"steps.{s.name}.{a}" for s in lib.steps for a in settings.AI_SCHEMA}}), "",
           "## Presets", ""]
    for name in settings.PRESETS:
        if name == "custom":
            out += ["- `custom`: your own step choices on top of `based_on`.", ""]
            continue
        data = tomllib.loads((lib_root / "presets" / f"{name}.toml").read_text())
        out += [f"### {name}", "", data.get("description", ""), "",
                "Steps: " + ", ".join(_preset_steps(lib, name)), ""]
    out += ["## Profiles", ""]
    for folder in sorted((lib_root / "profiles").iterdir()):
        file = folder / "profile.toml"
        if file.is_file():
            data = tomllib.loads(file.read_text())
            test = data.get("test", {})
            out.append(f"- `{folder.name}`: {data.get('title', '')}; image `{data.get('image', '')}`; "
                       f"test `{test.get('cmd', '')}`; deployer `{data.get('suggested_deployer', 'none')}`")
    return "\n".join(out) + "\n"


def steps_body(lib_root: Path) -> str:
    """The step library: needs, produces and safety steps."""
    lib = load_library(lib_root)
    out = ["# Step library", "", "Steps run in this order inside each group.", ""]
    for group in ("run-start", "task", "run-finish"):
        out += [f"## {group}", ""]
        for s in lib.group(group):
            out.append(f"### {s.name}")
            out += ["", f"{s.title}. {s.description}".strip(), "",
                    f"- kind: {s.kind}", f"- default: {s.default}",
                    f"- safety step: {'yes' if s.safety else 'no'}",
                    f"- needs: {', '.join(s.needs) or '(nothing)'}",
                    f"- produces: {', '.join(s.produces) or '(nothing)'}"]
            if s.only_with:
                out.append(f"- only with: {', '.join(s.only_with)}")
            out.append("")
    out += ["## Things", ""]
    for name, t in sorted(lib.things.items()):
        how = f"provided: {t.provided}" if t.provided else f"fallback: {t.fallback or 'none'}"
        out.append(f"- `{name}` ({how}) {t.description}".rstrip())
    return "\n".join(out) + "\n"


def pages_body() -> str:
    """The route catalogue with what each page shows."""
    out = ["# Dashboard pages", "", "Link with `phoenix ui open` style routes; params go in the hash in this order.", ""]
    for name, params in routes.ROUTES:
        out += [f"## `{name}`", "", PAGE_TEXT[name], "", f"- params: {', '.join(params) or '(none)'}", ""]
    return "\n".join(out)


def cards_body() -> str:
    """Card types and their query schema."""
    out = ["# Cards", "", "A card is shown in the Agent panel; its query keys and types:", ""]
    for name in cards.types():
        mod = cards.load(name)
        doc = (mod.__doc__ or "").strip().removeprefix("Card: ")
        keys = ", ".join(f"`{k}` ({v})" for k, v in sorted(mod.schema.items())) or "(no keys)"
        out += [f"## `{name}`", "", doc, "", f"- query: {keys}", ""]
    return "\n".join(out)


def render(lib_root: Path | None = None) -> dict[str, str]:
    """All five files as text, each starting with its version line."""
    root = Path(lib_root or paths.library())
    bodies = {"commands.md": commands_body(), "settings.md": settings_body(root), "steps.md": steps_body(root),
              "pages.md": pages_body(), "cards.md": cards_body()}
    return {n: f"<!-- phoenix {__version__} inputs {hashlib.sha256(b.encode()).hexdigest()[:16]} -->\n{b}"
            for n, b in bodies.items()}


def generate(out: Path, lib_root: Path | None = None) -> list[Path]:
    """Write the reference files into the folder out; return the paths."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in render(lib_root).items():
        (out / name).write_text(text)
        written.append(out / name)
    return written
