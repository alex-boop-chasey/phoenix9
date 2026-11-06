"""Demo data: four projects, five runs, two open questions, written straight into a Phoenix home and projects folder.

Used by the demo server, the browser tests and the screenshots. Everything has fixed times, so it looks the
same every time. It never calls the real project-creation code (that switches real services on).

    python3 tests/seed_demo.py <home> <projects>
"""
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phoenix9 import atomic, gates, git, keys, paths, resolve, runs, settings, spec, state  # noqa: E402
from phoenix9.library import load_library  # noqa: E402

MARKER = ".phoenix-demo"
REAL_FOLDERS = ("/srv/projects", "/var/lib/phoenix9")

SECRET_KEY_VALUE = "re_demo_0123456789abcdef"
PUBLIC_URL = "https://demo-site.example.test"
SERVICES_CONNECTED_AT = "2026-10-30T09:00:00+00:00"   # fixed, like every other demo time

PROJECTS = {
    "demo-site": {"repo": "rebirth-wd/demo-site", "profile": "web", "preset": "full", "merge": "ask",
                  "deploy": "vps-docker",
                  "about": "A small marketing site for a pretend bakery: home, menu, contact form.",
                  "chat": {"chat_session_url": "https://claude.ai/code/session_demo_site"},
                  "spec": ("Contact form", [
                      ("Contact form markup", "Add a contact form with name, email and message.", "no", ["pnpm test"],
                       ["The form shows name, email and message fields"]),
                      ("Send the message", "Post the form to the mail service.", "no", ["pnpm test"],
                       ["A message is sent when the form is submitted"]),
                      ("Thank-you page", "Show a thank-you page after sending.", "no", ["pnpm build"],
                       ["The thank-you page is shown after a send"])])},
    "tiny-tool": {"repo": "alex-boop-chasey/tiny-tool", "profile": "python-script", "preset": "simple",
                  "about": "A tiny command line tool that tidies CSV files.",
                  "chat": {"environment_id": "env_demo_tiny_tool"},
                  "spec": ("Add JSON output", [
                      ("Read the CSV", "Read a CSV file into rows.", "no", ["python3 -m pytest"],
                       ["A CSV file is read into rows with headers"]),
                      ("Write JSON", "Write the rows out as JSON.", "no", ["python3 -m pytest"],
                       ["The JSON output has one object per row"]),
                      ("Add a flag", "Add --json to choose the output.", "no", ["python3 -m pytest"],
                       ["The --json flag switches the output format"]),
                      ("Update the help", "Describe --json in the help text.", "no", ["python3 -m pytest"],
                       ["The help text mentions the --json flag"])])},
    "notes-only": {"repo": "", "profile": "research", "preset": None,
                   "about": "Reading notes and ideas; no code yet.", "chat": {},
                   "spec": ("Reading plan", [
                       ("Collect sources", "List the articles to read.", "yes", [],
                        ["The list has at least ten articles with links"])])},
    "ember-oak": {"repo": "rebirth-wd/ember-oak", "profile": "web", "preset": "full", "merge": "ask",
                  "about": "Furniture maker portfolio with a gallery and enquiry form.", "chat": {},
                  "spec": ("Gallery page", [
                      ("Gallery grid", "Show the photos in a grid.", "no", ["pnpm test"],
                       ["The gallery shows every photo in a grid"]),
                      ("Enquiry form", "Add an enquiry form.", "no", ["pnpm test"],
                       ["The enquiry form sends a message"])])},
    "railway-hotel": {"repo": "rebirth-wd/railway-hotel", "profile": "web", "preset": "quick", "merge": "auto",
                      "about": "Country hotel site with rooms, rates and bookings.", "chat": {},
                      "spec": ("Rooms page", [
                          ("Rooms list", "List the rooms and rates.", "no", ["pnpm test"],
                           ["The rooms page lists every room with its rate"])])},
    "phoenix9": {"repo": "alex-boop-chasey/phoenix9", "profile": "platform", "preset": "full", "merge": "ask",
                 "about": "Phoenix 9 itself: the project manager and build harness.",
                 "chat": {"environment_id": "env_demo_phoenix9"},
                 "spec": ("API and dashboard", [
                     ("API reads", "Add the read endpoints.", "no", ["python3 -m pytest"],
                      ["Every read endpoint returns the documented shape"]),
                     ("API writes", "Add the write endpoints.", "no", ["python3 -m pytest"],
                      ["Every write endpoint checks the request body"]),
                     ("Events stream", "Add the live events stream.", "no", ["python3 -m pytest"],
                      ["The stream sends new events as they are written"])])},
}

