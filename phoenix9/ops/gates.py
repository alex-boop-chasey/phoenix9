"""Ops for gates: list the open questions and answer one."""
from phoenix9 import gates as core, runs, settings
from phoenix9.ops import common
from phoenix9.ops.common import OpsError


def list_(project: str | None = None) -> list:
    """Open gates, oldest first (one project or all)."""
    if project:
        common.project_dir(project)
    return core.list_gates(project)


def answer(gate_id: str, action: str, note: str = "", who: str = "cli") -> dict:
    """Answer an open gate (the runner picks the answer up)."""
    gate = next((g for g in core.list_gates(open_only=False) if g["id"] == gate_id), None)
    if gate is None:
        raise OpsError(f"There is no gate called '{gate_id}'.")
    try:
        project_settings = settings.load_project(common.project_dir(gate["project"]))
    except (settings.SettingsError, OpsError):
        project_settings = {}
    if not core.may_answer(gate, who, project_settings):
        raise OpsError(f"'{who}' may not answer {gate['kind']} questions in {gate['project']}.")
    try:
        result = core.answer(gate_id, action, note=note, who=who)
    except ValueError as err:
        raise OpsError(str(err)) from None
    common.record_command(who, f"gate answer {gate_id} {action}", gate["project"],
                          f"answered gate {gate_id}: {action}")
    return {"gate": gate_id, **result}


list = list_
