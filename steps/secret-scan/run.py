"""Secret scan: fails the task if the change writes a secret value or key into the code."""
import importlib

from phoenix9 import paths, scrub, state
from phoenix9.stepctx import StepResult

MAX_NEW_FILE = 5_000_000


def _values(ctx) -> list[str]:
    """Every secret value to look for: project keys, the global secret files, the scrubber's values."""
    try:
        keys = importlib.import_module("phoenix9.keys")   # added by the project-keys step
        project_values = list(keys.secret_values(ctx.project))
    except ImportError:
        project_values = []
    env_files = sorted(paths.secrets().glob("*.env")) if paths.secrets().is_dir() else []
    return [*project_values, *scrub.secrets_from(env_files), *scrub.known_secrets()]


def _binary_files(ctx, git, changes, forms) -> list[str]:
    """Reasons for secrets inside new or changed binary files (the text diff cannot show them)."""
    out = []
    for c in changes:
        f = ctx.worktree / c.path
        if c.status == "D" or not c.binary or not f.is_file() or f.stat().st_size > MAX_NEW_FILE:
            continue
        if git.find_secrets(f.read_bytes().decode("latin-1"), forms):
            out.append(f"A secret was written into {c.path}")
    return out


def run(ctx):
    """Scan the lines the attempt added (against attempt_base) and any new binary file."""
    git, n = ctx.adapters.git, ctx.task["number"]
    base = state.load(ctx.run.folder)["tasks"][str(n)].get("attempt_base") or git.head(ctx.worktree)
    forms = git.secret_forms(_values(ctx))
    found = git.scan_added_lines(git.diff_text(ctx.worktree, base), forms)
    bad = [f"A secret was written into {path} (line {line}): it looks like {what}. "
           "Remove it and read the value from the environment instead." for path, line, what in found]
    bad += _binary_files(ctx, git, git.diff_changes(ctx.worktree, base), forms)
    return StepResult("fail", bad) if bad else StepResult("pass")
