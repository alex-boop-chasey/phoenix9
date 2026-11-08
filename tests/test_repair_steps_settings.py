"""Tests for the settings, spec and question repair steps, with the forbidden keys and the snapshot of frozen.json."""
import json

import pytest
from helpers.repair_runs import make_run

from phoenix9 import atomic, gates, paths, resolve, settings, state
from phoenix9.library import load_library
from phoenix9.repair import apply, snapshot, steps


def make(tmp_path, status="failed"):
    """A run whose settings.json and plan.json are the real library defaults."""
    r = make_run(tmp_path, status=status)
    lib = load_library(paths.library())
    values = settings.effective(paths.projects() / r["project"], lib).values
    atomic.write_json(r["run_dir"] / "settings.json", values)
    atomic.write_json(r["run_dir"] / "plan.json", resolve.resolve(lib, settings.enabled_map(settings.effective(
        paths.projects() / r["project"], lib))).to_json())
    r["lib"] = lib
    return r


def ctx_of(r):
    return steps.Context(r["run_dir"], who="tester")


def snap(r):
    """The bytes of settings.json and plan.json."""
    return ((r["run_dir"] / "settings.json").read_bytes(), (r["run_dir"] / "plan.json").read_bytes())


def plan_steps(r):
    """The step names that run according to plan.json."""
    return [n for names in atomic.read_json(r["run_dir"] / "plan.json")["groups"].values() for n in names]


def note(tmp_path, r, *lines, force=False):
    path = tmp_path / "note.md"
    body = "\n".join(f"- {s}" for s in lines) + ("\n- force" if force else "")
    path.write_text(f"# Repair {r['run']}\n\nWhy: test\n\n## Steps\n\n{body}\n")
    return path


def test_set_setting_writes_settings_and_freezes(tmp_path):
    r = make(tmp_path)
    out = steps.set_setting(ctx_of(r), "max_tries", "4")
    assert "max_tries" in out
    assert atomic.read_json(r["run_dir"] / "settings.json")["max_tries"] == 4
    assert "max_tries" in atomic.read_json(r["run_dir"] / "repairs" / "frozen.json")["settings"]


def test_set_setting_can_turn_a_step_on_and_replans(tmp_path):
    r = make(tmp_path)
    off = [row["name"] for row in atomic.read_json(r["run_dir"] / "plan.json")["steps"]
           if not row["on"] and r["lib"].step(row["name"]).default == "off"]
    if not off:
        pytest.skip("no step is off by default")
    steps.set_setting(ctx_of(r), f"steps.{off[0]}.on", "true")
    assert off[0] in plan_steps(r)


def test_set_setting_diff_deny_extra_can_grow(tmp_path):
    r = make(tmp_path)
    steps.set_setting(ctx_of(r), "diff.deny_extra", '["a/*"]')
    steps.set_setting(ctx_of(r), "diff.deny_extra", '["a/*", "b/*"]')
    assert atomic.read_json(r["run_dir"] / "settings.json")["diff"]["deny_extra"] == ["a/*", "b/*"]


FORBIDDEN = ["domains", "domains.allow", "diff.allow_extra", "services", "safety_files", "keys", "keys.x",
             "secrets", "secrets.x", "images", "images.x", "docker", "docker.x",
             "steps.diff-rules.on", "steps.secret-scan.on", "steps.diff-rules.anything"]


@pytest.mark.parametrize("key", FORBIDDEN)
def test_forbidden_keys_refused(tmp_path, key):
    r = make(tmp_path)
    before = snap(r)
    with pytest.raises(steps.StepRefused):
        steps.set_setting(ctx_of(r), key, '["x"]')
    with pytest.raises(steps.StepRefused):
        steps.set_setting(ctx_of(r), key, "false")
    assert snap(r) == before
    assert not (r["run_dir"] / "repairs" / "frozen.json").exists()


@pytest.mark.parametrize("key,value", [
    ("diff", '{allow_extra = ["*"]}'),
    ("diff", "{deny_extra = []}"),
    ("steps.builder", '{tools = ["Bash"]}'),
    ("steps.diff-rules", "{on = false}"),
    ("steps", "{diff-rules = {on = false}}"),
    ("steps", "{secret-scan = {on = false}}"),
    ("domains", '{allow = ["evil.example"]}'),
])
def test_table_values_reaching_forbidden_keys_refused(tmp_path, key, value):
    r = make(tmp_path)
    steps.set_setting(ctx_of(r), "diff.deny_extra", '["a/*"]')
    before = snap(r)
    with pytest.raises(steps.StepRefused):
        steps.set_setting(ctx_of(r), key, value)
    assert snap(r) == before


