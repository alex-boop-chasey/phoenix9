"""Ops for the bell: the list of what needs Alex and how many."""
from phoenix9 import bell as core, routes
from phoenix9.ops import common
from phoenix9.ops.common import OpsError


def _opened(item: dict) -> dict:
    """The item with its page's hash and label added."""
    try:
        return {**item, "page": {**item["page"], **routes.resolve(item["page"]["to"], item["page"]["params"])}}
    except OpsError:
        return item


def show() -> dict:
    """{count, items}: what needs Alex right now."""
    found = [_opened(i) for i in core.items(common.make_adapters())]
    return {"count": core.count(found), "items": found}
