"""Planning sessions: queued by the CLI, run by the runner service in a sealed step container (fake docker).

No real Claude and no real docker: a fake docker runner records the `docker run` argv, writes the scripted
stream-json log and the session's /out/spec.md into the mounted /out folder.
"""
import json
import subprocess
from pathlib import Path

import pytest

from phoenix9 import adapters as adapters_mod, events, paths, plans, plansession, watch
from phoenix9.__main__ import main
from tests.fakes import FakeDocker, FakeHost

SID = "0b6c5d4e-1111-4222-8333-944455556666"
GOOD = """# Plan a thing
Project: demo

## About
What it is.

## Task 1: Make it
Do it.
Depends on: none
For you: no
Done when:
- `true`

## Open questions
1. Which db? Recommended: sqlite
Answer:
2. Name? Recommended: x
Answer: yes
"""
DONE = GOOD.replace("## Open questions\n1. Which db? Recommended: sqlite\nAnswer:\n2. Name? Recommended: x\nAnswer: yes\n",
                    "## Decisions\n1. sqlite\n")
IMAGE = "phoenix9-step-python:1"


class PlanDocker(FakeDocker):
    """Fake docker: each run takes the next scripted (spec text or None, result) and writes it."""

    def __init__(self):
        super().__init__()
        self.images[IMAGE] = {}
        self.sessions = []

    def script(self, spec_text, kind="ok", cost=0.5, sid=SID):
        self.sessions.append((spec_text, kind, cost, sid))

    @staticmethod
    def mounts(argv):
        return [argv[i + 1] for i, a in enumerate(argv) if a == "--mount"]

    def mount_src(self, argv, dst):
        for m in self.mounts(argv):
            if f"dst={dst}," in m + ",":
                return m.split("src=")[1].split(",")[0]
        return None

    def run(self, argv, stdout_path, stderr_path, timeout_s, name, append_stdout=False):
        self.calls.append(("run", (list(argv), stdout_path, stderr_path, timeout_s, name), {}))
        self.argvs.append(list(argv))
        spec_text, kind, cost, sid = self.sessions.pop(0) if self.sessions else (None, "ok", 0.1, SID)
        out = self.mount_src(argv, "/out")
        if spec_text is not None and out:
            Path(out, "spec.md").write_text(spec_text)
        result = {"type": "result", "subtype": "success", "is_error": kind != "ok", "result": "PLAN DONE",
                  "session_id": sid, "total_cost_usd": cost, "num_turns": 2}
        Path(stdout_path).write_text(json.dumps({"type": "system", "subtype": "init", "session_id": sid}) + "\n"
                                     + json.dumps(result) + "\n")
        return 0 if kind == "ok" else 1


@pytest.fixture
def proj(phoenix_env):
    """A project folder with CLAUDE.md, notes/specs/ and a code/ repo with one commit on main."""
    folder = phoenix_env["projects"] / "demo"
    (folder / "notes" / "specs").mkdir(parents=True)
    (folder / "CLAUDE.md").write_text("# demo\n")
    code = folder / "code"
    code.mkdir()
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=code, check=True)
    (code / "app.py").write_text("print('hi')\n")
    subprocess.run(["git", "add", "-A"], cwd=code, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "first"], cwd=code, check=True)
    (code / "dirty.txt").write_text("not committed\n")
    return folder


@pytest.fixture
def ad():
    """Real Claude adapter (builds the container command) over a fake docker; fake host."""
    return adapters_mod.Adapters(docker=PlanDocker(), claude=adapters_mod.Claude(), git=adapters_mod.Git(),
                                 host=FakeHost(), http=None, clock=None, notify=None)


def _types():
    return [e["type"] for e in events.read(paths.events())]


def test_start_only_queues_and_runs_nothing(proj, ad):
    rec = plans.new_record("demo", "plan a thing", "m1", "cli")
    assert rec["status"] == "queued" and rec["job"]["kind"] == "start" and rec["job"]["resume"] is None
    assert "plan a thing" in plans.prompt_file(rec["id"]).read_text()
    assert ad.docker.argvs == [] and ad.host.calls == []
    assert "plan.queued" in _types()


