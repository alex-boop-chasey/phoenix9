"""Finishing a quick edit: the same checks a build uses, then commit, push and a merge request."""
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
    return SimpleNamespace(code=project_dir / "code", settings=settings.load_project(project_dir), profile=profile)


def _run_tests(adapters, rec: dict, ctx, worktree: Path) -> list[str]:
    """Run the profile's test command in a sealed container on a clean copy of the edit; return the problems."""
    test = ctx.profile.get("test") or {}
    if not test.get("cmd"):
        return ["This project's profile has no test command, so Phoenix cannot check the edit."]
    if not ctx.profile.get("image"):
        return ["This project's profile has no step image to run the tests in."]
    project, edit_id = rec["project"], rec["id"]
    checkout = paths.home() / "work" / f"edit-{edit_id}"
    log = paths.home() / "logs" / f"edit-{edit_id}-tests.txt"
    git.rmtree(checkout)
    git.fresh_checkout(worktree, checkout)
    try:
        domains = docker.write_domains_file(project, ctx.profile.get("allowed_domains", ()),
                                            (ctx.settings.get("domains") or {}).get("allow") or [])
        with keys.env_file(project) as env_file:
            rc, _ = docker.run_check_container(adapters.docker, project, f"edit-{edit_id}", 0, 1, ctx.profile["image"],
                                               checkout, test["cmd"], env_file, domains, TEST_MINUTES,
                                               stdout_path=log, role="edit-tests")
    finally:
        git.remove_checkout(worktree, checkout)
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


def check(adapters, rec: dict) -> tuple[list[str], list]:
    """Run every check on an edit; return (problems in plain words, the changes against the base branch)."""
    worktree, ctx = Path(rec["folder"]), _context(rec)
    base = git.git(worktree, "merge-base", "HEAD", git.default_branch(ctx.code)).strip()
    changes = git.diff_changes(worktree, base)
    if not changes:
        return ["The edit has no changes yet."], changes
    problems = _diff_problems(ctx, changes) + _secret_problems(rec, worktree, base, changes)
    problems += _lockfile_problems(ctx, worktree)
    return problems + _run_tests(adapters, rec, ctx, worktree), changes


def _body(rec: dict, changes) -> str:
    """The merge request text: what changed, then who made it."""
    files = "\n".join(f"- {c.status} {c.path}" for c in changes[:50])
    return f"{rec['title']}\n\nWhat changed:\n{files}\n\nQuick edit by the Phoenix agent"


def publish(adapters, rec: dict, message: str, changes) -> str:
    """Commit, push the branch and open the merge request; return the merge request link ."""
    worktree, host = Path(rec["folder"]), adapters.host
    ctx = _context(rec)
    base = git.default_branch(ctx.code)
    try:
        git.commit(worktree, message, {"Phoenix-Edit": rec["id"]}, allow_empty=False)
    except git.GitError:
        pass                                    # already committed by an earlier try that failed to push
    rc, _, err = host.run(["git", *SAFE, "-C", str(worktree), "push", "-u", "origin", rec["branch"]], 300)
    if rc != 0:
        raise RuntimeError(f"I could not push the branch: {scrub.scrub(err.strip())[-300:]}")
    rc, out, err = host.run(["gh", "pr", "create", "--title", rec["title"], "--body", _body(rec, changes),
                             "--base", base, "--head", rec["branch"]], 120, cwd=worktree)
    if rc != 0:
        raise RuntimeError(f"I could not open the merge request: {scrub.scrub(err.strip())[-300:]}")
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return lines[-1] if lines else ""
