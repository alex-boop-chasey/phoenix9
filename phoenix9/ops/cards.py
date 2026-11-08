"""Ops for cards: build a live card from a type and a query, and write its reply block and summary line."""
import json

from phoenix9 import cards
from phoenix9.ops import common


def build(type: str, query: dict | None = None, title: str | None = None) -> dict:
    """The ready card {type, title, data, actions, watch, inline}; a bad type or query is an OpsError."""
    module = cards.load(type)
    if module is None:
        raise common.OpsError(f"'{type}' is not a card type. Use one of: {', '.join(cards.types())}.")
    query = {} if query is None else query
    reason = cards.check_query(module, query)
    if reason:
        raise common.OpsError(reason)
    if title is not None and not isinstance(title, str):
        raise common.OpsError("The title must be text.")
    made = module.build(query)
    return {"type": type, "title": title or made["title"], "data": made["data"], "actions": made["actions"],
            "watch": made["watch"], "inline": bool(getattr(module, "inline", False))}


def summary(card: dict) -> str:
    """One plain line about a card, like '3 projects need you'."""
    data, kind = card["data"], card["type"]
    if kind == "projects":
        n = data["total"]
        noun = "project" if n == 1 else "projects"
        need = data["counts"]["need"]
        if card["title"] == "Projects that need you":
            n = len(data["top"])
            noun = "project" if n == 1 else "projects"
            return f"{n} {noun} {'needs' if n == 1 else 'need'} you"
        return f"{n} {noun}" + (f", {need} need you" if need else "")
    if kind == "gates":
        return f"{len(data)} open {'question' if len(data) == 1 else 'questions'}"
    if kind == "run":
        return f"Build {data['run_id']} of {data['project']} is {data['status']}"
    if kind == "builds":
        return f"{len(data)} {'build' if len(data) == 1 else 'builds'}"
    return card["title"]


def block(type: str, query: dict | None, title: str | None) -> str:
    """The fenced phoenix-card reply block for this card (only type, query, title travel)."""
    body = {"v": 1, "type": type}
    if query:
        body["query"] = query
    if title:
        body["title"] = title
    return "```phoenix-card\n" + json.dumps(body, sort_keys=True) + "\n```"
