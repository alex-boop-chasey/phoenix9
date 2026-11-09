"""Finishing a quick edit (a safety file): commit first, check that exact commit like a build does, then push
that commit and open a merge request for Alex.

The edit is squashed into one commit on top of its base, so nothing earlier (a file added and removed again)
is ever pushed. The checks run on a clean checkout of that commit, and the push sends exactly that commit id;
it is refused when the branch copy moved on or has uncommitted changes by then."""
import fnmatch
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from . import atomic, docker, git, keys, paths, scrub, settings
from .library import load_library

TEST_MINUTES = 10
SAFE = git.SAFE


def _context(rec: dict):
    """The project's folders, phoenix.toml settings and profile, as the checks need them."""
    project_dir = paths.projects() / rec["project"]
    values = settings.effective(project_dir, load_library(paths.library())).values
    name = values.get("profile") or ""
    profile = settings.load_profile(paths.library(), name) if name else {}
    return SimpleNamespace(code=project_dir / "code", settings=settings.load_project(project_dir), profile=profile,
                           safety_files=list(values.get("safety_files") or []))


def _run_tests(adapters, rec: dict, ctx, checkout: Path) -> list[str]:
    """Run the profile's test command in a sealed container on the clean checkout of the edit's commit; return the problems."""
    test = ctx.profile.get("test") or {}
    if not test.get("cmd"):
        return ["This project's profile has no test command, so Phoenix cannot check the edit."]
    if not ctx.profile.get("image"):
        return ["This project's profile has no step image to run the tests in."]
    project, edit_id = rec["project"], rec["id"]
    log = paths.home() / "logs" / f"edit-{edit_id}-tests.txt"
    domains = docker.write_domains_file(project, ctx.profile.get("allowed_domains", ()),
                                        (ctx.settings.get("domains") or {}).get("allow") or [])
    with keys.env_file(project) as env_file:
        rc, _ = docker.run_check_container(adapters.docker, project, f"edit-{edit_id}", 0, 1, ctx.profile["image"],
                                           checkout, test["cmd"], env_file, domains, TEST_MINUTES,
                                           stdout_path=log, role="edit-tests")
    if log.exists():
        atomic.write_text(log, scrub.scrub(log.read_text(errors="replace")))
    if rc == docker.TIMEOUT_RC:
        return [f"The tests ran out of time ({TEST_MINUTES} minutes)."]
    return [f"The tests failed (exit {rc}). The output is in {log}."] if rc != 0 else []


def _diff_problems(ctx, changes) -> list[str]:
    """Plain reasons for every changed file the diff rules refuse."""
    diff = ctx.settings.get("diff") or {}
    bad = git.check_changes(changes, allow_extra=[*ctx.profile.get("diff_allow_extra", ()), *diff.get("allow_extra", ())],
                            deny_extra=list(diff.get("deny_extra", ())), locked=())
    out = []
    for line in bad:
        head, _, why = line.rpartition(": ")
        out.append(f"Not allowed to change {head.split(' ', 1)[-1]} ({why})")
    return out


def _secret_problems(rec: dict, worktree: Path, base: str, changes) -> list[str]:
    """Plain reasons for every secret the change writes into the code (never the value)."""
    env_files = sorted(paths.secrets().glob("*.env")) if paths.secrets().is_dir() else []
    values = [*keys.secret_values(rec["project"]), *scrub.secrets_from(env_files), *scrub.known_secrets()]
    forms = git.secret_forms(values)
    found = git.scan_added_lines(git.diff_text(worktree, base), forms)
    bad = [f"A secret was written into {p} (line {n}): it looks like {what}. Remove it." for p, n, what in found]
    for c in changes:
        f = worktree / c.path
        if c.status != "D" and c.binary and f.is_file() and f.stat().st_size <= 5_000_000 \
                and git.find_secrets(f.read_bytes().decode("latin-1"), forms):
            bad.append(f"A secret was written into {c.path}")
    return bad


