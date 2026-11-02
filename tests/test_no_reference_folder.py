"""Pins that no code, script or config points into the removed reference/ folder."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUFFIXES = {".py", ".sh", ".ts", ".tsx", ".toml", ".json"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".grunt", ".pytest_cache", "dist"}


def _allowed(line: str) -> bool:
    """A mention is fine only in a comment line or a 'Ported from' docstring line."""
    text = line.strip()
    return text.startswith(("#", "//", "Ported from"))


def test_no_code_uses_reference_folder():
    """No source file refers to reference/ except as a history comment."""
    bad = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in SUFFIXES:
            continue
        if SKIP_DIRS & set(path.relative_to(ROOT).parts) or path.name == Path(__file__).name:
            continue
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if "reference/" in line and not _allowed(line):
                bad.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()[:80]}")
    assert not bad, bad