CHANGELOG = {
    "demo-site": ["created from the bakery template", "added the menu page", "added the contact form spec",
                  "set the merge question to ask", "connected the mail service"],
    "tiny-tool": ["created from an empty folder", "added the first CSV reader", "chose the simple preset",
                  "wrote the JSON output spec", "fixed the header row bug"],
    "notes-only": ["created for reading notes", "added the reading plan", "listed the first sources",
                   "noted two open questions", "tidied the notes"],
    "ember-oak": ["created from the portfolio template", "added the gallery spec", "chose the full preset",
                  "set the merge question to ask", "added the enquiry form spec"],
    "railway-hotel": ["created from a copy of a GitHub repo", "added the rooms spec", "chose the quick preset",
                      "set the merge rule to automatic", "tidied the notes"],
    "phoenix9": ["created the project", "chose the platform profile", "wrote the API spec",
                 "set the merge question to ask", "added the demo data"],
}

# Runs: project, id, spec title, status, per-task (status, tries, flagged), created, finished (or None)
RUNS = [
    {"project": "demo-site", "id": "20261020-090000-contact-form", "status": "done", "created": "2026-10-20T09:00:00+00:00",
     "finished": "2026-10-20T09:14:00+00:00", "tasks": [("passed", 1, ""), ("passed", 2, ""), ("passed", 1, "")],
     "cost": 1.23, "sessions": 9, "gate": "answered"},
    {"project": "demo-site", "id": "20261022-140000-blog-section", "status": "failed", "created": "2026-10-22T14:00:00+00:00",
     "finished": "2026-10-22T14:21:00+00:00", "title": "Blog section",
     "tasks": [("passed", 1, ""), ("failed", 3, "the checks still failed after 3 tries"), ("skipped", 0, "")],
     "cost": 2.04, "sessions": 8},
    {"project": "demo-site", "id": "20261031-100000-pricing-page", "status": "waiting", "created": "2026-10-31T10:00:00+00:00",
     "finished": None, "title": "Pricing page",
     "tasks": [("passed", 1, ""), ("waiting", 3, "the checks still failed after 3 tries"), ("pending", 0, "")],
     "cost": 1.67, "sessions": 7, "gate": "escalation"},
    {"project": "phoenix9", "id": "20261031-110000-api-and-dashboard", "status": "waiting",
     "created": "2026-10-31T11:00:00+00:00", "finished": None,
     "tasks": [("passed", 1, ""), ("passed", 1, ""), ("passed", 2, "")], "cost": 3.4, "sessions": 12, "gate": "merge"},
    {"project": "ember-oak", "id": "20261102-090000-gallery-page", "status": "failed",
     "created": "2026-11-02T09:00:00+00:00", "finished": "2026-11-02T09:20:00+00:00", "title": "Gallery page",
     "tasks": [("passed", 1, ""), ("failed", 3, "the checks still failed after 3 tries")], "cost": 1.9, "sessions": 6},
    {"project": "tiny-tool", "id": "20261101-080000-add-json-output", "status": "running",
     "created": "2026-11-01T08:00:00+00:00", "finished": None,
     "tasks": [("passed", 1, ""), ("running", 1, ""), ("pending", 0, ""), ("pending", 0, "")],
     "cost": 0.41, "sessions": 3},
]