def test_runner_runs_it_sealed_and_files_the_spec(proj, ad):
    rec = plans.new_record("demo", "plan a thing", "m1", "cli")
    ad.docker.script(GOOD)
    assert watch.run_plans(ad) == rec["id"]
    argv = ad.docker.argvs[0]
    mounts = PlanDocker.mounts(argv)
    # sealed like a step: firewall, no-new-privileges, non-root user, claude env file only, no socket
    assert "no-new-privileges" in argv and "HANDS_FIREWALL=1" in argv and "HOST_UID=0" not in argv
    env_files = [argv[i + 1] for i, a in enumerate(argv) if a == "--env-file"]
    assert [Path(f).name for f in env_files] == ["claude.env"]
    assert not any("PHOENIX_PROXY" in a for a in argv) and not any("docker.sock" in m for m in mounts)
    # mounts: workspace read-only copy (not code/), context read-only, /out the only writable thing but the session dir
    code = str((proj / "code").resolve())
    assert not any(f"src={code}," in m + "," or f"src={code}/" in m for m in mounts)
    ws = next(m for m in mounts if "dst=/workspace" in m)
    assert ws.endswith(",readonly") and f"work/plan-{rec['id']}/code" in ws
    assert any("dst=/project/CLAUDE.md" in m and m.endswith(",readonly") for m in mounts)
    assert any("dst=/project/notes" in m and m.endswith(",readonly") for m in mounts)
    writable = sorted(m.split("dst=")[1].split(",")[0] for m in mounts if not m.endswith(",readonly"))
    assert writable == ["/home/node/.claude/projects", "/out"]
    assert f"plans/{rec['id']}/claude" in next(m for m in mounts if "dst=/home/node/.claude/projects" in m)
    domains = Path(next(m for m in mounts if "allowed-domains" in m).split("src=")[1].split(",")[0])
    assert domains.read_text() == "api.anthropic.com\n"
    # the command: claude in the container, cwd /workspace, model from the record, never --bare
    assert "phoenix-claude" in argv and "/workspace" in argv and "--bare" not in argv
    assert argv[argv.index("--model") + 1] == "m1" and "--resume" not in argv
    # Phoenix filed the spec itself, at the path it picked
    filed = proj / "notes" / "specs" / f"plan-{rec['id']}.md"
    assert filed.read_text() == GOOD
    rec = plans.load(rec["id"])
    assert rec["status"] == "waiting" and rec["open_questions"] == 1 and rec["session_id"] == SID
    assert rec["spec"] == f"notes/specs/plan-{rec['id']}.md" and rec["usage"]["cost_usd"] == 0.5
    assert "job" not in rec
    assert not (paths.home() / "work" / f"plan-{rec['id']}").exists()      # the copy is removed
    assert not (proj / "code" / "dirty.txt").read_text() == ""             # live code/ untouched
    assert {"plan.queued", "plan.started", "plan.waiting"} <= set(_types())


def test_queued_running_waiting_then_continue_resumes_same_session(proj, ad):
    rec = plans.new_record("demo", "plan a thing", "m1", "cli")
    seen = []
    real_run = ad.docker.run

    def spy(argv, *a, **k):
        seen.append(plans.load(rec["id"])["status"])
        return real_run(argv, *a, **k)
    ad.docker.run = spy
    ad.docker.script(GOOD)
    watch.run_plans(ad)
    assert seen == ["running"] and plans.load(rec["id"])["status"] == "waiting"
    filed = proj / "notes" / "specs" / f"plan-{rec['id']}.md"
    filed.write_text(GOOD.replace("Answer:\n2.", "Answer: sqlite\n2."))
    rec = plans.queue_continue(rec["id"], answer="Use sqlite")
    assert rec["status"] == "queued" and rec["job"]["resume"] == SID
    ad.docker.script(DONE)
    watch.run_plans(ad)
    argv = ad.docker.argvs[1]
    assert argv[argv.index("--resume") + 1] == SID
    out_seed = [m for m in PlanDocker.mounts(argv) if "dst=/out" in m]
    assert out_seed
    rec = plans.load(rec["id"])
    assert rec["status"] == "done" and rec["open_questions"] == 0 and filed.read_text() == DONE
    assert rec["usage"]["sessions"] == 2


def test_continue_seeds_out_with_the_filed_spec(proj, ad):
    rec = plans.new_record("demo", "x", "m", "cli")
    ad.docker.script(GOOD)
    watch.run_plans(ad)
    filed = proj / "notes" / "specs" / f"plan-{rec['id']}.md"
    filed.write_text(GOOD.replace("Answer:\n2.", "Answer: postgres\n2."))
    plans.queue_continue(rec["id"])
    ad.docker.script(None)                         # the session changes nothing: Phoenix files the seed back
    watch.run_plans(ad)
    assert "Answer: postgres" in filed.read_text()
    assert plans.load(rec["id"])["status"] == "done"


def test_spec_problems_resume_the_same_session_then_pass(proj, ad):
    rec = plans.new_record("demo", "x", "m", "cli")
    ad.docker.script("nothing useful\n")
    ad.docker.script(GOOD)
    watch.run_plans(ad)
    first, second = ad.docker.argvs
    assert "--resume" not in first and second[second.index("--resume") + 1] == SID
    prompt = (plans.plan_folder(rec["id"]) / "session-prompt.md").read_text()
    assert "found these problems" in prompt
    assert plans.load(rec["id"])["status"] == "waiting"


def test_spec_problems_three_times_fail(proj, ad):
    rec = plans.new_record("demo", "x", "m", "cli")
    for _ in range(3):
        ad.docker.script("still bad\n")
    watch.run_plans(ad)
    rec = plans.load(rec["id"])
    assert len(ad.docker.argvs) == 3 and rec["status"] == "failed" and "after 2 rounds" in rec["report"]
    assert not list((proj / "notes" / "specs").iterdir())


