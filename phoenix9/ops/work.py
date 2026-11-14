"""Ops for quick edits and planning sessions: list, finish, start, reply to and abandon them."""
from phoenix9 import edits, plans, scrub
from phoenix9.ops import common

EDIT_FIELDS = ("id", "project", "title", "status", "last_activity", "branch", "pr")
PLAN_FIELDS = ("id", "project", "status", "open_questions", "brief", "started", "last_activity")
OPEN_EDIT = ("open", "stalled")


def _clean(value):
    """The value with every piece of text scrubbed of secrets."""
    if isinstance(value, str):
        return scrub.scrub(value)
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    return value


def _edit_view(rec: dict) -> dict:
    """What callers see of a quick edit: never its folder path."""
    return _clean({k: rec.get(k) for k in EDIT_FIELDS})


def _plan_view(rec: dict, report: bool = False) -> dict:
    """What callers see of a planning session, with its spec as a document id when there is one."""
    view = {k: rec.get(k) for k in PLAN_FIELDS}
    spec = rec.get("spec")
    view["spec"] = f"notes:{rec['project']}/{spec.removeprefix('notes/')}" if spec else None
    if report:
        view["report"] = rec.get("report", "")
    return _clean(view)


def list_edits(project: str | None = None) -> dict:
    """The open and stalled quick edits (one project or all), newest first."""
    found = [r for r in edits.list_edits(project) if r.get("status") in OPEN_EDIT]
    return {"edits": [_edit_view(r) for r in found]}


def finish_edit(edit_id: str, who: str, message: str | None = None) -> dict:
    """Check a quick edit like a build, then push it and open a merge request; OpsError listing the problems."""
    try:
        rec = edits.finish(edit_id, message, who=who)
    except edits.EditError as err:
        raise common.OpsError(scrub.scrub(str(err))) from None
    common.record_command(who, f"edit finish {edit_id}", rec["project"])
    return _edit_view(rec)


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


def list_plans(project: str | None = None) -> dict:
    """Planning sessions (one project or all), newest first."""
    return {"plans": [_plan_view(r) for r in plans.list_plans(project)]}


def show_plan(plan_id: str) -> dict:
    """One planning session, with its last report; OpsError when there is none."""
    try:
        return _plan_view(plans.load(plan_id), report=True)
    except plans.PlanError as err:
        raise common.OpsError(str(err)) from None


def start_plan(project: str, brief: str, who: str) -> dict:
    """Queue a planning session on a project with the usual planning model; OpsError in plain words when refused."""
    try:
        rec = plans.new_record(project, brief, plans.plan_model(), who)
    except plans.PlanError as err:
        raise common.OpsError(str(err)) from None
    common.record_command(who, f"plan start {project}", project)
    return _plan_view(rec, report=True)


def reply_plan(plan_id: str, text: str, who: str) -> dict:
    """Queue Alex's answer, word for word, for a waiting planning session; OpsError in plain words when refused."""
    if not (text or "").strip():
        raise common.OpsError("Say what the answer is.")
    try:
        rec = plans.queue_continue(plan_id, who=who, answer=text)
    except plans.PlanError as err:
        raise common.OpsError(str(err)) from None
    common.record_command(who, f"plan reply {plan_id}", rec["project"])
    return _plan_view(rec, report=True)
