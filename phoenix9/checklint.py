"""Two simple guards for locked checks (docs/architecture.md, "Locked checks are self-contained").

1. `unset_env(...)`: before checks are locked, the Check-writer step lists every environment variable
   a check file READS (shell `$VAR` / `${VAR}`, and python `os.environ["X"]`, `os.environ.get("X")`,
   `os.getenv("X")`, also inside heredocs) that the file never sets itself. A check may only lean on
   the names in `ALWAYS_SET`, the check container's own env, the project's keys and `PHOENIX_PROXY_*`.
2. `broken_reason(...)`: the Red check counts a failure only when it is not a crash in the check's own
   setup (a Python error raised in the check's own code, or the shell's "unbound variable" /
   "command not found").

Both are plain text rules, kept deliberately small; they are not a shell or Python parser.
"""
from __future__ import annotations

import re
import sys

# set by the shell or the container itself, never "the caller's environment"
ALWAYS_SET = frozenset({
    "PATH", "HOME", "TMPDIR", "PWD",
    "OLDPWD", "IFS", "RANDOM", "LINENO", "SECONDS", "UID", "EUID", "PPID", "BASHPID", "SHELL",
    "BASH", "BASH_SOURCE", "BASH_VERSION", "BASH_REMATCH", "BASH_LINENO", "FUNCNAME", "PIPESTATUS",
    "HOSTNAME", "HOSTTYPE", "OSTYPE", "MACHTYPE", "REPLY", "OPTARG", "OPTIND", "OPTERR", "SHLVL",
})
ALLOWED_PREFIXES = ("PHOENIX_PROXY_",)
SHELL_ENDINGS = (".sh", ".bash")

NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(" + NAME + r")\1")
_PY_READS = [
    re.compile(r"\benviron\[\s*['\"](" + NAME + r")['\"]\s*\](?!\s*=[^=])"),   # environ["X"], not environ["X"] = ...
    re.compile(r"\benviron\.get\(\s*['\"](" + NAME + r")['\"]\s*\)"),            # environ.get("X") with no default
    re.compile(r"\bgetenv\(\s*['\"](" + NAME + r")['\"]\s*\)"),                   # os.getenv("X") with no default
]
_PY_SETS = [
    re.compile(r"\benviron\[\s*['\"](" + NAME + r")['\"]\s*\]\s*=[^=]"),
    re.compile(r"\benviron\.setdefault\(\s*['\"](" + NAME + r")['\"]"),
    re.compile(r"\bputenv\(\s*['\"](" + NAME + r")['\"]"),
    re.compile(r"\bsetenv\(\s*['\"](" + NAME + r")['\"]"),                        # pytest monkeypatch.setenv
]
_SH_SETS = [
    re.compile(r"(?:^|[\s;&|(`])(" + NAME + r")(?:\[[^\]]*\])?\+?=", re.M),     # X=..., export X=..., X=1 cmd
    re.compile(r"(?:^|[\s;&|(])for\s+(" + NAME + r")\s+in\b", re.M),
]
_SH_READ = re.compile(r"(?:^|[\s;&|(])(?:read|getopts|mapfile|readarray)\b([^;&|\n]*)", re.M)   # read -r -d '' f
_SH_LISTS = re.compile(r"(?:^|[\s;&|(])(?:export|local|declare|readonly|typeset|unset)"
                       r"((?:[ \t]+(?:-\S+|" + NAME + r"))+)", re.M)


def is_shell(path: str, text: str) -> bool:
    """True for a shell script: a .sh/.bash file, or one starting with a sh/bash shebang."""
    first = text.split("\n", 1)[0]
    return path.endswith(SHELL_ENDINGS) or (first.startswith("#!") and re.search(r"\b(ba|da|z)?sh\b", first) is not None)


