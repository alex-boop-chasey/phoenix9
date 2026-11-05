"""Ops for gates: list the open questions and answer one."""
import builtins
import fnmatch
import re

from phoenix9 import git as gitmod, gates as core, runs, scrub, settings, state
from phoenix9.ops import common
from phoenix9.ops.common import OpsError


def list_(project: str | None = None) -> list:
    """Open gates, oldest first (one project or all)."""
    if project:
        common.project_dir(project)
    return core.list_gates(project)


def answer(gate_id: str, action: str, note: str = "", who: str = "cli") -> dict:
    """Answer an open gate (the runner picks the answer up)."""
    gate = next((g for g in core.list_gates(open_only=False) if g["id"] == gate_id), None)
    if gate is None:
        raise common.NotFound(f"There is no gate called '{gate_id}'.")
    if gate.get("answered"):
        raise common.Conflict(f"Gate {gate_id} is already answered.")
    try:
        project_settings = settings.load_project(common.project_dir(gate["project"]))
    except (settings.SettingsError, OpsError):
        project_settings = {}
    if not core.may_answer(gate, who, project_settings):
        raise OpsError(f"'{who}' may not answer {gate['kind']} questions in {gate['project']}.")
    try:
        result = core.answer(gate_id, action, note=note, who=who)
    except ValueError as err:
        raise OpsError(str(err)) from None
    common.record_command(who, f"gate answer {gate_id} {action}", gate["project"],
                          f"answered gate {gate_id}: {action}")
    return {"gate": gate_id, **result}


MAX_DIFF_CHARS = 200_000


def _find_gate(gate_id: str) -> dict:
    """The gate with this id (open or answered); NotFound when there is none."""
    gate = next((g for g in core.list_gates(open_only=False) if g["id"] == gate_id), None)
    if gate is None:
        raise common.NotFound(f"There is no gate called '{gate_id}'.")
    return gate


def _split_diff(text: str) -> dict:
    """Cut a git diff into {path: diff text of that file}."""
    found = {}
    for part in re.split(r"(?m)^(?=diff --git )", text):
        m = re.match(r"diff --git a/(.*?) b/(.*)\n", part)
        if m:
            found[m.group(2)] = part
    return found


def _count_lines(text: str) -> str:
    """Numstat-style lines (added, removed, path) counted from a diff text."""
    lines = []
    for path, body in _split_diff(text).items():
        rows = body.splitlines()
        added = sum(1 for r in rows if r.startswith("+") and not r.startswith("+++"))
        removed = sum(1 for r in rows if r.startswith("-") and not r.startswith("---"))
        lines.append(f"{added}\t{removed}\t{path}")
    return "\n".join(lines)


def _branch_diff(code, run_id: str) -> tuple[str, str]:
    """Return (numstat, diff text) of the run's branch against main, from local git objects."""
    branch = gitmod.branch_name(run_id)
    base = gitmod.git(code, "merge-base", gitmod.default_branch(code), branch).strip()
    rng = f"{base}..{branch}"
    return gitmod.git(code, "diff", "--numstat", rng), gitmod.git(code, "diff", rng)


def _patch_diff(folder) -> str:
    """Fallback: the run's own task patches joined into one diff text."""
    return "".join(p.read_text(errors="replace") for p in sorted(folder.glob("tasks/*/attempt-*/diff.patch"))
                   if p.is_file() and not p.is_symlink())


def _pr_diff(folder) -> str:
    """Last resort: ask GitHub for the merge request's diff (through the gh adapter)."""
    mr = folder / "merge-request.txt"
    if not mr.is_file():
        return ""
    rc, out, _ = common.make_adapters().host.gh("pr", "diff", mr.read_text().strip())
    return out if rc == 0 else ""


def _diff_for(project: str, folder, run_id: str) -> tuple[str, str]:
    """The run's diff: its git branch first, then its patch files, then GitHub."""
    try:
        numstat, text = _branch_diff(common.project_dir(project) / "code", run_id)
        if text.strip():
            return numstat, text
    except (gitmod.GitError, OSError):
        pass
    text = _patch_diff(folder) or _pr_diff(folder)
    return _count_lines(text), text


def _files(numstat: str, text: str, globs: list) -> list:
    """One entry per changed file: path, +/- counts, safety flag and its diff."""
    bodies = _split_diff(text)
    files = []
    for line in numstat.splitlines():
        added, removed, path = (line.split("\t", 2) + ["", ""])[:3]
        if not path:
            continue
        files.append({"path": path, "added": int(added) if added.isdigit() else 0,
                      "removed": int(removed) if removed.isdigit() else 0,
                      "binary": added == "-", "safety": any(fnmatch.fnmatch(path, g) for g in globs),
                      "diff": bodies.get(path, "")[:MAX_DIFF_CHARS]})
    return files


def _task_facts(st: dict) -> dict:
    """Tasks passed / total and which needed retries."""
    tasks = st.get("tasks", {})
    retried = [{"number": int(n), "title": t.get("title", ""), "tries": t.get("tries", 0)}
               for n, t in sorted(tasks.items(), key=lambda kv: int(kv[0])) if t.get("tries", 0) > 1]
    return {"passed": sum(1 for t in tasks.values() if t["status"] == "passed"), "total": len(tasks),
            "retried": retried}


def _suite(st: dict) -> dict:
    """The full-suite result as {status, note}."""
    line = next((x for x in st.get("steps", []) if x.get("step") == "full-suite"), None)
    if not line:
        return {"status": "not run", "note": ""}
    return {"status": line["status"], "note": line.get("note") or ""}


def _scrubbed(value):
    """The data with the secret scrubber run over every string."""
    if isinstance(value, str):
        return scrub.scrub(value)
    if isinstance(value, builtins.list):
        return [_scrubbed(v) for v in value]
    if isinstance(value, dict):
        return {k: _scrubbed(v) for k, v in value.items()}
    return value


def review(gate_id: str) -> dict:
    """Everything Alex needs to read a merge request inside the build (merge gates only)."""
    gate = _find_gate(gate_id)
    if gate["kind"] != "merge":
        raise OpsError(f"Gate {gate_id} is a {gate['kind']} question, not a merge.")
    folder = runs.find_run(gate["run"])
    if folder is None:
        raise common.NotFound(f"There is no run called '{gate['run']}'.")
    st = state.load(folder)
    try:
        globs = settings.load_project(common.project_dir(gate["project"])).get("safety_files") or []
    except (settings.SettingsError, OpsError):
        globs = []
    files = _files(*_diff_for(gate["project"], folder, gate["run"]), globs)
    summary, mr = folder / "summary.md", folder / "merge-request.txt"
    return _scrubbed({
        "gate": gate_id, "run": gate["run"], "project": gate["project"], "title": gate["title"],
        "why": gate.get("why", ""), "answered": bool(gate.get("answered")),
        "summary": summary.read_text(errors="replace") if summary.is_file() else "",
        "tasks": _task_facts(st), "full_suite": _suite(st),
        "safety": {"flag": any(f["safety"] for f in files), "files": [f["path"] for f in files if f["safety"]]},
        "files": files, "added": sum(f["added"] for f in files), "removed": sum(f["removed"] for f in files),
        "merge_request": mr.read_text().strip() if mr.is_file() else ""})


list = list_
