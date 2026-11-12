"""Find the running Phoenix agent chat session and report what state it is in."""
import signal
import time

from phoenix9 import settings, transcript
from phoenix9.adapters import Host
from phoenix9.chatlink import (  # noqa: F401  (the shared wire lives in chatlink; old-agent code and tests read it from here)
    CLAUDE_HOME,
    SOCKET_FOLDER,
    UUID_RE,
    KEYS,
    BRIDGE_RE,
    forget,
    encode_folder,
    transcript_dir,
    transcript_path,
    is_session_id,
    socket_ok,
    _entry,
    _is_live,
    _started,
    _choose,
    _bridge_id,
    _live_in,
    _shape,
    find_in,
    MAX_CHARS,
    SEND_TIMEOUT,
    PANEL_FROM,
    PANEL_NAME,
    SendError,
    TooLong,
    _escape,
    CONTEXT_RE,
    clean_context,
    WHO_RE,
    SPACED_WHO,
    clean_who,
    from_name,
    wrap_head,
    envelope,
    wire_line,
    connect_and_write,
    _log_send,
    send_to,
    send,
    find,
    _main_pid,
    AGENT_NAME,
    _chosen,
)


def _items(host, found: dict) -> list[dict]:
    """The panel items of the agent's transcript (empty when it is missing)."""
    if not found["transcript"]:
        return []
    return transcript.parse(host.read_lines(found["transcript"]))[0]


def _state(found: dict, items: list[dict]) -> str:
    """Pick working, queued or idle from the registry status and the transcript items."""
    if found["status"] == "busy" or (items and items[-1]["type"] == "action"
                                     and items[-1]["status"] == "running"):
        return "working"
    for item in reversed(items):
        if item["type"] == "user":
            break
        if item["type"] == "queued" and item.get("pending", True):
            return "queued"
    return "idle"


def status(home_dir=CLAUDE_HOME, host=None) -> dict:
    """The agent's {state: asleep|idle|working|queued, pid, session_id, name}."""
    host = host or Host()
    found = find(home_dir, host)
    if found is None:
        return {"state": "asleep", "pid": None, "session_id": None, "name": None}
    state = _state(found, _items(host, found))
    return {"state": state, "pid": found["pid"], "session_id": found["session_id"],
            "name": found["name"]}

STOP_TEXT = ("Stop. Alex pressed Stop in the panel, and Phoenix ended the command you were running. "
             "Start nothing new. Reply in a few lines: what was finished, what was cut off part-way, "
             "and anything left in a half-done state.")
TOOL_SHELL_MARK = "/.claude/shell-snapshots/"
KILL_AFTER = 2.0


def _below(table: dict, root: int, pid: int) -> bool:
    """True when pid is a descendant of root, following its parent chain as it is right now."""
    seen = set()
    while pid in table and pid not in seen:
        seen.add(pid)
        pid = table[pid][0]
        if pid == root:
            return True
    return False


def _descendants(table: dict, root: int) -> list[int]:
    """All processes under root, deepest first (children before their parents)."""
    kids: dict = {}
    for pid, (ppid, _) in table.items():
        kids.setdefault(ppid, []).append(pid)
    order, queue = [], [root]
    while queue:
        for kid in kids.get(queue.pop(0), []):
            order.append(kid)
            queue.append(kid)
    return order[::-1]


def _signal_all(host, agent_pid: int, pids: list[int], sig) -> None:
    """Signal each pid, but only while it is still under the agent (never the agent itself)."""
    for pid in pids:
        table = host.process_table()
        if pid != agent_pid and _below(table, agent_pid, pid):
            host.signal_pid(pid, sig)


def _end_commands(host, agent_pid: int) -> int:
    """End every command the agent is running: each tool shell and all under it. Returns how many shells."""
    table = host.process_table()
    shells = [p for p in _descendants(table, agent_pid) if TOOL_SHELL_MARK in table[p][1]]
    victims = []
    for shell in shells:
        victims += [p for p in _descendants(table, shell) + [shell] if p not in victims]
    _signal_all(host, agent_pid, victims, signal.SIGTERM)
    if victims:
        time.sleep(KILL_AFTER)
        alive = host.process_table()
        _signal_all(host, agent_pid, [p for p in victims if p in alive], signal.SIGKILL)
    return len([s for s in shells if not any(_below(table, o, s) for o in shells if o != s)])


def interrupt(who: str = "cli", host=None) -> dict:
    """End the command the agent is running, then tell it to stop; returns {stopped, sent}."""
    host = host or Host()
    found = find(host=host)
    if found is None:
        raise SendError("The agent isn't running, so there is nothing to stop.")
    stopped = _end_commands(host, found["pid"])
    send_to(found, STOP_TEXT, None, who, host=host, panel=True)
    return {"stopped": stopped, "sent": True}
