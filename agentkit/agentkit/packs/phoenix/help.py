"""The `phoenix_help` tool: reads one of the pack's help topics about how Phoenix works."""
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agentkit.pack import ServerTool

HELP_DIR = Path(__file__).with_name("help")
TOPICS = ("overview", "pages", "failures", "settings", "steps", "workflows")


class HelpInputs(BaseModel):
    """Which help topic to read."""

    model_config = ConfigDict(extra="forbid")
    topic: Literal[TOPICS] = Field(description="The topic: " + ", ".join(TOPICS) + ".")


def read_topic(topic) -> dict:
    """Return {topic, text} for a known topic, or an error for anything else."""
    if topic not in TOPICS:
        return {"error": f"There is no help topic called '{topic}'. The topics are: {', '.join(TOPICS)}."}
    return {"topic": topic, "text": (HELP_DIR / f"{topic}.md").read_text()}


def help_tool() -> ServerTool:
    """The read tool that returns one help topic; it calls no Phoenix route."""
    def run(**values) -> dict:
        """Return the topic's text."""
        return read_topic(values.get("topic"))
    return ServerTool("phoenix_help", "Read how Phoenix works, by topic: overview (start here), pages (the dashboard), "
                      "failures (why builds fail and repairs), settings (keys, presets, profiles), steps (what each "
                      "build step does), workflows (how to do things). Makes no change.", HelpInputs, "read", run)