def _split_heredocs(text: str) -> tuple[str, str, str]:
    """(shell code, unquoted heredoc bodies, quoted heredoc bodies). Shell does not expand quoted bodies."""
    code, open_body, quoted_body = [], [], []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        code.append(line)
        found = [] if line.lstrip().startswith("#") else _HEREDOC.findall(line)
        i += 1
        for quote, word in found:
            body = []
            while i < len(lines) and lines[i].strip() != word:
                body.append(lines[i])
                i += 1
            i += 1                                       # the closing word
            (quoted_body if quote else open_body).extend(body)
            code.extend("" for _ in range(len(body) + 1))
    return "\n".join(code), "\n".join(open_body), "\n".join(quoted_body)


def _open_body_reads(text: str) -> list[str]:
    """$X and ${X} in an unquoted heredoc body (quotes are plain text there; \\$ is not an expansion)."""
    found = []
    for m in re.finditer(r"(?<!\\)\$(?:(" + NAME + r")|\{(" + NAME + r")(.?)(.?))", text):
        if m.group(1):
            found.append(m.group(1))
        elif not _has_fallback(m.group(3), m.group(4)):
            found.append(m.group(2))
    return found


def _has_fallback(op: str, op2: str) -> bool:
    """${X-..}, ${X=..}, ${X+..} and their ':' forms give their own value when X is unset."""
    return op in ("-", "=", "+") or (op == ":" and op2 in ("-", "=", "+"))


def _shell_reads(text: str) -> list[str]:
    """Variable names expanded by the shell: $X and ${X...}, outside single quotes and comments.
    `${X:-..}`, `${X-..}`, `${X:=..}`, `${X=..}` and `${X:+..}` carry their own fallback and do not count."""
    found, i, n = [], 0, len(text)
    single = double = False
    while i < n:
        c = text[i]
        if single:
            single = c != "'"
        elif c == "\\":
            i += 1
        elif c == "'" and not double:
            single = True
        elif c == '"':
            double = not double
        elif c == "#" and not double and (i == 0 or text[i - 1] in " \t\n;&|("):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif c == "$" and i + 1 < n:
            rest = text[i + 1:]
            m = re.match(NAME, rest)
            if m:
                found.append(m.group(0))
            elif rest.startswith("{"):
                m = re.match(r"\{(" + NAME + r")(.?)(.?)", rest)
                if m and not _has_fallback(m.group(2), m.group(3)):
                    found.append(m.group(1))
                m = re.match(r"\{#(" + NAME + r")\}", rest)
                if m:
                    found.append(m.group(1))
        i += 1
    return found


def _shell_sets(code: str) -> set[str]:
    names = {m for rx in _SH_SETS for m in rx.findall(code)}
    for group in _SH_LISTS.findall(code):
        names.update(w for w in group.split() if not w.startswith("-"))
    for args in _SH_READ.findall(code):
        names.update(w for w in args.split() if re.fullmatch(NAME, w))
    return names


def env_reads(path: str, text: str) -> list[str]:
    """Every environment variable the file reads, in order of first use (no repeats)."""
    names: list[str] = []
    if is_shell(path, text):
        code, open_body, _quoted = _split_heredocs(text)
        names += _shell_reads(code) + _open_body_reads(open_body)
    names += [m for rx in _PY_READS for m in rx.findall(text)]
    return list(dict.fromkeys(names))


def env_sets(path: str, text: str) -> set[str]:
    """Every variable the file assigns or exports itself (shell or python)."""
    names = {m for rx in _PY_SETS for m in rx.findall(text)}
    if is_shell(path, text):
        names |= _shell_sets(_split_heredocs(text)[0])
    return names


def unset_env(path: str, text: str, allowed=()) -> list[str]:
    """Variables the file reads but never sets and that are not given to every check. [] = self-contained."""
    ok = ALWAYS_SET | set(allowed) | env_sets(path, text)
    return [x for x in env_reads(path, text) if x not in ok and not x.startswith(ALLOWED_PREFIXES)]


def container_env_names() -> set[str]:
    """Names a check container always sets (docker.check_run's env, without the Claude ones)."""
    from phoenix9 import docker
    return {k for k in docker.session_env() if not k.startswith("CLAUDE_")} | set(docker.GIT_ENV)


