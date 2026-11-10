"""The agent caller as the API sees it: who it is, what it may call, and the dashboard pages it may point at."""
from phoenix9 import access, agentaccess, routes

WHO = agentaccess.WHO
NOT_ALLOWED = agentaccess.NOT_ALLOWED
NEEDS_HEADER = agentaccess.NEEDS_HEADER
route_allowed = agentaccess.route_allowed
settings_refusal = agentaccess.settings_refusal


def is_agent(peer_uid) -> bool:
    """True when the connection's peer is the agent user ([agent_next] uid)."""
    return agentaccess.is_agent(peer_uid, access.peer_uids())


def pages() -> list:
    """The dashboard pages the agent may point at (routes.ROUTES)."""
    return routes.ROUTES
