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


class ChoiceOption(BaseModel):
    """One option in a choice card."""

    label: str = Field(max_length=60, description="Short option text.")
    hint: str = Field(default="", max_length=120, description="Optional one-line help.")


def ask_choice_inputs() -> type[BaseModel]:
    """The ask_choice input model: a question and 2 to 12 options; the answer is only indexes."""

    class AskChoice(BaseModel):
        """A question with options for Alex to pick from."""

        question: str = Field(max_length=200, description="The question to ask.")
        options: list[ChoiceOption] = Field(min_length=2, max_length=12, description="The options offered.")
        multiple: bool = Field(default=False, description="True when more than one option may be picked.")

    return AskChoice


def ask_env_file_inputs() -> type[BaseModel]:
    """The ask_env_file input model: project and why; there is no field for any value."""

    class AskEnvFile(BaseModel):
        """Which project's .env file to ask Alex for, and why."""

        project: str = Field(description="The project's name.")
        why: str = Field(max_length=200, description="One short sentence saying why the file is needed.")

    return AskEnvFile


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


def _event_row(event: dict) -> dict:
    """One event as a card row: number, time, type, who, task, step and a short plain note."""
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    note = data.get("title") or data.get("note") or data.get("text") or data.get("reason") or ""
    return {"id": event.get("id", 0), "time": str(event.get("ts") or ""), "type": str(event.get("type") or ""),
            "who": str(data.get("who") or ""), "task": event.get("task"), "step": event.get("step") or "",
            "note": str(note)}


def events_card(project: str, data: Any) -> dict:
    """Card data for a run's events: one row per event, oldest first, and the number to continue from."""
    data = data if isinstance(data, dict) else {}
    rows = [_event_row(e) for e in data.get("events", []) if isinstance(e, dict)]
    return {"project": project or str(data.get("project") or ""), "run_id": str(data.get("run_id") or ""),
            "events": rows, "next": data.get("next", 0)}


def try_line(entry: Any) -> str:
    """One plain line for one try: its number, step, result and reason."""
    entry = entry if isinstance(entry, dict) else {}
    line = f"Try {entry.get('attempt', '?')} ({entry.get('step') or 'a step'}): {entry.get('status') or 'unknown'}"
    return line + (f" - {entry['reason']}" if entry.get("reason") else "")


def tries_card(project: str, data: Any) -> dict:
    """Card data for the failing task: its number, title, status, max tries and one line per try."""
    data = data if isinstance(data, dict) else {}
    tries = [t for t in data.get("tries", []) if isinstance(t, dict)]
    return {"project": project or str(data.get("project") or ""), "run_id": str(data.get("run_id") or ""),
            "task": data.get("task"), "title": data.get("title") or "", "status": str(data.get("status") or ""),
            "max_tries": data.get("max_tries"), "tries": [try_line(t) for t in tries]}


def session_card(project: str, data: Any) -> dict:
    """Card data for a step's AI session: the excerpt wrapped as quoted data (never as instructions)."""
    from agentkit.quote import wrap
    data = data if isinstance(data, dict) else {}
    source = str(data.get("source") or "session")
    return {"project": project, "quoted": wrap(source, str(data.get("text") or ""))}


# The registry names of the repair controls, by the short names the diagnosis uses.
OPTION_TOOLS = {"step-rerun": "repair-rerun-step", "task-checks-rewrite": "repair-rewrite-checks",
                "task-skip": "repair-skip-task", "run-resume-from": "repair-resume-from",
                "run-restart-preset": "repair-restart-preset", "max-tries-raise": "repair-raise-max-tries"}


def _option_button(option: Any) -> dict:
    """One button of the diagnosis card: its label, the tool its approval card belongs to and the inputs to fill."""
    option = option if isinstance(option, dict) else {}
    control = str(option.get("control") or "")
    inputs = option.get("inputs") if isinstance(option.get("inputs"), dict) else {}
    if control == "max-tries-raise":
        inputs = {**inputs, "tries": inputs.get("max_tries")}
        inputs.pop("max_tries", None)
    return {"label": str(option.get("label") or ""), "tool": OPTION_TOOLS.get(control, control), "inputs": inputs}


def diagnose_card(project: str, data: Any) -> dict:
    """Card data for 'what happened': the cause in plain words, what was tried and one button per option."""
    data = data if isinstance(data, dict) else {}
    return {"project": project or str(data.get("project") or ""), "run_id": str(data.get("run_id") or ""),
            "status": str(data.get("status") or ""), "task": data.get("task"), "title": data.get("title") or "",
            "cause_code": str(data.get("cause_code") or ""), "cause": str(data.get("cause") or ""),
            "tried": [str(t) for t in data.get("tried", [])],
            "options": [_option_button(o) for o in data.get("options", [])]}


