"""Documents of a run or a project's notes, addressed by a Phoenix id (never a server path), served scrubbed."""
import os
import re
import stat
from pathlib import Path

from phoenix9 import runs
from phoenix9.ops import common, logs
from phoenix9.ops.common import NotFound, OpsError

SUFFIXES = (".md", ".txt")
MAX_BYTES = 1_000_000          # a longer document is cut here
MAX_LISTED = 200
TITLE_BYTES = 4096             # list() reads only this much of each file to find its title
SKIP_DIRS = ("logs", "gates", ".git")  # never served, nor any folder whose name starts with "."
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


def _skipped(rel: Path) -> bool:
    """True when a document sits in a folder that is never served (logs/, gates/, .git/ or any dot folder)."""
    return any(p in SKIP_DIRS or p.startswith(".") for p in rel.parts[:-1])


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


def _parse(id_: str) -> tuple[str, str, Path, Path]:
    """An id split into (kind, owner, base folder, relative path); OpsError/NotFound when it is wrong."""
    kind, sep, tail = (id_ or "").partition(":")
    owner, slash, rest = tail.partition("/")
    if not sep or kind not in ("run", "notes") or not slash:
        raise _bad(id_)
    rel = _relative(rest, id_)
    base = _base(kind, owner)
    if _skipped(rel):
        raise NotFound(f"There is no document '{id_}'.")
    return kind, owner, base, rel


def _fd_path(fd: int) -> Path | None:
    """The real path the kernel says an open file has, or None when /proc is not there."""
    try:
        return Path(os.readlink(f"/proc/self/fd/{fd}"))
    except OSError:
        return None


def _open_inside(base: Path, rel: Path, id_: str) -> int:
    """Open base/rel once for reading and prove the opened file is a regular file inside base; returns the fd.

    The file is opened a single time (never by name again), its final part is never a symlink (O_NOFOLLOW),
    and the kernel's own path of the open file must sit inside the real base folder, so a folder swapped
    for a symlink between any check and the read cannot reach outside."""
    root = base.resolve()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(base / rel, flags)
    except OSError as err:
        if err.errno == getattr(os, "ELOOP", 40) or (base / rel).is_symlink():
            raise OpsError("That document is outside the allowed folder.") from None
        raise NotFound(f"There is no document '{id_}'.") from None
    try:
        real = _fd_path(fd)
        if real is None:  # no /proc: fall back to the resolved name, checked to be the same file
            real = (base / rel).resolve()
            st, now = os.fstat(fd), os.stat(real)
            if (st.st_dev, st.st_ino) != (now.st_dev, now.st_ino):
                raise OpsError("That document is outside the allowed folder.")
        if not real.is_relative_to(root):
            raise OpsError("That document is outside the allowed folder.")
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise NotFound(f"There is no document '{id_}'.")
    except OSError:
        os.close(fd)
        raise NotFound(f"There is no document '{id_}'.") from None
    except OpsError:
        os.close(fd)
        raise
    return fd


def _read_fd(fd: int, limit: int) -> bytes:
    """Up to limit bytes from an open file, closing it; OSError becomes NotFound."""
    try:
        with os.fdopen(fd, "rb") as f:
            return f.read(limit)
    except OSError:
        raise NotFound("That document could not be read.") from None


def _head(raw: bytes) -> bytes:
    """The start of a file read for its title, without a last line that the read limit cut in half."""
    if len(raw) < TITLE_BYTES:
        return raw
    return raw[:raw.rfind(b"\n") + 1]


def resolve(id_: str) -> tuple[Path, str]:
    """The real file behind a document id and its project; OpsError/NotFound when the id is wrong or leaves its folder.

    Only for showing where a document lives; reading goes through _load, which opens the file once."""
    kind, owner, base, rel = _parse(id_)
    fd = _open_inside(base, rel, id_)
    os.close(fd)
    return base / rel, _project_of(kind, owner, base)


def _load(id_: str) -> tuple[str, str]:
    """The file name and scrubbed text of a document id, read through one checked open."""
    kind, owner, base, rel = _parse(id_)
    raw = _read_fd(_open_inside(base, rel, id_), MAX_BYTES)
    return rel.name, _scrub(raw, _project_of(kind, owner, base))


def _title(text: str, fallback: str) -> str:
    """The first '# ' heading of a document, else its file name."""
    for line in text.splitlines():
        if line.startswith("# ") and line[2:].strip():
            return line[2:].strip()
    return fallback


def _project_of(kind: str, owner: str, base: Path) -> str:
    """The project a document belongs to (the notes owner, or the run folder's parent)."""
    return owner if kind == "notes" else base.parent.name


def _scrub(raw: bytes, project: str) -> str:
    """The scrubbed text of some bytes (project keys, secret files and secret shapes)."""
    return logs._scrubber(project).text(raw.decode("utf-8", errors="replace"))


def list(run_id: str) -> list:
    """A run's documents as {id, title, size}, plan and summary first."""
    base = _base("run", run_id)
    found = []
    for path in sorted(base.rglob("*")):
        rel = path.relative_to(base)
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in SUFFIXES:
            continue
        if _skipped(rel):
            continue
        found.append((rel.as_posix(), path))
    found.sort(key=lambda x: (x[0] not in ("plan.md", "summary.md"), x[0]))
    project = _project_of("run", run_id, base)
    rows = []
    for rel, path in found[:MAX_LISTED]:
        try:
            text = _scrub(_head(_read_fd(_open_inside(base, Path(rel), rel), TITLE_BYTES)), project)
            size = path.stat().st_size
        except OpsError:
            continue  # gone or swapped since the folder was listed
        rows.append({"id": f"run:{run_id}/{rel}", "title": _title(text, path.name), "size": size})
    return rows


def show(id_: str) -> dict:
    """One document: {id, title, text}, the text scrubbed."""
    name, text = _load(id_)
    return {"id": id_, "title": _title(text, name), "text": text}


def download(id_: str) -> dict:
    """One document for download: {name, text} with a safe file name and the text scrubbed."""
    name, text = _load(id_)
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name).lstrip(".") or "document.txt"
    return {"name": name, "text": text}
