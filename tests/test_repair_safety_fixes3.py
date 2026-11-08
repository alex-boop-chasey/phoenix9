"""Round 3: a merge question's frozen flags cannot be used after a repair changed the run (chat answer + approve)."""
import pytest
from helpers.repair_runs import make_run
from helpers.stepunit import load
from test_step_merge import git, world  # noqa: F401  (fixture)

from phoenix9 import gates, paths, state
from phoenix9.ops import common, gates as ops_gates

ALLOW = {"home_chat_may_answer": ["merge"]}


def waiting_at_clean_merge(tmp_path):
    """A run waiting at a merge question with no flags, every task passed, chats allowed to answer merges."""
    r = make_run(tmp_path, status="waiting")
    state.update(r["run_dir"], lambda s: s.update(tasks={"1": {**state.new_task("One"), "status": "passed"}},
                                                  steps=[]))
    (paths.projects() / r["project"] / "phoenix.toml").write_text('home_chat_may_answer = ["merge"]\n')
    head = git(r["code"], "rev-parse", f"phoenix/{r['run']}").strip()
    gate = gates.open_gate(r["run_dir"], kind="merge", title="Merge?", why="all fine",
                           actions=["approve", "back", "skip", "stop"], flags=[], head=head, task_statuses={"1": "passed"})
    state.update(r["run_dir"], lambda s: s.setdefault("current", {}).update(gate=gate["id"]))
    return r, gate


def test_gate_file_keeps_the_head_and_task_statuses(tmp_path):
    r, gate = waiting_at_clean_merge(tmp_path)
    saved = gates.read(r["run_dir"], gate["id"])
    assert len(saved["head"]) == 40 and saved["task_statuses"] == {"1": "passed"}


def test_chat_may_answer_a_clean_merge_question(tmp_path):
    r, gate = waiting_at_clean_merge(tmp_path)
    assert gates.may_answer(gates.read(r["run_dir"], gate["id"]), "chat:home", ALLOW)


def test_chat_refused_once_a_repair_snapshot_exists(tmp_path):
    r, gate = waiting_at_clean_merge(tmp_path)
    (r["run_dir"] / "repairs" / "1").mkdir(parents=True)        # a repair note ran (keep my hand fix ...)
    assert not gates.may_answer(gates.read(r["run_dir"], gate["id"]), "chat:home", ALLOW)
    with pytest.raises(common.OpsError, match="may not answer"):
        ops_gates.answer(gate["id"], "approve", who="chat:home")
    assert gates.poll(r["run_dir"], gate["id"]) is None
    assert ops_gates.answer(gate["id"], "approve", who="dashboard")["action"] == "approve"


@pytest.mark.parametrize("status", ["pending", "running", "failed"])
def test_chat_refused_when_a_task_is_no_longer_passed(tmp_path, status):
    r, gate = waiting_at_clean_merge(tmp_path)
    state.set_task(r["run_dir"], 1, status=status)               # e.g. retry task 1
    with pytest.raises(common.OpsError, match="may not answer"):
        ops_gates.answer(gate["id"], "approve", who="chat:home")


def test_chat_refused_for_a_merge_question_without_its_run():
    assert not gates.may_answer({"kind": "merge", "flags": []}, "chat:home", ALLOW)


# ------------------------------------------------------------------ the approved merge checks again
def local_ask(world):  # noqa: F811
    """A local-only project (no GitHub repo) in ask mode, with the merge question asked."""
    ctx, code, _ = world
    git(code, "remote", "remove", "origin")
    ctx.project.settings["merge"] = "ask"
    mod = load("merge")
    result = mod.run(ctx)
    assert result.status == "gate"
    return ctx, code, mod, result


def test_question_records_the_branch_tip(world):  # noqa: F811
    ctx, code, _mod, result = local_ask(world)
    assert result.gate["head"] == git(code, "rev-parse", "phoenix/r").strip()
    assert result.gate["task_statuses"] == {"1": "passed"}


def test_approve_refused_after_a_hand_fix(world):  # noqa: F811
    ctx, code, mod, _ = local_ask(world)
    main = git(code, "rev-parse", "main")
    (ctx.worktree / "hand.txt").write_text("hand fix\n")
    git(ctx.worktree, "add", "-A")
    git(ctx.worktree, "commit", "-q", "-m", "hand fix")
    with pytest.raises(mod.MergeError, match="branch moved"):
        mod.on_approved(ctx, {})
    assert git(code, "rev-parse", "main") == main and not (code / "hand.txt").exists()


def test_approve_refused_after_a_retry(world):  # noqa: F811
    ctx, code, mod, _ = local_ask(world)
    main = git(code, "rev-parse", "main")
    state.set_task(ctx.run.folder, 1, status="pending")
    with pytest.raises(mod.MergeError, match="task 1 changed"):
        mod.on_approved(ctx, {})
    assert git(code, "rev-parse", "main") == main


def test_approve_refused_when_nothing_was_recorded(world):  # noqa: F811
    ctx, code, mod, _ = local_ask(world)
    (ctx.run.folder / mod.ASKED_FILE).unlink()
    with pytest.raises(mod.MergeError, match="did not record"):
        mod.on_approved(ctx, {})


def test_approve_of_an_unchanged_run_merges(world):  # noqa: F811
    ctx, code, mod, _ = local_ask(world)
    mod.on_approved(ctx, {})
    assert (code / "b.txt").exists()


def test_flag_unfinished_is_gone():
    assert not hasattr(gates, "FLAG_UNFINISHED")
