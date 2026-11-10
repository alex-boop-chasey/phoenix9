"""Demo server for the browser checks: the real service with a scripted model and a fake project list."""
import argparse
import asyncio
import hmac
import json
import sys
import tempfile
from pathlib import Path

import httpx
import uvicorn
from pydantic_ai.messages import ModelRequest, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agentkit import config, llm, pack as pack_mod, runs, spend  # noqa: E402
from agentkit.packs.phoenix import build_pack  # noqa: E402
from agentkit.packs.phoenix.client import PhoenixClient  # noqa: E402
from agentkit.store import Store  # noqa: E402

# Test-only prices so the demo never needs the real price list. They are never shown anywhere.
DEMO_PRICES = {"input_per_mtok": 1.0, "output_per_mtok": 1.0, "cache_read_per_mtok": 1.0, "cache_write_per_mtok": 1.0}
DEMO_MODEL = "demo"

ROUTES = [("projects", ["q", "status", "owner", "sort", "attention"]), ("new", []), ("p/<name>/overview", ["gate"]),
          ("p/<name>/build", ["run", "wizard"]), ("settings", ["section"])]
ROWS = [{"name": "demo-site", "activity": "idle", "last_used": "2026-11-01"},
        {"name": "old-experiment", "activity": "building", "last_used": "2026-10-02"}]
SUGGESTIONS = {"actions": [{"label": "Show my projects", "message": "show my projects"},
                           {"label": "Open the project list", "link": "#/"}]}
SLOW_STEPS = 60  # a slow reply lasts about 12 seconds, long enough to stop or reload in the middle


def fake_phoenix(request: httpx.Request) -> httpx.Response:
    """Answer the few Phoenix API calls the demo pack makes."""
    path = request.url.path
    if path == "/api/projects":
        return httpx.Response(200, json=ROWS)
    if path == "/api/routes":
        return httpx.Response(200, json=[{"name": n, "params": p} for n, p in ROUTES])
    if request.method == "POST":
        return httpx.Response(200, json={"ok": True})
    return httpx.Response(404, json={"error": "Phoenix has no such thing."})


def last_request_parts(messages) -> list:
    """The parts of the newest request the model is being shown."""
    requests = [m for m in messages if isinstance(m, ModelRequest)]
    return list(requests[-1].parts) if requests else []


def user_text(messages) -> str:
    """The newest thing Alex typed, in lower case."""
    texts = [p.content for m in messages if isinstance(m, ModelRequest) for p in m.parts
             if isinstance(p, UserPromptPart) and isinstance(p.content, str)]
    return texts[-1].lower() if texts else ""


def call(name: str, args: str) -> dict:
    """One scripted tool call."""
    return {0: DeltaToolCall(name=name, json_args=args, tool_call_id=f"call-{name}")}


async def script(messages, info: AgentInfo):
    """The scripted replies: a word in Alex's message picks the reply; tool answers pick the follow-up."""
    parts = last_request_parts(messages)
    returned = [p for p in parts if not isinstance(p, UserPromptPart)]
    if returned:
        part = returned[0]
        name = part.tool_name if isinstance(part, ToolReturnPart) else ""
        if name == "go_to":
            yield "I opened that page for you."
        elif name == "set_build_notifications":
            yield "Done. The change was made."
        elif name == "suggest_next_actions":
            yield "Here are some ideas."
        elif "Alex refused this" in str(getattr(part, "content", "")):
            yield "Understood. I did not make the change."
        else:
            yield "Here are your projects."
        return
    text = user_text(messages)
    if "go to" in text:
        yield call("go_to", '{"page": "projects"}')
    elif "projects" in text:
        yield call("list_projects", "{}")
    elif "change" in text:
        yield call("set_build_notifications", '{"name": "demo-site", "on": true}')
    elif "suggest" in text:
        yield call("suggest_next_actions", json.dumps(SUGGESTIONS))
    elif "slow" in text:
        yield "Working on it. "
        for _ in range(SLOW_STEPS):
            await asyncio.sleep(0.2)
            yield "…"
        yield "That took a while."
    else:
        yield "Hello from the demo agent. "
        yield "This reply is scripted."


def denied_for(token: str):
    """A check that is True when the bearer token is missing or wrong."""
    return lambda request: not hmac.compare_digest(request.headers.get("authorization", "").encode(), f"Bearer {token}".encode())


def status_route(info: dict, denied):
    """The GET /status handler."""
    async def status(request):
        """Say the demo service is up."""
        if denied(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return JSONResponse(info)
    return status


def build_app(token: str, db_file: str) -> Starlette:
    """The real routes on a store, the Phoenix pack (with a fake Phoenix) and the scripted model."""
    cfg = config.Config(model=DEMO_MODEL, monthly_cap_usd=95.0)
    cfg.prices = {DEMO_MODEL: dict(DEMO_PRICES)}
    store = Store(db_file)
    meter = spend.Meter(store, cfg)
    the_pack = pack_mod.check_pack(build_pack(PhoenixClient("http://phoenix.test", transport=httpx.MockTransport(fake_phoenix))))
    model = llm.SpendModel(FunctionModel(stream_function=script, model_name=DEMO_MODEL), meter)
    r = runs.Runs(store, llm.build_pack_agent(model, the_pack), the_pack)
    denied = denied_for(token)
    info = {"running": True, "key_present": True, "pack": the_pack.name, "model": DEMO_MODEL}
    return Starlette(routes=[
        Route("/status", status_route(info, denied), methods=["GET"]),
        Route("/spend", spend.spend_route(meter, denied), methods=["GET"]),
        Route("/threads", runs.list_route(r, denied), methods=["GET"]),
        Route("/threads", runs.new_route(r, denied), methods=["POST"]),
        Route("/threads/{id}", runs.read_route(r, denied), methods=["GET"]),
        Route("/threads/{id}/runs", runs.start_route(r, denied), methods=["POST"]),
        Route("/threads/{id}/stream", runs.stream_route(r, denied), methods=["GET"]),
        Route("/threads/{id}/stop", runs.stop_route(r, denied), methods=["POST"]),
        Route("/approvals/{id}", runs.approval_route(r, denied), methods=["POST"]),
        Route("/browser-results/{id}", runs.browser_route(r, denied), methods=["POST"]),
    ])


def main(argv: list) -> int:
    """Run the demo service on a port, with the token read from a file."""
    parser = argparse.ArgumentParser(description="agentkit demo service with a scripted model")
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--port", type=int, default=8097)
    args = parser.parse_args(argv)
    token = Path(args.token_file).read_text(encoding="utf-8").strip()
    with tempfile.TemporaryDirectory() as folder:
        app = build_app(token, str(Path(folder) / "demo.db"))
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
