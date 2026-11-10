"""Conversation store: threads, event logs, pending pauses and usage records in SQLite."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, created REAL NOT NULL, last_used REAL NOT NULL);
CREATE TABLE IF NOT EXISTS events (
    thread_id TEXT NOT NULL REFERENCES threads(id), seq INTEGER NOT NULL, data TEXT NOT NULL,
    PRIMARY KEY (thread_id, seq));
CREATE TABLE IF NOT EXISTS pauses (
    id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES threads(id), kind TEXT NOT NULL,
    tool TEXT NOT NULL, inputs TEXT NOT NULL, state TEXT NOT NULL, result TEXT, created REAL NOT NULL,
    call_id TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS histories (
    thread_id TEXT PRIMARY KEY REFERENCES threads(id), data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
    cache_read_tokens INTEGER NOT NULL, cache_write_tokens INTEGER NOT NULL);
"""


class Store:
    """The agent's SQLite database; every write is one transaction."""

    def __init__(self, path: str | Path):
        """Open (and create if needed) the database file."""
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(SCHEMA)
        if "call_id" not in [r["name"] for r in self._db.execute("PRAGMA table_info(pauses)")]:
            self._db.execute("ALTER TABLE pauses ADD COLUMN call_id TEXT NOT NULL DEFAULT ''")

    def close(self) -> None:
        """Close the database file."""
        with self._lock:
            self._db.close()

    def _write(self, fn):
        """Run fn inside one transaction and return its result."""
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                out = fn(self._db)
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")
            return out

    def _read(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        """Run a read query and return all rows."""
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    # threads
    def create_thread(self, title: str = "New chat") -> dict:
        """Make a new thread and return it."""
        tid, now = uuid.uuid4().hex, time.time()
        self._write(lambda db: db.execute(
            "INSERT INTO threads VALUES (?,?,?,?)", (tid, title, now, now)))
        return self.get_thread(tid)

    def get_thread(self, thread_id: str) -> dict | None:
        """Return one thread, or None if it doesn't exist."""
        rows = self._read("SELECT * FROM threads WHERE id=?", (thread_id,))
        return dict(rows[0]) if rows else None

    def list_threads(self) -> list[dict]:
        """Return all threads, most recently used first."""
        rows = self._read("SELECT * FROM threads ORDER BY last_used DESC, created DESC, rowid DESC")
        return [dict(r) for r in rows]

    def set_title(self, thread_id: str, title: str) -> None:
        """Rename a thread."""
        self._write(lambda db: db.execute("UPDATE threads SET title=? WHERE id=?", (title, thread_id)))

    def touch_thread(self, thread_id: str) -> None:
        """Mark a thread as just used."""
        self._write(lambda db: db.execute(
            "UPDATE threads SET last_used=? WHERE id=?", (time.time(), thread_id)))

    # events
    def append_event(self, thread_id: str, event: dict) -> int:
        """Add an event to a thread's log and return its number (1, 2, 3, ...)."""
        def run(db):
            cur = db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE thread_id=?", (thread_id,))
            seq = cur.fetchone()[0]
            db.execute("INSERT INTO events VALUES (?,?,?)", (thread_id, seq, json.dumps(event)))
            db.execute("UPDATE threads SET last_used=? WHERE id=?", (time.time(), thread_id))
            return seq
        return self._write(run)

    def events_after(self, thread_id: str, after: int = 0) -> list[tuple[int, dict]]:
        """Return (number, event) pairs with a number greater than `after`, in order."""
        rows = self._read(
            "SELECT seq, data FROM events WHERE thread_id=? AND seq>? ORDER BY seq", (thread_id, after))
        return [(r["seq"], json.loads(r["data"])) for r in rows]

    # pauses
    def create_pause(self, thread_id: str, kind: str, tool: str, inputs: dict, call_id: str = "") -> str:
        """Record a pending approval or browser result (for the model's tool call `call_id`) and return its id."""
        pid = uuid.uuid4().hex
        self._write(lambda db: db.execute(
            "INSERT INTO pauses (id, thread_id, kind, tool, inputs, state, result, created, call_id) "
            "VALUES (?,?,?,?,?,?,NULL,?,?)",
            (pid, thread_id, kind, tool, json.dumps(inputs), "pending", time.time(), call_id)))
        return pid

    def get_pause(self, pause_id: str) -> dict | None:
        """Return one pause (inputs and result decoded), or None."""
        rows = self._read("SELECT * FROM pauses WHERE id=?", (pause_id,))
        return self._pause(rows[0]) if rows else None

    def pending_pauses(self, thread_id: str | None = None) -> list[dict]:
        """Return pauses still waiting, optionally for one thread."""
        sql, args = "SELECT * FROM pauses WHERE state='pending'", ()
        if thread_id is not None:
            sql, args = sql + " AND thread_id=?", (thread_id,)
        return [self._pause(r) for r in self._read(sql + " ORDER BY created, rowid", args)]

    def resolve_pause(self, pause_id: str, state: str, result: object = None) -> bool:
        """Settle a pending pause once; return False if it was not pending."""
        def run(db):
            cur = db.execute(
                "UPDATE pauses SET state=?, result=? WHERE id=? AND state='pending'",
                (state, json.dumps(result), pause_id))
            return cur.rowcount == 1
        return self._write(run)

    def take_decided(self, thread_id: str, kind: str) -> list[dict]:
        """Return this thread's answered pauses of a kind that no run has used yet, marking them used."""
        def run(db):
            rows = db.execute(
                "SELECT * FROM pauses WHERE thread_id=? AND kind=? AND state IN ('approved','denied') "
                "ORDER BY created, rowid", (thread_id, kind)).fetchall()
            db.executemany("UPDATE pauses SET state='resumed' WHERE id=?", [(r["id"],) for r in rows])
            return [self._pause(r) for r in rows]
        return self._write(run)

    # history
    def save_history(self, thread_id: str, data: str) -> None:
        """Keep the model's message history for a thread (so a paused run can resume after a restart)."""
        self._write(lambda db: db.execute(
            "INSERT INTO histories VALUES (?,?) ON CONFLICT(thread_id) DO UPDATE SET data=excluded.data",
            (thread_id, data)))

    def load_history(self, thread_id: str) -> str | None:
        """Return the saved message history, or None."""
        rows = self._read("SELECT data FROM histories WHERE thread_id=?", (thread_id,))
        return rows[0]["data"] if rows else None

    @staticmethod
    def _pause(row: sqlite3.Row) -> dict:
        """Turn a pause row into a dict."""
        out = dict(row)
        out["inputs"] = json.loads(out["inputs"])
        out["result"] = json.loads(out["result"]) if out["result"] is not None else None
        return out

    # usage
    def record_usage(self, model: str, input_tokens: int, output_tokens: int,
                     cache_read_tokens: int = 0, cache_write_tokens: int = 0,
                     at: float | None = None) -> None:
        """Save one model call's token counts."""
        self._write(lambda db: db.execute(
            "INSERT INTO usage (at, model, input_tokens, output_tokens, cache_read_tokens, "
            "cache_write_tokens) VALUES (?,?,?,?,?,?)",
            (time.time() if at is None else at, model, input_tokens, output_tokens,
             cache_read_tokens, cache_write_tokens)))

    def usage_since(self, since: float = 0.0) -> list[dict]:
        """Return usage records at or after `since`, oldest first."""
        rows = self._read("SELECT * FROM usage WHERE at>=? ORDER BY at, id", (since,))
        return [dict(r) for r in rows]
