"""Tests that the Phoenix pack's tools are exactly the `tool` entries of controls.json and call what they describe."""
import json
import re

import pytest

from agentkit.pack import check_pack
from agentkit.packs.phoenix import build_pack
from agentkit.packs.phoenix.controls import fill_path, input_model, load_controls
from agentkit.packs.phoenix.client import PhoenixError
from fake_phoenix import FakePhoenix

CONTROLS = load_controls()
ENTRIES = {e["name"]: e for e in CONTROLS if e["agent"] == "tool"}
SAMPLES = {"string": "alpha", "integer": 3, "boolean": True, "list": ["github"], "object": {"a": 1}}


def tools():
    """A fake Phoenix and the pack's server tools by name."""
    fake = FakePhoenix()
    return fake, {t.name: t for t in build_pack(fake.client()).server_tools}


def sample_args(entry):
    """Valid arguments for an entry: every input filled in."""
    args = {}
    for item in entry["inputs"]:
        args[item["name"]] = item["choices"][0] if item["type"] == "choice" else SAMPLES[item["type"]]
        if item["name"] in ("run_id", "gate_id"):
            args[item["name"]] = "20261109-1"
        if item["name"] == "job_id":
            args["job_id"] = "a1b2c3d4e5f6"
    return args


def test_tool_names_and_risks_match_the_file():
    _fake, made = tools()
    made = {n: t for n, t in made.items() if n not in ("what_happened", "flow", "next_steps")}  # the agent's own card tools, not controls
    assert sorted(made) == sorted(ENTRIES)
    assert {n: t.risk for n, t in made.items()} == {n: e["risk"] for n, e in ENTRIES.items()}
    check_pack(build_pack(FakePhoenix().client()))


def test_no_alex_only_key_card_or_secret_entry_is_a_tool():
    _fake, made = tools()
    for entry in CONTROLS:
        if entry["agent"] in ("alex-only", "key-card", "secret", "later"):
            assert entry["name"] not in made
    assert not any(e["risk"] == "alex-only" for e in ENTRIES.values())


def test_confirm_field_follows_the_file():
    _fake, made = tools()
    for name, entry in ENTRIES.items():
        assert made[name].confirm_field == (entry["confirm_with"] or None)
        if entry["risk"] == "destructive":
            assert made[name].confirm_field in {i["name"] for i in entry["inputs"]}


def test_input_models_have_descriptions_choices_and_required():
    for entry in ENTRIES.values():
        schema = input_model(entry).model_json_schema()
        assert set(schema.get("required", [])) == {i["name"] for i in entry["inputs"] if i["required"]}
        for item in entry["inputs"]:
            prop = schema["properties"][item["name"]]
            assert prop["description"] == item["description"]
            if item["type"] == "choice":
                options = [prop] + prop.get("anyOf", [])
                assert item["choices"] in [o.get("enum") for o in options]


@pytest.mark.parametrize("name", sorted(ENTRIES))
def test_each_tool_calls_exactly_its_method_and_route(name):
    entry = ENTRIES[name]
    fake, made = tools()
    args = sample_args(entry)
    out = made[name].function(**input_model(entry)(**args).model_dump())
    assert "error" not in out, out
    (sent,) = fake.requests
    assert sent.method == entry["method"]
    assert re.fullmatch(entry["route"], sent.url.path)
    assert sent.url.path == fill_path(entry["route"], args)
    assert sent.headers["X-Phoenix"] == "1"
    for key, value in entry["fixed_query"].items():
        assert sent.url.params[key] == value
    if entry["method"] == "POST":
        body = json.loads(sent.content)
        for key, value in entry["fixed"].items():
            assert body[key] == value


def test_notifications_body_is_the_settings_set():
    fake, made = tools()
    made["notifications-set"].function(name="alpha", on=True)
    assert json.loads(fake.requests[0].content) == {"set": {"steps.notify.on": True}}


def test_gate_tools_send_their_fixed_action():
    fake, made = tools()
    made["plan-approve"].function(gate_id="g-1")
    made["plan-send-back"].function(gate_id="g-1", note="smaller")
    assert [json.loads(r.content) for r in fake.requests] == [
        {"action": "approve"}, {"action": "back", "note": "smaller"}]


def test_path_parts_must_be_plain():
    for bad in ("../x", "a/b", "", "a b", "..", "a?b"):
        with pytest.raises(PhoenixError):
            fill_path("/api/projects/(?P<name>[^/]+)", {"name": bad})
    fake, made = tools()
    out = made["project-show"].function(name="../secrets")
    assert "error" in out and fake.requests == []


