"""The `flow` tool: records where a guided flow is (the event log keeps it) and makes the flow card."""
from typing import Any

from pydantic import BaseModel, Field

from agentkit.flows import flow_card
from agentkit.pack import ServerTool


class FlowInputs(BaseModel):
    """Where a guided flow is now."""

    flow: str = Field(description="The flow's id, such as new-project, keys, hotfix or build-start.")
    status: str = Field(description="One of: active, done, cancelled.")
    step: int = Field(description="The number of the current step.")
    steps: int = Field(description="How many steps the flow has.")
    label: str = Field(description="The step's name in plain words.")
    values: dict[str, Any] = Field(default_factory=dict, description=(
        "Plain facts picked so far: text, numbers, yes/no or lists of text; at most 12, each at most 200 characters. "
        "Never a secret."))


def flow_tool() -> ServerTool:
    """The read tool that records a flow step; it calls no Phoenix route."""
    def run(**v) -> dict:
        """Return the flow card data for this step."""
        return flow_card(v.get("flow", ""), v.get("status", ""), v.get("step", 0), v.get("steps", 0),
                         v.get("label", ""), v.get("values"))
    return ServerTool("flow", "Record where a guided flow is (step, total, name and the plain facts picked so far) "
                      "and show it to Alex. Makes no change and holds no secrets.", FlowInputs, "read", run)
