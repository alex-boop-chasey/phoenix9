"""Demo server for the browser checks: the real service with a scripted model and a fake project list."""
import argparse
import sys
from pathlib import Path

import uvicorn
from pydantic_ai.messages import ModelRequest, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agentkit.service import create_app  # noqa: E402

# Test-only prices so the demo never needs the real price list. They are never shown anywhere.
DEMO_PRICES = {"input_per_mtok": 1.0, "output_per_mtok": 1.0, "cache_read_per_mtok": 1.0, "cache_write_per_mtok": 1.0}

CHANGE_ARGS = '{"what": "steps.notify.on", "value": "true"}'


def last_request_parts(messages) -> list:
    """The parts of the newest request the model is being shown."""
    requests = [m for m in messages if isinstance(m, ModelRequest)]
    return list(requests[-1].parts) if requests else []


def user_text(messages) -> str:
    """The newest thing Alex typed, in lower case."""
    texts = [p.content for m in messages if isinstance(m, ModelRequest) for p in m.parts
             if isinstance(p, UserPromptPart) and isinstance(p.content, str)]
    return texts[-1].lower() if texts else ""


async def script(messages, info: AgentInfo):
    """The scripted replies: a word in Alex's message picks the reply; tool answers pick the follow-up."""
    parts = last_request_parts(messages)
    returned = [p for p in parts if not isinstance(p, UserPromptPart)]
    if returned:
        part = returned[0]
        if isinstance(part, ToolReturnPart) and part.tool_name == "go_to":
            yield "I opened that page for you."
        elif isinstance(part, ToolReturnPart) and part.tool_name == "change":
            yield "Done. The change was made."
        elif "Alex refused this" in str(getattr(part, "content", "")):
            yield "Understood. I did not make the change."
        else:
            yield "Here are your projects."
        return
    text = user_text(messages)
    if "go to" in text:
        yield {0: DeltaToolCall(name="go_to", json_args='{"page": "agent-next"}' if "agent" in text
                                else '{"page": "projects"}', tool_call_id="call-go")}
    elif "projects" in text:
        yield {0: DeltaToolCall(name="list_projects", json_args="{}", tool_call_id="call-list")}
    elif "change" in text:
        yield {0: DeltaToolCall(name="change", json_args=CHANGE_ARGS, tool_call_id="call-change")}
    else:
        yield "Hello from the demo agent. "
        yield "This reply is scripted."


def main(argv: list) -> int:
    """Run the demo service on a port, with the token read from a file."""
    parser = argparse.ArgumentParser(description="agentkit demo service with a scripted model")
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--port", type=int, default=8097)
    args = parser.parse_args(argv)
    token = Path(args.token_file).read_text(encoding="utf-8").strip()
    app = create_app(FunctionModel(stream_function=script), token)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