def _check_folder(folder: Path, what: str) -> None:
    """Refuse the real server folders and any non-empty folder that is not a demo folder."""
    real = [Path(x).resolve() for x in REAL_FOLDERS]
    if folder.resolve() in real or any(r in folder.resolve().parents for r in real):
        raise ValueError(f"Refusing to seed {what} {folder}: that is a real Phoenix folder.")
    if folder.is_dir() and any(folder.iterdir()) and not (folder / MARKER).is_file():
        raise ValueError(f"Refusing to empty {what} {folder}: it is not empty and has no {MARKER} marker.")


def _empty(folder: Path) -> None:
    """Remove everything inside a folder (making it when missing)."""
    folder.mkdir(parents=True, exist_ok=True)
    for child in folder.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def is_empty(folder) -> bool:
    """True when the folder is missing or has nothing in it."""
    folder = Path(folder)
    return not folder.is_dir() or not any(folder.iterdir())


def spec_text(project: str, title: str, tasks: list, preset: str | None) -> str:
    """A valid spec in the architecture section 6 format."""
    lines = [f"# {title}", f"Project: {project}"]
    if preset:
        lines.append(f"Preset: {preset}")
    lines += ["", "## About", f"{title} for {project}.", ""]
    for n, (name, goal, for_you, commands, plain) in enumerate(tasks, start=1):
        lines += [f"## Task {n}: {name}", goal, "Depends on: none" if n == 1 else f"Depends on: {n - 1}",
                  f"For you: {for_you}", "Done when:"]
        lines += [f"- `{c}`" for c in commands] + [f"- {p}" for p in plain] + [""]
    return "\n".join(lines)


def _write_project(name: str, data: dict) -> Path:
    """The project folder: CLAUDE.md, notes, phoenix.toml, project.json and an empty code/ repo."""
    folder = paths.projects() / name
    (folder / "notes" / "specs").mkdir(parents=True)
    atomic.write_text(folder / "CLAUDE.md", f"# {name}\n\n{data['about']}\n\n- Code: code/\n- Repo: "
                      f"{data['repo'] or '(none yet)'}\n- Profile: {data['profile']}\n\n@notes/NOW.md\n")
    atomic.write_text(folder / "notes" / "NOW.md", f"# Now ({name})\n\n- 2026-10-30: demo project.\n")
    lines = "".join(f"- 2026-10-{15 + i} · chat · {words}\n" for i, words in enumerate(CHANGELOG[name]))
    atomic.write_text(folder / "notes" / "changelog.md", f"# Changelog ({name})\n\n{lines}")
    title, tasks = data["spec"]
    text = spec_text(name, title, tasks, data["preset"])
    atomic.write_text(folder / "notes" / "specs" / f"{runs.slugify(title)}.md", text)
    toml = {"profile": data["profile"]}
    if data["preset"]:
        toml["preset"] = data["preset"]
    if data.get("merge"):
        toml["merge"] = data["merge"]
    if data.get("deploy"):
        toml["deploy"] = {"with": data["deploy"]}
    settings.save_project(folder, toml)
    meta = {"profile": data["profile"], **data["chat"]}
    if data["repo"]:
        meta["repo"] = data["repo"]
    atomic.write_json(folder / ".phoenix" / "project.json", meta)
    (folder / "code").mkdir()
    git.git(folder / "code", "init", "-q", "-b", "main")
    return folder


# ---------------------------------------------------------------------------------------------- runs

def _plan_and_settings(folder: Path, overrides: dict | None = None) -> tuple[dict, dict]:
    """(plan.json, settings.json) bodies for a project's effective settings."""
    lib = load_library(paths.library())
    eff = settings.effective(folder, lib, overrides)
    plan = resolve.resolve(lib, settings.enabled_map(eff)).to_json()
    return plan, eff.values


def _at(created: str, minutes: int) -> str:
    """created plus some minutes, as the same kind of ISO string."""
    from datetime import datetime, timedelta
    return (datetime.fromisoformat(created) + timedelta(minutes=minutes)).isoformat(timespec="seconds")


