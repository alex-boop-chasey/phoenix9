"""The github-release deployer: builds files in a sealed container, then tags and publishes a GitHub release through the key proxy."""
import json
import re
from pathlib import Path
from urllib.parse import quote

from phoenix9 import docker, git, paths, project, scrub, settings
from phoenix9.deploy import DeployError, last_good

REPO_RE = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")
PROFILE_BUILDS = {"python-script": "python3 -m pip wheel --no-deps -w /out .",
                  "desktop": ""}                      # every other profile builds nothing
NO_BUILD = "none"
MAX_TOTAL = 2 * 1024 ** 3
BUILD_MINUTES = 30
NOTE_LINES = 50


# ---------- settings ----------
def _repo(dctx) -> str:
    """The repo to release to: the setting, else the project's own repo; DeployError when it is not owner/name."""
    repo = dctx.settings["repo"]
    if not repo:
        parts = project.split_repo(project.repo_of(dctx.project.folder))
        repo = f"{parts['owner']}/{parts['name']}" if parts["owner"] else ""
    if not repo or not REPO_RE.match(repo):
        raise DeployError(f"github-release needs a repo written owner/name (got '{repo or ''}'); set repo in [deploy.settings]")
    return repo


def _build_command(dctx) -> str:
    """The build command to run, or 'none'."""
    command = dctx.settings["build_command"]
    if command:
        return command
    default = PROFILE_BUILDS.get(project.profile_of(dctx.project.folder), NO_BUILD)
    if not default:
        raise DeployError("set build_command for desktop releases")
    return default


# ---------- GitHub through the proxy ----------
def _call(dctx, method: str, path: str, payload=None, *, raw: bytes | None = None, ok=(200, 201, 204)):
    """One call to the key proxy; returns (status, parsed JSON or None). DeployError for a status outside `ok`."""
    headers = {"X-Phoenix-Proxy-Token": dctx.proxy["token"], "Accept": "application/vnd.github+json"}
    body = raw
    if raw is not None:
        headers["Content-Type"] = "application/octet-stream"
    elif payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode()
    dctx.log(f"{method} {path.split('?')[0]}")
    status, _, data = dctx.adapters.http.request(method, dctx.proxy["url"] + path, headers=headers, body=body, timeout=300)
    try:
        parsed = json.loads(data) if data else None
    except ValueError:
        parsed = None
    if status not in ok:
        said = parsed.get("message") if isinstance(parsed, dict) else ""
        raise DeployError(scrub.scrub(f"GitHub answered {status} to {method} {path.split('?')[0]}" + (f": {said}" if said else "")))
    return status, parsed


def _tag_numbers(dctx, repo: str, prefix: str) -> tuple[list[int], dict]:
    """(numbers in use, {sha: tag}) for tags that are the prefix followed by a number."""
    _, refs = _call(dctx, "GET", f"/repos/{repo}/git/matching-refs/tags/{quote(prefix)}")
    pattern = re.compile(rf"^refs/tags/{re.escape(prefix)}(\d+)$")
    numbers, shas = [], {}
    for ref in refs or []:
        m = pattern.match(str(ref.get("ref", "")))
        if m:
            numbers.append(int(m.group(1)))
            shas[(ref.get("object") or {}).get("sha", "")] = f"{prefix}{m.group(1)}"
    return numbers, shas


def next_tag(dctx, repo: str) -> str:
    """The next numeric tag (v1, v2 ...); DeployError when this commit already has one."""
    prefix = dctx.settings["tag_prefix"]
    numbers, shas = _tag_numbers(dctx, repo, prefix)
    if dctx.commit and dctx.commit in shas:
        raise DeployError(f"this commit is already released as {shas[dctx.commit]}")
    return f"{prefix}{max(numbers) + 1 if numbers else 1}"


# ---------- release notes ----------
def _changelog_notes(dctx) -> str:
    """Changelog lines dated on or after the previous release (all recent lines when there is none)."""
    path = dctx.project.folder / "notes" / "changelog.md"
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError:
        return ""
    before = last_good(dctx.project.name)
    since = (before or {}).get("at", "")[:10]
    if since:
        lines = [ln for ln in lines if not re.match(r"^- \d{4}-\d\d-\d\d", ln) or ln[2:12] >= since]
    return "\n".join(lines[-NOTE_LINES:])


def _commit_notes(dctx) -> str:
    """Commit subjects since the previous release's commit (the last 20 when there is none)."""
    before = (last_good(dctx.project.name) or {}).get("commit")
    spans = [[f"{before}..{dctx.commit}"]] if before and dctx.commit else []
    for span in spans + [["-20", dctx.commit or "HEAD"]]:
        try:
            out = git.git(dctx.source_dir, "log", "--format=- %s", *span)
            return out.strip()
        except Exception:
            continue
    return ""


def release_notes(dctx) -> str:
    """The release text, scrubbed."""
    text = _commit_notes(dctx) if dctx.settings["notes_from"] == "commits" else _changelog_notes(dctx)
    return scrub.scrub(text)


# ---------- the build, sealed in a check container ----------
def _release_folder(dctx, tag: str) -> Path:
    base = paths.runs(dctx.project.name) / dctx.run_id if dctx.run_id else paths.logs()
    return base / f"release-{tag}"


