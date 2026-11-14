"""Hand-offs from Phoenix: a build task that ran out of tries opens a new chat for the agent to look at."""
import re

from starlette.requests import Request
from starlette.responses import JSONResponse

from .runs import Runs
from .spend import Meter, SpendRefused

RUN_ID = re.compile(r"\d{8}-\d{6}-[a-z0-9-]+")
PROJECT = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
KEYS = {"run_id", "task", "gate_id", "project"}
BAD_BODY = "A hand-off needs exactly run_id, task, gate_id and project, each in its usual shape."
NO_KEY = "The agent has no API key yet, so it cannot look at this build. Phoenix keeps the question for Alex."
TAG = "[Phoenix · escalation]"


def check_body(body) -> dict | None:
    """The four ids when the body holds exactly them, each in its strict shape; else None."""
    if not isinstance(body, dict) or set(body) != KEYS:
        return None
    run_id, task, gate_id, project = body["run_id"], body["task"], body["gate_id"], body["project"]
    if not (isinstance(run_id, str) and RUN_ID.fullmatch(run_id)):
        return None
    if not (isinstance(task, int) and not isinstance(task, bool) and 1 <= task <= 999):
        return None
    if not (isinstance(gate_id, str) and re.fullmatch(re.escape(run_id) + r"\.\d{1,6}", gate_id)):
        return None
    if not (isinstance(project, str) and PROJECT.fullmatch(project)):
        return None
    return {"run_id": run_id, "task": task, "gate_id": gate_id, "project": project}


def message_for(ids: dict) -> str:
    """The run's message, built only from the checked ids (nothing else from Phoenix reaches the model)."""
    return (f"{TAG} run {ids['run_id']} task {ids['task']} "
            f"(question {ids['gate_id']}, project {ids['project']})")


def title_for(ids: dict) -> str:
    """The new chat's title."""
    return f"Build needs help: {ids['project']} task {ids['task']}"


def refusal(meter: Meter, key_present: bool) -> str | None:
    """Why the agent cannot take a hand-off now (no key, prices not set, allowance used up), or None."""
    if not key_present:
        return NO_KEY
    try:
        meter.check()
    except SpendRefused as refused:
        return str(refused)
    return None


def handoff_route(runs: Runs, meter: Meter, key_present: bool, denied):
    """Make the POST /handoffs handler: one new chat and run per question; 409 when the agent cannot work now."""

    async def handoff(request: Request):
        """Open a chat for a build task that ran out of tries, or return the one already opened for that question."""
        if denied(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except ValueError:
            body = None
        ids = check_body(body)
        if ids is None:
            return JSONResponse({"error": BAD_BODY}, status_code=400)
        if (thread_id := runs.store.handoff_thread(ids["gate_id"])) is not None:
            return JSONResponse({"thread_id": thread_id, "run_id": None}, status_code=200)
        if (why := refusal(meter, key_present)) is not None:
            return JSONResponse({"error": why}, status_code=409)
        thread_id = runs.store.create_thread(title_for(ids))["id"]
        runs.store.save_handoff(ids["gate_id"], thread_id)
        started = runs.start(thread_id, message_for(ids))
        return JSONResponse({"thread_id": thread_id, "run_id": started["run_id"]}, status_code=202)

    return handoff