# ------------------------------------------------------------------ red check: broken, or failing properly?
_FRAME = re.compile(r'^\s*File "([^"]+)", line (\d+)')
_ERROR = re.compile(r"^([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt)|KeyError)\b:?\s?(.*)$")
_SHELL = re.compile(r"^(.+?): (?:line )?\d+: (?:(\S+): (unbound variable|parameter not set)|(\S+): (?:command )?not found)\s*$")
CRASHES = ("KeyError", "NameError", "ImportError", "ModuleNotFoundError", "SyntaxError", "IndentationError",
           "TabError", "FileNotFoundError")
WORKSPACE = "/workspace"


def _library(path: str) -> bool:
    """Python's own files and installed packages (frames to look past)."""
    return path.startswith("<frozen") or "/lib/python" in path or "site-packages" in path or "dist-packages" in path


def _own(path: str, checks: list[str]) -> bool:
    """A frame in the check's own code: a check file, or a program it wrote outside the project
    (heredoc temp file, `python3 -` stdin, `python3 -c`)."""
    if any(path == c or path.endswith("/" + c) for c in checks):
        return True
    return not path.startswith(WORKSPACE + "/") and not path.startswith(("./", "../")) and \
        (path.startswith("/") or path in ("<stdin>", "<string>"))


def _python_crash(lines: list[str], at: int, checks: list[str]) -> str | None:
    """The plain message for the error on lines[at] when it is a crash in the check's own setup."""
    kind, msg = _ERROR.match(lines[at]).groups()
    kind = kind.rsplit(".", 1)[-1]
    if kind not in CRASHES:
        return None
    frames = []
    j = at - 1
    while j >= 0 and not lines[j].startswith("Traceback (most recent call last)") and not _ERROR.match(lines[j]):
        m = _FRAME.match(lines[j])
        if m:
            frames.insert(0, (m.group(1), int(m.group(2)), lines[j + 1].strip() if j + 1 < at else ""))
        j -= 1
    inner = next((f for f in reversed(frames) if not _library(f[0])), None)
    if inner is None or not _own(inner[0], checks):
        return None
    where = f"{inner[0]} line {inner[1]}"
    if kind == "KeyError" and "environ" not in inner[2]:
        return None                                   # a missing key in data the code returned is a real red
    if kind in ("ImportError", "ModuleNotFoundError"):
        mod = re.search(r"(?:No module named|from) '([\w.]+)'", msg)
        if not mod or mod.group(1).split(".")[0] not in sys.stdlib_module_names:
            return None                               # the project's own code or a package the builder adds
    if kind == "FileNotFoundError":
        missing = re.search(r"No such file or directory: '([^']+)'", msg)
        if not missing or not missing.group(1).startswith("/") or missing.group(1).startswith(WORKSPACE + "/"):
            return None                               # a project file that is not built yet is a real red
    return f"{kind} {msg}".strip() + f" in the check's own code ({where})"


def broken_reason(output: str, checks: list[str]) -> str | None:
    """Why the checks crashed in their own setup instead of failing on the code, or None for a proper red.

    `checks` are the repo-relative check paths. A crash counts when:
    - a Python error (KeyError reading os.environ, NameError, SyntaxError, ImportError of a standard-library
      module, FileNotFoundError for an absolute path outside /workspace) is raised in the check's own code:
      the innermost frame that is not Python's own library is a check file or a program the check wrote
      outside the project (heredoc temp file, <stdin>, <string>);
    - the shell running a check file says "unbound variable" / "parameter not set" or "command not found".
    """
    lines = output.splitlines()
    for at, line in enumerate(lines):
        if _ERROR.match(line):
            why = _python_crash(lines, at, checks)
            if why:
                return why
        m = _SHELL.match(line)
        if m and (_own(m.group(1), checks) or m.group(1) in ("sh", "bash")):
            if m.group(2):
                return f"the shell stopped: {m.group(2)} is not set ({m.group(1)})"
            return f"the shell could not find the command {m.group(4)} ({m.group(1)})"
    return None
