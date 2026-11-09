"""Planner: a read-only Claude session turns a brief into a full spec; Alex approves it at the plan gate."""
from pathlib import Path

from phoenix9 import atomic, runs, spec
from phoenix9.aistep import fence, profile_test
from phoenix9.docker import Mount
from phoenix9.stepctx import StepResult

EARLY_END = ("crashed", "timed_out", "no_output", "error")
TREE_LINES = 300
CLAUDE_MD_CHARS = 20000


def _out_dir(ctx) -> Path:
    """The folder mounted at /out: the only place the planner may write."""
    return ctx.run.folder / "planner-out"


def _brief(ctx) -> str:
    """The run's whole spec.md, word for word (every heading and section kept), fenced as data."""
    return fence((ctx.run.folder / "spec.md").read_text(encoding="utf-8"))


def _tree(ctx) -> str:
    """`git ls-files` of the worktree, cut to a few hundred lines."""
    files = [f for f in ctx.adapters.git.git(ctx.worktree, "ls-files").splitlines() if f]
    if not files:
        return "(the repo has no files yet)"
    shown = files[:TREE_LINES]
    if len(files) > TREE_LINES:
        shown.append(f"... and {len(files) - TREE_LINES} more files")
    return "\n".join(shown)


def _claude_md(ctx) -> str:
    """The project's CLAUDE.md text (cut), or a note that there is none."""
    path = Path(ctx.worktree) / "CLAUDE.md"
    if not path.is_file():
        return "(the project has no CLAUDE.md)"
    return path.read_text(encoding="utf-8", errors="replace")[:CLAUDE_MD_CHARS]


def _profile_text(ctx) -> str:
    """The profile's name, image and test commands as plain lines."""
    profile = ctx.project.profile or {}
    lines = [f"title: {profile.get('title', '')}", f"image: {profile.get('image', '')}"]
    lines += [f"test.{k}: {v}" for k, v in profile_test(ctx).items()]
    return "\n".join(lines)


def _feedback(ctx) -> str:
    """Every back note so far, numbered; "none" when there are none."""
    notes = [n.strip() for n in ((ctx.answer or {}).get("notes") or []) if n and n.strip()]
    return "\n".join(f"{i}. {n}" for i, n in enumerate(notes, 1)) or "none"


def before(ctx) -> dict:
    """Fill the planner prompt's placeholders."""
    test = profile_test(ctx)
    return {"brief": _brief(ctx), "project": ctx.project.name, "check_command": test.get("check_command", "") or test.get("cmd", ""),
            "suite_command": test.get("cmd", ""), "project_claude_md": _claude_md(ctx),
            "repo_tree": _tree(ctx), "profile": _profile_text(ctx), "feedback": _feedback(ctx)}


def mounts(ctx) -> dict:
    """Ask for a read-only worktree and a fresh writable /out."""
    out = _out_dir(ctx)
    out.mkdir(parents=True, exist_ok=True)
    (out / "spec.md").unlink(missing_ok=True)       # a re-run after `back` must not see the old plan
    return {"workspace_ro": True, "extra_mounts": [Mount(out, "/out", ro=False)]}


def after(ctx, session) -> StepResult:
    """Read /out/spec.md only; bad plan = fail with its problems; good plan = open the plan gate."""
    if session.kind in EARLY_END:
        return StepResult("fail", [f"The planner session ended before it finished ({session.kind})."])
    path = _out_dir(ctx) / "spec.md"
    if not path.is_file():
        return StepResult("fail", ["The planner wrote no /out/spec.md."])
    text = path.read_text(encoding="utf-8")
    problems = spec.check(text)
    if problems:
        return StepResult("fail", [f"The planned spec has problems: {p}" for p in problems])
    parsed = spec.parse(text)
    plan = ctx.run.folder / "plan.md"
    atomic.write_text(plan, text)
    mine = sum(1 for t in parsed.tasks if t.for_you)
    gate = {"kind": "plan", "title": f"Approve the plan for {parsed.title}",
            "why": f"{len(parsed.tasks)} tasks, {mine} for you",
            "links": [{"label": "Plan", "doc": f"run:{ctx.run.id}/plan.md"}],
            "actions": ["approve", "back", "skip", "stop"]}
    return StepResult("gate", produces={"plan": str(plan)}, gate=gate)


def on_approved(ctx, produces) -> dict:
    """Plan approved: build the run's tasks from plan.md and mark the finished event."""
    runs.adopt_plan(ctx.run.folder, produces["plan"])
    return {"plan_adopted": True}
