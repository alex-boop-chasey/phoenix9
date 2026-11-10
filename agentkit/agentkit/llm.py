"""The thin layer over Pydantic AI: builds the agent, runs a turn and reports what happened."""
import functools
from collections.abc import AsyncIterator

from pydantic_ai import (
    Agent,
    AgentRunResultEvent,
    DeferredToolRequests,
    DeferredToolResults,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    Tool,
    ToolDenied,
    ToolReturn,
)
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import ExternalToolset, FunctionToolset

from . import tools


def build_agent(model, instructions: str = "", read_tools=(), browser_tools=(), change_tools=()) -> Agent:
    """Make a Pydantic AI agent; browser tools and change tools pause the run until answered."""
    toolsets = []
    if read_tools or change_tools:
        toolsets.append(
            FunctionToolset(
                [_with_card(fn) for fn in read_tools]
                + [Tool(fn, requires_approval=True) for fn in change_tools]
            )
        )
    if browser_tools:
        defs = [
            ToolDefinition(name=t["name"], description=t["description"], parameters_json_schema=t["parameters"])
            for t in browser_tools
        ]
        toolsets.append(ExternalToolset(defs))
    return Agent(
        model,
        instructions=instructions or None,
        toolsets=toolsets,
        output_type=[str, DeferredToolRequests],
    )


def _with_card(fn):
    """Wrap a read tool so its card data rides along without reaching the model."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        result = fn(*args, **kwargs)
        return ToolReturn(return_value=result, metadata=tools.card_for(fn.__name__, result["data"]))

    return wrapper


def resume_results(calls: dict, approvals: dict | None = None) -> DeferredToolResults:
    """Browser results and approval decisions (True or a refusal), keyed by tool call id."""
    return DeferredToolResults(calls=calls, approvals=approvals or {})


def refusal(message: str) -> ToolDenied:
    """A refusal that tells the model why the tool did not run."""
    return ToolDenied(message)


async def run_turn(agent: Agent, message: str | None, history: list, results=None) -> AsyncIterator[tuple]:
    """Run one turn and yield ("text", piece), ("card", call_id, card), then ("done", messages, browser_calls, approval_calls)."""
    async with agent.run_stream_events(
        message, message_history=history, deferred_tool_results=results
    ) as events:
        async for event in events:
            if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart) and event.part.content:
                yield "text", event.part.content
            elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                if event.delta.content_delta:
                    yield "text", event.delta.content_delta
            elif isinstance(event, FunctionToolResultEvent):
                part = event.part
                card = getattr(part, "metadata", None)
                yield "tool", part.tool_call_id, part.tool_name, card
            elif isinstance(event, AgentRunResultEvent):
                output = event.result.output
                asked = isinstance(output, DeferredToolRequests)
                yield "done", event.result.all_messages(), (output.calls if asked else []), (
                    output.approvals if asked else []
                )


async def stream_reply(agent: Agent, message: str) -> AsyncIterator[str]:
    """Run the agent on a message and yield the reply text piece by piece."""
    async for item in run_turn(agent, message, []):
        if item[0] == "text":
            yield item[1]


def make_model(name: str, api_key: str):
    """Make the Claude model, handing the key straight to the provider (never the environment)."""
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.providers.anthropic import AnthropicProvider

    return AnthropicModel(name, provider=AnthropicProvider(api_key=api_key))


def no_key_model():
    """A stand-in model for when no key is present: every reply says so plainly."""
    from pydantic_ai.models.function import FunctionModel

    async def say(messages, info):
        yield "The agent has no access key yet, so it can't answer."

    return FunctionModel(stream_function=say)
