"""Tests for the read-only logs ops: listing, readable rendering, path safety, scrubbing and truncation."""
import json

import pytest

from phoenix9 import keys, paths, routes
from phoenix9.ops import common, logs
from phoenix9.ops.common import OpsError

RUN = "20260101-000000-demo"


@pytest.fixture
def proj(phoenix_env):
    """A project folder with one run holding a session, step log, checks, diff and gates."""
    folder = phoenix_env["projects"] / "demo"
    folder.mkdir()
    (folder / "CLAUDE.md").write_text("# demo\n")
    run = paths.runs("demo") / RUN
    for sub in ("logs", "tasks/1/attempt-1", "gates"):
        (run / sub).mkdir(parents=True)
    session = [
        {"type": "system", "subtype": "init"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "hello there"},
                                                      {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "\n".join(f"l{i}" for i in range(30))}]}},
        {"type": "result", "result": "all done"},
    ]
    (run / "logs/1-1-builder.jsonl").write_text("\n".join(json.dumps(x) for x in session) + "\n")
    (run / "logs/1-1-builder.jsonl.stderr").write_text("")
    (run / "logs/builder.log").write_text("step output\n")
    (run / "logs/delegate-g1.log").write_text("delegated\n")
    (run / "tasks/1/attempt-1/checks.txt").write_text("PASS\n")
    (run / "tasks/1/attempt-1/diff.patch").write_text("diff --git a/x b/x\n")
    (run / "tasks/1/task.md").write_text("# Task 1\n")
    (run / "gates/g1.json").write_text(json.dumps({"id": "g1", "title": "Stuck", "why": "Because", "task": 1,
                                                    "step": "builder", "created": "T0"}))
    (run / "gates/g1.answer.json").write_text(json.dumps({"action": "skip", "who": "alex", "at": "T1", "note": "ok"}))
    paths.logs().mkdir(parents=True, exist_ok=True)
    (paths.logs() / "api.log").write_text("api line\n")
    return folder


def ids(entries):
    return {e["id"] for e in entries}


def test_list_kinds_and_filters(proj):
    entries = logs.list_("demo")
    # Phoenix's own logs (api.log, updater.log) are not a project's logs: they live in Global settings.
    assert {e["kind"] for e in entries} == {"session", "check", "diff", "step", "gate", "task-file"}
    task_file = next(e for e in entries if e["id"] == f"{RUN}/tasks/1/task.md")
    assert task_file["kind"] == "task-file" and task_file["task"] == 1
    assert f"{RUN}/logs/1-1-builder.jsonl" in ids(entries)
    assert f"{RUN}/logs/1-1-builder.jsonl.stderr" not in ids(entries)  # empty
    assert ids(logs.list_("demo", kind="diff")) == {f"{RUN}/tasks/1/attempt-1/diff.patch"}
    assert all(e["task"] == 1 for e in logs.list_("demo", task=1))
    assert ids(logs.list_("demo", step="delegate")) == {f"{RUN}/logs/delegate-g1.log"}
    assert logs.list_("demo", run="nope") == []


def test_read_session_stream_as_plain_text(proj):
    out = logs.read("demo", f"{RUN}/logs/1-1-builder.jsonl")
    lines = out["text"].splitlines()
    assert "assistant: hello there" in lines
    assert any(x.startswith("tool Bash:") for x in lines)
    assert any(x.startswith("tool result:") for x in lines)
    assert "result: all done" in lines
    assert "l25" not in out["text"] and "l5" in out["text"]
    assert out["truncated"] is False and out["is_diff"] is False
    assert logs.read("demo", f"{RUN}/tasks/1/attempt-1/diff.patch")["is_diff"] is True


@pytest.mark.parametrize("bad", ["../../etc/passwd", f"{RUN}/../../../x", "logs/../runs/../../x", "", "/etc/passwd",
                                 "logs/../../x", RUN])
def test_read_refuses_outside_paths(proj, bad):
    with pytest.raises(OpsError):
        logs.read("demo", bad)


