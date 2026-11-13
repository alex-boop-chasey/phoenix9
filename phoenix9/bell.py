"""The bell: one plain list of what needs Alex (questions, failed builds, held merge requests, services, allowance, the newest daily report
and every current suggestion from the status report).

Plain rules over Phoenix's own data, no AI. Every text is scrubbed and has no money figure; a source that fails is skipped.
Every item has a date (`since`), newest first; Alex can dismiss an item, and a later, separate event has a new id so it shows again.
"""
from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone

from phoenix9 import allowance, atomic, doctor, gates, paths, routes, runs, scrub, statusreport as sr, suggest
from phoenix9.ops.common import OpsError

MONEY = re.compile(r"(?:US|AU|A)?\$\s?\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\s?(?:USD|AUD|dollars?)\b|\b(?:USD|AUD)\s?\d[\d,]*(?:\.\d+)?", re.I)
TEXT_MAX = 200
ID_MAX = 20000


def store_path():
    """Where the dismissed items live: HOME/cache/bell-dismissed.json."""
    return paths.cache() / "bell-dismissed.json"


def seen_path():
    """Where the first time a service or the allowance was seen going wrong lives: HOME/cache/bell-seen.json."""
    return paths.cache() / "bell-seen.json"


def _iso(when: float) -> str:
    """An ISO time (UTC) for seconds since 1970."""
    return datetime.fromtimestamp(when, timezone.utc).isoformat(timespec="seconds")


def fingerprint(item_id: str) -> str:
    """A short fixed-size name for an item id (ids can be long and hold any characters)."""
    return hashlib.sha256(str(item_id).encode("utf-8")).hexdigest()[:24]


def check_id(item_id) -> str:
    """The id when it is usable text; ValueError with a plain message otherwise."""
    if not isinstance(item_id, str) or not item_id.strip() or len(item_id) > ID_MAX:
        raise ValueError("That is not a bell item id.")
    return item_id


def _load(path) -> dict:
    """A small JSON object from the cache ({} when missing or broken)."""
    data = atomic.read_json(path, {})
    return data if isinstance(data, dict) else {}


def dismissed() -> dict:
    """{fingerprint: time dismissed} for every dismissed item."""
    return _load(store_path())


def suggestion_key(item_id: str) -> str | None:
    """The suggestion key inside a bell id of kind suggestion ('suggestion:<project>:<key>'), else None."""
    kind, _, rest = str(item_id).partition(":")
    key = rest.partition(":")[2]
    return key if kind == "suggestion" and suggest.KEY_RE.fullmatch(key) else None


def dismiss_all(ids, now: float | None = None) -> int:
    """Hide these items from the bell (a suggestion is also dismissed in the suggest store); returns how many ids were given."""
    ids = [check_id(i) for i in ids]
    if not ids:
        return 0
    now = time.time() if now is None else now
    stamp = _iso(now)
    data = dismissed()
    for item_id in ids:
        data[fingerprint(item_id)] = stamp
    atomic.write_json(store_path(), data)
    for key in filter(None, map(suggestion_key, ids)):
        suggest.mark(key, "dismissed", now=now)
    return len(ids)


def dismiss(item_id: str, now: float | None = None) -> None:
    """Hide one item from the bell (it shows again only as a new event with a new id)."""
    dismiss_all([item_id], now)


def strip_money(text) -> str:
    """The text with any dollar figure taken out."""
    return MONEY.sub("an amount", str(text))


def _clean(text) -> str:
    """Text for the bell: one line, scrubbed, no money, not too long."""
    flat = " ".join(strip_money(scrub.scrub(str(text or ""))).split())
    return flat if len(flat) <= TEXT_MAX else flat[:TEXT_MAX - 1].rstrip() + "…"


def _page(to: str, **params) -> dict:
    """A page for the item; falls back to the projects list when routes does not accept it."""
    page = {"to": to, "params": {k: v for k, v in params.items() if v}}
    try:
        routes.resolve(to, page["params"])
    except OpsError:
        return {"to": "projects", "params": {}}
    return page


def _item(kind: str, project: str, key, title, detail, page: dict, since: str = "") -> dict:
    """One bell item with a stable id."""
    return {"id": f"{kind}:{project}:{key}", "kind": kind, "title": _clean(title), "detail": _clean(detail),
            "project": project, "page": page, "since": since}


