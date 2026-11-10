"""The agent service (proof slice): threads, runs and the AG-UI event stream over SSE."""
import asyncio
import hmac

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from . import llm, wire


class Thread:
    """One conversation: its ordered event list."""

    def __init__(self, thread_id: str):
        self.id = thread_id
        self.events: list[dict] = []
        self.busy = False


def create_app(model, token: str) -> Starlette:
    """Build the service app for a model and the shared token."""
    agent = llm.build_agent(model)
    threads: dict[str, Thread] = {}
    tasks: set[asyncio.Task] = set()

    def denied(request: Request) -> bool:
        """True when the bearer token is missing or wrong."""
        given = request.headers.get("authorization", "")
        return not hmac.compare_digest(given.encode(), f"Bearer {token}".encode())

    def find(request: Request) -> Thread | None:
        """The thread named in the URL, if any."""
        return threads.get(request.path_params["id"])

    async def drive(thread: Thread, message: str):
        """Run the model and append the events for it to the thread."""
        run_id, msg_id = wire.new_id(), wire.new_id()
        thread.events.append(wire.run_started(thread.id, run_id))
        try:
            thread.events.append(wire.text_start(msg_id))
            async for piece in llm.stream_reply(agent, message):
                thread.events.append(wire.text_content(msg_id, piece))
            thread.events.append(wire.text_end(msg_id))
            thread.events.append(wire.run_finished(thread.id, run_id))
        except Exception:
            thread.events.append(wire.run_error("The agent could not finish this reply."))
        finally:
            thread.busy = False

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
        task = asyncio.create_task(drive(thread, message))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
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
                if await request.is_disconnected():
                    return
                await asyncio.sleep(0.01)

        return StreamingResponse(frames(), media_type="text/event-stream")

    return Starlette(
        routes=[
            Route("/threads", new_thread, methods=["POST"]),
            Route("/threads/{id}/runs", start_run, methods=["POST"]),
            Route("/threads/{id}/stream", stream, methods=["GET"]),
        ]
    )
