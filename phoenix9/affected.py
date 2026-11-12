"""Works out which test files a change touches, with plain rules (no AI), so a build can run fewer tests."""
from __future__ import annotations

import re
import shlex
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

DEFAULT_MAX = 40


def _globs(value) -> list[str]:
    """A glob setting as a list (a space-separated string or a list)."""
    if isinstance(value, str):
        return value.split()
    return [str(v) for v in (value or [])]


def _matches(path: str, globs: list[str]) -> bool:
    """True when the path matches a glob (a glob with no slash matches the file name anywhere)."""
    name = PurePosixPath(path).name
    return any(fnmatch(path, g) or ("/" not in g and fnmatch(name, g)) for g in globs)


def _module_names(path: str) -> list[str]:
    """The names a test may use for a source file: stem, dotted path and slashed path."""
    p = PurePosixPath(path)
    bare = str(p.with_suffix(""))
    names = {bare, bare.replace("/", ".")}
    if p.stem not in ("__init__", "index"):
        names.add(p.stem)
    else:
        names.update({str(p.parent), str(p.parent).replace("/", ".")})
    return sorted(n for n in names if n and n != ".")


def _mentions(text: str, names: list[str]) -> bool:
    """True when the text contains any of the names as a whole word."""
    return any(re.search(r"(?<![\w])" + re.escape(n) + r"(?![\w])", text) for n in names)


def _read(root, path: str) -> str:
    """The text of a tracked file, or empty when it cannot be read."""
    try:
        return (Path(root or ".") / path).read_text(errors="replace")
    except OSError:
        return ""


def _all(why: str) -> dict:
    """The answer 'run everything'."""
    return {"mode": "all", "files": [], "command": "", "why": why}


def _command(template: str, files: list[str]) -> str:
    """The command with the files filled in, each shell-quoted."""
    return template.replace("{files}", " ".join(shlex.quote(f) for f in files))


def pick(profile_test: dict, changed_files: list[str], all_files: list[str], root=None) -> dict:
    """Pick the tests a change touches: {mode: some|all|none, files, command, why}; root is the checkout folder."""
    test = profile_test or {}
    template = test.get("affected_cmd") or ""
    if not template or "{files}" not in template:
        return _all("this project type has no way to run only some tests")
    changed = list(dict.fromkeys(changed_files or []))
    if any("\n" in f or "\r" in f for f in changed):
        return _all("a changed file name has a line break in it")
    if any(_matches(f, _globs(test.get("affected_all_globs"))) for f in changed):
        return _all("a file that can affect every test changed")
    existing = set(all_files or [])
    tests = [f for f in sorted(existing) if _matches(f, _globs(test.get("test_globs")))]
    test_set = set(tests)
    sources = [f for f in changed if f in existing and f not in test_set]
    picked = [f for f in changed if f in test_set]
    if test.get("affected_takes") == "sources":
        picked += sources
    else:
        for t in tests:
            if t in picked or not sources:
                continue
            text = _read(root, t)
            if any(_mentions(text, _module_names(s)) for s in sources):
                picked.append(t)
    picked = sorted(dict.fromkeys(picked))
    if any("\n" in f or "\r" in f for f in picked):
        return _all("a test file name has a line break in it")
    if not picked:
        return {"mode": "none", "files": [], "command": "",
                "why": "no test file changed and none mentions a changed file"}
    limit = test.get("affected_max", DEFAULT_MAX)
    limit = limit if isinstance(limit, int) and limit > 0 else DEFAULT_MAX
    if len(picked) > limit:
        return _all(f"{len(picked)} test files are affected (more than {limit})")
    return {"mode": "some", "files": picked, "command": _command(template, picked),
            "why": f"{len(picked)} test file(s) touched by the change"}