def _first_seen(prefix: str, wrong: list[str], now: float, stamp: str = "") -> dict:
    """{key: ISO time first seen (stamp, else now)} for the things now wrong under this prefix; ones that are fine again are forgotten."""
    data = _load(seen_path())
    mine = {k: v for k, v in data.items() if k.startswith(prefix)}
    kept = {k: mine.get(k) or stamp or _iso(now) for k in wrong}
    if kept != mine:
        atomic.write_json(seen_path(), {**{k: v for k, v in data.items() if not k.startswith(prefix)}, **kept})
    return kept


def _questions() -> list[dict]:
    """One item per open question."""
    return [_item("question", g["project"], g["id"], f"{g['project']} needs an answer: {g['title']}",
                  g.get("why") or "Answer it on the Needs you page.",
                  _page(f"p/{g['project']}/overview", gate=g["id"]), g.get("created", ""))
            for g in gates.list_gates()]


def _builds(now: float) -> list[dict]:
    """Builds that failed or stopped in the last 7 days and have not been redone."""
    found = runs.list_runs()
    out = []
    for r in found:
        age = sr._age(r["updated"], now)
        if r["status"] in ("failed", "stopped") and age is not None and age <= sr.FAILED_DAYS * sr.DAY and not sr._redone(r, found):
            why = sr._run_reason(runs.run_dir(r["project"], r["run_id"]))
            out.append(_item("build", r["project"], r["run_id"], f"{r['project']}: build {r['run_id']} {r['status']}", why,
                             _page(f"p/{r['project']}/build", run=r["run_id"]), r["updated"]))
    return out


def _merges(adapters, now: float) -> list[dict]:
    """Open merge requests held for more than 3 days."""
    out = []
    for pr in sr._open_prs(adapters):
        age = sr._age(pr["created"], now)
        if age is not None and age > sr.MR_OLD_DAYS * sr.DAY:
            out.append(_item("merge", pr["project"], pr["number"], f"{pr['project']}: merge request #{pr['number']} is waiting",
                             f"{pr['title']} has been open {sr.age_words(age)}.", _page(f"p/{pr['project']}/overview"), pr["created"]))
    return out


def _services(adapters, now: float) -> list[dict]:
    """One item per Phoenix service that is not active; the id holds when Phoenix first saw it down."""
    rc, out, _ = adapters.host.run(["systemctl", "is-active", *doctor.SERVICES])
    states = out.split()
    down = {name: states[i] if i < len(states) else "unknown"
            for i, name in enumerate(doctor.SERVICES) if i >= len(states) or states[i] != "active"}
    seen = _first_seen("service:", [f"service:{name}" for name in down], now)
    return [_item("service", "phoenix", f"{name}:{seen[f'service:{name}']}", f"{name} is not running",
                  f"It is {state}. Run `phoenix doctor`.", _page("settings", section="services"), seen[f"service:{name}"])
            for name, state in down.items()]


def _allowance(adapters, now: float) -> list[dict]:
    """An item when the month's allowance is low or used up; the id holds the state and when Phoenix first saw it."""
    a = allowance.read(adapters)
    if a["state"] == "unknown":
        return []
    wrong = [f"allowance:{a['state']}"] if a["state"] in ("low", "used_up") else []
    seen = _first_seen("allowance:", wrong, now)
    if not wrong:
        return []
    since = seen[f"allowance:{a['state']}"]
    return [_item("allowance", "phoenix", f"{a['state']}:{since}", f"The agent's allowance is {a['state'].replace('_', ' ')}",
                  a["words"], _page("settings", section="models"), since)]


def _reports() -> list[dict]:
    """One item for the newest daily report (the next one replaces it)."""
    from phoenix9 import dailyreport  # here because dailyreport itself reads the bell
    found = dailyreport.latest()
    if not found:
        return []
    try:
        since = _iso((dailyreport._dir() / f"{found['date']}.md").stat().st_mtime)
    except OSError:
        since = f"{found['date']}T00:00:00+00:00"
    return [_item("report", "phoenix", found["date"], f"Daily report for {found['date']}", found["text"], _page("projects"), since)]


PROJECT_KINDS = ("build-running", "build-failed", "mr-old", "edit-stalled", "toml-invalid", "keys-empty", "unpushed")
SUGGESTION_TITLES = {
    "waiting": "{p}: a question is waiting", "build-running": "{p}: a build is running",
    "build-failed": "{p}: a build failed", "mr-old": "{p}: a merge request is waiting",
    "edit-stalled": "{p}: a quick edit has stalled", "toml-invalid": "{p}: the project settings file is not valid",
    "keys-empty": "{p}: some keys are empty", "unpushed": "{p}: commits not pushed to GitHub",
    "build-repeat": "Several builds failed for the same reason", "update-available": "A Phoenix update is available",
    "worker-stuck": "The worker is not responding", "disk-low": "The disk is nearly full", "doctor": "A Phoenix health check failed",
}


