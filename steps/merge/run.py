"""Merge: fast-forwards the run's branch into the project's main (mode auto; ask comes in phase 2)."""
from phoenix9 import state
from phoenix9.stepctx import StepResult


def run(ctx):
    """Merge only when every task passed; `ask` mode opens a gate instead."""
    tasks = state.load(ctx.run.folder)["tasks"]
    if any(t["status"] != "passed" for t in tasks.values()):
        return StepResult("skip", ["Not every task passed, so nothing was merged."])
    if ctx.step.settings.get("mode", "auto") == "ask":
        return StepResult("gate", gate={"kind": "merge", "title": "Merge the run?",
                                        "why": "The run finished; it needs your OK to merge into main."})
    git = ctx.adapters.git
    branch = git.branch_name(ctx.run.id)
    code_dir = ctx.project.code_dir
    git.git(code_dir, "merge", "--ff-only", branch)
    return StepResult("pass", produces={"merged": git.head(code_dir)})
