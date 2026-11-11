"""Reads how much of this month's agent allowance is used, in words; never a money figure."""
from phoenix9.agentnext import AgentUnavailable

PLENTY = "plenty left this month"
USED_UP = "used up this month: the agent is paused until next month"
UNKNOWN = "can't tell right now: the agent service isn't answering"
STATES = ("plenty", "low", "used_up")


def words_for(state: str, used_share: float) -> str:
    """Plain English for an allowance state."""
    if state == "plenty":
        return PLENTY
    if state == "low":
        return f"getting low: about {round(used_share * 100)}% of this month's allowance is used"
    if state == "used_up":
        return USED_UP
    return UNKNOWN


def read(adapters) -> dict:
    """Ask the agent service for the allowance and return {state, used_share, words}; never raises."""
    try:
        data = adapters.agentnext.get_json("/spend")
    except AgentUnavailable:
        return {"state": "unknown", "used_share": None, "words": UNKNOWN}
    state = data.get("state")
    share = data.get("used_share")
    if state not in STATES or isinstance(share, bool) or not isinstance(share, (int, float)):
        return {"state": "unknown", "used_share": None, "words": UNKNOWN}
    share = min(1.0, max(0.0, float(share)))
    return {"state": state, "used_share": share, "words": words_for(state, share)}
