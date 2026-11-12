"""The bell: one plain list of what needs Alex (questions, failed builds, held merge requests, services, allowance, the newest daily report).

Plain rules over Phoenix's own data, no AI. Every text is scrubbed and has no money figure; a source that fails is skipped.
"""
from __future__ import annotations

import re
import time

from phoenix9 import allowance, doctor, gates, routes, runs, scrub, statusreport as sr
from phoenix9.ops.common import OpsError

MONEY = re.compile(r"(?:US|AU|A)?\$\s?\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\s?(?:USD|AUD|dollars?)\b|\b(?:USD|AUD)\s?\d[\d,]*(?:\.\d+)?", re.I)
TEXT_MAX = 200


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


def _services(adapters) -> list[dict]:
    """One item per Phoenix service that is not active."""
    rc, out, _ = adapters.host.run(["systemctl", "is-active", *doctor.SERVICES])
    states = out.split()
    return [_item("service", "phoenix", name, f"{name} is not running",
                  f"It is {states[i] if i < len(states) else 'unknown'}. Run `phoenix doctor`.", _page("settings", section="services"))
            for i, name in enumerate(doctor.SERVICES) if i >= len(states) or states[i] != "active"]


def _allowance(adapters) -> list[dict]:
    """An item when the month's allowance is low or used up."""
    a = allowance.read(adapters)
    if a["state"] not in ("low", "used_up"):
        return []
    return [_item("allowance", "phoenix", a["state"], f"The agent's allowance is {a['state'].replace('_', ' ')}", a["words"],
                  _page("settings", section="models"))]


def _reports() -> list[dict]:
    """One item for the newest daily report (the next one replaces it)."""
    from phoenix9 import dailyreport  # here because dailyreport itself reads the bell
    found = dailyreport.latest()
    if not found:
        return []
    return [_item("report", "phoenix", found["date"], f"Daily report for {found['date']}", found["text"], _page("projects"), found["date"])]


def items(adapters, now: float | None = None) -> list[dict]:
    """Everything that needs Alex, from the real state; a source that fails is skipped."""
    now = time.time() if now is None else now
    found = []
    for source in (_questions, lambda: _builds(now), lambda: _merges(adapters, now), lambda: _services(adapters),
                   lambda: _allowance(adapters), _reports):
        found += sr._safe(source) or []
    return found


def count(found: list[dict]) -> int:
    """How many items are in the list."""
    return len(found)
