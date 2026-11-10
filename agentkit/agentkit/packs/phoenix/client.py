"""A thin httpx client for the Phoenix API that turns refusals and failures into plain errors."""
import httpx

DEFAULT_URL = "http://127.0.0.1:8095"


class PhoenixError(Exception):
    """A plain-English reason a Phoenix call did not work."""


class PhoenixClient:
    """Calls Phoenix over HTTP with the X-Phoenix header; it never holds a key."""

    def __init__(self, base_url: str = DEFAULT_URL, transport: httpx.BaseTransport | None = None):
        """Make a client for the Phoenix API at base_url (a transport can be given for tests)."""
        self.http = httpx.Client(
            base_url=base_url, headers={"X-Phoenix": "1"}, transport=transport, timeout=15.0
        )

    def get(self, path: str, params: dict | None = None):
        """GET a path and return its JSON, or raise PhoenixError saying plainly what went wrong."""
        clean = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        return self._answer(lambda: self.http.get(path, params=clean), "look that up")

    def post(self, path: str, body: dict):
        """POST a JSON body to a path and return the JSON reply, or raise PhoenixError saying plainly why not."""
        return self._answer(lambda: self.http.post(path, json=body), "make that change")

    def _answer(self, send, what: str):
        """Send a request and return its JSON, turning every failure into a PhoenixError."""
        try:
            reply = send()
        except httpx.HTTPError as err:
            raise PhoenixError(f"Phoenix could not be reached, so I could not {what}.") from err
        if reply.status_code >= 400:
            raise PhoenixError(_reason(reply))
        try:
            return reply.json()
        except ValueError as err:
            raise PhoenixError("Phoenix gave an answer I could not read.") from err


def _reason(reply: httpx.Response) -> str:
    """The plain reason in a refusal, or a generic one for its status."""
    try:
        body = reply.json()
        text = body.get("error") or body.get("message") if isinstance(body, dict) else None
    except ValueError:
        text = None
    if text:
        return str(text)
    if reply.status_code == 403:
        return "Phoenix refused: the agent isn't allowed to do that."
    if reply.status_code == 404:
        return "Phoenix has no such thing."
    return f"Phoenix could not do that (it answered {reply.status_code})."
