"""The templates menu: templates/<name>/template.toml, with checks that recipes use pinned versions."""
import re

from phoenix9 import library, paths
from phoenix9.library import Field

KINDS = ("files", "recipe")
FIELDS = [Field("name", str, required=True), Field("title", str, required=True),
          Field("profile", str, required=True), Field("kind", str, required=True, choices=KINDS),
          Field("run", list, default=[], list_of=str), Field("check", str, default="")]
_PINNED = re.compile(r"@\d[\w.+-]*$")


def _unpinned(command: str) -> list[str]:
    """The package words in a recipe command that lack an exact @version."""
    words = command.split()
    bad = [w for w in words if "@latest" in w]
    for i, w in enumerate(words):
        if w in ("create", "add"):
            rest = [x for x in words[i + 1:] if not x.startswith("-") and x != "."]
            pkgs = rest if w == "add" else rest[:1]
            bad += [p for p in pkgs if not _PINNED.search(p) and p not in bad]
    return bad


def _adds_playwright(values: dict, folder) -> bool:
    """True when a template would put Playwright into a new project (Alex checks pages by hand instead)."""
    if any("playwright" in command.lower() for command in values["run"]):
        return True
    files = folder / "files"
    if not files.is_dir():
        return False
    for path in files.rglob("*"):
        if path.name.lower().startswith("playwright.config"):
            return True
        if path.name == "package.json" and path.is_file() and "playwright" in path.read_text(errors="replace").lower():
            return True
    return False


def _parse(data: dict, folder, where: str):
    """Check one template.toml; returns (template dict or None, problems)."""
    values, problems = library.check_fields(data, FIELDS, where)
    if values["name"] != folder.name:
        problems.append(f"{where}: name '{values['name']}' must match the folder name '{folder.name}'")
    if values["kind"] == "recipe":
        if not values["run"]:
            problems.append(f"{where}: a recipe needs a 'run' list")
        for command in values["run"]:
            for word in _unpinned(command):
                problems.append(f"{where}: '{word}' needs an exact version (name@1.2.3), not latest or none")
    elif values["kind"] == "files" and not (folder / "files").is_dir():
        problems.append(f"{where}: kind 'files' needs a files/ folder")
    if _adds_playwright(values, folder):
        problems.append(f"{where}: templates may not add Playwright or browser tests (Vitest only; "
                        "Alex checks pages by hand)")
    values["folder"] = str(folder)
    return (None if problems else values), problems


def load_menu() -> list[dict]:
    """Every template, by name; a broken one is left out (see load_problems)."""
    return library.load_folders(paths.library() / "templates", "template.toml", _parse)[0]


def load_problems() -> list[str]:
    """Plain-words problems found in the templates folder."""
    return library.load_folders(paths.library() / "templates", "template.toml", _parse)[1]


def get(name: str) -> dict | None:
    """One template from the menu, or None when the name is not on it."""
    return next((t for t in load_menu() if t["name"] == name), None)
