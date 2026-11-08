"""The one place that builds, runs and reads a Claude Code session (always inside a step container).

- `build_command()` makes the `claude -p ...` command line from a step's ai block.
- `session_mounts()` / `write_mcp_config()` prepare the CLAUDE.md, skills, advisor and MCP files.
- `run()` starts it, copies every output line into a log file, and stops it if it goes quiet or runs long.
- `parse()` reads that log and decides what happened (`Result.kind`).
- `run_with_fallback()` tries the fallback models when a model is unavailable.
- `wait_for_limit()` waits out a usage limit; `record_usage()` saves a session's cost into the run.
"""
# ported from reference/v8/phoenix/claude.py
from __future__ import annotations

import json
import os
import queue
import re
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from phoenix9 import atomic, paths, pause, prices, state
from phoenix9.docker import Mount
from phoenix9.scrub import Scrubber, read_env_file, scrub

# The Claude Code tools Phoenix supports in `ai.tools` / `ai.tools_denied` (passed as-is to
# --allowedTools / --disallowedTools). Each is (name, plain label, one-line explanation).
SUPPORTED_TOOLS: list[tuple[str, str, str]] = [
    ("Read", "Read files", "Look at files in the project."),
    ("Edit", "Edit files", "Change parts of existing files."),
    ("Write", "Write files", "Create new files or replace whole files."),
    ("Glob", "Find files", "Find files by name pattern."),
    ("Grep", "Search inside files", "Search the text of the project's files."),
    ("Bash", "Run commands", "Run shell commands inside the step's container."),
    ("WebFetch", "Fetch web pages", "Download and read a web page."),
    ("WebSearch", "Search the web", "Search the internet."),
]

KINDS = ("ok", "error", "rate_limited", "model_unavailable", "crashed", "timed_out", "no_output")
KILL_GRACE_S = 30        # seconds between SIGINT and SIGKILL
RESET_MARGIN = timedelta(minutes=2)
DEFAULT_PROBE_MIN = 30   # minutes between probes while the reset time is unknown
DEFAULT_MAX_WAIT_H = 12  # give up waiting for a usage limit after this many hours
CLAUDE_HOME = "/home/node/.claude"       # inside the container
MCP_MOUNT = "/phoenix/mcp.json"
SYSTEM_PROMPT_MOUNT = "/phoenix/system.md"

# ported from reference/v8/phoenix/claude.py:12
RATE_LIMIT = re.compile(
    r"rate.?limit|usage limit|hit your (?:session |weekly |opus |sonnet |fable |individual )?(?:usage )?limit"
    r"|too many requests|\b429\b|limit reached|spend limit",
    re.I,
)
# "You've hit your limit · resets 3:45pm" counts as a limit even in a long or non-error result.
HIT_LIMIT = re.compile(r"hit your .*limit", re.I)
RESETS = re.compile(r"\bresets\b", re.I)

# Messages that mean "this model cannot be used" (not an account-wide limit). Checked only in short error text.
MODEL_UNAVAILABLE = re.compile(
    r"model[^.\n]{0,60}(?:not found|not available|unavailable|does not exist|do(?:es)? not have access|not supported)"
    r"|(?:not found|not available|unavailable|no access)[^.\n]{0,30}\bmodel\b"
    r"|invalid model|unknown model|issue with the selected model"
    r"|overloaded[^.\n]{0,60}\bmodel\b|\bmodel\b[^.\n]{0,60}overloaded"
    r"|not_found_error",
    re.I,
)


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
    model: str = ""                 # the model this session was started with (set by run_with_fallback)
    cost_known: bool = True         # False: no result line and no token counts, so the cost could not be worked out
    cost_estimated: bool = False    # True: cost worked out from the token counts (no trustworthy result line)


