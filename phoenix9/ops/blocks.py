"""Ops for reply blocks: check one agent block (card, choice, confirm, nav) and resolve what it points at."""
import json
import re

from phoenix9 import cards, routes
from phoenix9.ops import common

KINDS = ("card", "choice", "confirm", "nav")
MAX_BYTES = 8 * 1024
_ID = re.compile(r"[A-Za-z0-9_-]{1,40}")


class _Bad(Exception):
    """A block that fails the check, with the plain reason."""


def _keys(obj: dict, required: set, optional: set, where: str) -> None:
    """Refuse missing or unknown keys of an object."""
    if "actions" in obj:
        raise _Bad("Blocks may not carry 'actions'; buttons come from Phoenix.")
    for key in sorted(set(obj) - required - optional):
        raise _Bad(f"{where} has an unknown key '{key}'.")
    for key in sorted(required - set(obj)):
        raise _Bad(f"{where} needs '{key}'.")


def _text(obj: dict, key: str, where: str) -> str:
    """A non-empty text field."""
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _Bad(f"{where} '{key}' must be non-empty text.")
    return value


def _flag(obj: dict, key: str, where: str) -> bool:
    """An optional true/false field (false when absent)."""
    value = obj.get(key, False)
    if not isinstance(value, bool):
        raise _Bad(f"{where} '{key}' must be true or false.")
    return value


def _id(obj: dict) -> str:
    """The block id: 1-40 letters, digits, '-' or '_'."""
    value = obj.get("id")
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise _Bad("'id' must be 1-40 characters of letters, digits, - or _.")
    return value


def _card(obj: dict) -> dict:
    """Check a card block against its card type's schema."""
    _keys(obj, {"v", "type"}, {"query", "title"}, "The card")
    name = _text(obj, "type", "The card")
    module = cards.load(name)
    if module is None:
        raise _Bad(f"'{name}' is not a card type. Use one of: {', '.join(cards.types())}.")
    query = obj.get("query", {})
    reason = cards.check_query(module, query)
    if reason:
        raise _Bad(reason)
    title = obj.get("title")
    if title is not None and not isinstance(title, str):
        raise _Bad("The card 'title' must be text.")
    return {"type": name, "query": query, "title": title}


def _nav(obj: dict) -> dict:
    """Check a nav block: resolve each link, drop the failed ones and list why."""
    _keys(obj, {"v", "links"}, set(), "The nav block")
    links = obj["links"]
    if not isinstance(links, list) or not 1 <= len(links) <= 8:
        raise _Bad("'links' must be a list of 1 to 8 links.")
    good, dropped = [], []
    for i, link in enumerate(links, 1):
        try:
            if not isinstance(link, dict):
                raise _Bad("A link must be an object.")
            _keys(link, {"to"}, {"params", "label"}, f"Link {i}")
            label = link.get("label")
            if label is not None and not isinstance(label, str):
                raise _Bad(f"Link {i} 'label' must be text.")
            found = routes.resolve(_text(link, "to", f"Link {i}"), link.get("params"))
            good.append({"hash": found["hash"], "label": label or found["label"]})
        except (_Bad, common.OpsError) as err:
            dropped.append({"link": i, "to": link.get("to") if isinstance(link, dict) else None, "reason": str(err)})
    if not good:
        raise _Bad("No link could be opened: " + "; ".join(d["reason"] for d in dropped))
    return {"links": good, "dropped": dropped}


def _option(option, seen: set) -> dict:
    """Check and normalise one choice option."""
    if not isinstance(option, dict):
        raise _Bad("An option must be an object.")
    _keys(option, {"key", "label"}, {"detail", "recommended"}, "An option")
    key = _text(option, "key", "An option")
    if key in seen:
        raise _Bad(f"Two options use the key '{key}'.")
    seen.add(key)
    out = {"key": key, "label": _text(option, "label", "An option")}
    if "detail" in option:
        out["detail"] = _text(option, "detail", "An option")
    if "recommended" in option:
        if option["recommended"] is not True:
            raise _Bad("An option's 'recommended' can only be true.")
        out["recommended"] = True
    return out


def _choice(obj: dict) -> dict:
    """Check and normalise a choice block."""
    _keys(obj, {"v", "id", "question", "mode", "options"}, {"other"}, "The choice")
    if obj["mode"] not in ("single", "multi"):
        raise _Bad("'mode' must be single or multi.")
    options = obj["options"]
    if not isinstance(options, list) or not 2 <= len(options) <= 8:
        raise _Bad("'options' must be a list of 2 to 8 options.")
    seen: set = set()
    clean = [_option(o, seen) for o in options]
    if sum(1 for o in clean if o.get("recommended")) > 1:
        raise _Bad("At most one option may be recommended.")
    return {"v": 1, "id": _id(obj), "question": _text(obj, "question", "The choice"), "mode": obj["mode"],
            "options": clean, "other": _flag(obj, "other", "The choice")}


def _confirm(obj: dict) -> dict:
    """Check and normalise a confirm block."""
    _keys(obj, {"v", "id", "action", "command"}, {"danger"}, "The confirm")
    return {"v": 1, "id": _id(obj), "action": _text(obj, "action", "The confirm"),
            "command": _text(obj, "command", "The confirm"), "danger": _flag(obj, "danger", "The confirm")}


_CHECKS = {"card": _card, "choice": _choice, "confirm": _confirm, "nav": _nav}


def _parse(kind: str, text) -> dict:
    """The block as an object, after the size, JSON and version checks."""
    if kind not in KINDS:
        raise _Bad(f"'{kind}' is not a block kind. Use one of: {', '.join(KINDS)}.")
    if not isinstance(text, str):
        raise _Bad("The block must be text.")
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise _Bad("The block is over 8 KB.")
    try:
        obj = json.loads(text)
    except ValueError:
        raise _Bad("The block is not valid JSON.") from None
    if not isinstance(obj, dict):
        raise _Bad("The block must be one JSON object.")
    version = obj.get("v")
    if "v" not in obj:
        raise _Bad('The block needs "v": 1.')
    if version != 1 or isinstance(version, bool) or not isinstance(version, int):
        raise _Bad(f"Block version {json.dumps(version)} is not supported; use 1.")
    return obj


def check(block: dict) -> dict:
    """Check a {kind, json} block; return {ok, reason, resolved} (resolved is None when not ok)."""
    if not isinstance(block, dict):
        raise common.OpsError("Give the block as {kind, json}.")
    try:
        obj = _parse(block.get("kind"), block.get("json"))
        resolved = _CHECKS[block["kind"]](obj)
    except _Bad as err:
        return {"ok": False, "reason": str(err), "resolved": None}
    return {"ok": True, "reason": None, "resolved": resolved}
