"""Ops for updating Phoenix 9: status, install, rollback, the updater log, tagging a release and growing the safety list."""
import tomllib
from pathlib import Path

from phoenix9 import atomic, events, paths, release as rel, settings, updater
from phoenix9.ops import common
from phoenix9.ops.common import OpsError

CHECKS_PREFIX, CHECKS_SUFFIX = "update-", "-checks.txt"


def status(refresh: bool = False) -> dict:
    """The updater's status (installed, previous, newest, running, last result)."""
    return updater.status(common.make_adapters(), refresh=refresh)


def _queue(action: str, tag: str | None, who: str) -> dict:
    """Queue an updater request and start its unit; OpsError when it was refused."""
    out = updater.request(action, tag, who, common.make_adapters())
    if not out["ok"]:
        raise OpsError(f"The {action} did not start: {out['reason']}.")
    return out


def install(tag: str | None, who: str, yes: bool) -> dict:
    """Queue an install of `tag` (the newest tag when omitted); needs yes."""
    if not yes:
        raise OpsError("Installing an update restarts Phoenix 9. Add --yes to go ahead.")
    st = status(False)
    if st["installed"] is None:
        raise OpsError("Phoenix 9 is not installed yet.")
    tag = tag or st.get("newest")
    if not tag:
        raise OpsError("There is no newer version to install. Try `phoenix update status --refresh`.")
    out = _queue("install", tag, who)
    common.record_command(who, f"update install {tag}")
    return out


def rollback(who: str, yes: bool) -> dict:
    """Queue a rollback to the previous version; needs yes."""
    if not yes:
        raise OpsError("Rolling back restarts Phoenix 9. Add --yes to go ahead.")
    out = _queue("rollback", None, who)
    common.record_command(who, "update rollback")
    return out


def _last_checks() -> str | None:
    """The file name of the newest checks output of an install, or None."""
    files = sorted(paths.logs().glob(f"{CHECKS_PREFIX}*{CHECKS_SUFFIX}"), key=lambda p: p.stat().st_mtime) \
        if paths.logs().is_dir() else []
    return files[-1].name if files else None


def log(lines: int = 200) -> dict:
    """The tail of the updater log and the name of the last checks file."""
    try:
        text = (paths.logs() / "updater.log").read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        text = []
    return {"lines": text[-max(lines, 1):], "checks_file": _last_checks()}


def release(who: str, yes: bool) -> dict:
    """Tag the current tip of main as the next release unless it already has a tag; needs yes."""
    if not yes:
        raise OpsError("Tagging a release is public. Add --yes to go ahead.")
    adapters = common.make_adapters()
    try:
        sha = rel.main_sha(adapters)
        known = {v: k for k, v in rel.remote_tags(adapters).items()}
        if sha in known:
            return {"ok": True, "tag": known[sha], "sha": sha, "created": False}
        out = rel.tag_release(adapters, sha, who=who)
    except rel.ReleaseError as err:
        raise OpsError(str(err)) from None
    common.record_command(who, f"update release {out['tag']}")
    return {"ok": True, **out, "created": True}



def history() -> list[dict]:
    """Past installs and roll-backs the updater recorded, newest first."""
    return updater.read_history()


def after_install(who: str) -> dict:
    """Grow Phoenix's own safety list from the installed copy (run by the updater after an install); {safety_added}."""
    common.record_command(who, "update after-install")
    return {"safety_added": add_safety_files()}


def _toml(path: Path) -> dict:
    """A TOML file as a dict ({} when missing or unreadable)."""
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _skip_safety(live: Path, why: str) -> list[str]:
    """Log that the safety list was left alone, and add nothing."""
    events.emit("update.safety_files_skipped", project=None, path=str(live), why=why)
    return []


def add_safety_files() -> list[str]:
    """Add the installed self-project.toml's safety_files that Phoenix's live phoenix.toml lacks (never remove).

    The live file is read with tomllib, the list grown (add only) and the file written back by the same writer
    `phoenix settings add` uses (same layout, atomic). A live file that does not parse is left alone (logged);
    the new text is parsed again before writing and nothing is written unless it gives back exactly the merged
    settings."""
    wanted = _toml(paths.install() / "deploy" / "self-project.toml").get("safety_files") or []
    folder = paths.projects() / "phoenix9"
    live = settings.project_file(folder)
    if not live.is_file():
        return []
    try:
        data = settings.load_project(folder)
    except settings.SettingsError as e:
        return _skip_safety(live, f"phoenix.toml does not parse, so it was left alone ({e})")
    have = data.get("safety_files")
    if have is not None and not isinstance(have, list):
        return _skip_safety(live, "safety_files in phoenix.toml is not a list, so it was left alone")
    have = list(have or [])
    added = []
    for w in wanted:
        if isinstance(w, str) and w not in have and w not in added:
            added.append(w)
    if not added:
        return []
    data["safety_files"] = have + added      # top level, never inside a table
    try:
        text = settings.render_project(data)
        again = tomllib.loads(text)
    except (TypeError, ValueError) as e:
        return _skip_safety(live, f"the new phoenix.toml would not parse ({e}), so nothing was written")
    if again != settings.prune(data):
        return _skip_safety(live, "the new phoenix.toml would not read back the same, so nothing was written")
    atomic.write_text(live, text)
    events.emit("update.safety_files_added", project=None, added=added)
    return added
