"""Merge: puts the run's branch into the project's main (auto), or opens a merge request and asks Alex (ask)."""
import fnmatch
import json
import re

from phoenix9 import atomic, deploy, git as gitmod, release, settings, state
from phoenix9.stepctx import StepResult

MR_FILE = "merge-request.txt"
NOTE_FILE = "merge-note.md"
DIRTY = "code/ has local changes"


class MergeError(Exception):
    """A plain-English reason the merge could not happen."""


def _first_line(text: str) -> str:
    """The first non-empty line of some output."""
    return next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "no details")


def _url_in(text: str) -> str:
    """The last https:// line of gh's output (gh pr create prints the new request's address)."""
    # ported from reference/v8/phoenix/run.py:274
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip().startswith("https://")]
    return lines[-1] if lines else ""


def _title(ctx) -> str:
    """The run's title."""
    return ctx.run.spec.get("title") or ctx.run.id


def _code_state(ctx):
    """Return (on main, clean) for the project's code/ folder."""
    git, code = ctx.adapters.git, ctx.project.code_dir
    on_main = git.git(code, "rev-parse", "--abbrev-ref", "HEAD").strip() == git.default_branch(code)
    clean = not git.git(code, "status", "--porcelain").strip()
    return on_main, clean


def _host_git(ctx, *args):
    """Run a git command that talks to the network, through the host adapter (safe flags kept)."""
    return ctx.adapters.host.run(["git", *gitmod.SAFE, "-C", str(ctx.project.code_dir), *args])


def _push(ctx, *refs):
    """Push refs to origin once; raise MergeError with a plain reason when it fails."""
    rc, out, err = _host_git(ctx, "push", "origin", *refs)
    if rc != 0:
        raise MergeError(f"GitHub refused the push: {_first_line(err or out)}")


