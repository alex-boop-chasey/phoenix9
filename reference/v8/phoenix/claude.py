"""The one place that runs a Claude Code session and reads its result.

Every AI call in Phoenix goes through this file, so the way Claude is
started (and how it logs in) can change in one place.

- `build_command()` makes the `claude -p ...` command line.
- `run()` starts it, copies every output line into a log file, and stops it
  if it goes quiet or runs too long.
- `parse()` reads that log file and decides what happened (`Result.kind`).
- `wait_for_limit()` waits out a usage limit.
- `record_usage()` writes the cost of each session into the run folder.
"""
from __future__ import annotations

import json
import os
import queue
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from phoenix import config
from phoenix.runs import load_run, now_iso, run_dir, save_run

KINDS = ("ok", "error", "rate_limited", "crashed", "timed_out", "no_output")
KILL_GRACE_S = 30        # seconds between SIGINT and SIGKILL
MIN_SECRET_LEN = 8       # shorter env values are not redacted (they would match ordinary words)
RESET_MARGIN = timedelta(minutes=2)

# Borrowed from Phoenix 0.6.0 hands/claude.py:12-16
RATE_LIMIT = re.compile(
    r"rate.?limit|usage limit|hit your (?:session |weekly |opus |sonnet |fable |individual )?(?:usage )?limit"
    r"|too many requests|\b429\b|limit reached|spend limit",
    re.I,
)
# "You've hit your limit · resets 3:45pm" counts as a limit even in a long or non-error result.
HIT_LIMIT = re.compile(r"hit your .*limit", re.I)
RESETS = re.compile(r"\bresets\b", re.I)


@dataclass
class Result:
    """What one Claude session ended with, as Phoenix sees it."""

    kind: str                       # one of KINDS
    text: str = ""                  # the final result text (or the end of stderr if there is none)
    session_id: str = ""
    cost_usd: float = 0.0
    turns: int = 0
    resets_at: datetime | None = None
    raw_path: Path | None = None    # the stream-json log the result was read from


# ------------------------------------------------------------- command line
def build_command(prompt_file: str, cwd: str, max_turns: int, allowed_tools: list[str],
                  disallowed_tools: list[str], append_system_prompt_file: str | None = None) -> list[str]:
    """Return the command that runs one Claude Code session.

    The prompt is fed in from `prompt_file` and the session runs in `cwd`
    (both are paths where the command runs, e.g. inside the container).
    A small `sh` wrapper does the `cd` and the `< prompt_file`, so the
    command is complete on its own. Never uses `--bare` (it ignores the
    OAuth token).
    """
    claude = ["claude", "-p", "--output-format", "stream-json", "--verbose",
              "--permission-mode", "bypassPermissions", "--max-turns", str(int(max_turns))]
    if allowed_tools:
        claude += ["--allowedTools", ",".join(allowed_tools)]
    if disallowed_tools:
        claude += ["--disallowedTools", ",".join(disallowed_tools)]
    if append_system_prompt_file:
        claude += ["--append-system-prompt-file", str(append_system_prompt_file)]
    assert "--bare" not in claude
    script = 'cd "$1" || exit 1; f="$2"; shift 2; exec "$@" < "$f"'
    return ["sh", "-c", script, "phoenix-claude", str(cwd), str(prompt_file)] + claude


# ------------------------------------------------------------- reading the result
MAX_LINE = 5_000_000


# Borrowed from Phoenix 0.6.0 hands/claude.py:67-105 (plain-json branch dropped: v8 only uses stream-json)
def _read_result(out_file: Path) -> dict:
    """Return the session's final result object, or {} if it cannot be trusted.

    The LAST non-empty line must be valid JSON with type "result", and it must
    be the ONLY line that looks like a result line. Anything else (no result,
    a cut-off or garbled last line, an extra forged result line) gives {}.
    """
    count, last = 0, b""
    try:
        with open(out_file, "rb") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if b'"result"' in line and len(line) <= MAX_LINE:
                    try:
                        o = json.loads(line)
                        if isinstance(o, dict) and o.get("type") == "result":
                            count += 1
                    except (json.JSONDecodeError, UnicodeError):
                        pass
                last = line if len(line) <= MAX_LINE else b"<too long>"
    except OSError:
        return {}
    if not last:
        return {}
    try:
        obj = json.loads(last)
    except (json.JSONDecodeError, UnicodeError):
        return {}
    if isinstance(obj, dict) and obj.get("type") == "result" and count == 1:
        return obj
    return {}


