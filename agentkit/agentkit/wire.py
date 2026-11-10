"""The thin layer over the AG-UI package: event objects and their SSE encoding."""
import time
import uuid

from ag_ui.core import (
    EventType,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    CustomEvent,
)
from ag_ui.encoder import EventEncoder

_encoder = EventEncoder()


def _now() -> int:
    """Current time in milliseconds."""
    return int(time.time() * 1000)


def new_id() -> str:
    """A fresh random id for a message or run."""
    return uuid.uuid4().hex


def run_started(thread_id: str, run_id: str) -> dict:
    """The RUN_STARTED event as a plain dict."""
    return _dump(RunStartedEvent(thread_id=thread_id, run_id=run_id, timestamp=_now()))


def run_finished(thread_id: str, run_id: str) -> dict:
    """The RUN_FINISHED event as a plain dict."""
    return _dump(RunFinishedEvent(thread_id=thread_id, run_id=run_id, timestamp=_now()))


def run_error(message: str) -> dict:
    """The RUN_ERROR event as a plain dict."""
    return _dump(RunErrorEvent(message=message, timestamp=_now()))


def text_start(message_id: str) -> dict:
    """The TEXT_MESSAGE_START event (assistant) as a plain dict."""
    return _dump(TextMessageStartEvent(message_id=message_id, role="assistant", timestamp=_now()))


def text_content(message_id: str, delta: str) -> dict:
    """The TEXT_MESSAGE_CONTENT event carrying one chunk of text."""
    return _dump(TextMessageContentEvent(message_id=message_id, delta=delta, timestamp=_now()))


def text_end(message_id: str) -> dict:
    """The TEXT_MESSAGE_END event as a plain dict."""
    return _dump(TextMessageEndEvent(message_id=message_id, timestamp=_now()))


def tool_call(call_id: str, name: str, args_json: str) -> list[dict]:
    """The three events (start, arguments, end) that announce one tool call."""
    return [
        _dump(ToolCallStartEvent(tool_call_id=call_id, tool_call_name=name, timestamp=_now())),
        _dump(ToolCallArgsEvent(tool_call_id=call_id, delta=args_json, timestamp=_now())),
        _dump(ToolCallEndEvent(tool_call_id=call_id, timestamp=_now())),
    ]


def component(call_id: str, name: str, data) -> dict:
    """A typed card for the panel: a component name plus its data, tied to a tool call."""
    value = {"toolCallId": call_id, "component": name, "data": data}
    return _dump(CustomEvent(name="component", value=value, timestamp=_now()))


def _dump(event) -> dict:
    """Turn an AG-UI event into a JSON-ready dict with its wire names."""
    return event.model_dump(mode="json", by_alias=True, exclude_none=True)


def is_final(event: dict) -> bool:
    """True when the event ends a run (finished or error)."""
    return event["type"] in (EventType.RUN_FINISHED.value, EventType.RUN_ERROR.value)


def to_sse(event: dict, number: int) -> str:
    """Encode one event dict as an SSE frame whose id is its number in the thread."""
    import json

    return f"id: {number}\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"


def approval_request(approval_id: str, call_id: str, tool_name: str, inputs) -> dict:
    """The CUSTOM event asking Alex to approve a change: its id, the tool and the exact inputs."""
    value = {"approvalId": approval_id, "toolCallId": call_id, "toolName": tool_name, "input": inputs}
    return _dump(CustomEvent(name="approval_request", value=value, timestamp=_now()))
