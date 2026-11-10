"""Server-side runs: a reply is an asyncio task that keeps going with no browser attached."""
import asyncio

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from pydantic import ValidationError

from . import llm, tools, wire
from .store import Store

BUSY = "A reply is already being written in this chat. Wait for it to finish or stop it first."
DEFAULT_TITLE = "New chat"
TITLE_LENGTH = 60
WAITING = "This chat is waiting for your answer on a change. Approve or refuse it first."
REFUSED = "Alex refused this"
FAILED = "The agent could not finish this reply."


class RunBusy(Exception):
    """Raised when a thread already has a run going."""


class Unknown(Exception):
    """Raised when an approval id is not one the store has."""


class AlreadyAnswered(Exception):
    """Raised when an approval already has an answer."""


class Runs:
    """Starts and tracks runs; each one logs every AG-UI event to its thread through wire.py."""

    def __init__(self, store: Store, agent, pack=None):
        """Keep the store (the event log), the agent that answers and the pack whose browser inputs get checked."""
        self.store = store
        self.agent = agent
        self.browser_inputs = {t.name: t.inputs for t in pack.browser_tools} if pack else {}
        self.ready: set[str] = set()
        self.active: dict[str, asyncio.Task] = {}
        self.history: dict[str, list] = {}

    def _history(self, thread_id: str) -> list:
        """The thread's model history: from memory, else from the store."""
        if thread_id not in self.history:
            saved = self.store.load_history(thread_id)
            self.history[thread_id] = llm.load_messages(saved) if saved else []
        return self.history[thread_id]

    def start(self, thread_id: str, message: str) -> str:
        """Start a run in the background and return its id at once; one run per thread."""
        if thread_id in self.active:
            raise RunBusy(BUSY)
        if self.store.pending_pauses(thread_id):
            raise RunBusy(WAITING)  # only POST /approvals can answer a pause, never a chat message
        run_id = wire.new_id()
        if (thread := self.store.get_thread(thread_id)) and thread["title"] == DEFAULT_TITLE:
            self.store.set_title(thread_id, message.strip()[:TITLE_LENGTH])
        self._launch(thread_id, run_id, message)
        return run_id

    def _launch(self, thread_id: str, run_id: str, message: str | None, results=None) -> None:
        """Run a turn as a background task, tracked as the thread's active run."""
        task = asyncio.create_task(self._drive(thread_id, run_id, message, results))
        self.active[thread_id] = task
        task.add_done_callback(lambda _t: self._finished(thread_id))

    def _finished(self, thread_id: str) -> None:
        """Forget the ended run; carry on at once if every call it left behind already has an answer."""
        self.active.pop(thread_id, None)
        if thread_id in self.ready:
            self.ready.discard(thread_id)
            if not self.store.pending_pauses(thread_id):
                self._resume(thread_id)

    def _resume(self, thread_id: str) -> None:
        """Start the follow-up run with every answer and decision collected for the thread."""
        approvals = {
            p["call_id"]: (True if p["state"] == "approved" else llm.refusal(REFUSED))
            for p in self.store.take_decided(thread_id, "approval")}
        calls = {p["call_id"]: p["result"] for p in self.store.take_decided(thread_id, "browser")}
        self._launch(thread_id, wire.new_id(), None, llm.resume_results(calls, approvals))

    async def browser_result(self, pause_id: str, result) -> None:
        """Record the browser's answer to a paused tool call once, log it, and resume when all are answered."""
        pause = self.store.get_pause(pause_id)
        if pause is None or pause["kind"] != "browser":
            raise Unknown(pause_id)
        if not self.store.resolve_pause(pause_id, "answered", tools.quoted("the browser", result)):
            raise AlreadyAnswered(pause_id)
        thread_id = pause["thread_id"]
        if (task := self.active.get(thread_id)) is not None:
            await asyncio.gather(task, return_exceptions=True)  # the run is still winding down
        if self.store.pending_pauses(thread_id) or thread_id in self.active:
            return
        self._resume(thread_id)

    def _check_browser_call(self, thread_id: str, call) -> None:
        """Check a browser call's inputs; pause for the browser if good, else answer the model with the error."""
        inputs = call.args_as_dict()
        model = self.browser_inputs.get(call.tool_name)
        problem = None
        if model is not None:
            try:
                model(**inputs)
            except ValidationError as err:
                problem = "; ".join(
                    f"{'.'.join(str(x) for x in e['loc']) or 'input'}: {e['msg']}" for e in err.errors())
            except TypeError:
                problem = "the inputs must be an object"
        self._log(thread_id, *wire.tool_call(call.tool_call_id, call.tool_name, call.args_as_json_str()))
        pause_id = self.store.create_pause(thread_id, "browser", call.tool_name, inputs, call.tool_call_id)
        if problem is None:
            self._log(thread_id, wire.browser_tool(pause_id, call.tool_call_id, call.tool_name, inputs))
            return
        error = tools.quoted("browser tool check", {"error": f"The inputs for {call.tool_name} were not valid: {problem}"})
        self.store.resolve_pause(pause_id, "answered", error)

    async def decide(self, approval_id: str, decision: str) -> None:
        """Record Alex's answer to a paused change once, log it, and resume the run when all are answered."""
        pause = self.store.get_pause(approval_id)
        if pause is None or pause["kind"] != "approval":
            raise Unknown(approval_id)
        state = "approved" if decision == "approve" else "denied"
        if not self.store.resolve_pause(approval_id, state, {"decision": decision}):
            raise AlreadyAnswered(approval_id)
        thread_id = pause["thread_id"]
        self._log(thread_id, wire.approval_decision(approval_id, decision))
        if (task := self.active.get(thread_id)) is not None:
            await asyncio.gather(task, return_exceptions=True)  # the run is still winding down
        if self.store.pending_pauses(thread_id) or thread_id in self.active:
            return
        self._resume(thread_id)

    def running(self, thread_id: str) -> bool:
        """True while the thread has a run going."""
        return thread_id in self.active

    async def stop(self, thread_id: str) -> bool:
        """Stop the thread's run now (cancelling the model call) and close its pauses; False when nothing is going."""
        task = self.active.get(thread_id)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)  # _drive logs the stop as it unwinds
            return True
        if self.store.pending_pauses(thread_id):
            self._log_stop(thread_id, wire.new_id())  # a run paused on an answer: nothing to cancel
            return True
        return False

    def _log_stop(self, thread_id: str, run_id: str) -> None:
        """Close every open pause as stopped, then log run_stopped and RUN_FINISHED."""
        for pause in self.store.pending_pauses(thread_id):
            self.store.resolve_pause(pause["id"], "stopped")
        self.ready.discard(thread_id)
        self._log(thread_id, wire.run_stopped(), wire.run_finished(thread_id, run_id))

    def _log(self, thread_id: str, *events: dict) -> None:
        """Append events to the thread's log."""
        for event in events:
            self.store.append_event(thread_id, event)

    async def _drive(self, thread_id: str, run_id: str, message: str | None, results=None) -> None:
        """Run one turn and log its events; always ends with RUN_FINISHED or RUN_ERROR (unless paused)."""
        msg_id, text_open, paused = wire.new_id(), False, False
        self._log(thread_id, wire.run_started(thread_id, run_id))
        if message is not None:
            self._log(thread_id, wire.user_message(wire.new_id(), message))
        try:
            async for item in llm.run_turn(self.agent, message, self._history(thread_id), results):
                if item[0] == "text":
                    if not text_open:
                        self._log(thread_id, wire.text_start(msg_id))
                        text_open = True
                    self._log(thread_id, wire.text_content(msg_id, item[1]))
                elif item[0] == "tool":
                    _, call_id, name, card = item
                    self._log(thread_id, *wire.tool_call(call_id, name, "{}"))
                    if card:
                        self._log(thread_id, wire.component(call_id, card["component"], card["data"]))
                elif item[0] == "done":
                    self.history[thread_id] = item[1]
                    self.store.save_history(thread_id, llm.dump_messages(item[1]))
                    for call in item[3]:
                        inputs = call.args_as_dict()
                        pause_id = self.store.create_pause(
                            thread_id, "approval", call.tool_name, inputs, call.tool_call_id)
                        self._log(thread_id, *wire.tool_call(call.tool_call_id, call.tool_name, call.args_as_json_str()))
                        self._log(thread_id, wire.approval_request(pause_id, call.tool_call_id, call.tool_name, inputs))
                        paused = True
                    for call in item[2]:
                        self._check_browser_call(thread_id, call)
                    if item[2] or item[3]:
                        paused = True
                        self.ready.add(thread_id)  # go on at once if nothing is left to wait for
            if text_open:
                self._log(thread_id, wire.text_end(msg_id))
            if not paused:
                self._log(thread_id, wire.run_finished(thread_id, run_id))
        except asyncio.CancelledError:
            self._log_stop(thread_id, run_id)
        except Exception:
            self._log(thread_id, wire.run_error(FAILED))


