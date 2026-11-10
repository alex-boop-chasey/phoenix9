"""The agent service (proof slice): threads, runs and the AG-UI event stream over SSE."""
import asyncio
import hmac

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from . import llm, tools, wire


class Thread:
    """One conversation: its ordered event list."""

    def __init__(self, thread_id: str):
        self.id = thread_id
        self.events: list[dict] = []
        self.busy = False
        self.history: list = []
        self.waiting: dict[str, object] = {}  # browser tool calls the run is paused on
        self.answers: dict[str, object] = {}  # results that came back so far


def create_app(model, token: str, projects=tools.fake_projects) -> Starlette:
    """Build the service app for a model, the shared token and a project source."""
    agent = llm.build_agent(
        model, read_tools=[tools.make_list_projects(projects)], browser_tools=[tools.GO_TO]
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
        text_open, pending = False, []
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
                    pending = item[2]
            if text_open:
                events.append(wire.text_end(msg_id))
            if pending:
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
        if not thread.waiting:
            answers, thread.answers = thread.answers, {}
            launch(thread, None, llm.resume_results(answers))
        return JSONResponse({"accepted": True}, status_code=202)

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
                if thread.waiting:
                    return  # paused on the browser; it reconnects with ?after=N after answering
                if await request.is_disconnected():
                    return
                await asyncio.sleep(0.01)

        return StreamingResponse(frames(), media_type="text/event-stream")

    return Starlette(
        routes=[
            Route("/threads", new_thread, methods=["POST"]),
            Route("/threads/{id}/runs", start_run, methods=["POST"]),
            Route("/browser-results/{id}", browser_result, methods=["POST"]),
            Route("/threads/{id}/stream", stream, methods=["GET"]),
        ]
    )
