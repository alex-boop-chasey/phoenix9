"""Documents of a run or a project's notes, addressed by a Phoenix id (never a server path), served scrubbed."""
import re
from pathlib import Path

from phoenix9 import runs
from phoenix9.ops import common, logs
from phoenix9.ops.common import NotFound, OpsError

SUFFIXES = (".md", ".txt")
MAX_BYTES = 1_000_000          # a longer document is cut here
MAX_LISTED = 200
SKIP_DIRS = ("logs", "gates", ".git")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _bad(id_: str) -> OpsError:
    return OpsError(f"'{id_}' is not a document id. Use run:<run id>/<file> or notes:<project>/<file>.")


def _relative(rest: str, id_: str) -> Path:
    """The relative path part of an id, or OpsError when it is empty, absolute, has '..' or the wrong suffix."""
    if not rest or rest.startswith("/") or "\\" in rest or "\x00" in rest:
        raise _bad(id_)
    parts = rest.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise _bad(id_)
    if not parts[-1].lower().endswith(SUFFIXES):
        raise OpsError("Only .md and .txt documents can be shown.")
    return Path(*parts)


def _base(kind: str, owner: str) -> Path:
    """The folder an id may reach into (a run's folder or a project's notes folder)."""
    if not _NAME.fullmatch(owner):
        raise NotFound(f"There is no {'run' if kind == 'run' else 'project'} called '{owner}'.")
    if kind == "run":
        folder = runs.find_run(owner)
        if folder is None:
            raise NotFound(f"There is no run called '{owner}'.")
        return folder
    return common.project_dir(owner) / "notes"


def resolve(id_: str) -> tuple[Path, str]:
    """The real file behind a document id and its project; OpsError/NotFound when the id is wrong or leaves its folder."""
    kind, sep, tail = (id_ or "").partition(":")
    owner, slash, rest = tail.partition("/")
    if not sep or kind not in ("run", "notes") or not slash:
        raise _bad(id_)
    rel = _relative(rest, id_)
    base = _base(kind, owner)
    target = (base / rel).resolve()
    if not target.is_relative_to(base.resolve()):
        raise OpsError("That document is outside the allowed folder.")
    if not target.is_file():
        raise NotFound(f"There is no document '{id_}'.")
    return target, _project_of(kind, owner, base)


def _title(text: str, fallback: str) -> str:
    """The first '# ' heading of a document, else its file name."""
    for line in text.splitlines():
        if line.startswith("# ") and line[2:].strip():
            return line[2:].strip()
    return fallback


def _project_of(kind: str, owner: str, base: Path) -> str:
    """The project a document belongs to (the notes owner, or the run folder's parent)."""
    return owner if kind == "notes" else base.parent.name


def _read(path: Path, project: str) -> str:
    """The scrubbed text of a file (project keys, secret files and secret shapes), cut at MAX_BYTES."""
    with open(path, "rb") as f:
        raw = f.read(MAX_BYTES)
    return logs._scrubber(project).text(raw.decode("utf-8", errors="replace"))


def list(run_id: str) -> list:
    """A run's documents as {id, title, size}, plan and summary first."""
    base = _base("run", run_id)
    found = []
    for path in sorted(base.rglob("*")):
        rel = path.relative_to(base)
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in SUFFIXES:
            continue
        if any(p in SKIP_DIRS for p in rel.parts[:-1]):
            continue
        found.append((rel.as_posix(), path))
    found.sort(key=lambda x: (x[0] not in ("plan.md", "summary.md"), x[0]))
    project = _project_of("run", run_id, base)
    return [{"id": f"run:{run_id}/{rel}", "title": _title(_read(path, project), path.name), "size": path.stat().st_size}
            for rel, path in found[:MAX_LISTED]]


def show(id_: str) -> dict:
    """One document: {id, title, text}, the text scrubbed."""
    path, project = resolve(id_)
    text = _read(path, project)
    return {"id": id_, "title": _title(text, path.name), "text": text}


def download(id_: str) -> dict:
    """One document for download: {name, text} with a safe file name and the text scrubbed."""
    path, project = resolve(id_)
    name = re.sub(r"[^A-Za-z0-9._-]", "_", path.name).lstrip(".") or "document.txt"
    return {"name": name, "text": _read(path, project)}
