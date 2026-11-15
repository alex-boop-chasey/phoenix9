"""Every outside program Phoenix starts goes through phoenix9/proc.py, so every failure can be recorded the same way.

This walks the code with `ast` and fails on any `import subprocess` / `from subprocess import ...`, and any call
that starts a program another way (os.system/popen/exec*/spawn*/posix_spawn*/fork, pty.spawn,
asyncio.create_subprocess_*), outside the allowed files below.
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = ("phoenix9", "steps", "deployers", "agentkit/agentkit")
FILES = ("bin/check-template-pins",)
ALLOWED = {"phoenix9/proc.py": "the one place that starts programs"}
OS_CALLS = re.compile(r"^(system|popen|exec[lv]p?e?|spawn[lv]p?e?|posix_spawnp?|fork|forkpty)$")
SKIP_PARTS = {".venv", "node_modules", "__pycache__"}


def _call_path(func) -> tuple[str, str]:
    """(module name, called name) of a call like os.system or asyncio.create_subprocess_exec."""
    if isinstance(func, ast.Attribute):
        base = func.value.id if isinstance(func.value, ast.Name) else ""
        return base, func.attr
    return "", getattr(func, "id", "")


def _aliases(tree) -> dict:
    """Names bound by `from os import system`-style imports: local name -> (module, name)."""
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in ("os", "pty", "asyncio"):
            for alias in node.names:
                found[alias.asname or alias.name] = (node.module, alias.name)
    return found


def _starts_program(module: str, name: str) -> bool:
    """True for a call that starts a program without proc.py."""
    if module == "os":
        return bool(OS_CALLS.match(name))
    if module == "pty":
        return name in ("spawn", "fork")
    if module == "asyncio":
        return name.startswith("create_subprocess_")
    return False


def offenders(source: str, rel: str) -> list[str]:
    """Every place in one file's source that starts a program outside proc.py."""
    if rel in ALLOWED:
        return []
    tree = ast.parse(source, filename=rel)
    aliases = _aliases(tree)
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name.split(".")[0] == "subprocess" for a in node.names):
                bad.append(f"{rel}:{node.lineno}: import subprocess")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "subprocess":
                bad.append(f"{rel}:{node.lineno}: from subprocess import")
        elif isinstance(node, ast.Call):
            module, name = _call_path(node.func)
            if not module and name in aliases:
                module, name = aliases[name]
            if _starts_program(module, name):
                bad.append(f"{rel}:{node.lineno}: {module}.{name}")
    return bad


def _files():
    """Every Python file the guard checks, as (path, path relative to the repo)."""
    for folder in FOLDERS:
        for path in sorted((ROOT / folder).rglob("*.py")):
            if not SKIP_PARTS & set(path.parts):
                yield path, path.relative_to(ROOT).as_posix()
    for name in FILES:
        yield ROOT / name, name


def test_programs_start_only_in_proc():
    bad = []
    for path, rel in _files():
        bad += offenders(path.read_text(encoding="utf-8"), rel)
    assert not bad, "start programs through phoenix9/proc.py (run, popen) instead:\n" + "\n".join(bad)


def test_every_allowed_file_exists_and_folders_are_there():
    for rel, why in ALLOWED.items():
        assert (ROOT / rel).is_file(), f"{rel} is allowed ({why}) but does not exist"
        assert why.strip()
    for folder in FOLDERS:
        assert (ROOT / folder).is_dir(), folder
    for name in FILES:
        assert (ROOT / name).is_file(), name


def test_the_guard_catches_a_bad_file(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("import subprocess\nfrom subprocess import run\nimport os, pty, asyncio\n"
                   "from os import system as sh\n"
                   "os.system('x')\nos.execvp('x', ['x'])\nos.posix_spawn('x', [], {})\nos.fork()\n"
                   "pty.spawn('x')\nasyncio.create_subprocess_exec('x')\nsh('x')\n")
    found = offenders(bad.read_text(), "phoenix9/bad.py")
    assert len(found) == 9, found
    assert offenders("import os\nos.path.join('a')\nos.getpid()\n", "phoenix9/fine.py") == []
    assert offenders(bad.read_text(), "phoenix9/proc.py") == []
