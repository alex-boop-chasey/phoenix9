"""Tests for the demo data seed and the demo server."""
import json
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

import seed_demo
import demo_server
from phoenix9 import gates, paths, state
from phoenix9.ops import common
from phoenix9.ops import gates as ops_gates

RUNS = {
    "demo-site": ["20261020-090000-contact-form", "20261022-140000-blog-section", "20261031-100000-pricing-page"],
    "phoenix9": ["20261031-110000-api-and-dashboard"],
    "tiny-tool": ["20261101-080000-add-json-output"],
    "ember-oak": ["20261102-090000-gallery-page"],
}


def tree(root: Path) -> dict:
    """Every file under root with its text."""
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and ".git/" not in str(p)}


@pytest.fixture
def seeded(tmp_path):
    home, projects = tmp_path / "h", tmp_path / "p"
    seed_demo.seed(home, projects)
    return home, projects


def test_seed_creates_documented_projects_runs_and_gates(seeded):
    home, projects = seeded
    names = sorted(p.name for p in projects.iterdir() if (p / "CLAUDE.md").is_file())
    assert names == ["demo-site", "ember-oak", "notes-only", "old-experiment", "phoenix9", "railway-hotel", "tiny-tool"]
    assert not (projects / "scratch-pad" / "CLAUDE.md").exists()
    from phoenix9 import project_removal
    assert project_removal.removed_names() == {"old-experiment"}
    for project, run_ids in RUNS.items():
        found = sorted(p.name for p in (home / "runs" / project).iterdir())
        assert found == sorted(run_ids)
    assert not (home / "runs" / "notes-only").exists()
    for name in [n for n in names if n != "old-experiment"]:
        lines = (projects / name / "notes/changelog.md").read_text().splitlines()
        assert len([x for x in lines if x.startswith("- ")]) == 5
        assert list((projects / name / "notes/specs").glob("*.md"))
    open_gates = [g for g in ops_gates.list_() if not g["answered"]]
    assert sorted(g["kind"] for g in open_gates) == ["escalation", "merge"]
    esc = next(g for g in open_gates if g["kind"] == "escalation")
    assert esc["actions"] == gates.ESCALATION_ACTIONS and esc["project"] == "demo-site" and esc["task"] == 2
    merge = next(g for g in open_gates if g["kind"] == "merge")
    assert merge["actions"] == gates.DEFAULT_ACTIONS and merge["flags"] == ["changes safety code"]


def test_seed_twice_gives_the_same_data(tmp_path):
    home, projects = tmp_path / "h", tmp_path / "p"
    seed_demo.seed(home, projects)
    first = (tree(home), tree(projects))
    seed_demo.seed(home, projects)
    assert (tree(home), tree(projects)) == first


def test_seed_refuses_real_or_unmarked_folders(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (other / "mine.txt").write_text("keep")
    with pytest.raises(ValueError):
        seed_demo.seed(other, tmp_path / "p")
    assert (other / "mine.txt").exists()
    for real in ("/srv/projects", "/var/lib/phoenix9"):
        with pytest.raises(ValueError):
            seed_demo.seed(Path(real), tmp_path / "p2")
        with pytest.raises(ValueError):
            seed_demo.seed(tmp_path / "h2", Path(real))


def test_seed_runs_load_with_state_and_plan_shapes(seeded):
    home, _ = seeded
    statuses = set()
    for project, run_ids in RUNS.items():
        for run_id in run_ids:
            run_dir = home / "runs" / project / run_id
            st = state.load(run_dir)
            state._validate(st)
            statuses.add(st["status"])
            assert {g for g in (line["group"] for line in st["steps"])} <= {"run-start", "task", "run-finish"}
            plan = json.loads((run_dir / "plan.json").read_text())
            assert set(plan) == {"groups", "sources", "off", "steps"}
            for name in ("settings.json", "spec.md", "spec.json", "events.jsonl"):
                assert (run_dir / name).is_file()
            assert list((run_dir / "logs").glob("*-builder.jsonl"))
    assert statuses == {"done", "failed", "waiting", "running"}
    done = state.load(home / "runs/demo-site" / RUNS["demo-site"][0])
    assert done["usage"]["cost_usd"] == 1.23


def test_api_serves_seeded_data(seeded, monkeypatch, tmp_path):
    monkeypatch.setenv("PHOENIX_HOME", str(seeded[0]))
    monkeypatch.setenv("PHOENIX_PROJECTS", str(seeded[1]))
    monkeypatch.setattr(common, "make_adapters", demo_server.demo_adapters)
    from phoenix9.api import server
    httpd = server.make_server(0)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        get = lambda p: json.loads(urllib.request.urlopen(base + p).read())["data"]
        assert len(get("/api/projects")) == 6
        assert len([g for g in get("/api/gates") if not g["answered"]]) == 2
        assert len(get("/api/projects/demo-site/runs")) == 3
        assert get("/api/logs?project=demo-site")
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_demo_server_never_uses_real_adapters(tmp_path):
    from fakes import FakeChat, FakeClaude, FakeDocker, FakeHost, FakeHttp, FakeNotify
    adapters = demo_server.demo_adapters()
    assert isinstance(adapters.docker, FakeDocker) and isinstance(adapters.host, FakeHost)
    assert isinstance(adapters.claude, FakeClaude) and isinstance(adapters.http, FakeHttp)
    assert isinstance(adapters.notify, FakeNotify) and isinstance(adapters.chat, FakeChat)
    httpd = demo_server.build_server(tmp_path / "h", tmp_path / "p", 0)
    try:
        assert common.make_adapters().docker.__class__ is FakeDocker
    finally:
        httpd.server_close()
