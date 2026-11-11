"""Builds the Phoenix pack's server tools from controls.json (one tool per entry whose agent is `tool`)."""
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from agentkit.pack import ServerTool
from agentkit.packs.phoenix.client import PhoenixClient, PhoenixError
from agentkit.packs.phoenix.tools import (build_card, diagnose_card, events_card, job_card, keys_card, options_list,
                                        plan_check_card, project_card, repair_card, run_card, search_card, session_card,
                                        settings_card, specs_card, task_list, tries_card, update_card)

CONTROLS_FILE = Path(__file__).with_name("controls.json")
PLAIN_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
PLACEHOLDER = re.compile(r"\(\?P<(\w+)>[^)]*\)")
SIMPLE_TYPES: dict[str, Any] = {"string": str, "integer": int, "boolean": bool, "list": list[str],
                                "object": dict[str, Any]}


def load_controls(path: Path = CONTROLS_FILE) -> list[dict]:
    """Read the description file: a list of control entries."""
    return json.loads(path.read_text())


def input_model(entry: dict) -> type[BaseModel]:
    """A Pydantic input model for one entry, from its typed inputs (descriptions and choices kept)."""
    fields: dict[str, Any] = {}
    for item in entry["inputs"]:
        kind = Literal[tuple(item["choices"])] if item["type"] == "choice" else SIMPLE_TYPES[item["type"]]
        if item["required"]:
            fields[item["name"]] = (kind, Field(description=item["description"]))
        else:
            fields[item["name"]] = (kind | None, Field(None, description=item["description"]))
    return create_model(entry["name"].replace("-", "_") + "_inputs", __doc__=entry["description"],
                        __config__=ConfigDict(extra="forbid"), **fields)


def fill_path(route: str, values: dict) -> str:
    """The route with each named part replaced by its value; refuses anything that is not a plain name or run id."""
    def one(found: re.Match) -> str:
        value = str(values.get(found.group(1), ""))
        if not PLAIN_NAME.match(value) or ".." in value:
            raise PhoenixError(f"'{value}' is not a plain name, so I did not use it.")
        return value
    return PLACEHOLDER.sub(one, route)


def _query_value(value: Any) -> Any:
    """A query value as text; false is left out."""
    return "1" if value is True else None if value is False else value


def _body(entry: dict, values: dict) -> dict:
    """The body: the entry's fixed values plus each body input (nested where it says `into`)."""
    body = dict(entry["fixed"])
    for item in entry["inputs"]:
        value = values.get(item["name"])
        if item["where"] != "body" or value is None:
            continue
        target = body
        for key in item["into"][:-1]:
            target = target.setdefault(key, {})
        target[item["into"][-1] if item["into"] else item["name"]] = value
    return body


def _card_data(entry: dict, data: Any, values: dict) -> dict:
    """What the tool returns: card data for the project and run cards, else the answer as it came."""
    if isinstance(data, dict) and data.get("ok") is True and "data" in data:
        data = data["data"]
    card, project = entry["card"], str(values.get("name") or values.get("project") or "")
    if entry["name"] == "projects-list":
        rows = data if isinstance(data, list) else data.get("top", []) + data.get("rest", [])
        return {"projects": [project_card(r) for r in rows]}
    if entry["name"] == "project-show":
        return {"project": project_card(data)}
    if entry["name"] == "builds-list":
        return {"project": project, "runs": [run_card(project, r) for r in data]}
    if not project and isinstance(data, dict):
        project = str(data.get("project") or "")
    if entry["name"] == "run-show" and isinstance(data, dict):
        return {"run": run_card(project, data), "tasks": task_list(data), "result": data}
    if entry["name"] == "job-status":
        return job_card(str(values.get("job_id") or ""), data)
    if entry["name"] == "build-plan":
        return plan_check_card(project, data)
    if entry["name"] == "project-specs":
        return specs_card(project, data)
    if entry["name"].startswith("library-"):
        return options_list(entry["name"].split("-", 1)[1], data)
    if card == "settings_card":
        return settings_card(project, data, entry["name"] == "settings-check")
    if card == "keys_card":
        return keys_card(project, data)
    if card == "events_card" and entry["name"] == "run-events":
        return events_card(project, data)
    if card == "tries_card":
        return tries_card(project, data)
    if card == "session_card":
        return session_card(project, data)
    if card == "search_card":
        return search_card(data)
    if card == "diagnose_card":
        return diagnose_card(project, data)
    if card == "repair_card":
        return repair_card(project, data, values)
    if card == "update_card":
        return update_card(data)
    if card == "run_card" and isinstance(data, dict):
        return {"build": build_card(project, data), "result": data}
    return {"result": data}


def make_function(entry: dict, client: PhoenixClient) -> Callable[..., dict]:
    """The tool body: fill the path, send query/body inputs and fixed values, return card data or {error}."""
    def run(**values) -> dict:
        try:
            path = fill_path(entry["route"], values)
            query = dict(entry["fixed_query"])
            query.update({i["name"]: _query_value(values.get(i["name"])) for i in entry["inputs"]
                          if i["where"] == "query"})
            if entry["method"] == "GET":
                data = client.get(path, query)
            else:
                data = client.post(path, _body(entry, values), query)
        except PhoenixError as err:
            return {"error": str(err)}
        return _card_data(entry, data, values)
    run.__doc__ = entry["description"]
    return run


def make_server_tools(client: PhoenixClient, controls: list[dict] | None = None) -> tuple[list[ServerTool], dict]:
    """The server tools for every `tool` entry, and the map of tool name to its card component."""
    tools, components = [], {}
    for entry in controls if controls is not None else load_controls():
        if entry["agent"] != "tool":
            continue
        tools.append(ServerTool(entry["name"], entry["description"], input_model(entry), entry["risk"],
                                make_function(entry, client), entry["confirm_with"] or None,
                                "run_id" if entry["name"].startswith("repair-") else None))
        if entry["card"]:
            components[entry["name"]] = entry["card"]
    return tools, components