def _lockfile_problems(ctx, worktree: Path) -> list[str]:
    """Plain reasons for every package list that has no lockfile (the build's lockfile check)."""
    spec = importlib.util.spec_from_file_location("edit_lockfile_step", paths.library() / "steps" / "lockfile" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    tracked = {p for p in git.git(worktree, "ls-files", "-z").split("\0") if p}
    bad = []
    for manifest in mod.DEFAULTS:
        if manifest not in tracked or (manifest == "pyproject.toml" and not mod._has_dependencies(worktree)):
            continue
        names = mod._accepted(ctx.profile, manifest)
        if not any(n in tracked for n in names):
            bad.append(f"{manifest} has no committed lockfile. Install with the package manager so it writes "
                       f"{' or '.join(names)}, and commit that file.")
    return bad


def _safety_problems(ctx, changes, who: str) -> list[str]:
    """A chat (who chat:*) may not change the project's safety files (the same rule as a repair's hand fix)."""
    if not (who or "").startswith("chat:"):
        return []
    return [f"{c.path} is a safety file (only Alex may change it)" for c in changes
            if any(fnmatch.fnmatch(p, g) for p in filter(None, (c.path, c.old_path)) for g in ctx.safety_files)]


def base_of(rec: dict) -> str:
    """The commit the edit started from (where its branch copy left the project's main branch)."""
    worktree, ctx = Path(rec["folder"]), _context(rec)
    return git.git(worktree, "merge-base", "HEAD", git.default_branch(ctx.code)).strip()


def commit_edit(rec: dict, message: str, who: str) -> str | None:
    """Squash everything in the branch copy into one commit on top of the base; return its id (None: no changes)."""
    worktree, base = Path(rec["folder"]), base_of(rec)
    git.git(worktree, "reset", "-q", "--soft", base)
    try:
        return git.commit(worktree, message, {"Phoenix-Edit": rec["id"], "Phoenix-Fix-By": who or "cli"},
                          allow_empty=False)
    except git.GitError:
        return None                             # the copy holds nothing the base does not


def check(adapters, rec: dict, sha: str | None = None, who: str = "cli") -> tuple[list[str], list]:
    """Run every check on the edit's commit `sha` (default: the branch copy's HEAD), on a clean checkout of
    exactly that commit; return (problems in plain words, the changes against the base)."""
    worktree, ctx = Path(rec["folder"]), _context(rec)
    base = base_of(rec)
    sha = sha or git.head(worktree)
    if sha == base:
        return ["The edit has no changes yet."], []
    checkout = paths.home() / "work" / f"edit-{rec['id']}"
    git.rmtree(checkout)
    git.git(worktree, "worktree", "prune")
    git.commit_checkout(worktree, sha, checkout)
    try:
        changes = git.diff_changes(checkout, base)
        if not changes:
            return ["The edit has no changes yet."], changes
        problems = _diff_problems(ctx, changes) + _safety_problems(ctx, changes, who)
        problems += _secret_problems(rec, checkout, base, changes) + _lockfile_problems(ctx, checkout)
        return problems + _run_tests(adapters, rec, ctx, checkout), changes
    finally:
        git.remove_checkout(worktree, checkout)


def _body(rec: dict, changes, who: str) -> str:
    """The merge request text: what changed, then who made it."""
    files = "\n".join(f"- {c.status} {c.path}" for c in changes[:50])
    return f"{rec['title']}\n\nWhat changed:\n{files}\n\nMade by {who or 'cli'}; Alex merges this.\n"


LABEL = "needs Alex"


def _label(host, worktree: Path) -> bool:
    """Make sure the repo has the "needs Alex" label; True when it is there (a failure is tolerated)."""
    rc, out, err = host.run(["gh", "label", "create", LABEL, "--color", "D93F0B",
                             "--description", "Made by Phoenix or its agent; only Alex merges it"], 60, cwd=worktree)
    return rc == 0 or "already exists" in f"{out} {err}".lower()


def publish(adapters, rec: dict, sha: str, changes, who: str = "cli") -> str:
    """Push exactly the checked commit to edit/<id> and open the merge request; return its link.

    Refused when the branch copy moved on from that commit or has uncommitted changes."""
    worktree, host = Path(rec["folder"]), adapters.host
    ctx = _context(rec)
    base = git.default_branch(ctx.code)
    if not git.SHA_RE.fullmatch(sha or ""):
        raise RuntimeError("The checked commit id is not a commit id.")
    if git.head(worktree) != sha:
        raise RuntimeError("The branch copy changed after the checks (a new commit). Run `phoenix edit finish` again.")
    if git.pending_paths(worktree):
        raise RuntimeError("The branch copy has changes that were not checked. Run `phoenix edit finish` again.")
    rc, _, err = host.run(["git", *SAFE, "-C", str(worktree), "push", "origin", f"{sha}:refs/heads/{rec['branch']}"], 300)
    if rc != 0:
        raise RuntimeError(f"I could not push the branch: {scrub.scrub(err.strip())[-300:]}")
    argv = ["gh", "pr", "create", "--title", rec["title"], "--body", _body(rec, changes, who),
            "--base", base, "--head", rec["branch"]]
    labelled = _label(host, worktree)
    rc, out, err = host.run(argv + (["--label", LABEL] if labelled else []), 120, cwd=worktree)
    if rc != 0 and labelled:                      # the label is a nice-to-have: never lose the merge request over it
        rc, out, err = host.run(argv, 120, cwd=worktree)
    if rc != 0:
        raise RuntimeError(f"I could not open the merge request: {scrub.scrub(err.strip())[-300:]}")
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return lines[-1] if lines else ""
