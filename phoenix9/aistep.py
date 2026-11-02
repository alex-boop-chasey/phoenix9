"""Helpers shared by the AI steps: fill prompts, read the finish line, get the profile's test block."""
from __future__ import annotations

import re

from phoenix9.stepctx import StepContext

_PLACEHOLDER = re.compile(r"\{\{\s*([\w-]+)\s*\}\}")


def render(template_text: str, values: dict) -> str:
    """Fill {{name}} placeholders; a name with no value is an error that names it."""
    def fill(m):
        if m.group(1) not in values:
            raise ValueError(f"the prompt uses {{{{{m.group(1)}}}}} but nothing fills it")
        return str(values[m.group(1)])
    return _PLACEHOLDER.sub(fill, template_text)


def render_prompt(template: str, values: dict) -> str:
    """Fill {{placeholders}} leniently: names with no value stay as written."""
    return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), template)


def project_domains(ctx) -> list:
    """The hosts the project itself allows ([domains] allow in phoenix.toml)."""
    return list((ctx.project.settings.get("domains") or {}).get("allow") or [])


def last_line(text: str) -> str:
    """The last non-empty line of the text (cut to 300 characters)."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return lines[-1][:300] if lines else ""


def finish_line(text: str) -> tuple[str, str]:
    """Read the session's last line: ("done"|"blocked"|"spec_problem"|"none", detail)."""
    line = last_line(text).strip("`* ")
    if line == "STEP DONE":
        return "done", ""
    for prefix, kind in (("STEP BLOCKED:", "blocked"), ("SPEC_PROBLEM:", "spec_problem")):
        if line.startswith(prefix):
            return kind, line[len(prefix):].strip()
    return "none", ""


def profile_test(ctx: StepContext) -> dict:
    """The profile's [test] block ({} when the project has no profile)."""
    return dict((ctx.project.profile or {}).get("test") or {})


def task_text(task: dict | None) -> str:
    """The task as plain text for a prompt."""
    if not task:
        return ""
    lines = [f"Task {task['number']}: {task['title']}", "", task.get("goal", "")]
    return "\n".join(lines).strip()


def checks_text(ctx: StepContext) -> str:
    """The 'Done when' bullets of the task (or the produced checks) as a list."""
    checks = ctx.things.get("checks")
    if checks and checks != "spec-done-when":
        return "\n".join(map(str, checks)) if isinstance(checks, list) else str(checks)
    done = (ctx.task or {}).get("done_when", [])
    return "\n".join(f"- {c['text']}" for c in done)