def test_session_error_fails_and_records_cost(proj, ad):
    rec = plans.new_record("demo", "x", "m", "cli")
    ad.docker.script(None, kind="error", cost=0.25)
    ad.docker.script(None, kind="error", cost=0.25)
    ad.docker.script(None, kind="error", cost=0.25)
    watch.run_plans(ad)
    rec = plans.load(rec["id"])
    assert rec["status"] == "failed" and "ended before it finished" in rec["report"]
    assert rec["usage"]["cost_usd"] > 0


def test_spending_cap_stops_the_plan(proj, ad):
    paths.config().mkdir(parents=True, exist_ok=True)
    (paths.config() / "global.toml").write_text("[plan]\nbudget_usd = 1\n")
    rec = plans.new_record("demo", "x", "m", "cli")
    for _ in range(3):
        ad.docker.script("bad\n", cost=0.75)
    watch.run_plans(ad)
    rec = plans.load(rec["id"])
    assert len(ad.docker.argvs) == 2 and rec["status"] == "failed" and "spending cap" in rec["report"]


def test_spec_target_link_is_refused(proj, ad, tmp_path):
    rec = plans.new_record("demo", "x", "m", "cli")
    elsewhere = tmp_path / "elsewhere.md"
    elsewhere.write_text("keep\n")
    (proj / "notes" / "specs" / f"plan-{rec['id']}.md").symlink_to(elsewhere)
    ad.docker.script(GOOD)
    watch.run_plans(ad)
    assert plans.load(rec["id"])["status"] == "failed" and elsewhere.read_text() == "keep\n"


def test_out_spec_link_is_not_followed(proj, ad, tmp_path):
    secret = tmp_path / "outside.md"
    secret.write_text(GOOD)
    rec = plans.new_record("demo", "x", "m", "cli")

    class LinkDocker(PlanDocker):
        def run(self, argv, *a, **k):
            rc = super().run(argv, *a, **k)
            out = Path(self.mount_src(argv, "/out"))
            (out / "spec.md").unlink(missing_ok=True)
            (out / "spec.md").symlink_to(secret)
            return rc
    ad.docker = LinkDocker()
    watch.run_plans(ad)
    rec = plans.load(rec["id"])
    assert rec["status"] == "failed" and not list((proj / "notes" / "specs").iterdir())


def test_bad_session_id_is_never_resumed(proj, ad):
    rec = plans.new_record("demo", "x", "m", "cli")
    plans.update(rec["id"], lambda r: r["job"].update(resume="--dangerous"))
    watch.run_plans(ad)
    assert ad.docker.argvs == [] and plans.load(rec["id"])["status"] == "failed"


def test_one_plan_per_project_and_stale_running_is_requeued(proj, ad):
    rec = plans.new_record("demo", "x", "m", "cli")
    with pytest.raises(plans.PlanError, match="already has"):
        plans.new_record("demo", "again", "m", "cli")
    plans.update(rec["id"], lambda r: r.update(status="running"))
    assert watch.run_plans(ad) is None
    assert plansession.requeue_stale() == [rec["id"]]
    assert plans.load(rec["id"])["status"] == "queued"


def test_refusals_agent_folder_and_phoenix9_for_chats(proj, phoenix_env):
    for name in ("home", "phoenix9"):
        (phoenix_env["projects"] / name).mkdir()
    with pytest.raises(plans.PlanError, match="agent's folder"):
        plans.new_record("home", "x", "m", "cli")
    with pytest.raises(plans.PlanError, match="only Alex"):
        plans.new_record("phoenix9", "x", "m", "chat:home")
    assert plans.new_record("phoenix9", "x", "m", "cli")["status"] == "queued"


def test_chat_may_abandon_only_its_own(proj):
    rec = plans.new_record("demo", "x", "m", "cli")
    with pytest.raises(plans.PlanError, match="only Alex or that chat"):
        plans.abandon(rec["id"], "chat:home")
    assert plans.abandon(rec["id"], "cli")["status"] == "abandoned"
    mine = plans.new_record("demo", "y", "m", "chat:home")
    assert plans.abandon(mine["id"], "chat:home")["status"] == "abandoned"


def test_model_and_budget_settings(proj):
    assert plans.plan_model() == "claude-fable-5-1" and plans.plan_budget() == 5.0
    ai = plansession.step_ai("m1")
    assert ai["model"] == "m1" and "m1" not in ai["fallback_models"] and ai["timeout"] == 40


def test_count_open():
    assert plans.count_open(GOOD) == 1


def test_cli_start_queues_status_list(proj, capsys, tmp_path):
    assert main(["plan", "start", "demo", "--brief", "hello"]) == 0
    out = capsys.readouterr().out
    assert "queued" in out and "phoenix plan status" in out
    found = plans.list_plans("demo")[0]
    assert main(["plan", "status", found["id"]]) == 0
    assert "queued" in capsys.readouterr().out
    assert main(["plan", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["plans"][0]["id"] == found["id"]
    assert main(["plan", "status", "nope"]) != 0
    bad = tmp_path / "bad.md"
    bad.write_text("nothing\n")
    assert main(["spec", "check", str(bad)]) == 1
