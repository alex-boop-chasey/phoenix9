"""Rule 1 (docs/architecture.md section 11): Phoenix never starts Claude on the host.

The only `claude` command line in Phoenix is `claude.build_command`, whose result runs inside a step container
(docker.py and the Claude adapter in adapters.py). This walks the code with `ast` and fails on any other
`claude` command line, and checks the Host adapter refuses one at run time.
"""
import ast
import re
from pathlib import Path

import pytest

from phoenix9 import adapters

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = ("phoenix9", "steps", "deployers")
# (file, enclosing function) where a claude command line is allowed: it is only ever run in a step container.
ALLOWED = {("phoenix9/claude.py", "build_command")}
ALLOWED_FILES = {"phoenix9/docker.py"}          # docker.py builds `docker run`, never a host claude
SHELL_CLAUDE = re.compile(r"(^|[\s;&|(`'\"])claude\s+(-p|--print|-c|--continue|--resume|remote-control)\b")
CALLS = {"run", "Popen", "call", "check_call", "check_output", "system", "execv", "execvp", "execve",
         "execvpe", "spawnv", "spawnvp", "getoutput", "getstatusoutput"}


def _is_claude_word(node) -> bool:
    if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
        return False
    return node.value.strip().rsplit("/", 1)[-1] == "claude"


def _docstrings(tree) -> set:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                found.add(id(body[0].value))
    return found


def _functions(tree) -> dict:
    """id(node) -> name of the innermost function holding it."""
    owner = {}

    def visit(node, name):
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else name
            owner[id(child)] = inner
            visit(child, inner)
    visit(tree, "")
    return owner


CLAUDE_IN_TEXT = re.compile(r"(^|[\s;&|(){}`'\"/=])claude($|[\s;&|(){}`'\"])")
PROCESS_MODULES = {"subprocess", "os", "pty", "asyncio"}
SPAWN_CALLS = re.compile(r"^(exec[lv]p?e?|spawn[lv]p?e?|posix_spawnp?|fork|forkpty|system|popen)$")


def _call_path(func) -> tuple[str, str]:
    """(module-ish prefix, name) of a call like subprocess.run / os.execv / asyncio.create_subprocess_exec."""
    if isinstance(func, ast.Attribute):
        base = func.value.id if isinstance(func.value, ast.Name) else ""
        return base, func.attr
    return "", getattr(func, "id", "")


def process_offenders(path: Path, rel: str) -> list[str]:
    """Process-starting calls with a `claude` word in any string argument (outside docker.py), and any
    os.exec* / os.spawn* / posix_spawn* use at all in phoenix9/."""
    if rel in ALLOWED_FILES:
        return []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        base, name = _call_path(node.func)
        if base == "os" and SPAWN_CALLS.match(name) and rel.startswith("phoenix9/"):
            bad.append(f"{rel}:{node.lineno}: os.{name} (Phoenix starts programs only through the adapters)")
            continue
        starts = (base in PROCESS_MODULES and (name in CALLS or name.startswith("create_subprocess")
                                                or SPAWN_CALLS.match(name))) or name in ("Popen", "run")
        if not starts:
            continue
        for arg in [*node.args, *(k.value for k in node.keywords)]:
            for inner in ast.walk(arg):
                if isinstance(inner, ast.Constant) and isinstance(inner.value, str) and CLAUDE_IN_TEXT.search(inner.value):
                    bad.append(f"{rel}:{node.lineno}: {base + '.' if base else ''}{name}(... 'claude' ...)")
    return bad


