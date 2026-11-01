"""Release tags for Phoenix 9 itself: pick the next v9.<n> and create it on GitHub."""
import json
import re

from phoenix9 import events, scrub, settings


class ReleaseError(Exception):
    """A plain-English reason a release tag could not be made."""


def next_tag(existing: list[str], prefix: str = "v9.") -> str:
    """The tag after the highest `<prefix><number>` in the list (none -> `<prefix>0`); other names are ignored."""
    pattern = re.compile(rf"^{re.escape(prefix)}(0|[1-9][0-9]*)$")
    numbers = [int(m.group(1)) for t in existing if (m := pattern.match(t))]
    return f"{prefix}{max(numbers) + 1 if numbers else 0}"


def _gh(adapters, *args) -> str:
    """Run gh through the host adapter; ReleaseError with the first line of its complaint when it fails."""
    rc, out, err = adapters.host.gh(*args)
    if rc != 0:
        first = next((ln.strip() for ln in (err or out or "").splitlines() if ln.strip()), "no details")
        raise ReleaseError(scrub.scrub(f"GitHub said: {first}"))
    return out


def remote_tags(adapters) -> dict:
    """{tag: commit sha} for every release-prefixed tag on the repo."""
    conf = settings.update_settings()
    out = _gh(adapters, "api", f"repos/{conf['repo']}/git/matching-refs/tags/{conf['tag_prefix']}")
    try:
        rows = json.loads(out or "[]")
        return {r["ref"].removeprefix("refs/tags/"): (r.get("object") or {}).get("sha", "") for r in rows}
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ReleaseError("GitHub's list of tags was not readable") from None


def main_sha(adapters) -> str:
    """The commit at the tip of main on GitHub."""
    conf = settings.update_settings()
    sha = _gh(adapters, "api", f"repos/{conf['repo']}/commits/main", "--jq", ".sha").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ReleaseError("GitHub did not give a commit for main")
    return sha


def tag_release(adapters, sha: str, *, who: str) -> dict:
    """Create the next release tag on `sha` and tell Alex; returns {tag, sha}."""
    conf = settings.update_settings()
    tag = next_tag(list(remote_tags(adapters)), conf["tag_prefix"])
    _gh(adapters, "api", "-X", "POST", f"repos/{conf['repo']}/git/refs", "-f", f"ref=refs/tags/{tag}", "-f", f"sha={sha}")
    events.emit("command", project=None, who=who, command=f"released {tag}")
    adapters.notify.send(f"Phoenix 9 {tag} is ready to install")
    return {"tag": tag, "sha": sha}
