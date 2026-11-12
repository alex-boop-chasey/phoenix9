"""Reference material: files Alex uploads to a project's notes/reference folder, which every build reads."""
import re
from datetime import datetime, timezone
from pathlib import Path

from phoenix9 import atomic, scrub
from phoenix9.ops import common

LINKS_NAME = "links.txt"
MAX_FILE = 5 * 1024 * 1024
MAX_FILES = 40
MAX_TOTAL = 25 * 1024 * 1024
MAX_NAME = 100
KINDS = {
    ".css": "style", ".scss": "style",
    ".json": "design tokens", ".js": "design tokens", ".ts": "design tokens",
    ".txt": "text", ".md": "text", ".csv": "text", ".yaml": "text", ".yml": "text", ".toml": "text",
    ".html": "text",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image", ".gif": "image", ".svg": "image",
    ".pdf": "document",
}
BINARY = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf"}
ALLOWED = ".txt .md .css .scss .json .js .ts .html .svg .png .jpg .jpeg .webp .gif .pdf .csv .yaml .yml .toml"


class ReferenceError_(ValueError):
    """A reference file was refused or could not be found; the message says why in plain English."""

    def __init__(self, message: str):
        super().__init__(scrub.scrub(message))


def folder(project: str, create: bool = False) -> Path:
    """The project's reference folder; refuses a symlinked notes or reference folder."""
    root = common.project_dir(project)
    notes = root / "notes"
    ref = notes / "reference"
    if notes.is_symlink() or ref.is_symlink():
        raise ReferenceError_("The reference folder is a symbolic link, so nothing can be saved there.")
    if create:
        ref.mkdir(parents=True, exist_ok=True)
    return ref


def kind_of(name: str) -> str:
    """What sort of file this is: style, design tokens, text, image, document or links."""
    if name == LINKS_NAME:
        return "links"
    return KINDS.get(Path(name).suffix.lower(), "text")


