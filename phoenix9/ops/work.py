"""Ops for quick edits and planning sessions: list them and abandon them (what the cards' buttons call)."""
from phoenix9 import edits, plans
from phoenix9.ops import common


def abandon_edit(edit_id: str, who: str) -> dict:
    """Throw away a quick edit's branch copy; OpsError in plain words when that is not possible."""
    try:
        rec = edits.abandon(edit_id, who)
    except edits.EditError as err:
        raise common.OpsError(str(err)) from None
    common.record_command(who, f"edit abandon {edit_id}", rec["project"])
    return rec


def abandon_plan(plan_id: str, who: str) -> dict:
    """Give up a planning session that is not running; OpsError in plain words when that is not possible."""
    try:
        rec = plans.abandon(plan_id, who)
    except plans.PlanError as err:
        raise common.OpsError(str(err)) from None
    common.record_command(who, f"plan abandon {plan_id}", rec["project"])
    return rec
