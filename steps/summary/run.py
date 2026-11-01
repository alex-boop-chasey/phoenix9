"""Summary: writes summary.md in plain English for Alex."""
from phoenix9 import atomic, state
from phoenix9.stepctx import StepResult


def run(ctx):
    """List the tasks with their statuses and the cost so far."""
    st = state.load(ctx.run.folder)
    lines = [f"# {ctx.run.spec.get('title', ctx.run.id)}", "", f"Run: {ctx.run.id}", "", "## Tasks", ""]
    for n, t in sorted(st["tasks"].items(), key=lambda kv: int(kv[0])):
        lines.append(f"- Task {n}: {t['title']} - {t['status']}")
    passed = sum(1 for t in st["tasks"].values() if t["status"] == "passed")
    cost = (st.get("usage") or {}).get("cost_usd", 0.0)
    lines += ["", f"{passed} of {len(st['tasks'])} tasks passed.", f"Cost: ${cost:.2f}", ""]
    atomic.write_text(ctx.run.folder / "summary.md", "\n".join(lines))
    return StepResult("pass")
