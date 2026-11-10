"""Server-side runs: a reply is an asyncio task that keeps going with no browser attached."""
import asyncio

from starlette.requests import Request
from starlette.responses import JSONResponse

from . import llm, wire
from .store import Store

BUSY = "A reply is already being written in this chat. Wait for it to finish or stop it first."
FAILED = "The agent could not finish this reply."


class RunBusy(Exception):
    """Raised when a thread already has a run going."""


class Runs:
    """Starts and tracks runs; each one logs every AG-UI event to its thread through wire.py."""

    def __init__(self, store: Store, agent):
        """Keep the store (the event log) and the agent that answers."""
        self.store = store
        self.agent = agent
        self.active: dict[str, asyncio.Task] = {}
        self.history: dict[str, list] = {}

    def start(self, thread_id: str, message: str) -> str:
        """Start a run in the background and return its id at once; one run per thread."""
        if thread_id in self.active:
            raise RunBusy(BUSY)
        run_id = wire.new_id()
        task = asyncio.create_task(self._drive(thread_id, run_id, message))
        self.active[thread_id] = task
        task.add_done_callback(lambda _t: self.active.pop(thread_id, None))
        return run_id

    def running(self, thread_id: str) -> bool:
        """True while the thread has a run going."""
        return thread_id in self.active

    def stop(self, thread_id: str) -> bool:
        """Cancel the thread's run; False when none is going."""
        task = self.active.get(thread_id)
        if task is None:
            return False
        task.cancel()
        return True

    def _log(self, thread_id: str, *events: dict) -> None:
        """Append events to the thread's log."""
        for event in events:
            self.store.append_event(thread_id, event)

    async def _drive(self, thread_id: str, run_id: str, message: str) -> None:
        """Run one turn and log its events; always ends with RUN_FINISHED or RUN_ERROR (unless paused)."""
        msg_id, text_open, paused = wire.new_id(), False, False
        self._log(thread_id, wire.run_started(thread_id, run_id))
        try:
            async for item in llm.run_turn(self.agent, message, self.history.get(thread_id, [])):
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
                    for call in item[3]:
                        self._log(thread_id, *wire.tool_call(call.tool_call_id, call.tool_name, call.args_as_json_str()))
                        self._log(thread_id, wire.approval_request(
                            call.tool_call_id, call.tool_call_id, call.tool_name, call.args_as_dict()))
                        paused = True
                    for call in item[2]:
                        self._log(thread_id, *wire.tool_call(call.tool_call_id, call.tool_name, call.args_as_json_str()))
                        paused = True
            if text_open:
                self._log(thread_id, wire.text_end(msg_id))
            if not paused:
                self._log(thread_id, wire.run_finished(thread_id, run_id))
        except asyncio.CancelledError:
            self._log(thread_id, wire.run_error("The reply was stopped."))
        except Exception:
            self._log(thread_id, wire.run_error(FAILED))


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