NOT_RUNNING = "Nothing is running in this chat, so there is nothing to stop."


def stop_route(runs: Runs, denied):
    """Make the POST /threads/{id}/stop handler: stops the run now, or says plainly that none is going."""

    async def stop(request: Request):
        """Stop the thread's run."""
        if denied(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        thread_id = request.path_params["id"]
        if runs.store.get_thread(thread_id) is None:
            return JSONResponse({"error": "no such thread"}, status_code=404)
        if not await runs.stop(thread_id):
            return JSONResponse({"stopped": False, "message": NOT_RUNNING})
        return JSONResponse({"stopped": True, "message": "Stopped."})

    return stop


def start_route(runs: Runs, denied):
    """Make the POST /threads/{id}/runs handler: answers at once with the run id, or 409 when busy."""

    async def start_run(request: Request):
        """Start a reply to a message in the background."""
        if denied(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        thread_id = request.path_params["id"]
        if runs.store.get_thread(thread_id) is None:
            return JSONResponse({"error": "no such thread"}, status_code=404)
        try:
            body = await request.json()
        except ValueError:
            body = None
        message = body.get("message") if isinstance(body, dict) else None
        if not isinstance(message, str) or not message.strip():
            return JSONResponse({"error": "message is required"}, status_code=400)
        try:
            run_id = runs.start(thread_id, message)
        except RunBusy as e:
            return JSONResponse({"error": str(e)}, status_code=409)
        return JSONResponse({"run_id": run_id}, status_code=202)

    return start_run


HEARTBEAT = ": heartbeat\n\n"
HEARTBEAT_EVERY = 15.0  # seconds of quiet during a run before a keep-alive comment


def start_number(request: Request) -> int:
    """Where to resume: ?after=N, else the Last-Event-ID header, else 0 (everything)."""
    raw = request.query_params.get("after") or request.headers.get("last-event-id") or "0"
    return int(raw) if raw.isdigit() else 0


def stream_route(runs: Runs, denied, poll: float = 0.02):
    """Make the GET /threads/{id}/stream handler: replay logged events after N, then follow live."""

    async def frames(thread_id: str, sent: int, request: Request):
        """Yield logged events after `sent`, follow new ones, and end when the run does."""
        quiet = 0.0
        while True:
            fresh = runs.store.events_after(thread_id, sent)
            for number, event in fresh:
                sent = number
                quiet = 0.0
                yield wire.to_sse(event, number)
                if wire.is_final(event):
                    return
            if not fresh and not runs.running(thread_id):
                # a run may have logged its last events just before it ended
                if not runs.store.events_after(thread_id, sent):
                    yield HEARTBEAT  # nothing going on: say we are alive, then let go
                    return
                continue
            if fresh:
                continue
            if await request.is_disconnected():
                return
            await asyncio.sleep(poll)
            quiet += poll
            if quiet >= HEARTBEAT_EVERY:
                quiet = 0.0
                yield HEARTBEAT

    async def stream(request: Request):
        """Send the thread's events as SSE with ids, from after N, until the run ends."""
        if denied(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        thread_id = request.path_params["id"]
        if runs.store.get_thread(thread_id) is None:
            return JSONResponse({"error": "no such thread"}, status_code=404)
        body = frames(thread_id, start_number(request), request)
        return StreamingResponse(body, media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    return stream


def list_route(runs: Runs, denied):
    """Make the GET /threads handler: every thread, newest used first."""

    async def list_threads(request: Request):
        """List threads with title, created and last used."""
        if denied(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        rows = runs.store.list_threads()
        return JSONResponse({"threads": [
            {"id": t["id"], "title": t["title"], "created": t["created"], "last_used": t["last_used"]}
            for t in rows]})

    return list_threads


def read_route(runs: Runs, denied):
    """Make the GET /threads/{id} handler: the thread and its logged events."""

    async def read_thread(request: Request):
        """Return one thread with all its events, or 404 with a plain message."""
        if denied(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        thread = runs.store.get_thread(request.path_params["id"])
        if thread is None:
            return JSONResponse({"error": "no such thread"}, status_code=404)
        events = [{"number": n, "event": e} for n, e in runs.store.events_after(thread["id"])]
        return JSONResponse({"thread": thread, "events": events, "running": runs.running(thread["id"])})

    return read_thread


def new_route(runs: Runs, denied):
    """Make the POST /threads handler: a new empty thread; old ones stay."""

    async def new_thread(request: Request):
        """Create an empty thread and return it."""
        if denied(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return JSONResponse(runs.store.create_thread(), status_code=201)

    return new_thread


def approval_route(runs: Runs, denied):
    """Make the POST /approvals/{id} handler: the only way a paused change gets approved or refused."""

    async def answer(request: Request):
        """Take approve or deny for one approval id; 404 if unknown, 409 if already answered."""
        if denied(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except ValueError:
            body = None
        decision = body.get("decision") if isinstance(body, dict) else None
        if decision not in ("approve", "deny"):
            return JSONResponse({"error": "decision must be approve or deny"}, status_code=400)
        try:
            await runs.decide(request.path_params["id"], decision)
        except Unknown:
            return JSONResponse({"error": "no such pending approval"}, status_code=404)
        except AlreadyAnswered:
            return JSONResponse({"error": "this approval was already answered"}, status_code=409)
        return JSONResponse({"accepted": True}, status_code=202)

    return answer


def browser_route(runs: Runs, denied):
    """Make the POST /browser-results/{id} handler: the only way a paused browser tool call gets its result."""

    async def answer(request: Request):
        """Take the browser's result for one id; 404 if unknown, 409 if already answered."""
        if denied(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict) or "result" not in body:
            return JSONResponse({"error": "result is required"}, status_code=400)
        try:
            await runs.browser_result(request.path_params["id"], body["result"])
        except Unknown:
            return JSONResponse({"error": "no such pending browser call"}, status_code=404)
        except AlreadyAnswered:
            return JSONResponse({"error": "this browser call was already answered"}, status_code=409)
        return JSONResponse({"accepted": True}, status_code=202)

    return answer