def _line(group, task, step, status, attempt=None, note="", at="") -> dict:
    return {"group": group, "task": task, "step": step, "status": status,
            "started": at if status != "pending" else None,
            "finished": at if status in ("passed", "failed", "skipped") else None, "note": note,
            **({"attempt": attempt} if attempt is not None else {})}


def _task_lines(plan: dict, n: int, status: str, tries: int, at: str) -> list:
    """Step lines of one task: finished tasks all passed, a stuck one fails at the Builder."""
    names = plan["groups"]["task"]
    attempt = max(tries, 1)
    if status == "passed":
        return [_line("task", n, s, "passed", attempt, at=at) for s in names]
    lines = []
    for s in names:
        if s == "builder":
            lines.append(_line("task", n, s, "running" if status == "running" else "failed", attempt,
                               "" if status == "running" else "the checks failed", at))
            break
        lines.append(_line("task", n, s, "passed", attempt, at=at))
    return lines


def _finish_lines(plan: dict, run: dict, at: str) -> list:
    """Step lines of the run-finish group for this run's status."""
    names = plan["groups"]["run-finish"]
    status = run["status"]
    lines = []
    for s in names:
        if status == "done":
            lines.append(_line("run-finish", None, s, "passed", at=at))
        elif status == "failed":
            lines.append(_line("run-finish", None, s, "skipped", note="the run failed", at=at))
        elif status == "waiting" and run.get("gate") == "merge" and s == "merge":
            lines.append(_line("run-finish", None, s, "waiting", at=at))
            break
        elif status == "waiting" and run.get("gate") == "merge":
            lines.append(_line("run-finish", None, s, "passed", at=at))
        else:
            lines.append(_line("run-finish", None, s, "pending"))
    return lines


def _gate_body(run: dict, kind: str) -> dict:
    """The gate file for a run (the shape gates.open_gate writes)."""
    gate_id = f"{run['id']}.1"
    created = _at(run["created"], 12 if kind != "merge" else 25)
    if kind == "escalation":
        return {"id": gate_id, "run": run["id"], "project": run["project"], "kind": "escalation",
                "title": "Task 2 is stuck", "why": "The checks still failed after 3 tries.", "task": 2,
                "step": "builder", "links": [], "actions": list(gates.ESCALATION_ACTIONS), "flags": [],
                "created": created, "answered": False}
    return {"id": gate_id, "run": run["id"], "project": run["project"], "kind": "merge",
            "title": "Merge the finished work?", "why": "Every task passed; the merge question is set to ask.",
            "task": None, "step": "merge", "links": [], "actions": list(gates.DEFAULT_ACTIONS),
            "flags": ["changes safety code"] if run["project"] == "phoenix9" else [],
            "created": created, "answered": kind == "answered"}


def _session_lines(task: int, attempt: int, ok: bool) -> list:
    """A short stream-json log like the one Claude writes."""
    result = "Done: the checks pass." if ok else "I could not make the checks pass."
    return [
        {"type": "system", "subtype": "init", "session_id": f"demo-{task}-{attempt}", "model": "claude-opus-5-5",
         "tools": ["Read", "Edit", "Bash"]},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": f"Starting task {task}. I will read the code first."}]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls src"}}]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "index.ts\nform.ts\nmail.ts"}]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": "src/form.ts"}}]}},
        {"type": "result", "subtype": "success" if ok else "error", "is_error": not ok, "result": result,
         "duration_ms": 41000, "num_turns": 4, "total_cost_usd": 0.12},
    ]


DIFF = """diff --git a/src/form.ts b/src/form.ts
index 3b18e51..a94c2d7 100644
--- a/src/form.ts
+++ b/src/form.ts
@@ -1,5 +1,9 @@
 export function render(root: HTMLElement) {
-  root.innerHTML = "<form></form>";
+  root.innerHTML = `<form>
+    <input name="name" />
+    <input name="email" type="email" />
+    <textarea name="message"></textarea>
+  </form>`;
 }
"""