def test_read_scrubs_secret_values(proj):
    keys.set_key("demo", "TOKEN", "sekrit-value-12345", secret=True)
    (paths.runs("demo") / RUN / "logs/builder.log").write_text("the key is sekrit-value-12345 ok\n")
    text = logs.read("demo", f"{RUN}/logs/builder.log")["text"]
    assert "sekrit-value-12345" not in text and "the key is" in text


def test_read_truncates_large_files(proj):
    big = paths.runs("demo") / RUN / "logs/builder.log"
    big.write_text(("a" * 99 + "\n") * (logs.MAX_BYTES // 100 + 5) + "END\n")
    out = logs.read("demo", f"{RUN}/logs/builder.log")
    assert out["truncated"] is True and out["text"].endswith("END\n") and len(out["text"]) <= logs.MAX_BYTES


def test_gate_rendered_readable(proj):
    text = logs.read("demo", f"{RUN}/gates/g1.json")["text"]
    assert text == "Opened T0: Stuck\nWhy: Because\nAnswer: skip by alex at T1: ok\n"


def test_command_log_only_this_project(proj):
    lines = [{"ts": "T", "who": "alex", "command": "phoenix a", "project": "demo"},
             {"ts": "T", "who": "alex", "command": "phoenix b", "project": "other"}]
    (paths.logs() / "commands.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    out = logs.read("demo", "logs/commands.jsonl")
    assert "phoenix a" in out["text"] and "phoenix b" not in out["text"]
    assert "logs/commands.jsonl" in ids(logs.list_("demo", kind="command"))


def test_project_list_never_holds_service_logs(proj):
    (paths.logs() / "updater.log").write_text("updated\n")
    assert not [e for e in logs.list_("demo") if e["id"].startswith("logs/api") or e["kind"] == "service"]
    for bad in ("logs/api.log", "logs/updater.log"):
        with pytest.raises(OpsError):
            logs.read("demo", bad)


def test_reports_listed_only_for_home(proj, phoenix_env):
    (phoenix_env["projects"] / "home").mkdir()
    (paths.home() / "reports").mkdir(parents=True, exist_ok=True)
    (paths.home() / "reports/status.md").write_text("# Status\nAll fine\n")
    assert "reports/status.md" in ids(logs.list_("home"))
    assert logs.read("home", "reports/status.md")["kind"] == "report"
    routes._check_log("home", "reports/status.md")    # the bell's "Full report" link is accepted
    assert "reports/status.md" not in ids(logs.list_("demo"))
    with pytest.raises(OpsError):
        logs.read("demo", "reports/status.md")


def test_service_list_and_read(proj):
    (paths.logs() / "updater.log").write_text("updated to v2\n")
    (paths.logs() / "commands.jsonl").write_text("")
    entries = logs.service_list()
    assert ids(entries) == {"api.log", "updater.log"}
    assert all(e["kind"] == "service" and e["size"] > 0 and e["modified"] for e in entries)
    out = logs.service_read("updater.log")
    assert out["text"] == "updated to v2\n" and out["kind"] == "service" and out["truncated"] is False


def test_service_read_truncates_and_scrubs(proj, monkeypatch):
    monkeypatch.setattr(logs.scrub, "known_secrets", lambda: ["sekrit-value-12345"])
    (paths.logs() / "api.log").write_text(("a" * 99 + "\n") * (logs.MAX_BYTES // 100 + 5) + "key sekrit-value-12345\n")
    out = logs.service_read("api.log")
    assert out["truncated"] is True and len(out["text"]) <= logs.MAX_BYTES and "sekrit-value-12345" not in out["text"]


@pytest.mark.parametrize("bad", ["commands.jsonl", "logs/api.log", "../logs/api.log", "", "/etc/passwd", "events.jsonl",
                                 "api", "runner.log"])
def test_service_read_refuses_other_ids(proj, bad):
    with pytest.raises(OpsError):
        logs.service_read(bad)


def test_service_read_missing_is_not_found(proj):
    with pytest.raises(common.NotFound):
        logs.service_read("updater.log")
