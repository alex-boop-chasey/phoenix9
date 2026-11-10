"""Checks that agentkit's pinned environment has the packages it needs, at the locked versions."""
import importlib
from importlib import metadata
from pathlib import Path

LOCK = Path(__file__).resolve().parent.parent / "requirements.lock"


def locked_versions():
    """Read requirements.lock into a name -> version map."""
    found = {}
    for line in LOCK.read_text().splitlines():
        if "==" in line:
            name, version = line.strip().split("==", 1)
            found[name.lower().replace("_", "-")] = version
    return found


def test_key_packages_import():
    for module in ("pydantic_ai", "starlette", "uvicorn", "httpx"):
        importlib.import_module(module)


def test_versions_match_lock():
    locked = locked_versions()
    for package in ("pydantic-ai-slim", "starlette", "uvicorn", "httpx"):
        assert metadata.version(package) == locked[package]


def test_every_lock_line_is_pinned():
    for line in LOCK.read_text().splitlines():
        assert line.count("==") == 1, line
