"""Remembers whole-suite passes by the exact code tested, so the same code is never whole-suite tested twice."""
import hashlib
import json
from pathlib import Path

from phoenix9 import atomic, git, paths, settings, state

KEEP = 50


def key(tree_id, command, image, profile) -> str:
    """A sha256 id for one whole-suite result: the exact files, the command, the toolbox image and the profile."""
    text = json.dumps([str(tree_id), str(command), str(image), str(profile)])
    return hashlib.sha256(text.encode()).hexdigest()


def enabled() -> bool:
    """True unless the global setting `remember_suite_passes` is switched off."""
    return settings.remember_suite_passes()


def _file(project) -> Path:
    """The project's remembered-passes file in Phoenix's cache folder."""
    return paths.cache() / "suite-passes" / f"{project}.json"


def _load(project) -> list:
    """The remembered entries, oldest first; anything unreadable counts as nothing remembered."""
    try:
        data = json.loads(_file(project).read_text(encoding="utf-8"))
        return [e for e in data if isinstance(e, dict) and isinstance(e.get("key"), str)]
    except (OSError, ValueError, TypeError):
        return []


def remember(project, key, facts=None) -> None:
    """Remember a passing whole-suite result (newest 50 kept); never raises."""
    if not enabled():
        return
    try:
        entries = [e for e in _load(project) if e["key"] != key]
        entries.append({"key": key, "at": state.now(), "facts": dict(facts or {})})
        path = _file(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic.write_json(path, entries[-KEEP:])
    except OSError:
        pass


def lookup(project, key) -> dict | None:
    """The remembered pass for this key ({key, at, facts}), or None."""
    if not enabled():
        return None
    return next((e for e in _load(project) if e["key"] == key), None)


def image_identity(run_folder, profile) -> str:
    """The toolbox image the run recorded (its id when known, else its tag)."""
    recorded = (state.load(run_folder).get("image") or {})
    return recorded.get("id") or recorded.get("tag") or (profile or {}).get("image", "")


def key_for(ctx, tree, command) -> str:
    """The key for this step's project, the given tree, command and the run's image and profile."""
    profile = ctx.project.settings.get("profile", "") or ctx.project.profile.get("name", "")
    return key(tree, command, image_identity(ctx.run.folder, ctx.project.profile), profile)


def tree_of(checkout) -> str:
    """The tree id of a clean checkout including its uncommitted changes."""
    return git.tree_id(checkout)
