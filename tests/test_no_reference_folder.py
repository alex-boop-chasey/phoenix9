"""Pins that no code, script or config points into the removed reference/ folder."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUFFIXES = {".py", ".sh", ".ts", ".tsx", ".toml", ".json"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".grunt", ".pytest_cache", "dist", ".venv"}


# The reference-uploads feature (a project's own notes/reference/ folder) is a different thing from the
# removed repo folder: its API routes, the builds' read-only copy and the dashboard's feature folder are fine.
FEATURE = re.compile(r"/reference/(?:files|links|vision)\b|/phoenix/reference/|notes/reference/|features/reference/")


def _allowed(line: str) -> bool:
    """A mention is fine in a comment line, a 'Ported from' docstring line, or as the uploads feature."""
    text = line.strip()
    return text.startswith(("#", "//", "Ported from")) or "reference/" not in FEATURE.sub("", text)


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