def test_deny_extra_cannot_lose_entries(tmp_path):
    r = make(tmp_path)
    steps.set_setting(ctx_of(r), "diff.deny_extra", '["a/*", "b/*"]')
    before = snap(r)
    for value in ("[]", '["a/*"]', '["c/*"]'):
        with pytest.raises(steps.StepRefused):
            steps.set_setting(ctx_of(r), "diff.deny_extra", value)
    assert snap(r) == before


def test_bad_values_and_keys_refused(tmp_path):
    r = make(tmp_path)
    before = snap(r)
    for key, value in [("max_tries", '"many"'), ("nonsense", "1"), ("max_tries", "not toml ["), ("merge", '"never"')]:
        with pytest.raises(steps.StepRefused):
            steps.set_setting(ctx_of(r), key, value)
    assert snap(r) == before


def test_turn_off_step(tmp_path):
    r = make(tmp_path)
    plan = atomic.read_json(r["run_dir"] / "plan.json")
    candidates = [row["name"] for row in plan["steps"]
                  if row["on"] and not row["safety"] and r["lib"].step(row["name"]).default == "on"]
    for name in candidates:
        try:
            steps.turn_off_step(ctx_of(r), name)
        except steps.StepRefused:
            continue
        assert name not in plan_steps(r)
        assert atomic.read_json(r["run_dir"] / "repairs" / "frozen.json")["plan"] is True
        return
    pytest.skip("no step can be turned off")


def test_turn_off_refuses_guards_and_unknown(tmp_path):
    r = make(tmp_path)
    before = snap(r)
    always = [s.name for s in r["lib"].steps if s.default == "always"]
    for name in ["diff-rules", "secret-scan", "no-such-step", *always]:
        with pytest.raises(steps.StepRefused):
            steps.turn_off_step(ctx_of(r), name)
    for s in r["lib"].steps:
        if s.safety:
            with pytest.raises(steps.StepRefused):
                steps.turn_off_step(ctx_of(r), s.name)
    assert snap(r) == before


def test_set_step_off_cannot_bypass_the_guard(tmp_path):
    r = make(tmp_path)
    before = snap(r)
    for s in r["lib"].steps:
        if s.safety or s.default == "always":
            with pytest.raises(steps.StepRefused):
                steps.set_setting(ctx_of(r), f"steps.{s.name}.on", "false")
    assert snap(r) == before


SPEC = """# Demo

Project: demo

## About
A test project.

## Task 1: One
Do one.

Done when:
- page one shows its heading

## Task 2: Brand new
Do two.

Done when:
- page two shows its heading
"""


def put_notes(r, name="new-spec.md", text=SPEC):
    notes = paths.projects() / r["project"] / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    (notes / name).write_text(text)
    return f"notes/{name}"


def set_tasks(r, **tasks):
    def change(s):
        s["tasks"] = tasks
    state.update(r["run_dir"], change)


def test_replace_spec_keeps_matching_and_adds_new(tmp_path):
    r = make(tmp_path)
    set_tasks(r, **{"1": dict(state.new_task("One"), status="passed", tries=1),
                    "3": state.new_task("Old pending")})
    steps.replace_spec(ctx_of(r), put_notes(r))
    tasks = state.load(r["run_dir"])["tasks"]
    assert tasks["1"]["status"] == "passed" and tasks["1"]["tries"] == 1
    assert tasks["2"]["status"] == "pending" and tasks["2"]["title"] == "Brand new"
    assert "3" not in tasks
    assert (r["run_dir"] / "spec.md").read_text() == SPEC
    assert [t["number"] for t in atomic.read_json(r["run_dir"] / "spec.json")["tasks"]] == [1, 2]


def test_replace_spec_refuses_bad_places_and_specs(tmp_path):
    r = make(tmp_path)
    set_tasks(r, **{"1": dict(state.new_task("One"), status="passed")})
    outside = tmp_path / "outside.md"
    outside.write_text(SPEC)
    for bad in (str(outside), "../outside.md", "notes/missing.md", "notes/../../x.md"):
        with pytest.raises(steps.StepRefused):
            steps.replace_spec(ctx_of(r), bad)
    with pytest.raises(steps.StepRefused):
        steps.replace_spec(ctx_of(r), put_notes(r, "broken.md", "not a spec at all\n"))
    assert (r["run_dir"] / "spec.md").read_text() == "# Demo\n"


