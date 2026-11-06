"""Lockfile check: fails the run if the code has a package list but no committed lockfile for it."""
import tomllib

from phoenix9 import git
from phoenix9.stepctx import StepResult

DEFAULTS = {
    "package.json": ("pnpm-lock.yaml", "package-lock.json", "yarn.lock"),
    "Cargo.toml": ("Cargo.lock",),
    "pyproject.toml": ("uv.lock", "poetry.lock"),
}


def _tracked(worktree) -> set[str]:
    """Every file committed at the worktree's HEAD."""
    out = git.git(worktree, "ls-tree", "-r", "--name-only", "-z", "HEAD")
    return {p for p in out.split("\0") if p}


def _has_dependencies(worktree) -> bool:
    """True when pyproject.toml declares any dependencies (project, poetry or dependency groups)."""
    try:
        data = tomllib.loads((worktree / "pyproject.toml").read_text(errors="replace"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    poetry = data.get("tool", {}).get("poetry", {})
    uv = data.get("tool", {}).get("uv", {})
    deps = [data.get("project", {}).get("dependencies"), data.get("project", {}).get("optional-dependencies"),
            data.get("dependency-groups"), uv.get("dev-dependencies"), poetry.get("dependencies"),
            poetry.get("group")]
    if isinstance(poetry.get("dependencies"), dict):           # poetry always lists python itself
        deps[4] = {k: v for k, v in poetry["dependencies"].items() if k != "python"}
    return any(deps)


def _accepted(profile: dict, manifest: str) -> tuple[str, ...]:
    """The lockfile names that satisfy this package list (the profile's `lockfiles` key wins)."""
    return tuple(profile.get("lockfiles") or DEFAULTS[manifest])


def run(ctx):
    """Fail naming each package list at the project root that has no tracked lockfile."""
    tracked = _tracked(ctx.worktree)
    profile = ctx.project.profile or {}
    bad = []
    for manifest in DEFAULTS:
        if manifest not in tracked:
            continue
        if manifest == "pyproject.toml" and not _has_dependencies(ctx.worktree):
            continue
        names = _accepted(profile, manifest)
        if not any(n in tracked for n in names):
            bad.append(f"{manifest} has no committed lockfile. Install with the package manager so it writes "
                       f"{' or '.join(names)}, and commit that file.")
    return StepResult("fail", bad) if bad else StepResult("pass")