# ------------------------------------------------------------- command line
def build_command(ai: dict, prompt_file, cwd, system_prompt_file=None, mcp_config=None,
                  resume: str | None = None) -> list[str]:
    """Return the command that runs one Claude Code session, from a step's ai block.

    The prompt is fed in from `prompt_file` and the session runs in `cwd` (paths as seen where the
    command runs, i.e. inside the container). `mcp_config` is the in-container path of the MCP file
    (default /phoenix/mcp.json) and is only used when the ai block names MCP servers. `resume` is a
    Claude session id to continue (`--resume <id>`, used when a paused step starts again). Never `--bare`.
    """
    claude = ["claude", "-p", "--output-format", "stream-json", "--verbose"]
    if resume:
        if not pause.valid_session_id(str(resume)):
            raise ValueError("a session to continue must be named by its UUID")
        claude += ["--resume", str(resume)]
    if ai.get("model"):
        claude += ["--model", str(ai["model"])]
    claude += ["--max-turns", str(int(ai.get("max_turns") or 50))]
    if ai.get("tools"):
        claude += ["--allowedTools", ",".join(ai["tools"])]
    if ai.get("tools_denied"):
        claude += ["--disallowedTools", ",".join(ai["tools_denied"])]
    if ai.get("mcp_servers"):
        claude += ["--mcp-config", str(mcp_config or MCP_MOUNT)]
    if system_prompt_file:
        claude += ["--append-system-prompt-file", str(system_prompt_file)]
    # Safe only because the session runs inside the sealed container (docs/architecture.md section 11).
    claude += ["--permission-mode", "bypassPermissions"]
    assert "--bare" not in claude
    script = 'cd "$1" || exit 1; f="$2"; shift 2; exec "$@" < "$f"'
    return ["sh", "-c", script, "phoenix-claude", str(cwd), str(prompt_file)] + claude


def write_mcp_config(names: list[str], registry: dict, dest) -> Path:
    """Write the MCP servers named in `names` (looked up in `registry`) to `dest` as Claude's JSON file."""
    missing = [n for n in names if n not in registry]
    if missing:
        raise ValueError(f"unknown MCP server(s): {', '.join(missing)}")
    atomic.write_json(Path(dest), {"mcpServers": {n: registry[n] for n in names}})
    return Path(dest)


def _claude_md_mount(mode: str, step_dir: Path, project_dir: Path, tmp: Path) -> Mount | None:
    """The CLAUDE.md the session sees, for claude_md = library | project | both."""
    parts = []
    if mode in ("library", "both") and (Path(step_dir) / "CLAUDE.md").is_file():
        parts.append((Path(step_dir) / "CLAUDE.md").read_text())
    if mode in ("project", "both") and (Path(project_dir) / "code" / "CLAUDE.md").is_file():
        parts.append((Path(project_dir) / "code" / "CLAUDE.md").read_text())
    if not parts:
        return None
    joined = tmp / "CLAUDE.md"
    joined.write_text("\n\n".join(parts))
    return Mount(joined, f"{CLAUDE_HOME}/CLAUDE.md")


ADVISOR_NOTE = "Note: the advisor skill is not available in this setup; carry on without it."


def advisor_usable(skills_root=None) -> bool:
    """True when the advisor skill folder exists and `phoenix doctor` has not found it missing in Claude."""
    root = Path(skills_root) if skills_root else paths.library() / "skills"
    if not (root / "advisor").is_dir():
        return False
    try:
        info = atomic.read_json(paths.config() / "doctor.json", {})
    except (OSError, ValueError):
        info = {}
    return not (isinstance(info, dict) and info.get("advisor_available") is False)


def advisor_note(ai: dict, skills_root=None) -> str:
    """One line for the prompt when the step asks for the advisor but it cannot be mounted, else ''."""
    if (ai.get("advisor") or {}).get("on") and not advisor_usable(skills_root):
        return ADVISOR_NOTE
    return ""


def session_mounts(ai: dict, step_dir, project_dir, tmp_dir=None, skills_root=None) -> list[Mount]:
    """Return the read-only mounts a session needs: CLAUDE.md, skills, and the advisor skill plus advisor.json.

    Skills come from `skills_root` (default: the library's `skills/` folder) by name. Files that have to
    be made (the joined CLAUDE.md, advisor.json) go in `tmp_dir` (default: a new temp folder).
    """
    step_dir, project_dir = Path(step_dir), Path(project_dir)
    tmp = Path(tmp_dir) if tmp_dir else Path(tempfile.mkdtemp(prefix="phoenix-session-"))
    tmp.mkdir(parents=True, exist_ok=True)
    root = Path(skills_root) if skills_root else paths.library() / "skills"
    mounts: list[Mount] = []
    md = _claude_md_mount(ai.get("claude_md") or "library", step_dir, project_dir, tmp)
    if md:
        mounts.append(md)
    for name in ai.get("skills") or []:
        if "/" in name or name.startswith("."):
            raise ValueError(f"bad skill name: {name}")
        mounts.append(Mount(root / name, f"{CLAUDE_HOME}/skills/{name}"))
    advisor = ai.get("advisor") or {}
    if advisor.get("on") and advisor_usable(root):
        info = tmp / "advisor.json"
        atomic.write_json(info, {"model": advisor.get("model", ""), "when": list(advisor.get("when") or []),
                                 "instructions": advisor.get("instructions", "")})
        mounts.append(Mount(root / "advisor", f"{CLAUDE_HOME}/skills/advisor"))
        mounts.append(Mount(info, f"{CLAUDE_HOME}/skills/advisor.json"))
    return mounts