def test_refusal_is_a_plain_error():
    made = {t.name: t for t in build_pack(FakePhoenix(refuse=True).client()).server_tools}
    assert made["global-show"].function() == {"error": "Refused: the agent isn't allowed to do that."}


def test_cards_use_the_pack_card_names():
    pack = build_pack(FakePhoenix().client())
    assert pack.components["builds-list"] == "RunCards" and pack.components["projects-list"] == "project_cards"
    assert [t.name for t in pack.browser_tools] == ["go_to", "ask_for_key", "ask_choice", "ask_env_file"]


def test_build_tools_return_build_card_data():
    fake, made = tools()
    out = made["build-start"].function(name="alpha")
    assert set(out["build"]) == {"project", "run_id", "status", "started", "link"}
    assert out["build"]["project"] == "alpha" and out["build"]["link"] == "#/p/alpha/build"
    paused = made["build-pause"].function(run_id="20261109-1")
    assert paused["build"]["run_id"] == "20261109-1"


def test_run_show_returns_run_and_task_list_card_data():
    from agentkit.packs.phoenix.tools import run_card, task_list
    state = {"run_id": "r1", "status": "running", "created": "2026-11-10 09:00", "current": {"step": "build"},
             "tasks": {"2": {"title": "Two", "status": "pending"}, "1": {"title": "One", "status": "passed"}}}
    card = run_card("alpha", {**state, "title": "T"})
    assert card["current_step"] == "build" and (card["tasks_done"], card["tasks_total"]) == (1, 2)
    assert card["started"] == "2026-11-10 09:00" and card["link"] == "#/p/alpha/build"
    assert task_list(state) == [{"number": 1, "title": "One", "status": "passed"},
                                {"number": 2, "title": "Two", "status": "pending"}]
    assert task_list({}) == []


def test_builds_list_rows_carry_progress_and_no_dollars():
    from agentkit.packs.phoenix.tools import run_card
    card = run_card("alpha", {"run_id": "r", "status": "done", "tasks_total": 4, "tasks_passed": 3, "cost": "$1.00"})
    assert (card["tasks_done"], card["tasks_total"]) == (3, 4)
    assert "$" not in json.dumps(card)


def test_settings_check_does_not_claim_fine_without_a_problems_list():
    from agentkit.packs.phoenix.tools import settings_card
    real_reply = {"project": "alpha", "values": {"steps": {"notify": {"on": True}}}, "source": {}}
    card = settings_card("alpha", real_reply, check=True)
    assert "fine" not in json.dumps(card).lower() and "not known" in card["note"]
    assert card["rows"] == [{"name": "steps.notify.on", "value": "True"}]
    _fake, made = tools()
    out = made["settings-check"].function(name="alpha")
    assert "fine" not in json.dumps(out).lower()
    assert settings_card("alpha", {"ok": True, "problems": []}, check=True)["note"] == "Check: fine."
    found = settings_card("alpha", {"ok": False, "problems": ["bad model"]}, check=True)
    assert found["problems"] == ["bad model"] and "fine" not in found["note"].lower()


def test_settings_card_has_rows_explanation_and_link():
    from agentkit.packs.phoenix.tools import settings_card
    card = settings_card("alpha", {"project": "alpha", "text": "Builds use one model."})
    assert card["explanation"] == "Builds use one model." and card["link"] == "#/p/alpha/settings"


def test_key_names_card_has_names_and_status_but_never_a_value():
    from agentkit.packs.phoenix.tools import keys_card
    rows = [{"name": "STRIPE_KEY", "secret": True, "has_value": True, "value_if_not_secret": None},
            {"name": "SITE_URL", "secret": False, "has_value": True, "value_if_not_secret": "https://x.test"},
            {"name": "EMPTY", "secret": True, "has_value": False, "value_if_not_secret": None}]
    card = keys_card("alpha", rows)
    assert card["keys"] == [{"name": "STRIPE_KEY", "status": "set"}, {"name": "SITE_URL", "status": "set"},
                            {"name": "EMPTY", "status": "missing"}]
    assert "https://x.test" not in json.dumps(card)


def test_update_card_has_versions_and_queue_state():
    from agentkit.packs.phoenix.tools import update_card
    status = {"installed": {"tag": "v1"}, "newest": "v2", "running": False, "log_tail": "secret-ish"}
    assert update_card(status) == {"installed": "v1", "newest": "v2", "queued": False, "link": "#/settings?section=updates"}
    assert update_card({"ok": True, "queued": True, "tag": "v2"})["queued"] is True
