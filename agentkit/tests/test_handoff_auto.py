"""Alex's hand-off rule: handoff-fix / handoff-give-up run without a card ONLY in the hand-off chat with its own ids."""
from agentkit import runs
from test_service_real import AUTH, approvals, make, posts, settle

RUN = "20261110-100000-demo"
BODY = {"run_id": RUN, "task": 3, "gate_id": f"{RUN}.2", "project": "beta"}

FIX = {"project": "beta", "run_id": RUN, "task": 3, "action": "retry", "note": "Run the migrations first."}
GIVE_UP = {"project": "beta", "run_id": RUN, "task": 3, "why": "It needs the task skipped."}


def notes(got):
    """The plain note lines in a list of events."""
    return [e["value"]["text"] for _, e in got if e["type"] == "CUSTOM" and e.get("name") == "note"]


def hand_over(client):
    """Phoenix hands task 3 over; wait until the hand-off chat's work has settled and return its events."""
    tid = client.post("/handoffs", json=BODY, headers=AUTH).json()["thread_id"]
    got = settle(client, tid)
    while got[-1][1]["type"] != "RUN_FINISHED" and not approvals(got):
        got = settle(client, tid)
    return got


def test_handoff_fix_with_matching_ids_runs_with_no_card(tmp_path):
    client, fake, store = make(tmp_path, [("handoff-fix", FIX)])
    with client:
        got = hand_over(client)
        assert approvals(got) == [] and got[-1][1]["type"] == "RUN_FINISHED"
        assert [r.url.path for r in posts(fake)] == [f"/api/runs/beta/{RUN}/handoff/fix"]
        assert notes(got) == ["Done on its own (Alex's hand-off rule): tried task 3 again with a note for the builder"]
        (pause,) = [p for p in store._read("SELECT id FROM pauses")]
        assert store.get_pause(pause["id"])["result"] == runs.HANDOFF_APPROVAL
        assert store.pending_pauses() == []


def test_handoff_give_up_with_matching_ids_runs_with_no_card(tmp_path):
    client, fake, _store = make(tmp_path, [("handoff-give-up", GIVE_UP)])
    with client:
        got = hand_over(client)
        assert approvals(got) == []
        assert [r.url.path for r in posts(fake)] == [f"/api/runs/beta/{RUN}/handoff/give-up"]
        assert notes(got) == ["Done on its own (Alex's hand-off rule): handed task 3 back to Alex"]


def test_other_task_run_or_project_shows_the_card(tmp_path):
    others = ({**FIX, "task": 4}, {**FIX, "run_id": "20261110-100000-other"}, {**FIX, "project": "alpha"},
              {**FIX, "task": True})
    for number, other in enumerate(others):
        (tmp_path / str(number)).mkdir()
        client, fake, _store = make(tmp_path / str(number), [("handoff-fix", other)])
        with client:
            got = hand_over(client)
            (card,) = approvals(got)
            assert card["toolName"] == "handoff-fix" and notes(got) == [] and posts(fake) == [], other


def test_normal_thread_shows_the_card(tmp_path):
    client, fake, _store = make(tmp_path, [("handoff-fix", FIX)])
    with client:
        tid = client.post("/threads", headers=AUTH).json()["id"]
        assert client.post(f"/threads/{tid}/runs", json={"message": "fix it"}, headers=AUTH).status_code == 202
        got = settle(client, tid)
        (card,) = approvals(got)
        assert card["toolName"] == "handoff-fix" and notes(got) == [] and posts(fake) == []


def test_other_tools_in_the_handoff_thread_still_show_the_card(tmp_path):
    for name, args in (("run-again", {"project": "beta", "run_id": RUN}),
                       ("repair-skip-task", {"project": "beta", "run_id": RUN, "task": 3, "why": "Stuck."})):
        (tmp_path / name).mkdir()
        client, fake, _store = make(tmp_path / name, [(name, args)])
        with client:
            got = hand_over(client)
            (card,) = approvals(got)
            assert card["toolName"] == name and notes(got) == [] and posts(fake) == []