# ------------------------------------------------------------- reading the result
MAX_LINE = 5_000_000


# ported from reference/v8/phoenix/claude.py:67
def _read_result(out_file: Path) -> dict:
    """Return the session's final result object, or {} if it cannot be trusted.

    The LAST non-empty line must be valid JSON with type "result". Normally it is the only result line.
    Claude Code also writes one result line per turn when a session takes more than one turn (e.g. a
    background command finishes after the first answer); then EVERY result line must carry an integer
    `result_index`, the indexes must be 0, 1, 2... in file order, all with the same session_id, and the
    last line must be the last of them. Anything else (none, cut off, garbled, out of order, or an extra
    result line without an index) gives {}.
    """
    results, last = [], b""
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
                            results.append(o)
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
    if not (isinstance(obj, dict) and obj.get("type") == "result") or not results:
        return {}
    if len(results) == 1:
        return obj
    indexes = [r.get("result_index") for r in results]
    sessions = {r.get("session_id") for r in results}
    if (all(type(i) is int for i in indexes) and indexes == list(range(len(results)))
            and len(sessions) == 1 and obj.get("result_index") == len(results) - 1):
        return obj
    return {}


def session_id_in_log(out_file) -> str:
    """The session id Claude printed when the session started (first line that has one), else ''.

    Lets a session cut short (Pause now) still be continued later: it never wrote a result line."""
    try:
        with open(out_file, "rb") as f:
            for line in f:
                if b'"session_id"' not in line or len(line) > MAX_LINE:
                    continue
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, UnicodeError):
                    continue
                if isinstance(obj, dict) and obj.get("session_id"):
                    return str(obj["session_id"])
    except OSError:
        pass
    return ""


def estimate_cost(out_file, model: str = "") -> float | None:
    """Work out a session's cost from the token counts in its stream log, or None when it has none.

    Used when there is no trustworthy result line (Pause now, a timeout, a crash). Every assistant message
    carries a `usage` block; one message is written as several lines (one per content block) with the same
    id, so each message id is counted once, with its largest numbers. A resumed session's reloaded context
    is in the input and cache numbers of its first messages, so it is counted too. Prices come from
    phoenix9/prices.py, by the message's own model (else `model`, else the most expensive known)."""
    seen: dict[str, tuple[str, dict]] = {}
    found = False
    try:
        with open(out_file, "rb") as f:
            for i, line in enumerate(f):
                if b'"usage"' not in line or len(line) > MAX_LINE:
                    continue
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, UnicodeError):
                    continue
                if not isinstance(obj, dict) or obj.get("type") != "assistant":
                    continue
                msg = obj.get("message")
                if not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict):
                    continue
                found = True
                key = str(msg.get("id") or f"line-{i}")
                usage = msg["usage"]
                old = seen.get(key)
                if old is not None:
                    usage = {k: max(_num(old[1].get(k)), _num(usage.get(k)))
                             for k in set(old[1]) | set(usage)}
                seen[key] = (str(msg.get("model") or model or ""), usage)
    except OSError:
        return None
    if not found:
        return None
    return round(sum(prices.cost(m, u) for m, u in seen.values()), 6)


def _num(v) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def _is_rate_limited(raw: dict, text: str) -> bool:
    """Return True if the result says a usage limit was hit (general words only count in short error text)."""
    if HIT_LIMIT.search(text) and RESETS.search(text):
        return True
    if str(raw.get("api_error_status") or "") == "429":
        return True
    return bool(raw.get("is_error")) and len(text) <= 600 and bool(RATE_LIMIT.search(text))


