"""Ops for logs: list the readable logs of a project and read one as scrubbed plain text (read-only)."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from phoenix9 import atomic, keys, paths, scrub
from phoenix9.ops import common
from phoenix9.ops.common import OpsError

MAX_BYTES = 2 * 1024 * 1024
RESULT_LINES = 20
SESSION_RE = re.compile(r"^(\d+)-(\d+)-([a-z0-9-]+)\.jsonl(\.stderr)?$")
ATTEMPT_RE = re.compile(r"^tasks/(\d+)/attempt-(\d+)/(checks\.txt|diff\.patch)$")
TASK_FILE_RE = re.compile(r"^tasks/(\d+)/task\.md$")
SERVICE_LOGS = ("api.log", "updater.log")


def _stamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")


def _entry(id_, kind, title, path, run=None, task=None, attempt=None, step=None) -> dict:
    return {"id": id_, "kind": kind, "run": run, "task": task, "attempt": attempt, "step": step,
            "title": title, "size": path.stat().st_size, "modified": _stamp(path)}


def _classify(rel: str, path: Path) -> dict | None:
    """kind, task, attempt, step and title for a file inside a run folder, or None when it is not a log."""
    name = Path(rel).name
    if rel.startswith("logs/"):
        found = SESSION_RE.match(name)
        if found and found.group(4):
            if path.stat().st_size == 0:
                return None
            where = f"task {found.group(1)}, attempt {found.group(2)}" if found.group(1) != "0" else "run step"
            return {"kind": "step", "task": int(found.group(1)), "attempt": int(found.group(2)),
                    "step": found.group(3), "title": f"{found.group(3)} errors ({where})"}
        if found:
            task, attempt, role = int(found.group(1)), int(found.group(2)), found.group(3)
            where = f"task {task}, attempt {attempt}" if task else "run step"
            return {"kind": "session", "task": task, "attempt": attempt, "step": role,
                    "title": f"{role} session ({where})"}
        if name.endswith(".log"):
            step = "delegate" if name.startswith("delegate-") else name[:-4]
            title = f"project chat hand-over ({name[9:-4]})" if step == "delegate" else f"{step} log"
            return {"kind": "step", "task": None, "attempt": None, "step": step, "title": title}
        return None
    found = ATTEMPT_RE.match(rel)
    if found:
        task, attempt, which = int(found.group(1)), int(found.group(2)), found.group(3)
        kind = "check" if which == "checks.txt" else "diff"
        title = f"{'checks' if kind == 'check' else 'changes'} (task {task}, attempt {attempt})"
        return {"kind": kind, "task": task, "attempt": attempt,
                "step": "acceptance" if kind == "check" else "builder", "title": title}
    found = TASK_FILE_RE.match(rel)
    if found:
        return {"kind": "task-file", "task": int(found.group(1)), "attempt": None, "step": None,
                "title": f"task file (task {found.group(1)})"}
    if rel == "repairs/report.md":
        return {"kind": "repair-report", "task": None, "attempt": None, "step": None, "title": "run report"}
    if rel.startswith("repairs/notes/") and name.endswith(".md"):
        return {"kind": "repair-note", "task": None, "attempt": None, "step": None,
                "title": f"repair note {name[:-3]}"}
    if rel.startswith("gates/") and name.endswith(".json") and not name.endswith(".answer.json"):
        gate = atomic.read_json(path) or {}
        return {"kind": "gate", "task": gate.get("task"), "attempt": None, "step": gate.get("step"),
                "title": gate.get("title") or name[:-5]}
    return None


def _run_entries(project: str, run_dir: Path) -> list[dict]:
    found = []
    for path in sorted(p for p in run_dir.rglob("*") if p.is_file() and not p.is_symlink()):
        rel = path.relative_to(run_dir).as_posix()
        info = _classify(rel, path)
        if info:
            found.append(_entry(f"{run_dir.name}/{rel}", info.pop("kind"), info.pop("title"), path,
                                run=run_dir.name, **info))
    return found


def _command_lines(project: str, path: Path) -> list[dict]:
    lines = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if isinstance(line, dict) and line.get("project") == project:
            lines.append(line)
    return lines


def _home_entries(project: str) -> list[dict]:
    found = []
    commands = paths.logs() / "commands.jsonl"
    if commands.is_file() and _command_lines(project, commands):
        found.append(_entry("logs/commands.jsonl", "command", "commands run on this project", commands))
    for name in SERVICE_LOGS:
        path = paths.logs() / name
        if path.is_file():
            found.append(_entry(f"logs/{name}", "service", f"{name[:-4]} log", path))
    return found


def list_(project: str, run: str | None = None, task: int | None = None, step: str | None = None,
          kind: str | None = None) -> list[dict]:
    """The logs of a project, newest run first; filters narrow by run, task, step and kind."""
    common.project_dir(project)
    root = paths.runs(project)
    found = []
    folders = sorted((p for p in root.iterdir() if p.is_dir()), reverse=True) if root.is_dir() else []
    for folder in folders:
        found += _run_entries(project, folder)
    found += _home_entries(project)
    wanted = {"run": run, "task": task, "step": step, "kind": kind}
    return [e for e in found if all(v is None or e[k] == v for k, v in wanted.items())]


def _resolve(project: str, id_: str) -> tuple[Path, str]:
    """The real file for a log id and its run-folder-relative name ('' for HOME logs); OpsError if outside."""
    refuse = OpsError("That log is not one Phoenix can show.")
    if not id_ or "\0" in id_:
        raise refuse
    home = paths.home().resolve()
    if id_.startswith("logs/"):
        base, target = (home / "logs").resolve(), (home / id_).resolve()
        rel = ""
    else:
        base = (paths.runs(project)).resolve()
        target = (base / id_).resolve()
        rel = id_.split("/", 1)[1] if "/" in id_ else ""
    if not target.is_relative_to(base) or target == base:
        raise refuse
    if not target.is_file():
        raise common.NotFound("There is no log with that id.")
    return target, rel


def _tail_text(path: Path) -> tuple[str, bool]:
    """The last MAX_BYTES of a file as text, and whether anything was cut off the front."""
    size = path.stat().st_size
    with open(path, "rb") as f:
        if size > MAX_BYTES:
            f.seek(size - MAX_BYTES)
            data = f.read()
            data = data[data.find(b"\n") + 1:]
        else:
            data = f.read()
    return data.decode("utf-8", errors="replace"), size > MAX_BYTES


def _first_lines(text: str, count: int = RESULT_LINES) -> str:
    lines = text.splitlines()
    more = f"\n... ({len(lines) - count} more lines)" if len(lines) > count else ""
    return "\n".join(lines[:count]) + more


def _block_text(content) -> str:
    """Plain text of a tool result's content (a string, or a list of text blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
    return ""


