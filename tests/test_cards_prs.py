"""Tests for the prs card and the needs_merge flag on the projects card."""
import pytest

from phoenix9.ops import cards as ops_cards, common, github
from test_api_server import api, dist, make_project  # noqa: F401  (fixtures)
from test_ops_github import repo_project


@pytest.fixture
def fake_ops(adapters, monkeypatch):
    """Ops use the fake adapters, with an empty cache."""
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    github._pr_cache.clear()
    return adapters


def test_prs_card(fake_ops):
    repo_project("alpha")
    fake_ops.host.script_prs()
    card = ops_cards.build("prs", {"project": "alpha"})
    assert card["title"] == "Open pull requests in alpha"
    assert [r["number"] for r in card["data"]] == [7, 8]
    assert [a["href"] for a in card["actions"]] == ["https://github.com/o/r/pull/7", "https://github.com/o/r/pull/8"]
    assert all(a["kind"] == "link" for a in card["actions"])
    assert card["watch"]["poll_s"] == 60


def test_prs_card_refuses_bad_query(fake_ops):
    with pytest.raises(common.OpsError):
        ops_cards.build("prs", {"state": 3})


def test_projects_rows_need_merge(fake_ops):
    repo_project("alpha")
    make_project("beta")
    fake_ops.host.script_prs()
    rows = {r["name"]: r for r in (lambda d: d["top"] + d["rest"])(ops_cards.build("projects")["data"])}
    assert rows["alpha"]["needs_merge"] is True
    assert rows["alpha"]["pr"] == {"number": 7, "title": "Add search", "url": "https://github.com/o/r/pull/7"}
    assert rows["beta"]["needs_merge"] is False and rows["beta"]["pr"] is None


def test_only_drafts_do_not_need_merge(fake_ops):
    repo_project("alpha")
    fake_ops.host.script_prs([{"number": 1, "title": "x", "state": "OPEN", "isDraft": True,
                                                    "url": "u", "updatedAt": "", "statusCheckRollup": []}])
    data = ops_cards.build("projects")["data"]
    assert (data["top"] + data["rest"])[0]["needs_merge"] is False
