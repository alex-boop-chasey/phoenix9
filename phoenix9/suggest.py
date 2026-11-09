"""Suggestions: the status report's lines with their stable ids, and the small store of what was shown, snoozed or dismissed."""
from __future__ import annotations

import re
import time

from phoenix9 import atomic, paths

MAX_SUGGESTIONS = 3
SNOOZE_HOURS = 24.0
ID_RE = re.compile(r"\s*<!--\s*id:\s*([A-Za-z0-9._:+-]+)\s*-->\s*$")
KEY_RE = re.compile(r"[A-Za-z0-9._:+-]{1,200}")
ATTENTION_SECTION = "Waiting for Alex"
ATTENTION_KEYS = ("build-failed:", "build-repeat:", "worker-stuck", "disk-low")


def store_path():
    """Where the store lives: HOME/cache/suggestions.json."""
    return paths.cache() / "suggestions.json"


def check_key(key: str) -> str:
    """The key when it looks like a suggestion id; ValueError with a plain message otherwise."""
    if not isinstance(key, str) or not KEY_RE.fullmatch(key):
        raise ValueError("That is not a suggestion key (letters, digits and . _ : + - only).")
    return key


def load() -> dict:
    """{key: {shown, snoozed_until, dismissed}} from the store ({} when missing or broken)."""
    data = atomic.read_json(store_path(), {})
    return data if isinstance(data, dict) else {}


def mark(key: str, what: str, hours: float = SNOOZE_HOURS, now: float | None = None) -> dict:
    """Record 'shown', 'snoozed' or 'dismissed' for a key; returns the key's entry."""
    check_key(key)
    now = time.time() if now is None else now
    data = load()
    entry = {"shown": None, "snoozed_until": None, "dismissed": False, **(data.get(key) or {})}
    if what == "shown":
        entry["shown"] = now
    elif what == "snoozed":
        entry["snoozed_until"] = now + hours * 3600
    elif what == "dismissed":
        entry["dismissed"] = True
    else:
        raise ValueError(f"Unknown mark '{what}'.")
    data[key] = entry
    atomic.write_json(store_path(), data)
    return entry


def parse(text: str) -> list[dict]:
    """[{key, text, section, attention}] for every report line that carries an id comment."""
    out, section = [], ""
    for raw in text.splitlines():
        if raw.startswith("## "):
            section = raw[3:].strip()
            continue
        found = ID_RE.search(raw)
        if not found or not raw.startswith("- "):
            continue
        key = found.group(1)
        attention = section == ATTENTION_SECTION or key.startswith(ATTENTION_KEYS)
        out.append({"key": key, "text": raw[2:ID_RE.search(raw).start()].strip(), "section": section, "attention": attention})
    return out


def pick(text: str, store: dict | None = None, now: float | None = None, limit: int = MAX_SUGGESTIONS) -> list[dict]:
    """Report lines not dismissed or snoozed, attention ones first, at most `limit`; each row also says if it was shown."""
    now = time.time() if now is None else now
    store = load() if store is None else store
    rows = []
    for row in parse(text):
        entry = store.get(row["key"]) or {}
        if entry.get("dismissed") or (entry.get("snoozed_until") or 0) > now:
            continue
        rows.append({**row, "shown": bool(entry.get("shown"))})
    rows.sort(key=lambda r: not r["attention"])
    return rows[:limit]