def _repo_args(ctx) -> list:
    """`--repo owner/name` when origin is a GitHub address, else nothing."""
    m = re.search(r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?/?$", ctx.adapters.git.remote_url(ctx.project.code_dir))
    return ["--repo", m.group(1)] if m else []


def matches_safety(path, globs) -> bool:
    """Say whether a changed path matches any of the project's safety file globs."""
    return any(fnmatch.fnmatch(path, g) for g in globs)


def _flags(ctx, tasks, base, branch):
    """Return (flags, why parts) saying why this merge needs Alex."""
    flags, why = [], []
    failed = [n for n, t in tasks.items() if t["status"] == "failed"]
    if failed:
        flags.append(f"{len(failed)} tasks failed")
        why.append(f"{len(failed)} of {len(tasks)} tasks failed")
    else:
        why.append(f"all {len(tasks)} tasks passed")
    line = next((x for x in state.load(ctx.run.folder)["steps"] if x.get("step") == "full-suite"), None)
    if line and (line["status"] == "failed" or (line["status"] == "skipped" and (line.get("note") or "").startswith("skipped by"))):
        flags.append("full suite did not pass")
        why.append("the full suite did not pass")
    elif line and line["status"] == "passed":
        why.append("the full suite passed")
    names = ctx.adapters.git.git(ctx.project.code_dir, "diff", "--name-only", f"{base}..{branch}").split("\n")
    globs = ctx.project.settings.get("safety_files") or []
    hit = [n for n in names if n and matches_safety(n, globs)]
    if hit:
        flags.append("changes safety code")
        why.append("touches safety files: " + ", ".join(hit))
    return flags, why


def _local_merge(ctx, branch) -> str:
    """Merge the branch into code/ main with a merge commit; return the new sha."""
    git, code = ctx.adapters.git, ctx.project.code_dir
    git.git(code, *gitmod.IDENT, "merge", "--no-ff", branch, "-m", f"Merge run {ctx.run.id}: {_title(ctx)}")
    return git.head(code)


def _tag_release(ctx, sha) -> tuple[str, str]:
    """Tag a merge of Phoenix 9 itself as the next release; return (tag, note). Other projects: ("", "")."""
    if ctx.project.name != settings.update_settings()["project"]:
        return "", ""
    try:
        return release.tag_release(ctx.adapters, sha, who="runner")["tag"], ""
    except release.ReleaseError as err:
        ctx.adapters.notify.send("Phoenix 9 was merged but not tagged: run `phoenix update release`")
        return "", f"merged but not tagged ({err}): run `phoenix update release`"


def _preview_url(ctx) -> str:
    """The run's preview address, or "" when Preview did not make one."""
    url = str(ctx.things.get("preview-url") or "")
    return url if url.startswith("http") else ""


def _stop_preview(ctx) -> None:
    """Stop the run's preview after the merge was decided (best effort, logged)."""
    if _preview_url(ctx):
        ctx.log(deploy.try_stop_preview(ctx.adapters, ctx.project.name, ctx.run.id))


def _tidy(ctx, branch, pushed) -> list:
    """Delete a merged run branch here (and on GitHub when it was pushed); returns notes for what went wrong."""
    git, code = ctx.adapters.git, ctx.project.code_dir
    notes = []
    try:
        if ctx.worktree:
            git.git(ctx.worktree, "checkout", "-q", "--detach")   # the worktree keeps its files but lets go of the branch
        git.git(code, "branch", "-D", branch)
    except Exception as err:
        notes.append(f"merged, but the branch {branch} was not deleted here: {_first_line(str(err))}")
    if pushed:
        rc, out, err = _host_git(ctx, "push", "origin", "--delete", branch)
        if rc != 0:
            notes.append(f"merged, but the branch {branch} was not deleted on GitHub: {_first_line(err or out)}")
    return notes


def _auto(ctx, branch) -> StepResult:
    """Merge in code/ and push main and the branch when there is an origin."""
    sha = _local_merge(ctx, branch)
    preview = [f"preview was at {_preview_url(ctx)}"] if _preview_url(ctx) else []
    _stop_preview(ctx)
    if not ctx.adapters.git.remote_url(ctx.project.code_dir):
        return StepResult("pass", ["local only (no GitHub repo)", *_tidy(ctx, branch, False), *preview], produces={"merged": sha})
    _push(ctx, ctx.adapters.git.default_branch(ctx.project.code_dir), branch)
    tag, note = _tag_release(ctx, sha)
    reasons = [f"release: {tag}"] if tag else [note] if note else []
    return StepResult("pass", [*reasons, *_tidy(ctx, branch, True), *preview], produces={"merged": sha})


def _open_request(ctx, branch) -> str:
    """Push the branch and open (or find) the merge request; return its URL."""
    _push(ctx, branch)
    summary = ctx.run.folder / "summary.md"
    argv = ["pr", "create", *_repo_args(ctx), "--base", ctx.adapters.git.default_branch(ctx.project.code_dir),
            "--head", branch, "--title", _title(ctx)]
    if summary.is_file():
        argv += ["--body-file", str(summary)]
    rc, out, err = ctx.adapters.host.gh(*argv)
    url = _url_in(out)
    if rc != 0 or not url:
        raise MergeError(f"GitHub refused the merge request: {_first_line(err or out)}")
    (ctx.run.folder / MR_FILE).write_text(url + "\n")
    return url


def _ask(ctx, branch, flags, why) -> StepResult:
    """Open the merge gate (with a merge request when the project has a GitHub repo)."""
    links = []
    if ctx.adapters.git.remote_url(ctx.project.code_dir):
        links.append({"label": "Merge request", "url": _open_request(ctx, branch)})
        text = "; ".join(why)
    else:
        text = "local only: approve merges into code/ main; " + "; ".join(why)
    if _preview_url(ctx):
        links.append({"label": "Preview", "url": _preview_url(ctx)})
    links.append({"label": "Summary", "url": str(ctx.run.folder / "summary.md")})
    gate = {"kind": "merge", "title": f"Merge {_title(ctx)}?", "why": text, "links": links,
            "actions": ["approve", "back", "skip", "stop"], "flags": flags}
    return StepResult("gate", gate=gate)


def _sent_back(ctx) -> StepResult:
    """Alex sent the merge back: keep the note, comment on the merge request, pass."""
    _stop_preview(ctx)
    note = (ctx.answer.get("note") or "").strip() or "no note"
    (ctx.run.folder / NOTE_FILE).write_text(f"# Merge sent back\n\n{note}\n")
    mr = ctx.run.folder / MR_FILE
    if mr.is_file():
        rc, out, err = ctx.adapters.host.gh("pr", "comment", mr.read_text().strip(), "--body", f"Sent back: {note}")
        if rc != 0:
            return StepResult("fail", [f"GitHub refused the comment: {_first_line(err or out)}"])
    return StepResult("pass", [f"sent back: {note}"])


def run(ctx):
    """Merge the run's branch (auto), or open the merge gate (ask, or when something needs Alex)."""
    if ctx.answer and ctx.answer.get("action") == "back":
        return _sent_back(ctx)
    git, code = ctx.adapters.git, ctx.project.code_dir
    branch = git.branch_name(ctx.run.id)
    base = git.git(code, "merge-base", git.default_branch(code), branch).strip()
    if git.git(code, "rev-list", "--count", f"{base}..{branch}").strip() == "0":
        return StepResult("skip", ["No changes to merge"])
    tasks = state.load(ctx.run.folder)["tasks"]
    flags, why = _flags(ctx, tasks, base, branch)
    mode = ctx.project.settings.get("merge", "auto")
    try:
        if mode == "auto" and not flags:
            on_main, clean = _code_state(ctx)
            if on_main and clean:
                return _auto(ctx, branch)
            flags.append(DIRTY)
            why.append(DIRTY)
        return _ask(ctx, branch, flags, why)
    except MergeError as err:
        return StepResult("fail", [str(err)])


def _remember_merged(ctx, extra) -> dict:
    """Record the merged sha as the step's produced thing and return the event data."""
    path = ctx.run.folder / "things.json"
    things = json.loads(path.read_text()) if path.is_file() else {}
    things["merged"] = extra["merged"]
    atomic.write_json(path, things)
    return extra


def on_approved(ctx, produces) -> dict:
    """Alex approved: merge the request on GitHub (or locally for a local-only project) and update code/."""
    extra = _approved(ctx)
    _stop_preview(ctx)
    return extra


def _approved(ctx) -> dict:
    """Do the approved merge and return the event data."""
    git, code = ctx.adapters.git, ctx.project.code_dir
    on_main, clean = _code_state(ctx)
    mr = ctx.run.folder / MR_FILE
    if not mr.is_file():
        if not (on_main and clean):
            raise MergeError(f"{DIRTY}, so the run was not merged")
        branch = git.branch_name(ctx.run.id)
        sha = _local_merge(ctx, branch)
        notes = _tidy(ctx, branch, False)
        return _remember_merged(ctx, {"merged": sha, **({"note": "; ".join(notes)} if notes else {})})
    rc, out, err = ctx.adapters.host.gh("pr", "merge", mr.read_text().strip(), "--merge")
    if rc != 0:
        raise MergeError(f"GitHub refused the merge: {_first_line(err or out)}")
    extra = {}
    if on_main and clean:
        rc, out, err = _host_git(ctx, "pull", "--ff-only")
        if rc != 0:
            extra["note"] = f"code/ was not updated: {_first_line(err or out)}"
    else:
        extra["note"] = "code/ was not updated: it has local changes"
    extra["merged"] = git.head(code)
    if ctx.project.name == settings.update_settings()["project"]:
        extra = _release_after_ask(ctx, mr.read_text().strip(), extra)
    return _remember_merged(ctx, extra)


def _release_after_ask(ctx, url, extra) -> dict:
    """Tag the merge commit GitHub reports for the merged request; a failure only adds a note."""
    rc, out, err = ctx.adapters.host.gh("pr", "view", url, "--json", "mergeCommit", "--jq", ".mergeCommit.oid")
    sha = out.strip()
    if rc != 0 or not re.fullmatch(r"[0-9a-f]{40}", sha):
        ctx.adapters.notify.send("Phoenix 9 was merged but not tagged: run `phoenix update release`")
        note = f"merged but not tagged (could not read the merge commit: {_first_line(err or out)}): run `phoenix update release`"
        return {**extra, "note": "; ".join(x for x in (extra.get("note"), note) if x)}
    tag, note = _tag_release(ctx, sha)
    if tag:
        return {**extra, "release": tag}
    return {**extra, "note": "; ".join(x for x in (extra.get("note"), note) if x)}