def _write_attempt_files(run_dir: Path, n: int, attempt: int, ok: bool) -> None:
    """Session stream, checks and diff for one attempt of one task."""
    stream = "".join(json.dumps(x) + "\n" for x in _session_lines(n, attempt, ok))
    atomic.write_text(run_dir / "logs" / f"{n}-{attempt}-builder.jsonl", stream)
    folder = run_dir / "tasks" / str(n) / f"attempt-{attempt}"
    atomic.write_text(folder / "checks.txt", ("$ pnpm test\n2 passed, 0 failed\nexit 0\n" if ok
                                             else "$ pnpm test\n1 passed, 1 failed\nexit 1\n"))
    atomic.write_text(folder / "diff.patch", DIFF)


def _events_for(run: dict) -> list:
    """The fixed-time events of a run, in the architecture section 8 shape."""
    def ev(ts, type_, task=None, step=None, **data):
        return {"ts": ts, "type": type_, "project": run["project"], "run": run["id"], "task": task,
                "step": step, "data": data}
    out = [ev(run["created"], "run.queued", title=run["title"]), ev(run["created"], "run.started")]
    for i, (status, tries, _) in enumerate(run["tasks"], start=1):
        if status == "pending":
            continue
        out.append(ev(_at(run["created"], 2 * i), "task.started", task=i))
        if status in ("passed", "failed", "skipped"):
            out.append(ev(_at(run["created"], 2 * i + 1), "task.finished", task=i, status=status, tries=tries))
    if run.get("gate"):
        out.append(ev(_gate_body(run, run["gate"])["created"], "gate.opened", task=2 if run["gate"] == "escalation" else None,
                      step="builder" if run["gate"] == "escalation" else "merge",
                      gate=f"{run['id']}.1", kind="merge" if run["gate"] != "escalation" else "escalation"))
    if run["finished"]:
        out.append(ev(run["finished"], "run.finished", status=run["status"]))
    return out


def _build_state(run: dict, plan: dict, spec_tasks: dict) -> dict:
    """state.json for one demo run."""
    st = state.new_state(run["id"], run["project"], spec_tasks)
    created = run["created"]
    st.update(status=run["status"], created=created, updated=run["finished"] or _at(created, 20))
    st["usage"] = {"cost_usd": run["cost"], "sessions": run["sessions"]}
    steps = [_line("run-start", None, s, "passed", at=created) for s in plan["groups"]["run-start"]]
    for i, (status, tries, flagged) in enumerate(run["tasks"], start=1):
        task = st["tasks"][str(i)]
        task.update(status=status, tries=tries, flagged=flagged)
        if flagged:
            task["failures"] = [flagged]
        if status != "pending":
            steps += _task_lines(plan, i, status, tries, _at(created, 2 * i))
    steps += _finish_lines(plan, run, _at(created, 25))
    st["steps"] = steps
    gate = run.get("gate")
    if gate in ("escalation", "merge"):
        gate_id = f"{run['id']}.1"
        waiting_task = 2 if gate == "escalation" else None
        st["current"] = {"group": "task" if waiting_task else "run-finish", "task": waiting_task,
                         "step": "builder" if waiting_task else "merge", "attempt": 3 if waiting_task else None,
                         "gate": gate_id}
        if waiting_task:
            st["tasks"]["2"]["gate"] = gate_id
    elif run["status"] == "running":
        st["current"] = {"group": "task", "task": 2, "step": "builder", "attempt": 1, "gate": None}
    return st


def _fix_times(folder: Path, stamp: str) -> None:
    """Give every file in a run folder the same fixed modified time."""
    from datetime import datetime
    seconds = datetime.fromisoformat(stamp).timestamp()
    for path in [folder, *folder.rglob("*")]:
        os.utime(path, (seconds, seconds))


