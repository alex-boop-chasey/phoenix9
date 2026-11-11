"""Search across projects, runs, notes, research and run logs: read-only, scrubbed, plain text matching."""
import os
from pathlib import Path

from phoenix9 import paths, project, runs, scrub
from phoenix9.ops import common, docs, logs
from phoenix9.ops.common import OpsError

KINDS = ("project", "run", "note", "research", "log")
MIN_QUERY, MAX_QUERY = 2, 100
MAX_LIMIT = 50
MAX_FILE_BYTES = 200_000      # a notes file or log over this size is skipped
MAX_FILES = 400               # notes files looked at per project
MAX_LOGS = 200                # logs looked at per project
SNIPPET = 120                 # a snippet is cut to this many characters


def check_query(q) -> str:
    """The query as text (2 to 100 characters), else a plain OpsError."""
    text = q.strip() if isinstance(q, str) else ""
    if not MIN_QUERY <= len(text) <= MAX_QUERY:
        raise OpsError(f"Search for between {MIN_QUERY} and {MAX_QUERY} characters.")
    return text


def _snippet(text: str, needle: str) -> str:
    """The first line of the text that holds the needle, cut short, scrubbed (the title line if none)."""
    lowered = needle.lower()
    line = next((x for x in text.splitlines() if lowered in x.lower()), "")
    line = " ".join(line.split())
    at = max(line.lower().find(lowered) - SNIPPET // 4, 0)
    cut = line[at:at + SNIPPET]
    return scrub.scrub(("..." if at else "") + cut + ("..." if len(line) > at + SNIPPET else ""))


def _hit(kind: str, title: str, snippet: str, owner: str, to: str, params: dict | None = None) -> dict:
    return {"kind": kind, "title": scrub.scrub(title), "snippet": snippet, "project": owner,
            "page": {"to": to, "params": params or {}}}


def _has(text: str, needle: str) -> bool:
    return needle.lower() in (text or "").lower()


def _projects(needle: str) -> list:
    """Projects whose name or description holds the needle."""
    found = []
    for name in project.project_names():
        desc = project.description(paths.projects() / name)
        if _has(name, needle) or _has(desc, needle):
            found.append(_hit("project", name, _snippet(desc, needle) if _has(desc, needle) else desc[:SNIPPET],
                              name, f"p/{name}/overview"))
    return found


def _spec_title(folder: Path) -> str:
    """The first heading of a run's spec.md, or ''."""
    try:
        with open(folder / "spec.md", "rb") as f:
            return docs._title(f.read(docs.TITLE_BYTES).decode("utf-8", errors="replace"), "")
    except OSError:
        return ""


def _runs(owner: str, needle: str) -> list:
    """Runs of a project whose id or spec title holds the needle."""
    found = []
    for item in runs.list_runs(owner):
        title = _spec_title(runs.run_dir(owner, item["run_id"]))
        if _has(item["run_id"], needle) or _has(title, needle):
            found.append(_hit("run", title or item["run_id"], f"{item['status']}: {item['run_id']}", owner,
                              f"p/{owner}/build", {"run": item["run_id"]}))
    return found


def _note_files(base: Path) -> list:
    """Relative paths of .md/.txt files under a notes folder, skipping never-served and dot folders and links."""
    found = []
    if not base.is_dir() or base.is_symlink():
        return found
    for here, dirs, files in os.walk(base, followlinks=False):
        rel_dir = Path(here).relative_to(base)
        dirs[:] = sorted(d for d in dirs if d not in docs.SKIP_DIRS and not d.startswith("."))
        for name in sorted(files):
            rel = rel_dir / name
            if name.lower().endswith(docs.SUFFIXES) and not docs._skipped(rel) and not (Path(here) / name).is_symlink():
                found.append(rel)
    return found[:MAX_FILES]


def _read_note(owner: str, base: Path, rel: Path) -> str | None:
    """The scrubbed text of a notes file, or None when it is too big, gone or outside the notes folder."""
    try:
        if (base / rel).stat().st_size > MAX_FILE_BYTES:
            return None
        raw = docs._read_fd(docs._open_inside(base, rel, rel.as_posix()), MAX_FILE_BYTES)
    except (OSError, OpsError):
        return None
    return docs._scrub(raw, owner)


def _notes(owner: str, needle: str) -> list:
    """Notes and research files of a project whose name or text holds the needle."""
    found = []
    base = common.project_dir(owner) / "notes"
    for rel in _note_files(base):
        text = _read_note(owner, base, rel)
        if text is None or not (_has(text, needle) or _has(rel.as_posix(), needle)):
            continue
        kind = "research" if rel.parts[0] == "research" else "note"
        doc = f"notes:{owner}/{rel.as_posix()}"
        found.append(_hit(kind, docs._title(text, rel.name), _snippet(text, needle) or rel.as_posix(), owner,
                          "doc", {"path": doc}))
    return found


def _logs(owner: str, needle: str, room: int) -> list:
    """Run logs of a project whose scrubbed text holds the needle (stops once `room` are found)."""
    found = []
    entries = [e for e in logs.list_(owner) if e.get("run") and e["size"] <= MAX_FILE_BYTES][:MAX_LOGS]
    for entry in entries:
        if len(found) >= room:
            break
        try:
            text = logs.read(owner, entry["id"])["text"]
        except OpsError:
            continue
        if _has(text, needle):
            found.append(_hit("log", entry["title"], _snippet(text, needle), owner, f"p/{owner}/logs",
                              {"run": entry["run"], "log": entry["id"]}))
    return found


def _wanted(kinds) -> tuple:
    """The kinds to search (all when none given); OpsError for an unknown kind."""
    chosen = tuple(kinds) if kinds else KINDS
    for kind in chosen:
        if kind not in KINDS:
            raise OpsError(f"'{kind}' is not a kind of result. Use one of: {', '.join(KINDS)}.")
    return chosen


def search(query: str, kinds=None, limit: int = 20) -> list:
    """Results {kind, title, snippet, project, page} for a plain-text query; nothing is written anywhere."""
    needle = check_query(query)
    chosen = _wanted([kinds] if isinstance(kinds, str) else kinds)
    limit = min(max(int(limit), 1), MAX_LIMIT)
    found = _projects(needle) if "project" in chosen else []
    for owner in project.project_names():
        if len(found) >= limit:
            break
        if "run" in chosen:
            found += _runs(owner, needle)
        if "note" in chosen or "research" in chosen:
            found += [h for h in _notes(owner, needle) if h["kind"] in chosen]
        if "log" in chosen:
            found += _logs(owner, needle, limit - len(found))
    return found[:limit]