def repair_card(project: str, data: Any, values: dict) -> dict:
    """Card data for a repair result: what was asked, the reason given, and the outcome as Phoenix said it."""
    data = data if isinstance(data, dict) else {}
    keep = {k: values[k] for k in ("task", "tries", "preset", "step", "finish_step") if values.get(k) is not None}
    return {"project": project or str(data.get("project") or ""), "run_id": str(data.get("run_id") or values.get("run_id") or ""),
            "reason": str(values.get("why") or ""), "asked": keep, "result": data}


WHAT_HAPPENED_TOOLS = ("repair-rerun-step", "repair-rewrite-checks", "repair-skip-task", "repair-resume-from",
                       "repair-restart-preset", "repair-raise-max-tries", "build-resume")


def check_option(option: Any, models: dict) -> dict:
    """One card button checked against its tool's input model; raises ValueError saying what is wrong."""
    if not isinstance(option, dict):
        raise ValueError("Each option must have a label, a tool and inputs.")
    tool, label, inputs = option.get("tool"), str(option.get("label") or "").strip(), option.get("inputs")
    if tool not in WHAT_HAPPENED_TOOLS or tool not in models:
        raise ValueError(f"'{tool}' is not a repair control, so it cannot be an option on this card.")
    if not label:
        raise ValueError("Every option needs a label.")
    if not isinstance(inputs, dict):
        raise ValueError(f"The inputs for '{tool}' must be an object.")
    try:
        models[tool].model_validate(inputs)
    except Exception as err:
        raise ValueError(f"The inputs for '{tool}' are not valid: {err}") from None
    return {"label": label, "tool": tool, "inputs": inputs}


def what_happened_card(models: dict, values: dict) -> dict:
    """Card data for the agent's own 'what happened' answer, or {error} when an option is not a repair control."""
    try:
        options = [check_option(o, models) for o in values.get("options") or []]
    except ValueError as err:
        return {"error": str(err)}
    return {"project": str(values.get("project") or ""), "run_id": str(values.get("run_id") or ""),
            "cause": str(values.get("cause") or ""), "tried": [str(t) for t in values.get("tried") or []],
            "suggestion": str(values.get("suggestion") or ""), "options": options}


def job_card(job_id: str, data: Any) -> dict:
    """Card data for a background job: its kind, project, status, one label and status per step, and the message."""
    data = data if isinstance(data, dict) else {}
    steps = [{"label": str(s.get("label") or ""), "status": str(s.get("status") or "")}
             for s in data.get("steps") or [] if isinstance(s, dict)]
    return {"job": str(data.get("id") or job_id), "kind": str(data.get("kind") or ""),
            "project": str(data.get("project") or ""), "status": str(data.get("status") or ""),
            "steps": steps, "message": str(data.get("message") or "")}


def plan_check_card(project: str, data: Any) -> dict:
    """Card data for a plan check: the steps by group, the errors if any, and whether it is fine."""
    data = data if isinstance(data, dict) else {}
    groups = data.get("groups") if isinstance(data.get("groups"), dict) else {}
    errors = [str(e) for e in data.get("errors") or []]
    return {"project": project, "groups": {str(g): [str(s) for s in steps] for g, steps in groups.items()
                                           if isinstance(steps, list)},
            "errors": errors, "ok": not errors}


def specs_card(project: str, data: Any) -> dict:
    """Card data for a project's specs: name, title and whether each is in task format."""
    rows = data if isinstance(data, list) else []
    return {"project": project, "specs": [{"name": str(r.get("path") or ""), "title": str(r.get("title") or ""),
                                           "task_format": r.get("task_format") is True}
                                          for r in rows if isinstance(r, dict)]}


def _library_rows(data: Any) -> list:
    """The rows of a library answer, whether it is a list or an object holding one list."""
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), [])
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def options_list(what: str, data: Any) -> dict:
    """A plain options list for a library read (name and one-line description only), wrapped as quoted data."""
    from agentkit.quote import wrap
    rows = [{"name": str(r.get("name") or ""), "description": " ".join(str(r.get("title") or "").split())[:120]}
            for r in _library_rows(data)]
    return {"quoted": wrap(f"phoenix library {what}", rows)}
