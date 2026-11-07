"""Tests for ops.github.prs: command line, cache, failure and no token."""
import json

import pytest

from phoenix9 import settings
from phoenix9.ops import common, github
from test_api_server import api, dist, make_project  # noqa: F401  (fixtures)


@pytest.fixture
def fake_ops(adapters, monkeypatch):
    """Ops use the fake adapters, with an empty cache."""
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    github._pr_cache.clear()
    return adapters


def repo_project(name, repo="o/r"):
    """A project whose CLAUDE.md names a GitHub repo."""
    folder = make_project(name)
    (folder / ".phoenix").mkdir(exist_ok=True)
    (folder / ".phoenix" / "project.json").write_text(json.dumps({"repo": repo}))
    return folder


def pr_calls(host):
    """The gh pr list calls made so far."""
    return [c for c in host.calls if c[:3] == ["gh", "pr", "list"]]


def test_rows_and_command_line(fake_ops):
    repo_project("alpha")
    make_project("norepo")
    fake_ops.host.script_prs()
    rows = github.prs()
    assert pr_calls(fake_ops.host) == [["gh", "pr", "list", "--repo", "o/r", "--state", "open", "--json",
                                        "number,title,state,isDraft,statusCheckRollup,url,updatedAt"]]
    assert rows[0] == {"project": "alpha", "number": 7, "title": "Add search", "state": "open", "draft": False,
                       "checks": "passing", "url": "https://github.com/o/r/pull/7",
                       "updated_at": "2026-11-07T10:00:00Z"}
    assert rows[1]["draft"] is True and rows[1]["checks"] == "none"


def test_check_words():
    assert github._checks([{"conclusion": "FAILURE"}, {"conclusion": "SUCCESS"}]) == "failing"
    assert github._checks([{"status": "IN_PROGRESS", "conclusion": ""}]) == "pending"
    assert github._checks([{"state": "SUCCESS"}]) == "passing"


def test_cache_per_repo_and_state(fake_ops):
    repo_project("alpha")
    fake_ops.host.script_prs()
    github.prs("alpha")
    github.prs("alpha")
    assert len(pr_calls(fake_ops.host)) == 1
    github.prs("alpha", "closed")
    assert len(pr_calls(fake_ops.host)) == 2


def test_failure_gives_error_field(fake_ops):
    repo_project("alpha")
    fake_ops.host.script_prs(rc=1)
    rows = github.prs()
    assert len(rows) == 1 and rows[0]["project"] == "alpha" and rows[0]["error"]


def test_bad_state(fake_ops):
    with pytest.raises(common.OpsError):
        github.prs(state="nope")


def test_no_token_in_calls_or_output(fake_ops, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "ghp_secret123")
    repo_project("alpha")
    fake_ops.host.script_prs()
    rows = github.prs()
    assert "ghp_secret123" not in str(fake_ops.host.calls) + str(rows)