def _build(dctx, tag: str, command: str) -> Path:
    """Run the build command in a firewalled check container; returns the host folder that was /out."""
    folder = _release_folder(dctx, tag)
    out_dir, checkout, log = folder / "out", folder / "checkout", folder / "build.txt"
    git.rmtree(folder)
    out_dir.mkdir(parents=True)
    docker.hand_to_agent(dctx.adapters.docker, out_dir)
    prof = settings.load_profile(paths.library(), project.profile_of(dctx.project.folder))
    domains = docker.write_domains_file(dctx.project.name, prof.get("allowed_domains", ()),
                                        (dctx.project.settings.get("domains") or {}).get("allow") or [])
    git.fresh_checkout(dctx.source_dir, checkout)
    try:
        rc, _ = docker.run_check_container(
            dctx.adapters.docker, dctx.project.name, dctx.run_id or "release", tag, 1, prof.get("image", ""),
            checkout, command, None, domains, BUILD_MINUTES, stdout_path=log, role="release",
            mounts=[docker.Mount(out_dir, "/out", ro=False)])
    finally:
        git.remove_checkout(dctx.source_dir, checkout)
    if rc != 0:
        tail = scrub.scrub(log.read_text(errors="replace")).splitlines()[-20:] if log.exists() else []
        raise DeployError(f"the build failed (exit {rc}):\n" + "\n".join(tail))
    return out_dir


def collect_artefacts(out_dir: Path, patterns: list[str]) -> list[Path]:
    """Files in out_dir matching the globs (all files when none): no symlinks, nothing outside, at most 2 GB in all."""
    root = Path(out_dir).resolve()
    found: dict[str, Path] = {}
    for pattern in patterns or ["**/*"]:
        if pattern.startswith("/") or ".." in Path(pattern).parts:
            raise DeployError(f"artefact pattern '{pattern}' must stay inside /out")
        for path in sorted(root.glob(pattern)):
            if path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(root)
            if any((root / Path(*rel.parts[:i + 1])).is_symlink() for i in range(len(rel.parts))):
                continue
            found[str(rel)] = path
    files = [found[k] for k in sorted(found)]
    names = [f.name for f in files]
    if len(set(names)) != len(names):
        raise DeployError("two build files have the same name; narrow the artefacts patterns")
    if sum(f.stat().st_size for f in files) > MAX_TOTAL:
        raise DeployError("the build files add up to more than 2 GB")
    return files


# ---------- the deployer functions ----------
def _partial(repo: str, tag: str, release_id) -> dict:
    return {"target": repo, "version": tag, "details": {"release_id": release_id, "assets": []}}


def _publish(dctx, repo: str, tag: str, files: list[Path], state: dict) -> dict:
    """Tag, release and upload; `state` is kept up to date so a failure knows what to remove."""
    _call(dctx, "POST", f"/repos/{repo}/git/refs", {"ref": f"refs/tags/{tag}", "sha": dctx.commit})
    state["tag"] = True
    _, release = _call(dctx, "POST", f"/repos/{repo}/releases", {
        "tag_name": tag, "name": tag, "body": release_notes(dctx), "draft": False, "prerelease": False})
    release = release or {}
    state["release_id"] = release.get("id")
    if not state["release_id"]:
        raise DeployError("GitHub did not say the id of the new release")
    for f in files:
        _call(dctx, "POST", f"/repos/{repo}/releases/{state['release_id']}/assets?name={quote(f.name)}",
              raw=f.read_bytes())
        state["assets"].append(f.name)
    return release


def deploy(dctx) -> dict:
    """Build the files, tag the commit, publish the release and upload the files; undo the tag and release on failure."""
    repo = _repo(dctx)
    tag = next_tag(dctx, repo)
    command = _build_command(dctx)
    files = []
    if command != NO_BUILD:
        out_dir = _build(dctx, tag, command)
        files = collect_artefacts(out_dir, dctx.settings["artefacts"])
        if not files:
            raise DeployError("the build ran but left no files in /out to attach")
    state = {"tag": False, "release_id": None, "assets": []}
    try:
        release = _publish(dctx, repo, tag, files, state)
    except Exception:
        result = _partial(repo, tag if state["tag"] else "", state["release_id"])
        try:
            rollback(dctx, result, None)
        except Exception as err:
            dctx.log(f"cleaning up the half release failed: {err}")
        raise
    return {"target": repo, "url": release.get("html_url", ""), "version": tag,
            "details": {"release_id": state["release_id"], "assets": state["assets"]}}


def health(dctx, result) -> tuple[bool, str]:
    """The release is there under its tag and carries exactly the uploaded files."""
    repo, tag = result.get("target") or _repo(dctx), result["version"]
    try:
        _, release = _call(dctx, "GET", f"/repos/{repo}/releases/tags/{quote(tag)}", ok=(200,))
    except DeployError as err:
        return False, str(err)
    have = sorted(a.get("name") for a in (release or {}).get("assets") or [])
    want = sorted((result.get("details") or {}).get("assets") or [])
    if have != want:
        missing = sorted(set(want) - set(have))
        return False, "release files differ from what was uploaded" + (f"; missing {', '.join(missing)}" if missing else "")
    return True, f"{tag} is published with {len(have)} file(s)"


def rollback(dctx, result, previous) -> dict:
    """Delete the new release and its tag; the previous release stays the latest."""
    repo, tag = (result or {}).get("target") or _repo(dctx), (result or {}).get("version") or ""
    release_id = ((result or {}).get("details") or {}).get("release_id")
    if release_id:
        _call(dctx, "DELETE", f"/repos/{repo}/releases/{release_id}", ok=(200, 204, 404))
    if tag:
        _call(dctx, "DELETE", f"/repos/{repo}/git/refs/tags/{quote(tag)}", ok=(200, 204, 404, 422))
    return {"removed": tag}