def _write_run(run: dict) -> list:
    """One run folder; returns its events."""
    project = run["project"]
    data = PROJECTS[project]
    folder = paths.projects() / project
    title, tasks = data["spec"]
    run.setdefault("title", title)
    if run["title"] != title:
        tasks = [(f"{run['title']}: part {n}", "Do one part.", "no", ["python3 -m pytest"],
                  [f"Part {n} of {run['title']} works as described"]) for n in range(1, len(run["tasks"]) + 1)]
    text = spec_text(project, run["title"], tasks, data["preset"])
    parsed = spec.parse(text)
    run_dir = runs.run_dir(project, run["id"])
    run_dir.mkdir(parents=True)
    plan, frozen = _plan_and_settings(folder)
    st = _build_state(run, plan, {str(t.number): state.new_task(t.title, t.depends_on) for t in parsed.tasks})
    atomic.write_text(run_dir / "spec.md", text, mode=0o444)
    atomic.write_json(run_dir / "spec.json", spec.to_json(parsed))
    atomic.write_json(run_dir / "settings.json", frozen)
    atomic.write_json(run_dir / "plan.json", plan)
    atomic.write_json(run_dir / "state.json", st)
    for n, (status, tries, _) in enumerate(run["tasks"], start=1):
        for attempt in range(1, tries + 1):
            _write_attempt_files(run_dir, n, attempt, ok=(status == "passed" and attempt == tries))
    atomic.write_text(run_dir / "logs" / "builder.log",
                      "builder: started\nbuilder: reading the task\nbuilder: finished the last attempt\n")
    kind = run.get("gate")
    if kind:
        body = _gate_body(run, kind)
        atomic.write_json(run_dir / "gates" / f"{body['id']}.json", body)
        if kind == "answered":
            atomic.write_json(run_dir / "gates" / f"{body['id']}.answer.json",
                              {"action": "approve", "note": "looks good", "who": "dashboard",
                               "at": _at(run["created"], 13)})
    found = _events_for(run)
    atomic.write_text(run_dir / "events.jsonl", "".join(json.dumps(e) + "\n" for e in found))
    _fix_times(run_dir, st["updated"])
    return found


def _write_logs(all_events: list) -> None:
    """HOME events.jsonl (oldest first) and the global command and API logs."""
    all_events.sort(key=lambda e: (e["ts"], e["run"] or ""))
    atomic.write_text(paths.events(), "".join(json.dumps(e) + "\n" for e in all_events))
    commands = [
        {"ts": "2026-10-20T08:59:00+00:00", "who": "dashboard", "command": "run start demo-site", "project": "demo-site"},
        {"ts": "2026-10-31T09:59:00+00:00", "who": "dashboard", "command": "run start demo-site", "project": "demo-site"},
        {"ts": "2026-11-01T07:59:00+00:00", "who": "cli", "command": "run start tiny-tool", "project": "tiny-tool"},
    ]
    paths.logs().mkdir(parents=True, exist_ok=True)
    atomic.write_text(paths.logs() / "commands.jsonl", "".join(json.dumps(c) + "\n" for c in commands))
    atomic.write_text(paths.logs() / "api.log", "GET /api/projects 200 12ms\nGET /api/gates 200 4ms\n")


def _seed_install(home: Path) -> None:
    """A fake installed Phoenix (v9.1), its rollback copy (v9.0) and a cached newest tag (v9.2)."""
    for suffix, tag in (("", "v9.1"), ("-prev", "v9.0")):
        folder = home / f"phoenix9-install{suffix}"
        folder.mkdir()
        (folder / "VERSION").write_text(tag + "\n")
        for args in (("init", "-q", "-b", "main"), ("add", "-A"),
                     ("-c", "user.name=demo", "-c", "user.email=demo@example.com", "commit", "-q", "-m", tag),
                     ("tag", tag)):
            git.git(folder, *args)
    atomic.write_json(home / "update" / "status.json", {
        "newest": "v9.2", "checked": "2026-10-31T09:00:00+00:00",
        "last": {"action": "install", "tag": "v9.1", "result": "installed", "reason": "", "at": "2026-10-20T08:00:00+00:00"}})
    atomic.write_text(home / "logs" / "updater.log", "2026-10-20T08:00:00 install v9.1\n2026-10-20T08:02:10 installed v9.1\n")


