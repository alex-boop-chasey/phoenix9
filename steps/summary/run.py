"""Summary: writes summary.md and summary.html in the run folder, in plain English for Alex."""
from phoenix9 import atomic, summary
from phoenix9.stepctx import StepResult


def run(ctx):
    """Collect the run's facts and write them as summary.md and summary.html."""
    shots = bool((ctx.project.profile or {}).get("screenshots", False))
    try:
        facts = summary.facts(ctx.run.folder, screenshots=shots)
        atomic.write_text(ctx.run.folder / "summary.md", summary.markdown(facts))
        atomic.write_text(ctx.run.folder / "summary.html", summary.html(facts))
    except OSError as err:
        return StepResult("fail", [f"could not write the summary: {err}"])
    return StepResult("pass", produces={})
