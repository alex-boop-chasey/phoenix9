"""Safe file writes: write to a temp file, then swap it in, so readers never see half a file."""
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_text(path: Path, text: str, mode: int | None = None) -> None:
    """Write text to path atomically, optionally setting its permission bits."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_json(path: Path, data: Any, mode: int | None = None) -> None:
    """Write data as pretty JSON atomically."""
    write_text(path, json.dumps(data, indent=2, sort_keys=False) + "\n", mode)


def read_json(path: Path, default: Any = None) -> Any:
    """Read JSON from path, or return default when the file does not exist."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write_bytes(path: Path, data: bytes, mode: int | None = None) -> None:
    """Write raw bytes to path atomically, optionally setting its permission bits."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
