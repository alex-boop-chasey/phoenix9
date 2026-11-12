"""The agent service (proof slice): threads, runs and the AG-UI event stream over SSE."""
import argparse
import asyncio
import hmac
import logging
import os
import sqlite3
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from . import config, llm, runs, spend, tools, wire
from .packs.phoenix import build_pack
from .packs.phoenix.client import PhoenixClient
from .store import Store

log = logging.getLogger("agentkit")


class Thread:
    """One conversation: its ordered event list."""

    def __init__(self, thread_id: str):
        self.id = thread_id
        self.events: list[dict] = []
        self.busy = False
        self.history: list = []
        self.waiting: dict[str, object] = {}  # browser tool calls the run is paused on
        self.answers: dict[str, object] = {}  # results that came back so far
        self.approving: dict[str, object] = {}  # change calls waiting for Alex's decision
        self.decisions: dict[str, object] = {}  # decisions that came back so far


def create_app(
    model, token: str, projects=tools.fake_projects, change_log=None, info=None, blocked: str | None = None
) -> Starlette:
    """The first proof-slice app (fake projects, in-memory threads, no store, no meter).

    Kept only because older proof tests build their small apps from it; the deployed service uses
    build_service_app instead.
    """
    info = info or {"key_present": False, "pack": "phoenix", "model": ""}
    change_log = change_log if change_log is not None else []
    agent = llm.build_agent(
        model,
        read_tools=[tools.make_list_projects(projects)],
        browser_tools=[tools.GO_TO],
        change_tools=[tools.make_change(change_log)],
    )
    threads: dict[str, Thread] = {}
    tasks: set[asyncio.Task] = set()

    def denied(request: Request) -> bool:
        """True when the bearer token is missing or wrong."""
        given = request.headers.get("authorization", "")
        return not hmac.compare_digest(given.encode(), f"Bearer {token}".encode())

    def find(request: Request) -> Thread | None:
        """The thread named in the URL, if any."""
        return threads.get(request.path_params["id"])

    async def drive(thread: Thread, message: str | None, results=None):
        """Run the model (new message or resumed) and append its events; pause on browser tools."""
        run_id, msg_id = wire.new_id(), wire.new_id()
        events = thread.events
        events.append(wire.run_started(thread.id, run_id))
        text_open, pending, asking = False, [], []
        try:
            async for item in llm.run_turn(agent, message, thread.history, results):
                if item[0] == "text":
                    if not text_open:
                        events.append(wire.text_start(msg_id))
                        text_open = True
                    events.append(wire.text_content(msg_id, item[1]))
                elif item[0] == "tool":
                    _, call_id, name, card = item
                    events.extend(wire.tool_call(call_id, name, "{}"))
                    if card:
                        events.append(wire.component(call_id, card["component"], card["data"]))
                elif item[0] == "done":
                    thread.history = item[1]
                    pending, asking = item[2], item[3]
            if text_open:
                events.append(wire.text_end(msg_id))
            for call in asking:
                thread.approving[call.tool_call_id] = call
                args = call.args_as_dict()
                events.extend(wire.tool_call(call.tool_call_id, call.tool_name, call.args_as_json_str()))
                events.append(wire.approval_request(call.tool_call_id, call.tool_call_id, call.tool_name, args))
            if pending or asking:
                for call in pending:
                    thread.waiting[call.tool_call_id] = call
                    events.extend(wire.tool_call(call.tool_call_id, call.tool_name, call.args_as_json_str()))
                return  # paused: no RUN_FINISHED until the browser answers
            events.append(wire.run_finished(thread.id, run_id))
        except Exception:
            events.append(wire.run_error("The agent could not finish this reply."))
        thread.busy = False

    def launch(thread: Thread, message: str | None, results=None):
        """Start a drive in the background."""
        task = asyncio.create_task(drive(thread, message, results))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    async def browser_result(request: Request):
        """Take the browser's answer to a paused tool call; resume the run when all are in."""
        if denied(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        call_id = request.path_params["id"]
        thread = next((t for t in threads.values() if call_id in t.waiting), None)
        if thread is None:
            return JSONResponse({"error": "no such pending call"}, status_code=404)
        body = await request.json()
        if not isinstance(body, dict) or "result" not in body:
            return JSONResponse({"error": "result is required"}, status_code=400)
        thread.waiting.pop(call_id)
        thread.answers[call_id] = tools.quoted("the browser", body["result"])
        resume(thread)
        return JSONResponse({"accepted": True}, status_code=202)

    def resume(thread: Thread):
        """Continue the run once every paused call has an answer."""
        if thread.waiting or thread.approving:
            return
        answers, thread.answers = thread.answers, {}
        decisions, thread.decisions = thread.decisions, {}
        launch(thread, None, llm.resume_results(answers, decisions))

    async def approval(request: Request):
        """Take Alex's decision on a paused change; only this route can let the tool run."""
        if denied(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        call_id = request.path_params["id"]
        thread = next((t for t in threads.values() if call_id in t.approving), None)
        if thread is None:
            return JSONResponse({"error": "no such pending approval"}, status_code=404)
        try:
            body = await request.json()
        except ValueError:
            body = None
        decision = body.get("decision") if isinstance(body, dict) else None
        if decision not in ("approve", "deny"):
            return JSONResponse({"error": "decision must be approve or deny"}, status_code=400)
        thread.approving.pop(call_id)
        thread.decisions[call_id] = True if decision == "approve" else llm.refusal("Alex refused this")
        resume(thread)
        return JSONResponse({"accepted": True}, status_code=202)

    async def status(request: Request):
        """Say whether the service is up, has a key, and which pack and model it uses."""
        if denied(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return JSONResponse({"running": True, **info})

    async def new_thread(request: Request):
        """Start a new empty thread."""
        if denied(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        thread = Thread(wire.new_id())
        threads[thread.id] = thread
        return JSONResponse({"id": thread.id}, status_code=201)

    async def start_run(request: Request):
        """Start a reply to a message in the background."""
        if denied(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        thread = find(request)
        if thread is None:
            return JSONResponse({"error": "no such thread"}, status_code=404)
        body = await request.json()
        message = body.get("message") if isinstance(body, dict) else None
        if not isinstance(message, str) or not message.strip():
            return JSONResponse({"error": "message is required"}, status_code=400)
        if blocked:
            return JSONResponse({"error": blocked}, status_code=503)
        if thread.busy:
            return JSONResponse({"error": "a reply is already running"}, status_code=409)
        thread.busy = True
        launch(thread, message)
        return JSONResponse({"started": True}, status_code=202)

    async def stream(request: Request):
        """Send the thread's events as SSE, from after N, until the run ends."""
        if denied(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        thread = find(request)
        if thread is None:
            return JSONResponse({"error": "no such thread"}, status_code=404)
        raw = request.query_params.get("after") or request.headers.get("last-event-id") or "0"
        after = int(raw) if raw.isdigit() else 0

        async def frames():
            """Yield each new event as it appears; stop after a run ends."""
            sent = after
            while True:
                while sent < len(thread.events):
                    event = thread.events[sent]
                    sent += 1
                    yield wire.to_sse(event, sent)
                    if wire.is_final(event):
                        return
                if thread.waiting or thread.approving:
                    return  # paused on the browser; it reconnects with ?after=N after answering
                if await request.is_disconnected():
                    return
                await asyncio.sleep(0.01)

        return StreamingResponse(frames(), media_type="text/event-stream")

    return Starlette(
        routes=[
            Route("/status", status, methods=["GET"]),
            Route("/threads", new_thread, methods=["POST"]),
            Route("/threads/{id}/runs", start_run, methods=["POST"]),
            Route("/approvals/{id}", approval, methods=["POST"]),
            Route("/browser-results/{id}", browser_result, methods=["POST"]),
            Route("/threads/{id}/stream", stream, methods=["GET"]),
        ]
    )


REFUSE_ROOT = "The agent service won't run as root. Start it as its own user (phoenix-agentkit)."


def read_secret_file(path: str) -> str | None:
    """Read a one-line secret file; None when it is missing, unreadable or empty."""
    try:
        return Path(path).read_text().strip() or None
    except OSError:
        return None


def build_service_app(cfg: config.Config, token: str, model, phoenix: PhoenixClient, store: Store,
                      key_present: bool = True) -> Starlette:
    """Assemble the real service: store, spend meter, the Phoenix pack, runs and every route.

    The model is wrapped so every call is checked against the allowance (prices not filled in means
    every call is refused with a plain message) and its tokens are recorded.
    """
    meter = spend.Meter(store, cfg)
    pack = build_pack(phoenix)
    agent = llm.build_pack_agent(llm.SpendModel(model, meter), pack, tuple(cfg.link_schemes))
    run = runs.Runs(store, agent, pack)
    info = {"key_present": key_present, "pack": cfg.pack, "model": cfg.model}

    def denied(request: Request) -> bool:
        """True when the bearer token is missing or wrong."""
        given = request.headers.get("authorization", "")
        return not hmac.compare_digest(given.encode(), f"Bearer {token}".encode())

    async def status(request: Request):
        """Say whether the service is up, has a key, and which pack and model it uses."""
        if denied(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return JSONResponse({"running": True, **info})

    @asynccontextmanager
    async def lifespan(_app):
        """Close the database file when the service stops."""
        yield
        store.close()

    return Starlette(
        routes=[
            Route("/status", status, methods=["GET"]),
            Route("/spend", spend.spend_route(meter, denied), methods=["GET"]),
            Route("/threads", runs.new_route(run, denied), methods=["POST"]),
            Route("/threads", runs.list_route(run, denied), methods=["GET"]),
            Route("/threads/{id}", runs.read_route(run, denied), methods=["GET"]),
            Route("/threads/{id}/runs", runs.start_route(run, denied), methods=["POST"]),
            Route("/threads/{id}/stream", runs.stream_route(run, denied), methods=["GET"]),
            Route("/threads/{id}/stop", runs.stop_route(run, denied), methods=["POST"]),
            Route("/approvals/{id}", runs.approval_route(run, denied), methods=["POST"]),
            Route("/browser-results/{id}", runs.browser_route(run, denied), methods=["POST"]),
        ],
        lifespan=lifespan,
    )


def app_from_config(cfg: config.Config) -> Starlette:
    """Build the real app: read the token and the key once; the key goes only to llm.py."""
    token = read_secret_file(cfg.token_file)
    if not token:
        raise config.ConfigError("The agent's shared token file is missing or empty.")
    key = read_secret_file(cfg.api_key_file)
    model = llm.make_model(cfg.model, key) if key else llm.no_key_model()
    try:
        store = Store(cfg.db_file)
    except (OSError, sqlite3.Error) as err:
        raise config.ConfigError(f"The agent's database can't be opened ({type(err).__name__}).") from err
    return build_service_app(cfg, token, model, PhoenixClient(cfg.phoenix_api), store, key is not None)


def main(argv=None) -> int:
    """Start the service with uvicorn on 127.0.0.1; refuse to run as root."""
    parser = argparse.ArgumentParser(prog="agentkit.service")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    if os.getuid() == 0:
        print(REFUSE_ROOT, file=sys.stderr)
        return 1
    try:
        cfg = config.load(args.config)
        if cfg.host != "127.0.0.1":
            raise config.ConfigError("The agent service only listens on 127.0.0.1.")
        app = app_from_config(cfg)
    except config.ConfigError as e:
        print(str(e), file=sys.stderr)
        return 1
    import uvicorn

    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
