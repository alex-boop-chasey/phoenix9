"""The `what_happened` tool: the agent's plain-English answer about a stopped run, with one button per repair."""
from typing import Any

from pydantic import BaseModel, Field

from agentkit.pack import ServerTool
from agentkit.packs.phoenix.tools import WHAT_HAPPENED_TOOLS, what_happened_card


class OptionInput(BaseModel):
    """One button: its label, the repair tool it leads to and that tool's inputs."""

    label: str = Field(description="The button text, in plain words.")
    tool: str = Field(description="One of: " + ", ".join(WHAT_HAPPENED_TOOLS) + ".")
    inputs: dict[str, Any] = Field(description="The inputs for that tool, exactly as its own approval card needs them.")


class WhatHappenedInputs(BaseModel):
    """The cause, what was tried, a suggestion and the repair options."""

    project: str = Field(description="The project's name.")
    run_id: str = Field(description="The run's id.")
    cause: str = Field(description="Why the run stopped, in plain English.")
    tried: list[str] = Field(description="What was already tried, one line each.")
    suggestion: str = Field(description="What you suggest Alex does.")
    options: list[OptionInput] = Field(description="One entry per button; each leads to a repair tool's approval card.")


def what_happened_tool(server_tools: list[ServerTool]) -> ServerTool:
    """The read tool that makes the card; it calls nothing and only accepts repair controls as options."""
    models = {t.name: t.inputs for t in server_tools if t.name in WHAT_HAPPENED_TOOLS}

    def run(**values) -> dict:
        """Return card data for the 'what happened' card."""
        options = [o.model_dump() if isinstance(o, BaseModel) else o for o in values.get("options") or []]
        return what_happened_card(models, {**values, "options": options})
    return ServerTool("what_happened", "Show Alex what happened to a stopped or failed run: the cause, what was tried, "
                      "your suggestion and one button per repair option. Makes no change.",
                      WhatHappenedInputs, "read", run)