def list_files(project: str) -> list[dict]:
    """Each reference file as {name, size, modified, kind}, sorted by name; hidden files and symlinks are skipped."""
    ref = folder(project)
    if not ref.is_dir():
        return []
    out = []
    for path in sorted(ref.iterdir(), key=lambda p: p.name):
        if path.name.startswith(".") or path.is_symlink() or not path.is_file():
            continue
        st = path.stat()
        modified = datetime.fromtimestamp(st.st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        out.append({"name": path.name, "size": st.st_size, "modified": modified, "kind": kind_of(path.name)})
    return out


def clean_name(filename: str) -> str:
    """Reduce a file name to a safe basename; refuses names with nothing usable or a type that is not allowed."""
    base = re.split(r"[\\/]", str(filename or ""))[-1].replace(" ", "-")
    base = re.sub(r"[^A-Za-z0-9._-]", "", base)
    base = re.sub(r"\.{2,}", ".", base).lstrip(".")
    stem, dot, ext = base.rpartition(".")
    if not dot:
        stem, ext = base, ""
    ext = "." + ext.lower() if ext else ""
    if ext not in ALLOWED.split():
        raise ReferenceError_(f"Files of that type are not accepted. Allowed types: {ALLOWED}.")
    stem = stem.strip(".")
    if not stem:
        raise ReferenceError_("That file name has nothing usable in it. Please rename the file and try again.")
    return stem[:MAX_NAME - len(ext)] + ext


def _taken(ref: Path, name: str) -> bool:
    """True when something (even a broken symlink) already has this name."""
    return (ref / name).exists() or (ref / name).is_symlink()


def _unique(ref: Path, name: str) -> str:
    """The name, or name-2, name-3... when a file of that name already exists."""
    if not _taken(ref, name):
        return name
    stem, ext = Path(name).stem, Path(name).suffix
    n = 2
    while True:
        tail = f"-{n}"
        candidate = stem[:MAX_NAME - len(ext) - len(tail)] + tail + ext
        if not _taken(ref, candidate):
            return candidate
        n += 1


def _check_content(name: str, data: bytes) -> None:
    """Refuse empty files, binary data behind a text extension, and text that holds a secret."""
    ext = Path(name).suffix.lower()
    if not data:
        raise ReferenceError_("That file is empty.")
    if ext in BINARY:
        return
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = "\x00"
    if "\x00" in text:
        raise ReferenceError_(f"{name} is not readable text, so it cannot be saved as a {ext} file.")
    if scrub.mask_patterns(text) != text:
        raise ReferenceError_(f"{name} looks like it contains a secret (a key, token or password). "
                              "Keys belong in the key manager, not in reference files.")


def add_file(project: str, filename: str, data: bytes, who: str, replace: bool = False) -> dict:
    """Validate and save one reference file; returns its list entry. `who` is the person or agent adding it."""
    name = clean_name(filename)
    if len(data) > MAX_FILE:
        raise ReferenceError_(f"{name} is too big: files can be at most {MAX_FILE // (1024 * 1024)} MB.")
    _check_content(name, data)
    ref = folder(project, create=True)
    existing = {f["name"]: f["size"] for f in list_files(project)}
    if replace:
        if (ref / name).is_symlink():
            raise ReferenceError_(f"{name} is a symbolic link and cannot be replaced.")
    else:
        name = _unique(ref, name)
    count = len(existing) + (0 if name in existing else 1)
    total = sum(existing.values()) - existing.get(name, 0) + len(data)
    if count > MAX_FILES:
        raise ReferenceError_(f"A project can hold at most {MAX_FILES} reference files. Remove one first.")
    if total > MAX_TOTAL:
        raise ReferenceError_(f"Reference files can be at most {MAX_TOTAL // (1024 * 1024)} MB in total. "
                              "Remove one first.")
    atomic.write_bytes(ref / name, data, 0o644)
    return next(f for f in list_files(project) if f["name"] == name)


def remove_file(project: str, filename: str) -> None:
    """Delete one reference file by name; refuses names with folders in them and files that are not there."""
    if not filename or filename != Path(filename).name or filename.startswith("."):
        raise ReferenceError_(f"'{filename}' is not a reference file name.")
    path = folder(project) / filename
    if path.is_symlink() or not path.is_file():
        raise ReferenceError_(f"There is no reference file called '{filename}'.")
    path.unlink()


MAX_LINKS = 100
MAX_URL = 500
MAX_NOTE = 200
_URL_RE = re.compile(r"https?://[^\s|]+", re.IGNORECASE)
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_LOCAL_SUFFIXES = (".internal", ".local", ".localhost", ".localdomain")


def _clean_note(note: str) -> str:
    """Plain-text note: control characters removed, spaces tidied, at most 200 characters."""
    return _CONTROL_RE.sub(" ", note).strip()[:MAX_NOTE].strip()


def _check_url(url: str) -> None:
    """Refuse URLs that are too long, carry a password, or point at this server or a private network."""
    import ipaddress
    from urllib.parse import urlsplit
    if len(url) > MAX_URL:
        raise ReferenceError_(f"A link is longer than {MAX_URL} characters: {url[:60]}...")
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").rstrip(".").lower()
        parts.port
    except ValueError:
        raise ReferenceError_(f"'{url[:80]}' is not a valid web address.")
    if parts.scheme not in ("http", "https") or not host:
        raise ReferenceError_(f"'{url[:80]}' is not a web address. Only http and https links are accepted.")
    if parts.username is not None or parts.password is not None:
        raise ReferenceError_(f"{url.split('@')[-1][:80]} has a user name or password in it. Remove it and try again.")
    local = host == "localhost" or host.endswith(_LOCAL_SUFFIXES) or "." not in host and ":" not in host
    try:
        ip = ipaddress.ip_address(host)
        local = local or not ip.is_global
    except ValueError:
        if re.fullmatch(r"[0-9.x]+|0x[0-9a-f]+", host):
            local = True
    if local:
        raise ReferenceError_(f"{host} is a local or private address. Links must point at public websites.")


def _parse_links(text: str) -> list[tuple[str, str]]:
    """Pull (url, note) pairs out of text, line by line; refuses any non-web address. Order is kept."""
    found: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        left, bar, right = line.partition("|")
        left = left.strip()
        urls = _URL_RE.findall(left)
        if not urls:
            if _SCHEME_RE.match(left.split()[0]) or "://" in left:
                raise ReferenceError_(f"'{left[:80]}' is not a web address. Only http and https links are accepted.")
            continue
        for first in left.split():
            if _SCHEME_RE.match(first) and not first.lower().startswith(("http://", "https://")):
                raise ReferenceError_(f"'{first[:80]}' is not a web address. Only http and https links are accepted.")
        note = _clean_note(right) if bar and len(urls) == 1 else ""
        for url in urls:
            found.append((url, note))
    return found


def list_links(project: str) -> list[dict]:
    """Saved links as [{url, note}] in file order; blank and # comment lines are skipped."""
    path = folder(project) / LINKS_NAME
    if path.is_symlink() or not path.is_file():
        return []
    out = []
    for raw in path.read_text("utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        url, _, note = line.partition("|")
        url = url.strip()
        if url:
            out.append({"url": url, "note": _clean_note(note)})
    return out


def _write_links(project: str, links: list[dict]) -> None:
    """Rewrite links.txt from a list of {url, note}."""
    ref = folder(project, create=True)
    lines = [f"{l['url']} | {l['note']}" if l["note"] else l["url"] for l in links]
    atomic.write_bytes(ref / LINKS_NAME, ("\n".join(lines) + "\n" if lines else "").encode(), 0o644)


def add_links(project: str, text: str, who: str) -> dict:
    """Add every http/https link in the text (URL or 'URL | note' per line); returns {added, skipped, links}."""
    if (folder(project) / LINKS_NAME).is_symlink():
        raise ReferenceError_("links.txt is a symbolic link, so nothing can be saved there.")
    if scrub.mask_patterns(text) != text:
        raise ReferenceError_("That text looks like it contains a secret (a key, token or password).")
    pairs = _parse_links(text)
    for url, _ in pairs:
        _check_url(url)
    current = list_links(project)
    seen = {l["url"] for l in current}
    added = []
    for url, note in pairs:
        if url not in seen:
            seen.add(url)
            added.append({"url": url, "note": note})
    if not pairs:
        raise ReferenceError_("No web links (starting http:// or https://) were found.")
    if len(current) + len(added) > MAX_LINKS:
        raise ReferenceError_(f"A project can hold at most {MAX_LINKS} links. Remove some first.")
    if added:
        _write_links(project, current + added)
    return {"added": added, "skipped": len(pairs) - len(added), "links": current + added}


def import_links_file(project: str, data: bytes, who: str) -> dict:
    """Read an uploaded .txt of URLs as a links list (see add_links)."""
    if len(data) > MAX_FILE:
        raise ReferenceError_("That file is too big to be a list of links.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ReferenceError_("That file is not readable text.")
    return add_links(project, text, who)


def remove_link(project: str, url: str) -> None:
    """Remove one saved link by its exact URL; refuses when it is not in the list."""
    current = list_links(project)
    left = [l for l in current if l["url"] != url]
    if len(left) == len(current):
        raise ReferenceError_("That link is not in the list.")
    _write_links(project, left)
