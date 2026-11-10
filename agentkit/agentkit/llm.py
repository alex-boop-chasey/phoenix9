"""The thin layer over Pydantic AI: builds the agent, runs a turn and reports what happened."""
import functools
from contextlib import asynccontextmanager
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

from pydantic import BaseModel, Field

from pydantic_ai.models.wrapper import WrapperModel

from . import tools
from .pack import Pack
from .spend import Meter


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


def dump_messages(messages: list) -> str:
    """Turn a message history into JSON text for the store."""
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    return ModelMessagesTypeAdapter.dump_json(messages).decode()


def load_messages(text: str) -> list:
    """Turn stored JSON text back into a message history."""
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    return ModelMessagesTypeAdapter.validate_json(text)


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


SUGGEST = "suggest_next_actions"
CACHE_SETTINGS = {"anthropic_cache_instructions": True, "anthropic_cache_tool_definitions": True}


class Suggestions(BaseModel):
    """What suggest_next_actions takes: a few short follow-ups Alex could pick."""

    actions: list[str] = Field(max_length=4, description="Short follow-up actions, in plain words.")


def suggest_next_actions(actions: list[str]) -> dict:
    """Offer Alex a few follow-up actions; it changes nothing."""
    return tools.quoted("agent suggestions", {"actions": actions})


def _quote_result(name: str, result):
    """Wrap a tool result as quoted material unless it already is."""
    if isinstance(result, dict) and "quoted_from" in result and "data" in result:
        return result
    return tools.quoted(name, result)


def _pack_tool(tool) -> Tool:
    """Turn one pack server tool into a Pydantic AI tool whose result is quoted; changes need approval."""

    def run(**kwargs):
        args = tool.inputs(**kwargs).model_dump()
        return _quote_result(tool.name, tool.function(**args))

    made = Tool.from_schema(
        run,
        name=tool.name,
        description=tool.description,
        json_schema=tool.inputs.model_json_schema(),
    )
    return made if tool.risk == "read" else _approved(made)


def _approved(tool: Tool) -> Tool:
    """Mark a tool as needing Alex's approval before it runs."""
    tool.requires_approval = True
    return tool


def build_pack_agent(model, pack: Pack) -> Agent:
    """Make the agent from a site pack: exactly its tools plus suggest_next_actions, with prompt caching on."""
    function_tools = [_pack_tool(t) for t in pack.server_tools]
    function_tools.append(
        Tool.from_schema(
            suggest_next_actions,
            name=SUGGEST,
            description="Offer Alex a few short follow-up actions he can pick from.",
            json_schema=Suggestions.model_json_schema(),
        )
    )
    toolsets = [FunctionToolset(function_tools)]
    if pack.browser_tools:
        defs = [
            ToolDefinition(name=t.name, description=t.description, parameters_json_schema=t.inputs.model_json_schema())
            for t in pack.browser_tools
        ]
        toolsets.append(ExternalToolset(defs))
    return Agent(
        model,
        instructions=pack.instructions or None,
        toolsets=toolsets,
        output_type=[str, DeferredToolRequests],
        model_settings=dict(CACHE_SETTINGS),
    )


class SpendModel(WrapperModel):
    """A model wrapper that refuses calls once the allowance is gone and records every call's tokens."""

    def __init__(self, wrapped, meter: Meter):
        """Wrap a model with the meter that checks and records."""
        super().__init__(wrapped)
        self.meter = meter

    def _record(self, usage) -> None:
        """Save one call's token counts (pydantic-ai counts cache tokens inside input, so take them out)."""
        cached = usage.cache_read_tokens + usage.cache_write_tokens
        self.meter.record(self.model_name, max(0, usage.input_tokens - cached), usage.output_tokens,
                          usage.cache_read_tokens, usage.cache_write_tokens)

    async def request(self, messages, model_settings, model_request_parameters):
        """Check the allowance, make the call, then record its usage."""
        self.meter.check()
        response = await self.wrapped.request(messages, model_settings, model_request_parameters)
        self._record(response.usage)
        return response

    @asynccontextmanager
    async def request_stream(self, messages, model_settings, model_request_parameters, run_context=None):
        """Check the allowance, stream the call, and record what was used even if it is stopped early."""
        self.meter.check()
        async with self.wrapped.request_stream(
            messages, model_settings, model_request_parameters, run_context
        ) as response:
            try:
                yield response
            finally:
                self._record(response.usage)
