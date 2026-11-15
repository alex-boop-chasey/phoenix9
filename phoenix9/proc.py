"""The one place Phoenix starts outside programs: run, popen, the step a command belongs to, and failure records.

Every program Phoenix runs (systemctl, gh, git, docker...) goes through `run` (or `popen` for the one streaming
caller). A real action passes a plain `what="..."` label; when it fails, one `command.failed` event records the
exit code, the program (never its other arguments), a scrubbed error tail and the project/run/task/step from
`context`. A probe that fails on purpose passes no `what` and records nothing.
"""
from __future__ import annotations

import contextlib
import contextvars
import os
import re
import subprocess
from subprocess import CalledProcessError, Popen, TimeoutExpired  # noqa: F401 - re-exported for callers

from phoenix9 import events, scrub

DEVNULL = subprocess.DEVNULL
STDOUT = subprocess.STDOUT
PIPE = subprocess.PIPE
TIMEOUT_RC = 124
NOT_FOUND_RC = 127
TAIL_LINES = 20
TAIL_CHARS = 2000
LINE_CHARS = 300
VALUE_OPTIONS = {"-c", "-C"}                # options whose next word is their value (git -c x=y, git -C path)
SUBCOMMAND = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,40}$")

_CONTEXT: contextvars.ContextVar[dict] = contextvars.ContextVar("phoenix9_proc_context", default={})


class Result(tuple):
    """What a command gave back: (rc, out, err); unpacks as a 3-tuple and also reads like a CompletedProcess."""

    def __new__(cls, rc: int, out, err, *, timed_out: bool = False, not_found: bool = False):
        self = super().__new__(cls, (rc, out, err))
        self.timed_out = timed_out
        self.not_found = not_found
        return self

    rc = property(lambda self: self[0])
    out = property(lambda self: self[1])
    err = property(lambda self: self[2])
    returncode = rc
    stdout = out
    stderr = err

    @property
    def failed(self) -> bool:
        """True when the command did not end with exit code 0."""
        return self[0] != 0


@contextlib.contextmanager
def context(project=None, run=None, task=None, step=None):
    """Name the project/run/task/step that commands started inside this block belong to."""
    outer = _CONTEXT.get()
    given = {"project": project, "run": run, "task": task, "step": step}
    token = _CONTEXT.set({**outer, **{k: v for k, v in given.items() if v is not None}})
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def current() -> dict:
    """The active {project, run, task, step} (each None when no block named it)."""
    active = _CONTEXT.get()
    return {key: active.get(key) for key in ("project", "run", "task", "step")}


def _text(value) -> str:
    """Command output as text (bytes are decoded, None is empty)."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def tail(text, lines: int = TAIL_LINES, chars: int = TAIL_CHARS) -> str:
    """The last `lines` lines of a command's output (at most `chars` characters), with secrets removed."""
    kept = scrub.scrub(_text(text)).strip().splitlines()[-lines:]
    out = "\n".join(kept)
    return out[-chars:] if len(out) > chars else out


def _last_line(text) -> str:
    """The last non-empty line of a command's output, scrubbed and capped."""
    for line in reversed(scrub.scrub(_text(text)).splitlines()):
        if line.strip():
            line = line.strip()
            return line[:LINE_CHARS] + "..." if len(line) > LINE_CHARS else line
    return ""


def failure_text(what: str, result) -> str:
    """One plain line saying what failed and why, e.g. "Pushing the branch failed (exit code 1): <reason>"."""
    rc, out, err = result
    reason = _last_line(err) or _last_line(out)
    head = f"{what} failed (exit code {rc})"
    return f"{head}: {reason}" if reason else head


def program(argv) -> str:
    """The program's name plus its first word that is not an option (e.g. "git push"), never other arguments.

    The value after an option that takes one (`git -c x=y`, `git -C path`) is skipped, and a word that does not
    look like a subcommand (a path, `x=y`, code) is never used: then only the program's name is given."""
    words = [str(a) for a in (argv or [])]
    if not words:
        return ""
    name = os.path.basename(words[0].rstrip("/")) or words[0]
    rest = iter(words[1:])
    for word in rest:
        if word in VALUE_OPTIONS:
            next(rest, None)
        elif not word.startswith("-"):
            return f"{name} {word}" if SUBCOMMAND.match(word) else name
    return name


def record_failure(what: str, program_name: str, rc: int, text) -> None:
    """Record one `command.failed` event for a command that failed; a failure to write it is ignored."""
    where = current()
    try:
        events.emit("command.failed", project=where["project"], run=where["run"], task=where["task"],
                    step=where["step"], what=what, program=program_name, exit_code=rc, stderr_tail=tail(text))
    except OSError:
        pass


def run(argv, *, what: str | None = None, timeout: float | None = 60, cwd=None, env=None, input=None,
        text: bool = True) -> Result:
    """Run a program to the end and return Result(rc, out, err); 124 on timeout, 127 when it is not there.

    With `what` (a plain label of the action), a failure is recorded as one `command.failed` event."""
    argv = list(argv)
    try:
        p = subprocess.run(argv, capture_output=True, text=text, timeout=timeout, cwd=cwd, env=env, input=input,
                           stdin=None if input is not None else subprocess.DEVNULL)
        result = Result(p.returncode, p.stdout, p.stderr)
    except subprocess.TimeoutExpired:
        message = f"timed out after {timeout}s"
        result = Result(TIMEOUT_RC, "" if text else b"", message if text else message.encode(), timed_out=True)
    except FileNotFoundError:
        message = f"not found: {argv[0]}"
        result = Result(NOT_FOUND_RC, "" if text else b"", message if text else message.encode(), not_found=True)
    if what and result.failed:
        record_failure(what, program(argv), result.rc, result.err or result.out)
    return result


def popen(argv, **kw) -> Popen:
    """Start a program and return it running (for the one caller that streams output to files)."""
    return subprocess.Popen(list(argv), **kw)
