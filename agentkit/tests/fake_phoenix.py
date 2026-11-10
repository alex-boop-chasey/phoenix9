"""A fake Phoenix on httpx MockTransport at the default address; it records every request."""
import httpx

BASE = "http://127.0.0.1:8095"

PROJECTS = [
    {"name": "alpha", "activity": "idle", "status_line": "Quiet", "last_used": "2026-01-02", "repo_owner": "alex",
     "description": "old site"},
    {"name": "beta", "activity": "run", "status_line": "Building", "last_used": "2026-11-09", "repo_owner": None,
     "description": "new shop"},
]
ROUTES = [["projects", ["q", "status"]], ["new", []], ["p/<name>/build", ["run", "wizard"]], ["settings", ["section"]]]
RUNS = [{"run_id": "20261109-1", "title": "First build", "status": "done", "started": "2026-11-09 10:00"}]


class FakePhoenix:
    """Answers the allowed read routes; `refuse` makes it answer 403 to everything."""

    def __init__(self, refuse: bool = False):
        self.requests: list[httpx.Request] = []
        self.refuse = refuse

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Answer one request."""
        self.requests.append(request)
        if request.headers.get("X-Phoenix") != "1":
            return httpx.Response(400, json={"error": "Missing X-Phoenix."})
        if self.refuse:
            return httpx.Response(403, json={"error": "Refused: the agent isn't allowed to do that."})
        path, query = request.url.path, dict(request.url.params)
        if path == "/api/routes":
            return httpx.Response(200, json={"ok": True, "data": ROUTES})
        if request.method == "POST" and path.endswith("/settings"):
            return httpx.Response(200, json={"ok": True})
        if path == "/api/projects":
            if not query:
                return httpx.Response(200, json=PROJECTS)
            rows = [p for p in PROJECTS if query.get("q", "").lower() in f"{p['name']} {p['description']}"]
            if query.get("status"):
                rows = [p for p in rows if p["activity"] == query["status"]]
            return httpx.Response(200, json={"top": [], "rest": rows, "total": len(rows), "counts": {}})
        parts = path.strip("/").split("/")
        found = next((p for p in PROJECTS if len(parts) >= 3 and p["name"] == parts[2]), None)
        if found is None:
            return httpx.Response(404, json={"error": "There is no project called that."})
        if len(parts) == 3:
            return httpx.Response(200, json=found)
        if parts[3] == "runs":
            return httpx.Response(200, json=RUNS)
        return httpx.Response(404, json={"error": "No such route."})

    def transport(self) -> httpx.MockTransport:
        """The transport to give PhoenixClient."""
        return httpx.MockTransport(self.handle)

    def client(self):
        """A PhoenixClient wired to this fake at the default address."""
        from agentkit.packs.phoenix.client import PhoenixClient
        return PhoenixClient(BASE, transport=self.transport())
