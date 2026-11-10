"""The Phoenix pack's read tools: list_projects, show_project and list_runs, each giving typed card data."""
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from agentkit.packs.phoenix.client import PhoenixClient, PhoenixError

SOURCE = "phoenix"


class ListProjects(BaseModel):
    """The same filters as the Projects page."""

    q: str = Field("", description="Words to look for in project names and descriptions.")
    status: Literal["all", "run", "fail", "idle", "need"] = Field(
        "all", description="Only projects in this state: run (building), fail, idle, or need (needs Alex)."
    )
    owner: str = Field("all", description="A GitHub owner, 'none' for projects without a repo, or 'all'.")
    sort: Literal["name", "active", "size", "created", "modified"] = Field(
        "name", description="Order of the list; 'modified' puts the most recently changed first."
    )
    attention: bool = Field(False, description="Put projects that need Alex first.")


class ShowProject(BaseModel):
    """Which project to show."""

    name: str = Field(description="The project's name.")


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


def make_tools(client: PhoenixClient) -> tuple[Callable, Callable, Callable]:
    """Build the three read tool bodies around a Phoenix client."""

    def failed(err: PhoenixError) -> dict:
        return {"error": str(err)}

    def list_projects(q: str = "", status: str = "all", owner: str = "all", sort: str = "name",
                      attention: bool = False) -> dict:
        """List projects with the Projects page filters; each is a card."""
        params = {"q": q, "status": None if status == "all" else status,
                  "owner": None if owner == "all" else owner,
                  "sort": None if sort == "name" else sort, "attention": "1" if attention else None}
        if not any(params.values()):
            params = {"sort": "name"}
        try:
            found = client.get("/api/projects", params)
        except PhoenixError as err:
            return failed(err)
        rows = found if isinstance(found, list) else found.get("top", []) + found.get("rest", [])
        return {"projects": [project_card(r) for r in rows]}

    def show_project(name: str) -> dict:
        """Show one project as a card."""
        try:
            return {"project": project_card(client.get(f"/api/projects/{name}"))}
        except PhoenixError as err:
            return failed(err)

    def list_runs(name: str) -> dict:
        """List a project's build runs, newest first."""
        try:
            rows = client.get(f"/api/projects/{name}/runs")
        except PhoenixError as err:
            return failed(err)
        return {"project": name, "runs": [run_card(name, r) for r in rows]}

    return list_projects, show_project, list_runs


class SetNotifications(BaseModel):
    """Which project, and whether to tell Alex when its builds end."""

    name: str = Field(description="The project's name.")
    on: bool = Field(description="True to notify Alex when a build ends, False to stop.")


def make_change_tools(client: PhoenixClient) -> Callable:
    """Build the change tool body around a Phoenix client; it only runs after Alex approves."""

    def set_build_notifications(name: str, on: bool) -> dict:
        """Switch 'notify me when a build ends' on or off for one project."""
        try:
            client.post(f"/api/projects/{name}/settings", {"set": {"steps.notify.on": on}})
        except PhoenixError as err:
            return {"error": str(err)}
        return {"project": name, "build_notifications": on}

    return set_build_notifications


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
