"""Ops for updating Phoenix 9: status, install, rollback, the updater log and tagging a release."""
from phoenix9 import paths, release as rel, updater
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