def _is_model_unavailable(raw: dict, text: str) -> bool:
    """Return True if a short error result says the chosen model cannot be used."""
    return bool(raw.get("is_error")) and len(text) <= 600 and bool(MODEL_UNAVAILABLE.search(text))


def _classify(raw: dict, rc: int, text: str) -> str:
    """Decide the kind of a finished session from its result object and exit code."""
    if not raw:
        return "crashed"
    if _is_rate_limited(raw, text):
        return "rate_limited"
    if _is_model_unavailable(raw, text):
        return "model_unavailable"
    if rc == 0 and not raw.get("is_error"):
        return "ok"
    return "error"


def parse(out_file: Path, rc: int = 0, stderr_file: Path | None = None,
          now: float | None = None, tz: str = "UTC", model: str = "") -> Result:
    """Read a stream-json log and return what the session ended with.

    Only the single final `type: result` line counts; no result, an extra result line or a cut-off
    log is `crashed`. `now` and `tz` are used to read a reset time like "resets 3:45pm".
    The cost is the result line's total; without one it is worked out from the log's token counts
    (`estimate_cost`, priced by `model` when a message names none), or marked unknown (`cost_known`).
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
    total = raw.get("total_cost_usd")
    cost, known, estimated = 0.0, True, False
    if isinstance(total, (int, float)) and not isinstance(total, bool) and total >= 0:
        cost = float(total)
    else:                       # no trustworthy result line: work it out from the token counts
        guess = estimate_cost(out_file, model)
        estimated = guess is not None
        cost, known = (guess, True) if guess is not None else (0.0, False)
    return Result(kind=kind, text=text, session_id=str(raw.get("session_id") or ""),
                  cost_usd=cost, turns=int(raw.get("num_turns") or 0),
                  resets_at=resets_at, raw_path=out_file, cost_known=known, cost_estimated=estimated)


# ------------------------------------------------------------- reset time parsing
_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _zone(tz: str):
    """Return a time zone object; 'UTC' works even without the system zone files."""
    return timezone.utc if tz.upper() == "UTC" else ZoneInfo(tz)


# ported from reference/v8/phoenix/claude.py:144
def parse_resets_at(text: str, tz: str = "UTC", now: float | None = None) -> float | None:
    """Return the limit reset time as epoch seconds, or None if the text has none.

    Bare clock times ("resets 3:45pm") are read in `tz` and always point to the future.
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
    m = re.search(r"resets\s+(?:(mon|tue|wed|thu|fri|sat|sun)[a-z]*\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)",
                  text, re.I)
    if not m:
        return None
    wd, h, mi, ap = m.groups()
    h = int(h) % 12 + (12 if ap.lower() == "pm" else 0)
    cand = now_dt.replace(hour=h, minute=int(mi or 0), second=0, microsecond=0)
    if wd:
        cand += timedelta(days=(_WEEKDAYS.index(wd.lower()[:3]) - cand.weekday()) % 7)
    if cand <= now_dt:
        cand += timedelta(days=7 if wd else 1)
    return cand.timestamp()


# ------------------------------------------------------------- running a session
def start_local(cmd: list[str], cwd: Path, env_files: list[Path]) -> subprocess.Popen:
    """Start the command on this machine with the env files' values added (used by tests)."""
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


def _watch(proc, lines: queue.Queue, log, scrubber: Scrubber, timeout_s: float, quiet_s: float) -> str | None:
    """Copy output lines to the log until the output ends.

    Returns None when the output ended by itself, "no_output" if no line came for `quiet_s` seconds,
    or "timed_out" if `timeout_s` seconds passed.
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
        log.write(scrubber.text(line.decode("utf-8", errors="replace")).encode())
        log.flush()


def _save_stderr(stream, path: Path, scrubber: Scrubber) -> None:
    """Copy a process's stderr into a file, with secrets removed."""
    try:
        data = stream.read()
    except (OSError, ValueError):
        return
    path.write_text(scrubber.text(data.decode("utf-8", errors="replace")))


