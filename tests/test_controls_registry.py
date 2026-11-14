"""The controls registry covers every API route and every public ops function, with valid risk and agent values."""
import ast
import importlib
import inspect
from pathlib import Path

from phoenix9.api import server
from phoenix9.ops import controls

OPS_DIR = Path(controls.__file__).parent
ROUTE_SET = {(m, p) for m, p, _ in server.ROUTES}
NOT_CONTROLS = {("GET", r"/api/agent-next")}


def public_functions() -> set:
    """Every `module.function` that is public in phoenix9/ops/*.py (except this registry)."""
    found = set()
    for path in OPS_DIR.glob("*.py"):
        if path.stem in ("__init__", "controls"):
            continue
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
                found.add(f"{path.stem}.{node.name}")
    return found


def test_every_route_has_an_entry():
    covered = {(c.method, c.route) for c in controls.CONTROLS}
    assert sorted(ROUTE_SET - covered) == []


def test_every_entry_route_is_a_real_route():
    for c in controls.CONTROLS:
        assert (c.method, c.route) in ROUTE_SET, c.name


def test_ops_names_real_public_functions():
    for c in controls.CONTROLS:
        if not c.ops:
            continue
        module, _, function = c.ops.partition(".")
        assert f"{module}.{function}" in public_functions(), f"{c.name}: {c.ops}"
        assert callable(getattr(importlib.import_module(f"phoenix9.ops.{module}"), function)), c.name


def test_every_public_ops_function_is_a_control_or_a_helper():
    named = {c.ops for c in controls.CONTROLS} | set(controls.HELPERS)
    assert sorted(public_functions() - named) == [], "add a registry entry or a HELPERS line"


def test_helpers_are_real_and_explained():
    assert sorted(set(controls.HELPERS) - public_functions()) == []
    assert all(reason.strip() for reason in controls.HELPERS.values())


def test_names_are_unique():
    names = [c.name for c in controls.CONTROLS]
    assert len(names) == len(set(names))


def test_risk_and_agent_values_are_valid():
    for c in controls.CONTROLS:
        assert c.risk in controls.RISKS, c.name
        assert c.agent in controls.AGENTS, c.name
        assert c.method in ("GET", "POST", "PUT", "DELETE"), c.name
        if c.agent != "tool":
            assert c.why.strip(), f"{c.name} needs a why"


def test_inputs_are_well_formed():
    for c in controls.CONTROLS:
        names = [i.name for i in c.inputs]
        assert len(names) == len(set(names)), c.name
        for i in c.inputs:
            assert i.type in controls.TYPES and i.where in controls.WHERES, f"{c.name}.{i.name}"
            assert (i.type == "choice") == bool(i.choices), f"{c.name}.{i.name}"
            assert i.description.strip(), f"{c.name}.{i.name}"


def test_destructive_entries_name_an_input_to_type():
    for c in controls.CONTROLS:
        if c.risk == "destructive" and c.agent == "tool":
            assert c.confirm_with in [i.name for i in c.inputs], c.name
        elif c.confirm_with:
            assert c.confirm_with in [i.name for i in c.inputs], c.name


def test_tool_risks_follow_the_decision():
    by_name = {c.name: c for c in controls.CONTROLS}
    assert by_name["build-stop"].risk == "destructive"
    assert by_name["global-addresses"].risk == "destructive"
    for c in controls.CONTROLS:
        if c.agent == "tool" and c.method == "GET":
            assert c.risk == "read", c.name
        if c.agent == "tool" and c.method == "POST":
            assert c.risk in ("change", "destructive") or c.name == "build-plan", c.name  # the plan check only reads


def test_deleting_is_alex_only():
    by_route = {c.route: c for c in controls.CONTROLS if c.method == "POST"}
    for suffix in ("delete", "delete-repo"):
        entry = by_route[rf"/api/projects/{controls.NAME}/{suffix}"]
        assert entry.risk == "alex-only" and entry.agent == "alex-only"
    assert [c.name for c in controls.CONTROLS if c.agent == "alex-only" and c.risk != "alex-only"] == []


def test_no_tool_takes_a_key_value():
    for c in controls.CONTROLS:
        if c.agent != "tool":
            continue
        assert not c.route.endswith(("/keys/save", "/keys/reveal", "/connect", "/test")), c.name
        for i in c.inputs:
            assert i.name not in ("value", "values", "rows", "secret", "token", "key_value"), f"{c.name}.{i.name}"


def test_key_controls_are_never_tools():
    by_name = {c.name: c for c in controls.CONTROLS}
    assert by_name["keys-save"].agent == "key-card"
    assert by_name["keys-reveal"].agent == "secret"
    assert by_name["service-connect"].agent == "secret" and by_name["service-test"].agent == "secret"


# Agent tools whose route starts slow work in the background and answers at once with a job or run id, so the agent
# never waits on it. update-install (queued to the updater, answers {"queued"} with no id) is left out on purpose.
BACKGROUND = {"edit-finish": "job_id", "project-create": "job", "build-start": "run_id", "hotfix-start": "run_id",
              "service-restart": "job"}   # (the runner; the api and agent restarts answer at once)


def returned_keys(handler) -> set:
    """Every string constant inside the handler's return statements (the keys of the reply it builds)."""
    tree = ast.parse(inspect.getsource(handler))
    return {node.value for ret in ast.walk(tree) if isinstance(ret, ast.Return) and ret.value is not None
            for node in ast.walk(ret.value) if isinstance(node, ast.Constant) and isinstance(node.value, str)}


def test_background_tools_answer_with_a_job_or_run_id():
    by_name = {c.name: c for c in controls.CONTROLS}
    handlers = {(m, p): h for m, p, h in server.ROUTES}
    for name, key in BACKGROUND.items():
        c = by_name[name]
        assert c.agent == "tool", name
        assert key in returned_keys(handlers[(c.method, c.route)]), name


def test_only_known_slow_controls_wait_longer():
    slow = {c.name: c.timeout_s for c in controls.CONTROLS if c.timeout_s}
    assert slow == {"chat-open": 90}
    assert all(c.timeout_s >= 0 for c in controls.CONTROLS)