def _tool_summary(tool_input) -> str:
    if not isinstance(tool_input, dict):
        return str(tool_input)
    for key in ("command", "file_path", "path", "pattern", "description", "url"):
        if isinstance(tool_input.get(key), str):
            return tool_input[key]
    return json.dumps(tool_input)


def _render_message(event: dict) -> list[str]:
    """Readable lines for one assistant or user stream event."""
    content = (event.get("message") or {}).get("content", [])
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    who = "assistant" if event.get("type") == "assistant" else "user"
    out = []
    for block in content:
        kind = block.get("type") if isinstance(block, dict) else None
        if kind == "text":
            out.append(f"{who}: {block.get('text', '')}")
        elif kind == "tool_use":
            out.append(f"tool {block.get('name', '?')}: {_tool_summary(block.get('input'))}")
        elif kind == "tool_result":
            out.append("tool result: " + _first_lines(_block_text(block.get("content"))))
    return out


def render_session(text: str) -> str:
    """A Claude stream-json log as plain readable lines."""
    out = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except ValueError:
            out.append(raw)
            continue
        kind = event.get("type") if isinstance(event, dict) else None
        if kind == "system":
            out.append(f"session started ({event.get('model') or 'model unknown'})")
        elif kind in ("assistant", "user"):
            out += _render_message(event)
        elif kind == "result":
            out.append(f"result: {event.get('result', '')}")
        else:
            out.append(raw)
    return "\n".join(out) + ("\n" if out else "")


def render_gate(gate: dict, answer: dict | None) -> str:
    """A gate and its answer as a few readable lines."""
    text = f"Opened {gate.get('created', '?')}: {gate.get('title', '')}\nWhy: {gate.get('why', '')}\n"
    if answer and answer.get("action") == "closed":
        return text + f"Answer: closed: {answer.get('reason') or 'its run ended'} (by {answer.get('who')} at {answer.get('at')})\n"
    if answer:
        return text + (f"Answer: {answer.get('action')} by {answer.get('who')} at {answer.get('at')}: "
                       f"{answer.get('note', '')}\n")
    return text + "Answer: none yet\n"


def render_commands(project: str, path: Path) -> str:
    """This project's lines of the commands log as 'time · who · command'."""
    return "".join(f"{x.get('ts', '?')} · {x.get('who', '?')} · {x.get('command', '')}\n"
                   for x in _command_lines(project, path))


def _scrubber(project: str) -> scrub.Scrubber:
    """A scrubber holding the process-wide secrets, the global secret files and this project's keys."""
    files = sorted(p for p in paths.secrets().glob("*") if p.is_file()) if paths.secrets().is_dir() else []
    try:
        mine = keys.secret_values(project)
    except (OSError, ValueError):
        mine = []
    try:
        filed = scrub.secrets_from(files)
    except (OSError, UnicodeDecodeError):
        filed = []
    return scrub.Scrubber(scrub.known_secrets() + filed + mine)


def read(project: str, id_: str) -> dict:
    """One log as readable, scrubbed text: {id, kind, title, text, truncated, is_diff}."""
    common.project_dir(project)
    path, rel = _resolve(project, id_)
    info = _classify(rel, path) if rel else None
    if rel == "" and path.name == "commands.jsonl":
        info = {"kind": "command", "title": "commands run on this project"}
    elif rel == "":
        info = {"kind": "service", "title": f"{path.stem} log"}
    info = info or {"kind": "step", "title": path.name}
    text, truncated = _tail_text(path)
    if info["kind"] == "session":
        text = render_session(text)
    elif info["kind"] == "gate":
        answer = atomic.read_json(path.with_name(path.name[:-5] + ".answer.json"))
        text = render_gate(atomic.read_json(path) or {}, answer)
    elif info["kind"] == "command":
        text = render_commands(project, path)
    return {"id": id_, "kind": info["kind"], "title": info["title"], "text": _scrubber(project).text(text),
            "truncated": truncated, "is_diff": info["kind"] == "diff"}


list = list_