def _seed_deploys(project: str) -> None:
    """A short deploy history: one good deploy, then one that was rolled back."""
    rows = [
        {"at": "2026-10-25T10:00:00+00:00", "deployer": "vps-docker", "commit": "a1b2c3d4e5f6", "version": "v1",
         "url": "https://demo-site.example.com", "ok": True, "rolled_back": False, "reason": "", "who": "alex",
         "run": None, "kind": "deploy"},
        {"at": "2026-10-28T15:30:00+00:00", "deployer": "vps-docker", "commit": "f6e5d4c3b2a1", "version": "v2",
         "url": "", "ok": False, "rolled_back": True, "reason": "the health check got a 502", "who": "alex",
         "run": None, "kind": "deploy"}]
    path = paths.projects() / project / ".phoenix" / "deploys.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _seed_extras(home: Path, projects: Path) -> None:
    """A removed project, an unlisted folder, and two connected services (the rest stay unconnected)."""
    from phoenix9 import tomlw
    old = projects / "old-experiment"
    (old / "notes").mkdir(parents=True)
    atomic.write_text(old / "CLAUDE.md", "# old-experiment\n\nA project that was removed from Phoenix.\n")
    tomlw.dump(paths.config() / "global.toml", {"removed_projects": [{
        "name": "old-experiment", "path": str(old), "repo": "alex-boop-chasey/old-experiment",
        "removed_on": "2026-10-28"}]})
    (projects / "scratch-pad").mkdir()
    atomic.write_text(projects / "scratch-pad" / "ideas.txt", "loose notes, not a Phoenix project\n")
    from phoenix9.ops import services as ops_services
    for name in ("github", "resend"):
        svc = ops_services._service(name)
        ops_services.connect(name, {k: f"demo-{k.lower()}-0123456789" for k in svc["account_keys"]},
                             who="demo", check=False)
    from phoenix9 import services
    registry = services.read_registry()
    for name in ("github", "resend"):
        registry[name]["connected_at"] = SERVICES_CONNECTED_AT
    services.write_registry(registry)


def seed(home: Path, projects: Path) -> None:
    """Empty the two folders (only if they are empty or demo folders) and fill them with the demo data."""
    home, projects = Path(home), Path(projects)
    _check_folder(home, "the Phoenix home")
    _check_folder(projects, "the projects folder")
    os.environ["PHOENIX_HOME"], os.environ["PHOENIX_PROJECTS"] = str(home), str(projects)
    os.environ["PHOENIX_INSTALL"] = str(home / "phoenix9-install")
    _empty(home)
    _empty(projects)
    (home / MARKER).write_text("demo data; safe to empty\n")
    (projects / MARKER).write_text("demo data; safe to empty\n")
    for name, data in PROJECTS.items():
        _write_project(name, data)
    keys.set_key("demo-site", "RESEND_API_KEY", SECRET_KEY_VALUE, secret=True)
    keys.set_key("demo-site", "PUBLIC_SITE_URL", PUBLIC_URL, secret=False)
    _seed_install(home)
    _seed_extras(home, projects)
    _seed_deploys("demo-site")
    all_events = []
    for run in RUNS:
        all_events += _write_run(json.loads(json.dumps(run)))
    _write_logs(all_events)


def main(argv: list) -> int:
    """Command line: seed <home> <projects>."""
    if len(argv) != 2:
        print("usage: python3 tests/seed_demo.py <home> <projects>", file=sys.stderr)
        return 2
    try:
        seed(Path(argv[0]), Path(argv[1]))
    except ValueError as err:
        print(str(err), file=sys.stderr)
        return 1
    print(f"Demo data written to {argv[0]} and {argv[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