def offenders(path: Path, rel: str) -> list[str]:
    """Every claude command line in one file outside the allowed places."""
    if rel in ALLOWED_FILES:
        return []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
    docs, owner = _docstrings(tree), _functions(tree)
    bad = []
    for node in ast.walk(tree):
        where = (rel, owner.get(id(node), ""))
        if where in ALLOWED:
            continue
        if isinstance(node, (ast.List, ast.Tuple)) and node.elts and _is_claude_word(node.elts[0]):
            bad.append(f"{rel}:{node.lineno}: a ['claude', ...] command line")
        elif isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if name in CALLS and node.args and _is_claude_word(node.args[0]):
                bad.append(f"{rel}:{node.lineno}: {name}('claude', ...)")
        elif (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs
              and SHELL_CLAUDE.search(node.value)):
            bad.append(f"{rel}:{node.lineno}: a shell command that starts claude")
    return bad


def test_no_claude_command_line_outside_the_container_builder():
    found = []
    for folder in FOLDERS:
        for path in sorted((ROOT / folder).rglob("*.py")):
            found += offenders(path, path.relative_to(ROOT).as_posix())
            found += process_offenders(path, path.relative_to(ROOT).as_posix())
    assert found == [], "Claude may only start inside a step container:\n" + "\n".join(found)


def test_the_walker_catches_a_host_claude(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("import subprocess\n"
                   "def go(host):\n"
                   "    host.run(['claude', '-p', 'hi'])\n"
                   "    subprocess.Popen(('/usr/bin/claude', '-p'))\n"
                   "    subprocess.run('claude -p hi', shell=True)\n")
    assert len(offenders(bad, "phoenix9/bad.py")) == 3


def test_build_command_only_runs_claude_through_a_wrapper_for_the_container():
    from phoenix9 import claude
    argv = claude.build_command({"model": "m"}, "/phoenix/prompt.md", "/workspace")
    assert argv[0] == "sh" and "claude" in argv


def test_start_local_is_gone():
    from phoenix9 import claude
    assert not hasattr(claude, "start_local")
    with pytest.raises(ValueError):
        claude.run(["true"], ROOT, [], ROOT / "unused.jsonl", 1, 1)


@pytest.mark.parametrize("argv", [["claude", "-p", "x"], ["/usr/local/bin/claude", "--resume", "u"],
                                  ["env", "A=1", "claude", "-p"], ["timeout", "60", "claude"]])
def test_host_run_refuses_claude(argv):
    with pytest.raises(adapters.ClaudeOnHost, match="never starts Claude on the host"):
        adapters.Host().run(argv)


def test_host_run_still_runs_other_programs():
    assert adapters.Host().run(["true"])[0] == 0


def test_the_process_walker_catches_claude_in_any_argument_and_exec(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("import os, subprocess\n"
                   "def go(host, x):\n"
                   "    subprocess.run(['bash', '-c', 'cd /x && claude -p ' + x])\n"
                   "    subprocess.Popen(['env', 'A=1', '/usr/local/bin/claude'])\n"
                   "    os.execvp('sh', ['sh', '-c', 'echo hi'])\n"
                   "    os.posix_spawn('/bin/true', ['true'], {})\n"
                   "    host.run(['systemctl', 'restart', 'claude-rc@home'])\n")
    found = process_offenders(bad, "phoenix9/bad.py")
    assert len(found) == 4 and not any(":7:" in f for f in found)


@pytest.mark.parametrize("argv", [["/opt/x/claude"], ["git", "claude"], ["bash", "-c", "cd /srv && claude -p hi"],
                                  ["xargs", "claude"], ["npx", "claude", "-p"], ["node", "/x/cli.js", "claude"],
                                  ["sh", "-c", "exec claude"], ["timeout", "9", "sh", "-c", "(claude)"]])
def test_host_run_refuses_claude_anywhere(argv):
    with pytest.raises(adapters.ClaudeOnHost):
        adapters.Host().run(argv)


@pytest.mark.parametrize("argv", [["systemctl", "restart", "claude-rc@home"], ["du", "-sb", "/root/.claude"],
                                  ["bash", "-c", "systemctl is-active claude-rc-chat@demo"]])
def test_host_run_allows_claude_lookalikes(argv):
    adapters.refuse_claude(argv)
