"""The thin layer over Pydantic AI: builds the agent and streams its reply as plain text chunks."""
from collections.abc import AsyncIterator

from pydantic_ai import Agent


def build_agent(model, instructions: str = "") -> Agent:
    """Make a Pydantic AI agent for the given model (a model object or a name)."""
    return Agent(model, instructions=instructions or None)


async def stream_reply(agent: Agent, message: str) -> AsyncIterator[str]:
    """Run the agent on a message and yield the reply text piece by piece."""
    async with agent.run_stream(message) as result:
        async for piece in result.stream_text(delta=True, debounce_by=None):
            if piece:
                yield piece