def run(cmd: list[str], cwd: Path, env_files: list[Path], log_path: Path,
        timeout_min: float, no_output_timeout_min: float,
        start: Callable[[list[str], Path, list[Path]], subprocess.Popen] = start_local,
        grace_s: float = KILL_GRACE_S, tz: str = "UTC", secrets: list[str] | None = None) -> Result:
    """Run one Claude session and return its Result.

    Every stdout line goes to `log_path` (values from the env files and `secrets` are replaced by
    [secret]); stderr goes to `<log_path>.stderr`. If no line arrives for `no_output_timeout_min`
    minutes the process is stopped (kind `no_output`); if it runs longer than `timeout_min` minutes
    it is stopped (kind `timed_out`). `start(cmd, cwd, env_files)` starts the process with pipes.
    """
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path = log_path.with_name(log_path.name + ".stderr")
    scrubber = Scrubber.from_env_files(env_files)
    scrubber.add(secrets or [])
    proc = start(cmd, cwd, env_files)
    lines: queue.Queue = queue.Queue()
    out_thread = threading.Thread(target=_pump, args=(proc.stdout, lines), daemon=True)
    err_thread = threading.Thread(target=_save_stderr, args=(proc.stderr, stderr_path, scrubber), daemon=True)
    out_thread.start()
    err_thread.start()
    with open(log_path, "wb") as log:
        stopped = _watch(proc, lines, log, scrubber, timeout_min * 60, no_output_timeout_min * 60)
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


def run_with_fallback(ai: dict, launch: Callable[[str], Result]) -> Result:
    """Run `launch(model)` with the ai block's model, then each fallback model while it is unavailable.

    Only a `model_unavailable` result moves on to the next model. Every other result, including
    `rate_limited`, is returned as is: account-wide limits pause the run, they never switch model.
    """
    models = [m for m in [ai.get("model"), *(ai.get("fallback_models") or [])] if m]
    result = Result(kind="error", text="no model configured")
    spent, known = 0.0, True               # what the tries before this one cost (counted on the last result)
    for model in models:
        result = launch(model)
        result.model = model
        result.cost_usd = round(result.cost_usd + spent, 6)
        result.cost_known = result.cost_known and known
        if result.kind != "model_unavailable":
            return result
        spent, known = result.cost_usd, result.cost_known
    return result


# ------------------------------------------------------------- usage limits
def wait_for_limit(result: Result, probe: Callable[[], Result], now: Callable[[], datetime],
                   sleep: Callable[[float], None] = time.sleep,
                   probe_min: float = DEFAULT_PROBE_MIN, max_wait_h: float = DEFAULT_MAX_WAIT_H) -> bool:
    """Wait out a usage limit. Return True when Claude can be used again, False to give up.

    Not `rate_limited`: nothing to wait for (True). With a known reset time: sleep until 2 minutes
    after it. Without one (or beyond the give-up time): call `probe()` every `probe_min` minutes until
    a probe comes back `ok`. Gives up after `max_wait_h` hours. `now()` gives an aware datetime and
    `sleep(seconds)` waits, so tests can use a fake clock. The caller must not count this as a try.
    """
    if result.kind != "rate_limited":
        return True
    probe_s = 60 * float(probe_min)
    deadline = now() + timedelta(hours=float(max_wait_h))
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
def record_usage(run_dir, result: Result, attempt_dir=None) -> None:
    """Add one session to the run's state.json `usage` and, if given, write the attempt's result.json."""
    known = getattr(result, "cost_known", True)

    def change(s):
        usage = s.setdefault("usage", {"cost_usd": 0.0, "sessions": 0})
        usage["cost_usd"] = round(float(usage.get("cost_usd") or 0.0) + result.cost_usd, 6)
        usage["sessions"] = int(usage.get("sessions") or 0) + 1
        if getattr(result, "cost_estimated", False):
            usage["estimated_sessions"] = int(usage.get("estimated_sessions") or 0) + 1
        if not known:           # the spending cap asks Alex instead of counting this session as $0
            usage["unknown_cost_sessions"] = int(usage.get("unknown_cost_sessions") or 0) + 1
    state.update(Path(run_dir), change)
    if attempt_dir is not None:
        atomic.write_json(Path(attempt_dir) / "result.json", {
            "at": state.now(), "kind": result.kind, "model": result.model, "session_id": result.session_id,
            "cost_usd": result.cost_usd, "cost_known": known,
            "cost_estimated": bool(getattr(result, "cost_estimated", False)), "turns": result.turns, "text": scrub(result.text)[-2000:],
            "resets_at": result.resets_at.isoformat() if result.resets_at else None})
