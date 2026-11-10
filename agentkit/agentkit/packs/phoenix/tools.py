"""The Phoenix pack's read tools: list_projects, show_project and list_runs, each giving typed card data."""
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, Field

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
    return f"#/projects/{name}"


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
        "link": f"{link_for(name)}/builds/{row.get('run_id', '')}",
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