def _suggestion_kind(key: str) -> str:
    """The kind of report line a suggestion key names: its first part ('…-waiting' for every kind of question)."""
    head = key.split(":", 1)[0]
    return "waiting" if head.endswith("-waiting") else head


def _suggestion_project(key: str) -> str:
    """The project a suggestion key names, or '' when it names none (or the project is not there)."""
    parts = key.split(":")
    if len(parts) < 2 or _suggestion_kind(key) not in ("waiting", *PROJECT_KINDS):
        return ""
    return parts[1] if (paths.projects() / parts[1]).is_dir() else ""


def _suggestion_page(key: str, project: str) -> dict:
    """The most useful page for a suggestion: the project's Keys or Build tab, the project, or Phoenix settings."""
    kind, parts = _suggestion_kind(key), key.split(":")
    if project and kind in ("keys-empty", "toml-invalid"):
        return _page(f"p/{project}/settings", section="project")
    if project and kind in ("build-running", "build-failed"):
        return _page(f"p/{project}/build", run=parts[2] if len(parts) > 2 else "")
    if project:
        return _page(f"p/{project}/overview")
    if kind == "update-available":
        return _page("settings", section="updates")
    if kind in ("doctor", "worker-stuck", "disk-low"):
        return _page("settings", section="services")
    return _page("projects")


def _same_as(key: str) -> str:
    """The id of the bell item from another source that is about the same thing, or '' when there is none."""
    kind, parts = _suggestion_kind(key), key.split(":")
    other = {"waiting": "question", "build-failed": "build", "mr-old": "merge"}.get(kind)
    if other and len(parts) == 3:
        return f"{other}:{parts[1]}:{parts[2]}"
    return "service" if key == "doctor:services" else ""


def _suggestions(others: list[dict], now: float) -> list[dict]:
    """One item per current suggestion in the saved status report that is not dismissed or snoozed and is not
    already listed by another source; dated from when the report first carried it."""
    path = sr.report_path()
    try:
        text, written = path.read_text(encoding="utf-8"), _iso(path.stat().st_mtime)
    except (OSError, UnicodeError):
        return []
    seen = _first_seen("suggestion:", [f"suggestion:{r['key']}" for r in suggest.parse(text)], now, written)
    listed = {i["id"] for i in others} | {i["kind"] for i in others}
    out = []
    for row in suggest.pick(text, now=now, limit=None):
        key = row["key"]
        if _same_as(key) in listed:
            continue
        project = _suggestion_project(key)
        title = SUGGESTION_TITLES.get(_suggestion_kind(key), "{p}: a suggestion" if project else "A suggestion").format(p=project or "A project")
        out.append(_item("suggestion", project or "phoenix", key, title, row["text"].replace("`", ""),
                         _suggestion_page(key, project), seen.get(f"suggestion:{key}") or written))
    return out


def _prune(store: dict, found: list[dict]) -> None:
    """Forget dismissed entries whose item is gone (so the file never grows); writes only when something went."""
    live = {fingerprint(i["id"]) for i in found}
    kept = {k: v for k, v in store.items() if k in live}
    if len(kept) != len(store):
        atomic.write_json(store_path(), kept)


def _newest_first(found: list[dict]) -> list[dict]:
    """The items sorted by their date, newest first (an unreadable date goes last)."""
    return sorted(found, key=lambda i: sr._epoch(i["since"]) or 0.0, reverse=True)


def items(adapters, now: float | None = None) -> list[dict]:
    """Everything that needs Alex and is not dismissed, newest first, from the real state; a source that fails is skipped."""
    now = time.time() if now is None else now
    found, broken = [], False
    for source in (_questions, lambda: _builds(now), lambda: _merges(adapters, now), lambda: _services(adapters, now),
                   lambda: _allowance(adapters, now), _reports):
        got = sr._safe(source)
        broken = broken or got is None
        found += got or []
    got = sr._safe(_suggestions, found, now)
    broken = broken or got is None
    found += got or []
    store = dismissed()
    if not broken:  # a source that failed hides its items for now; their dismissals must survive that
        _prune(store, found)
    return _newest_first([i for i in found if fingerprint(i["id"]) not in store])


def count(found: list[dict]) -> int:
    """How many items are shown."""
    return len(found)