def _is_rate_limited(raw: dict, text: str) -> bool:
    """Return True if the result says a usage limit was hit.

    Borrowed from Phoenix 0.6.0 hands/claude.py:42-54: the general limit words
    only count in short error text, never in a long answer that mentions "429".
    """
    if HIT_LIMIT.search(text) and RESETS.search(text):
        return True
    if str(raw.get("api_error_status") or "") == "429":
        return True
    is_error = bool(raw.get("is_error"))
    return is_error and len(text) <= 600 and bool(RATE_LIMIT.search(text))


def _classify(raw: dict, rc: int, text: str) -> str:
    """Decide the kind of a finished session from its result object and exit code."""
    if not raw:
        return "crashed"
    if _is_rate_limited(raw, text):
        return "rate_limited"
    if rc == 0 and not raw.get("is_error"):
        return "ok"
    return "error"


def parse(out_file: Path, rc: int = 0, stderr_file: Path | None = None,
          now: float | None = None, tz: str = "UTC") -> Result:
    """Read a stream-json log and return what the session ended with.

    Only the single final `type: result` line counts; no result, an extra
    result line or a cut-off log is `crashed`. `now` and `tz` are used to
    read a reset time like "resets 3:45pm".
    """
    out_file = Path(out_file)
    raw = _read_result(out_file)
    errs = raw.get("errors") or []
    if isinstance(errs, list):
        errs = " ".join(str(e) for e in errs)
    text = f"{raw.get('result') or ''} {errs}".strip()
    if not raw and stderr_file and Path(stderr_file).exists():
        text = Path(stderr_file).read_text(errors="replace")[-4000:]
    kind = _classify(raw, rc, text)
    resets_at = None
    if kind == "rate_limited":
        stamp = parse_resets_at(text, tz=tz, now=now)
        resets_at = datetime.fromtimestamp(stamp, timezone.utc) if stamp is not None else None
    return Result(
        kind=kind,
        text=text,
        session_id=str(raw.get("session_id") or ""),
        cost_usd=float(raw.get("total_cost_usd") or 0.0),
        turns=int(raw.get("num_turns") or 0),
        resets_at=resets_at,
        raw_path=out_file,
    )


# ------------------------------------------------------------- reset time parsing
_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _zone(tz: str):
    """Return a time zone object; 'UTC' works even without the system zone files."""
    return timezone.utc if tz.upper() == "UTC" else ZoneInfo(tz)


