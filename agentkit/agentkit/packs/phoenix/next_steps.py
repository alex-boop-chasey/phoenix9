"""The `next_steps` tool: state-aware follow-up chips chosen by fixed rules from a project's real state."""
from pydantic import BaseModel, Field

from agentkit.pack import ServerTool
from agentkit.packs.phoenix.client import PhoenixClient, PhoenixError
from agentkit.packs.phoenix.controls import PLAIN_NAME
from agentkit.suggest import MAX_ACTIONS, check_actions

STOPPED = ("failed", "stopped")
GOING = ("queued", "running", "waiting", "paused-limit", "paused")
DEFAULT = {"label": "Show me the settings", "message": "Show me the settings"}


class NextStepsInputs(BaseModel):
    """Which project to work out next steps for."""

    project: str = Field(description="The project's name.")


def _plain(value) -> bool:
    """True when a name or id is plain (letters, digits, dot, dash, underscore)."""
    return isinstance(value, str) and bool(PLAIN_NAME.match(value)) and ".." not in value


def _rows(client: PhoenixClient, path: str, query: dict | None = None) -> list[dict]:
    """The list a read gives, or an empty list when it fails or has another shape."""
    try:
        data = client.get(path, query)
    except PhoenixError:
        return []
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def suggestions(project: str, runs: list[dict], gates: list[dict]) -> list[dict]:
    """Up to three {label, message} chosen by rule; names and ids appear only after the plain check."""
    newest = runs[0] if runs else {}
    run_id = newest.get("run_id") if _plain(newest.get("run_id")) else None
    found = []
    if not runs:
        found.append({"label": "Start a build", "message": f"Start a build for {project}"})
    if newest.get("status") in STOPPED:
        found.append({"label": "What went wrong?", "message": f"What went wrong with run {run_id} of {project}?"
                      if run_id else f"What went wrong with the last build of {project}?"})
    if gates:
        found.append({"label": "Answer the open question", "message": f"Show me the open question for {project}"})
    if newest.get("status") in GOING:
        found.append({"label": "How is the build doing?", "message": f"How is the build of {project} doing?"})
    return (found or [DEFAULT])[:MAX_ACTIONS]


def next_steps_tool(client: PhoenixClient) -> ServerTool:
    """The read tool that looks at the project, its builds and its questions and returns typed suggestions."""
    def run(**values) -> dict:
        """Return {project, suggestions}; a project with no usable data gets the safe default."""
        project = values.get("project")
        if not _plain(project):
            return {"error": f"'{project}' is not a plain name, so I did not use it."}
        try:
            client.get(f"/api/projects/{project}")
        except PhoenixError as err:
            return {"error": str(err)}
        runs = _rows(client, f"/api/projects/{project}/runs", {"limit": 5})
        gates = _rows(client, "/api/gates", {"project": project})
        return {"project": project, "suggestions": check_actions(suggestions(project, runs, gates))}
    return ServerTool("next_steps", "Work out up to three next-step suggestions for a project from its real state "
                      "(builds and open questions). Pass them on to suggest_next_actions. Makes no change.",
                      NextStepsInputs, "read", run)
