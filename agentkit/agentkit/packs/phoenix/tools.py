"""The Phoenix pack's card helpers (project and run cards) and the go_to tool's page checks."""
from typing import Any

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


def _task_rows(row: dict) -> list[dict]:
    """The tasks of a run as [{number, title, status}], from a state's task map (empty when it has none)."""
    tasks = row.get("tasks")
    if not isinstance(tasks, dict):
        return []
    out = []
    for key, task in tasks.items():
        task = task if isinstance(task, dict) else {}
        out.append({"number": int(key) if str(key).isdigit() else 0, "title": str(task.get("title") or ""),
                    "status": str(task.get("status") or "")})
    return sorted(out, key=lambda t: t["number"])


def run_card(name: str, row: dict) -> dict:
    """Card data for one build run: id, title, status, current step, tasks done of total, when and link hash."""
    rows = _task_rows(row)
    current = row.get("current") if isinstance(row.get("current"), dict) else {}
    done = row.get("tasks_passed") if rows == [] else sum(1 for t in rows if t["status"] == "passed")
    total = row.get("tasks_total") if rows == [] else len(rows)
    step = current.get("step") or row.get("step") or ""
    return {
        "run_id": row.get("run_id", ""),
        "title": row.get("title") or "",
        "status": row.get("status") or "",
        "current_step": str(step),
        "tasks_done": done if isinstance(done, int) else 0,
        "tasks_total": total if isinstance(total, int) else 0,
        "started": row.get("started") or row.get("created") or "",
        "last_used": row.get("finished") or row.get("started") or row.get("created") or "",
        "link": f"{link_for(name)}/build",
    }


def build_card(name: str, row: dict) -> dict:
    """Card data for a build you started or changed: project, run id, status, started and link hash."""
    return {
        "project": name,
        "run_id": row.get("run_id", ""),
        "status": row.get("status") or "",
        "started": row.get("started") or row.get("created") or "",
        "link": f"{link_for(name)}/build",
    }


def task_list(row: dict) -> list[dict]:
    """Card data for a run's task list: number, title and status per task."""
    return _task_rows(row)


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


def ask_for_key_inputs() -> type[BaseModel]:
    """The ask_for_key input model: project, key name and why; there is no field for a value."""

    class AskForKey(BaseModel):
        """Which key to ask Alex for, and why."""

        project: str = Field(description="The project's name.")
        name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", description="The key's name, e.g. STRIPE_KEY.")
        why: str = Field(max_length=200, description="One short sentence saying why the key is needed.")

    return AskForKey


def _flat(values: Any, prefix: str = "") -> list[tuple[str, Any]]:
    """Nested settings as (dotted name, value) pairs."""
    if not isinstance(values, dict):
        return [(prefix, values)]
    out: list[tuple[str, Any]] = []
    for key, value in values.items():
        out += _flat(value, f"{prefix}.{key}" if prefix else str(key))
    return out


def settings_card(name: str, data: Any, check: bool = False) -> dict:
    """Card data for settings: name/value rows, the plain explanation if given, and problems only if the answer lists them."""
    data = data if isinstance(data, dict) else {}
    rows = [{"name": k, "value": "" if v is None else str(v)} for k, v in _flat(data.get("values", {}))] \
        if isinstance(data.get("values"), dict) else []
    card: dict = {"project": name or str(data.get("project") or ""), "rows": rows,
                  "explanation": str(data.get("text") or ""), "link": f"{link_for(name)}/settings"}
    if isinstance(data.get("problems"), list):
        card["problems"] = [str(p) for p in data["problems"]]
        card["note"] = "Check: fine." if not card["problems"] else "Check: problems found."
    elif check:
        card["note"] = "The check result is not known."
    return card


def keys_card(name: str, data: Any) -> dict:
    """Card data for a project's keys: names and set/missing only, never a value."""
    rows = data if isinstance(data, list) else []
    return {"project": name, "keys": [{"name": str(r.get("name", "")), "status": "set" if r.get("has_value") else "missing"}
                                      for r in rows if isinstance(r, dict)],
            "link": f"{link_for(name)}/settings"}


def _version(value: Any) -> str:
    """A version as text from a tag string or a {tag} dict."""
    return str(value.get("tag") or "") if isinstance(value, dict) else str(value or "")


def update_card(data: Any) -> dict:
    """Card data for the updater: installed version, newest version, and whether an install is queued."""
    data = data if isinstance(data, dict) else {}
    queued = data.get("queued") is True or data.get("running") is True
    return {"installed": _version(data.get("installed")), "newest": _version(data.get("newest") or data.get("tag")),
            "queued": queued, "link": "#/settings?section=updates"}
