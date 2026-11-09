"""Planning sessions: records in HOME/plans/<id>.json, the prompts, and reading what a session wrote."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import atomic, events, paths, runs, settings

BUSY = ("running",)
DEFAULT_MODEL = "claude-fable-5-1"
QUESTION = re.compile(r"^\s*\d+[.)]\s")
ANSWER = re.compile(r"^\s*Answer:\s*(.*)$")


class PlanError(Exception):
    """A planning session was refused or could not be done; the message is plain words."""


def plans_dir() -> Path:
    """The folder holding every planning session's record and output."""
    return paths.home() / "plans"


def record_file(plan_id: str) -> Path:
    """The record file of one planning session."""
    return plans_dir() / f"{plan_id}.json"


def session_file(plan_id: str) -> Path:
    """The stream-json output of one planning session."""
    return plans_dir() / plan_id / "session.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def plan_model() -> str:
    """The model for planning sessions (setting plan.model, default claude-fable-5-1)."""
    table = settings.read_global().get("plan")
    value = table.get("model") if isinstance(table, dict) else None
    return value if isinstance(value, str) and value else DEFAULT_MODEL


def load(plan_id: str) -> dict:
    """Read one planning session's record; PlanError when there is none."""
    data = atomic.read_json(record_file(plan_id)) if re.fullmatch(r"[a-z0-9][a-z0-9-]*", plan_id or "") else None
    if not data:
        raise PlanError(f"There is no planning session called '{plan_id}'.")
    return data


def save(rec: dict) -> None:
    """Write a record."""
    atomic.write_json(record_file(rec["id"]), rec)


def list_plans(project: str | None = None) -> list[dict]:
    """Planning sessions (one project or all), newest first."""
    found = []
    for f in sorted(plans_dir().glob("*.json")) if plans_dir().is_dir() else []:
        rec = atomic.read_json(f)
        if rec and (not project or rec.get("project") == project):
            found.append(rec)
    return sorted(found, key=lambda r: (r["started"], r["id"]), reverse=True)


def running(project: str) -> dict | None:
    """The running planning session of a project, or None."""
    return next((r for r in list_plans(project) if r["status"] in BUSY), None)


def new_record(project: str, brief: str, model: str, who: str) -> dict:
    """Make and save the record of a new planning session; refuse when the project has one running."""
    brief = (brief or "").strip()
    if not brief:
        raise PlanError("Say what to plan (--brief).")
    if not (paths.projects() / project).is_dir():
        raise PlanError(f"There is no project called '{project}'.")
    cur = running(project)
    if cur:
        raise PlanError(f"{project} already has a planning session running ({cur['id']}).")
    now = datetime.now(timezone.utc)
    base, plan_id, n = f"{now:%Y%m%d}-{runs.slugify(brief, 30)}", None, 1
    plan_id = base
    while record_file(plan_id).exists():
        n += 1
        plan_id = f"{base}-{n}"
    rec = {"id": plan_id, "project": project, "brief": brief, "model": model, "started": _now(), "who": who,
           "status": "running", "session_id": None, "spec": None, "open_questions": None, "report": "",
           "last_activity": _now()}
    save(rec)
    events.emit("plan.started", project=project, plan=plan_id, model=model, who=who)
    return rec


def start_prompt(brief: str) -> str:
    """The first prompt: read the project, write the spec, keep questions in it."""
    return (
        "You are planning, not building. Read this project's CLAUDE.md and its notes/ folder first. Then write "
        "or update a spec in notes/specs/ in the harness spec format (docs/architecture.md section 6 of Phoenix 9). "
        "Check it with `phoenix spec check <file>` and fix every problem.\n"
        "Keep your questions IN the spec: an `## Open questions` section, one numbered question per line with "
        "your recommended answer, each followed by an `Answer:` line left empty. Do not ask in chat.\n"
        "Do not change code. When done, end with one line: `PLAN REPORT: <spec path>, <n> open questions`.\n\n"
        f"What to plan:\n{brief}\n")


CONTINUE_PROMPT = (
    "Alex or the agent has filled in `Answer:` lines in the spec's `## Open questions` section. Read the answers, "
    "update the spec, and move answered questions into a `## Decisions` section. Check it again with `phoenix "
    "spec check <file>`. Leave unanswered questions in `## Open questions` with an empty `Answer:` line. "
    "End with one line: `PLAN REPORT: <spec path>, <n> open questions`.")


def build_argv(model: str, prompt: str, session_id: str | None = None) -> list[str]:
    """The claude command line of a planning session (a new one, or --resume of the same one)."""
    argv = ["claude", "-p", "--model", model, "--output-format", "stream-json", "--verbose",
            "--permission-mode", "bypassPermissions"]
    if session_id:
        argv += ["--resume", session_id]
    return argv + [prompt]


def read_session(plan_id: str) -> tuple[str | None, str]:
    """(session id, final result text) read from the session's stream-json output."""
    sid, text = None, ""
    f = session_file(plan_id)
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines() if f.exists() else []:
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        sid = obj.get("session_id") or sid
        if obj.get("type") == "result" and isinstance(obj.get("result"), str):
            text = obj["result"]
    return sid, text


def count_open(spec_text: str) -> int:
    """The number of questions under '## Open questions' whose Answer: line is empty."""
    in_section, pending, open_n = False, False, 0
    for line in spec_text.splitlines():
        if line.startswith("## "):
            in_section = line[3:].strip().lower() == "open questions"
            pending = False
            continue
        if not in_section:
            continue
        if QUESTION.match(line):
            pending = True
            continue
        m = ANSWER.match(line)
        if m and pending:
            open_n += 0 if m.group(1).strip() else 1
            pending = False
    return open_n


def find_spec(text: str) -> str | None:
    """The spec path named in the session's report line, or None."""
    m = re.search(r"PLAN REPORT:\s*(\S+?),?\s+(\d+)\s+open", text or "")
    return m.group(1) if m else None


def settle(rec: dict, rc: int) -> dict:
    """Read the finished session's files and set the record's status: failed, waiting (open questions) or done."""
    sid, text = read_session(rec["id"])
    rec["session_id"] = sid or rec.get("session_id")
    rec["last_activity"] = _now()
    spec = find_spec(text)
    root = (paths.projects() / rec["project"]).resolve()
    spec_file = (root / spec).resolve() if spec else None
    if spec_file and not spec_file.is_relative_to(root):
        spec_file = None
    if rc != 0 or not rec["session_id"]:
        rec.update(status="failed", report=(text or f"claude exit {rc}").strip()[-300:])
    else:
        rec["spec"] = spec
        n = count_open(spec_file.read_text(encoding="utf-8", errors="replace")) if spec_file and spec_file.is_file() else 0
        rec.update(open_questions=n, status="waiting" if n else "done",
                   report=f"{spec or 'no spec'}, {n} open questions")
    save(rec)
    events.emit(f"plan.{rec['status']}", project=rec["project"], plan=rec["id"], spec=rec.get("spec"),
                open_questions=rec.get("open_questions"))
    return rec
