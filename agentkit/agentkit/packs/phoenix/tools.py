"""The Phoenix pack's card helpers (project and run cards) and the go_to tool's page checks."""
from pydantic import BaseModel, Field, model_validator

from agentkit.packs.phoenix.client import PhoenixClient, PhoenixError

SOURCE = "phoenix"


def link_for(name: str) -> str:
    """The dashboard hash link to a project."""
    return f"#/p/{name}"


def project_card(row: dict) -> dict:
    """Card data for one project: name, status, last used and link hash."""
    return {
        "name": row.get("name", ""),
        "status": row.get("activity") or row.get("status") or "idle",
        "status_line": row.get("status_line") or "",
        "last_used": row.get("last_used") or "",
        "link": link_for(row.get("name", "")),
    }


def run_card(name: str, row: dict) -> dict:
    """Card data for one build run: id, title, status, when and link hash."""
    return {
        "run_id": row.get("run_id", ""),
        "title": row.get("title") or "",
        "status": row.get("status") or "",
        "last_used": row.get("finished") or row.get("started") or "",
        "link": f"{link_for(name)}/build",
    }


def route_table(client: PhoenixClient) -> dict[str, list[str]]:
    """The dashboard pages from GET /api/routes as {page name: its params}."""
    found = client.get("/api/routes")
    rows = found.get("data", []) if isinstance(found, dict) else found
    table = {}
    for row in rows:
        name, params = (row.get("name"), row.get("params")) if isinstance(row, dict) else (row[0], row[1])
        table[name] = list(params or [])
    return table


def find_page(table: dict[str, list[str]], page: str) -> list[str] | None:
    """The params allowed for a page such as 'p/test-site/build', or None when the page is unknown."""
    parts = page.split("/")
    generic = f"p/<name>/{parts[2]}" if len(parts) == 3 and parts[0] == "p" and parts[1] else page
    return table.get(generic)


def go_to_inputs(client: PhoenixClient) -> type[BaseModel]:
    """A go_to input model that refuses unknown pages and params (so the run never pauses for them)."""

    class GoTo(BaseModel):
        """Which dashboard page to open, and its params."""

        page: str = Field(description="A page from the dashboard's page list, e.g. 'projects' or 'p/<name>/build'.")
        params: dict[str, str | int | bool] = Field(default_factory=dict, description="Optional page params.")

        @model_validator(mode="after")
        def known_page(self):
            try:
                allowed = find_page(route_table(client), self.page)
            except PhoenixError as err:
                raise ValueError(str(err)) from err
            if allowed is None:
                raise ValueError(f"there is no dashboard page called '{self.page}'")
            extra = sorted(set(self.params) - set(allowed))
            if extra:
                raise ValueError(f"the page '{self.page}' has no setting called '{extra[0]}'")
            return self

    return GoTo