# Borrowed from Phoenix 0.6.0 hands/claude.py:144-168 (default tz changed to UTC)
def parse_resets_at(text: str, tz: str = "UTC", now: float | None = None) -> float | None:
    """Return the limit reset time as epoch seconds, or None if the text has none.

    Bare clock times ("resets 3:45pm") are read in `tz` (the time zone of the
    machine that wrote the message) and always point to the future.
    """
    zone = _zone(tz)
    now_dt = datetime.fromtimestamp(now if now is not None else time.time(), zone)
    m = re.search(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?\s*(Z|UTC|[+-]\d{2}:?\d{2})?", text)
    if m:
        d, hh, mm, ss, z = m.groups()
        base = datetime.fromisoformat(f"{d}T{hh}:{mm}:{ss or '00'}")
        if z in ("Z", "UTC"):
            base = base.replace(tzinfo=timezone.utc)
        elif z:
            z = z.replace(":", "")
            base = datetime.fromisoformat(f"{d}T{hh}:{mm}:{ss or '00'}{z[:3]}:{z[3:]}")
        else:
            base = base.replace(tzinfo=zone)
        return base.timestamp()
    m = re.search(r"resets\s+(?:(mon|tue|wed|thu|fri|sat|sun)[a-z]*\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)", text, re.I)
    if not m:
        return None
    wd, h, mi, ap = m.groups()
    h = int(h) % 12 + (12 if ap.lower() == "pm" else 0)
    cand = now_dt.replace(hour=h, minute=int(mi or 0), second=0, microsecond=0)
    if wd:
        delta = (_WEEKDAYS.index(wd.lower()[:3]) - cand.weekday()) % 7
        cand += timedelta(days=delta)
    if cand <= now_dt:
        cand += timedelta(days=7 if wd else 1)
    return cand.timestamp()


# ------------------------------------------------------------- running a session
def read_env_file(path: Path) -> dict[str, str]:
    """Read KEY=VALUE lines from an env file (blank lines and # comments skipped)."""
    values: dict[str, str] = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


def secrets_from(env_files: list[Path]) -> list[str]:
    """Return the values in the env files that must never reach a log, longest first."""
    found: set[str] = set()
    for path in env_files:
        for value in read_env_file(path).values():
            if len(value) >= MIN_SECRET_LEN:
                found.add(value)
                found.add(json.dumps(value)[1:-1])    # the same value as it appears inside JSON text
    return sorted(found, key=len, reverse=True)


def redact(text: str, secrets: list[str]) -> str:
    """Replace every secret value in the text with [redacted]."""
    for secret in secrets:
        text = text.replace(secret, "[redacted]")
    return text


def start_local(cmd: list[str], cwd: Path, env_files: list[Path]) -> subprocess.Popen:
    """Start the command on this machine, with the env files' values added to its environment.

    This is the default starter, used by tests. Step 4 passes its own
    starter that runs the command with `docker run`.
    """
    env = dict(os.environ)
    for path in env_files:
        env.update(read_env_file(path))
    return subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _pump(stream, lines: queue.Queue) -> None:
    """Copy lines from a process pipe into a queue; put None at the end."""
    try:
        for line in iter(stream.readline, b""):
            lines.put(line)
    except (OSError, ValueError):
        pass
    finally:
        lines.put(None)


def stop(proc, grace_s: float = KILL_GRACE_S) -> None:
    """Stop a process: SIGINT, wait up to `grace_s` seconds, then SIGKILL."""
    if proc.poll() is not None:
        return
    try:
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=grace_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    except ProcessLookupError:
        pass


def _watch(proc, lines: queue.Queue, log, secrets: list[str],
           timeout_s: float, quiet_s: float) -> str | None:
    """Copy output lines to the log until the output ends.

    Returns None when the output ended by itself, "no_output" if no line came
    for `quiet_s` seconds, or "timed_out" if `timeout_s` seconds passed.
    """
    started = last = time.monotonic()
    while True:
        now = time.monotonic()
        if now - started >= timeout_s:
            return "timed_out"
        if now - last >= quiet_s:
            return "no_output"
        wait = min(timeout_s - (now - started), quiet_s - (now - last))
        try:
            line = lines.get(timeout=max(wait, 0.01))
        except queue.Empty:
            continue
        if line is None:
            return None
        last = time.monotonic()
        log.write(redact(line.decode("utf-8", errors="replace"), secrets).encode())
        log.flush()


def _save_stderr(stream, path: Path, secrets: list[str]) -> None:
    """Copy a process's stderr into a file, with secrets redacted."""
    try:
        data = stream.read()
    except (OSError, ValueError):
        return
    path.write_text(redact(data.decode("utf-8", errors="replace"), secrets))


def run(cmd: list[str], cwd: Path, env_files: list[Path], log_path: Path,
        timeout_min: float, no_output_timeout_min: float,
        start: Callable[[list[str], Path, list[Path]], subprocess.Popen] = start_local,
        grace_s: float = KILL_GRACE_S, tz: str = "UTC") -> Result:
    """Run one Claude session and return its Result.

    Every stdout line goes to `log_path` (values from the env files are
    redacted); stderr goes to `<log_path>.stderr`. If no line arrives for
    `no_output_timeout_min` minutes the process is stopped and the kind is
    `no_output`; if it runs longer than `timeout_min` minutes it is stopped
    and the kind is `timed_out`. `start(cmd, cwd, env_files)` starts the
    process and must give it stdout and stderr pipes.
    """
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path = log_path.with_name(log_path.name + ".stderr")
    secrets = secrets_from(env_files)
    proc = start(cmd, cwd, env_files)
    lines: queue.Queue = queue.Queue()
    out_thread = threading.Thread(target=_pump, args=(proc.stdout, lines), daemon=True)
    err_thread = threading.Thread(target=_save_stderr, args=(proc.stderr, stderr_path, secrets), daemon=True)
    out_thread.start()
    err_thread.start()
    with open(log_path, "wb") as log:
        stopped = _watch(proc, lines, log, secrets, timeout_min * 60, no_output_timeout_min * 60)
    if stopped:
        stop(proc, grace_s)
    rc = proc.wait()
    out_thread.join(timeout=5)
    err_thread.join(timeout=5)
    result = parse(log_path, rc, stderr_path, tz=tz)
    if stopped:
        result.kind = stopped
        result.resets_at = None
    return result


# ------------------------------------------------------------- usage limits
def wait_for_limit(result: Result, probe: Callable[[], Result], now: Callable[[], datetime],
                   sleep: Callable[[float], None] = time.sleep,
                   probe_min: float | None = None, max_wait_h: float | None = None) -> bool:
    """Wait out a usage limit. Return True when Claude can be used again, False to give up.

    If the result is not `rate_limited` there is nothing to wait for (True).
    With a known reset time: sleep until 2 minutes after it. Without one (or
    if it lies beyond the give-up time): call `probe()` every `probe_min`
    minutes until a probe comes back `ok`. Gives up after `max_wait_h` hours.
    `now()` returns the current time (aware datetime) and `sleep(seconds)`
    waits, so tests can use a fake clock. The caller must not count this
    wait as a try. Shape borrowed from Phoenix 0.6.0 hands/loop.py:973-997.
    """
    if result.kind != "rate_limited":
        return True
    settings = config.load() if probe_min is None or max_wait_h is None else {}
    probe_s = 60 * float(probe_min if probe_min is not None else settings["usage_probe_min"])
    deadline = now() + timedelta(hours=float(max_wait_h if max_wait_h is not None else settings["usage_max_wait_h"]))
    resets = result.resets_at
    while True:
        current = now()
        if current >= deadline:
            return False
        if resets is not None and current < resets + RESET_MARGIN <= deadline:
            sleep((resets + RESET_MARGIN - current).total_seconds())
            return True
        sleep(min(probe_s, (deadline - current).total_seconds()))
        if now() >= deadline:
            return False
        answer = probe()
        if answer.kind == "ok":
            return True
        if answer.kind == "rate_limited":
            resets = answer.resets_at


# ------------------------------------------------------------- usage records
def record_usage(run_id: str, result: Result, *, role: str = "", step=None, try_no=None) -> None:
    """Add one session's usage to the run's usage.jsonl and its cost to run.json.

    Every Claude session of a run is recorded (check writer, builder, usage
    probe); `role`, `step` and `try_no` say which one it was.
    """
    folder = run_dir(run_id)
    entry = {"at": now_iso(), "session_id": result.session_id, "kind": result.kind,
             "cost_usd": result.cost_usd, "turns": result.turns}
    if role:
        entry.update(role=role, step=step, try_no=try_no)
    with open(folder / "usage.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")
    record = load_run(run_id)
    record["cost_usd"] = round(float(record.get("cost_usd") or 0.0) + result.cost_usd, 6)
    save_run(record)