def test_replace_spec_refuses_to_lose_worked_tasks(tmp_path):
    r = make(tmp_path)
    set_tasks(r, **{"1": dict(state.new_task("Renamed"), status="passed"), "5": dict(state.new_task("Gone"), status="failed")})
    with pytest.raises(steps.StepRefused):
        steps.replace_spec(ctx_of(r), put_notes(r))
    set_tasks(r, **{"1": dict(state.new_task("One"), status="passed"), "5": dict(state.new_task("Gone"), status="failed")})
    with pytest.raises(steps.StepRefused):
        steps.replace_spec(ctx_of(r), put_notes(r))
    assert "5" in state.load(r["run_dir"])["tasks"]


def open_question(r):
    return gates.open_gate(r["run_dir"], kind="human-task", title="Do it", why="needed")


def test_close_question_answers_it(tmp_path):
    r = make(tmp_path, status="paused")
    gate = open_question(r)
    out = steps.close_question(ctx_of(r), gate["id"], "approve")
    assert "approve" in out
    ans = gates.poll(r["run_dir"], gate["id"])
    assert ans["action"] == "approve" and ans["who"] == "tester"


def test_close_question_closed_and_refusals(tmp_path):
    r = make(tmp_path, status="paused")
    gate = open_question(r)
    with pytest.raises(steps.StepRefused):
        steps.close_question(ctx_of(r), gate["id"], "nonsense")
    with pytest.raises(steps.StepRefused):
        steps.close_question(ctx_of(r), f"{r['run']}.99", "approve")
    with pytest.raises(steps.StepRefused):
        steps.close_question(ctx_of(r), "other-run.1", "approve")
    with pytest.raises(steps.StepRefused):
        steps.close_question(steps.Context(r["run_dir"], who="chat:home"), gate["id"], "approve")
    steps.close_question(ctx_of(r), gate["id"], "closed")
    assert gates.poll(r["run_dir"], gate["id"])["action"] == "closed"
    with pytest.raises(steps.StepRefused):
        steps.close_question(ctx_of(r), gate["id"], "closed")


def test_close_question_only_closes_that_one(tmp_path):
    r = make(tmp_path, status="paused")
    a, b = open_question(r), open_question(r)
    steps.close_question(ctx_of(r), a["id"], "closed")
    assert gates.poll(r["run_dir"], a["id"]) is not None
    assert gates.poll(r["run_dir"], b["id"]) is None


def test_rolled_back_note_removes_frozen_json(tmp_path):
    r = make(tmp_path)
    before = snap(r)
    info = apply.apply(note(tmp_path, r, "set max_tries=4 for this run", "set services=[\"x\"] for this run"), "tester")
    assert info["rolled_back"] and "services" in info["refused"]
    assert not (r["run_dir"] / "repairs" / "frozen.json").exists()
    assert snap(r) == before


def test_frozen_json_restored_to_old_content(tmp_path):
    r = make(tmp_path)
    first = apply.apply(note(tmp_path, r, "set max_tries=4 for this run"), "tester")
    assert not first["rolled_back"], first
    old = (r["run_dir"] / "repairs" / "frozen.json").read_bytes()
    bad = apply.apply(note(tmp_path, r, "set merge=\"ask\" for this run", "set docker=1 for this run"), "tester")
    assert bad["rolled_back"]
    assert (r["run_dir"] / "repairs" / "frozen.json").read_bytes() == old


def test_undo_removes_frozen_json(tmp_path):
    r = make(tmp_path)
    info = apply.apply(note(tmp_path, r, "set max_tries=4 for this run"), "tester")
    assert not info["rolled_back"], info
    assert (r["run_dir"] / "repairs" / "frozen.json").exists()
    snapshot.undo(r["run_dir"], who="tester")
    assert not (r["run_dir"] / "repairs" / "frozen.json").exists()
    assert atomic.read_json(r["run_dir"] / "settings.json")["max_tries"] == 3


def test_dry_run_changes_nothing_for_these_steps(tmp_path):
    r = make(tmp_path, status="paused")
    gate = open_question(r)
    before = snap(r)
    spec_before = (r["run_dir"] / "spec.md").read_text()
    info = apply.apply(note(tmp_path, r, "set max_tries=5 for this run", f"close question {gate['id']} as approve",
                            f"replace the spec with {put_notes(r)}"), "tester", dry_run=True)
    assert not info["refused"], info
    assert snap(r) == before and (r["run_dir"] / "spec.md").read_text() == spec_before
    assert gates.poll(r["run_dir"], gate["id"]) is None
    assert not (r["run_dir"] / "repairs" / "frozen.json").exists()
