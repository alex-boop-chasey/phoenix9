"""Reviewer: a fresh Claude session reads the change read-only; only its verdict.json counts."""
import json
from pathlib import Path

from phoenix9 import atomic
from phoenix9.aistep import checks_text, task_text
from phoenix9.docker import Mount
from phoenix9.stepctx import StepResult

EARLY_END = ("crashed", "timed_out", "no_output", "error")
NO_VERDICT = "The reviewer gave no usable verdict"
INPUTS = "/inputs"


def _attempt_dir(ctx) -> Path:
    """The folder of this task attempt."""
    return ctx.run.folder / "tasks" / str(ctx.task["number"]) / f"attempt-{ctx.attempt}"


def _out_dir(ctx) -> Path:
    """The attempt's `out` folder: the only place the reviewer may write."""
    return _attempt_dir(ctx) / "out"


def _report(ctx) -> dict | None:
    """The test report as data: the fallback dict, or the JSON file Verify wrote."""
    report = ctx.things.get("test-report")
    if isinstance(report, dict):
        return report
    try:
        data = json.loads(Path(str(report)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _report_text(ctx) -> str:
    """A short summary of the test report: counts and first failure, or "exit codes only"."""
    report = _report(ctx)
    if not report:
        return "No test report is available."
    if report.get("reader") == "exit-codes-only":
        text = "Only exit codes were checked (no test report)."
    else:
        text = f"{report.get('passed', 0)} passed, {report.get('failed', 0)} failed, {report.get('skipped', 0)} skipped."
    if report.get("first_failed"):
        text += f" First failure: {report['first_failed']}"
    return text


def _mode_text(ctx) -> str:
    """One plain sentence on which tests verify ran (checks only / touched tests / whole suite)."""
    report = _report(ctx) or {}
    mode, picked = report.get("mode"), report.get("picked") or []
    if mode == "suite":
        return "Verify ran the whole test suite."
    if mode == "affected":
        files = ", ".join(str(f) for f in picked) if picked else "the tests that cover the changed files"
        return (f"Verify ran only the tests that cover the changed files: {files}. "
                "Other test files were not run.")
    if mode == "checks":
        return ("Verify ran only the task's own checks, not the project's other tests. "
                "If the change is risky for code those tests cover, name the test file that ought to be run.")
    return "The report does not say which tests were run (older report, or verify was off)."


def _input_files(ctx) -> dict:
    """The host files the reviewer may read, by name inside /inputs (only files that exist)."""
    found = {}
    diff = ctx.things.get("diff")
    if diff and Path(str(diff)).is_file():
        found["diff.patch"] = Path(str(diff))
    report = ctx.things.get("test-report")
    if isinstance(report, str) and Path(report).is_file():
        found["test-report.json"] = Path(report)
    return found


def _done_when(task: dict | None) -> str:
    """The task's Done-when bullets as a numbered list."""
    items = (task or {}).get("done_when", [])
    return "\n".join(f"{i}. {c['text']}" for i, c in enumerate(items, 1)) or "(none)"


def before(ctx) -> dict:
    """Fill the reviewer prompt's placeholders."""
    return {
        "spec_title": ctx.run.spec.get("title", ""),
        "about": ctx.run.spec.get("about", "").strip() or "(none)",
        "task": task_text(ctx.task),
        "done_when": _done_when(ctx.task),
        "diff_path": f"{INPUTS}/diff.patch",
        "test_report": _report_text(ctx),
        "test_mode": _mode_text(ctx),
        "checks": checks_text(ctx) or "(none)",
    }


def mounts(ctx) -> dict:
    """Ask for a read-only worktree, the diff and report mounted read-only, and a writable /out."""
    out = _out_dir(ctx)
    out.mkdir(parents=True, exist_ok=True)
    extra = [Mount(src, f"{INPUTS}/{name}", ro=True) for name, src in _input_files(ctx).items()]
    extra.append(Mount(out, "/out", ro=False))
    return {"workspace_ro": True, "extra_mounts": extra}


def _read_verdict(ctx) -> tuple[str, list] | None:
    """(verdict, reasons) from /out/verdict.json, or None when it is missing or not valid."""
    try:
        data = json.loads((_out_dir(ctx) / "verdict.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("verdict") not in ("pass", "fail"):
        return None
    reasons = data.get("reasons") or []
    if not isinstance(reasons, list):
        reasons = [reasons]
    return data["verdict"], [str(r) for r in reasons if str(r).strip()]


def after(ctx, session) -> StepResult:
    """Judge from /out/verdict.json only; what the session said in text never counts."""
    if session.kind in EARLY_END:
        return StepResult("fail", [f"The reviewer session ended before it finished ({session.kind})."])
    got = _read_verdict(ctx)
    if got is None:
        return StepResult("fail", [NO_VERDICT])
    verdict, reasons = got
    path = str(_out_dir(ctx) / "verdict.json")
    if verdict == "pass":
        return StepResult("pass", produces={"verdict": path})
    reasons = [f"Reviewer: {r}" for r in reasons] or ["Reviewer: the change was rejected (no reasons given)"]
    if ctx.step.settings.get("strict", True):
        return StepResult("fail", reasons)
    atomic.write_text(_attempt_dir(ctx) / "reviewer-notes.txt", "\n".join(reasons) + "\n")
    return StepResult("pass", [f"{r} (not strict: recorded only)" for r in reasons], produces={"verdict": path})
