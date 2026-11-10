"""Follow-up suggestions: checks the few buttons the agent offers after a turn."""
from urllib.parse import urlparse

from pydantic import BaseModel, Field

MAX_ACTIONS = 3
MAX_LABEL = 60
MAX_MESSAGE = 500
MAX_LINK = 500
NEVER = ("javascript", "data", "vbscript", "file", "blob")


class SuggestionError(ValueError):
    """Raised when a suggestion is not allowed, with a plain-English reason."""


class Action(BaseModel):
    """One follow-up: a label plus either a message to send or a link to open."""

    label: str = Field(max_length=MAX_LABEL, description="Short button text, in plain words.")
    message: str | None = Field(default=None, max_length=MAX_MESSAGE, description="What to send as Alex.")
    link: str | None = Field(default=None, max_length=MAX_LINK, description="A #/ page, https link or allowed scheme.")


class Suggestions(BaseModel):
    """What suggest_next_actions takes: at most three follow-ups."""

    actions: list[Action] = Field(max_length=MAX_ACTIONS)


def check_link(link: str, schemes) -> str:
    """Return the link if it is a dashboard hash, an https URL or an allowed scheme; else raise."""
    if any(ord(c) < 33 or ord(c) == 127 for c in link):
        raise SuggestionError("A link may not contain spaces or control characters.")
    if link.startswith("#/"):
        return link
    parsed = urlparse(link)
    scheme = parsed.scheme.lower()
    if scheme in NEVER or not scheme:
        raise SuggestionError(f"Links of that kind are not allowed: {link[:40]}")
    if scheme == "https" and parsed.netloc:
        return link
    if scheme in {s.lower().rstrip(":/") for s in schemes} and link[len(scheme):].startswith("://"):
        return link
    raise SuggestionError(f"That kind of link is not allowed: {link[:40]}")


def check_actions(raw, schemes=("claude",)) -> list[dict]:
    """Check the whole list and return it as plain dicts, or raise SuggestionError."""
    if not isinstance(raw, list):
        raise SuggestionError("The actions must be a list.")
    if len(raw) > MAX_ACTIONS:
        raise SuggestionError(f"At most {MAX_ACTIONS} follow-up actions are allowed.")
    out = []
    for item in raw:
        try:
            action = Action.model_validate(item)
        except ValueError as err:
            raise SuggestionError(f"A follow-up action is not valid: {err}") from err
        if not action.label.strip():
            raise SuggestionError("Every follow-up action needs a label.")
        if (action.message is None) == (action.link is None):
            raise SuggestionError("Each follow-up action needs either a message or a link, not both.")
        if action.message is not None and not action.message.strip():
            raise SuggestionError("A message may not be empty.")
        if action.link is not None:
            check_link(action.link, schemes)
        out.append(action.model_dump(exclude_none=True))
    return out
