"""The shared project search and filter: ops.projects.query, `phoenix project list` options."""
import json

import pytest

from phoenix9.__main__ import main
from phoenix9.ops import common, projects


def fake_row(name, description="", repo="", owner=None, size=0, used=None, needs=0, run=None, activity="idle"):
    """A made-up row; `activity` is what status.project_state would have said for it."""
    return {"name": name, "description": description, "repo": repo, "repo_owner": owner, "size": size,
            "last_used_at": used, "needs_you": needs, "run": run, "activity": activity,
            "harness": "idle", "last_used": "never"}


ROWS = [
    fake_row("alpha", "Billing tool", "acme/alpha", "acme", size=300, used=100),
    fake_row("beta", "Garden notes", "", None, size=900, used=300, needs=2, activity="need"),
    fake_row("gamma", "Billing site", "zed/gamma", "zed", size=None, used=200, run={"status": "running"}, activity="run"),
    fake_row("delta", "Old thing", "acme/delta", "acme", size=50, used=None, run=None, activity="fail"),
    fake_row("eps", "Waiting", "", None, size=10, used=400, needs=1, run={"status": "waiting"}, activity="need"),
    fake_row("zeta", "Paused", "", None, run={"status": "paused-limit"}, activity="fail"),
]


@pytest.fixture(autouse=True)
def fake_rows(monkeypatch):
    monkeypatch.setattr(projects, "rows", lambda: [dict(r) for r in ROWS])


def names(rows):
    return [r["name"] for r in rows]


def test_default_everything_in_rest_by_name():
    r = projects.query()
    assert r["top"] == [] and r["total"] == 6
    assert names(r["rest"]) == ["alpha", "beta", "delta", "eps", "gamma", "zeta"]


def test_counts():
    assert projects.query()["counts"] == {"all": 6, "run": 1, "fail": 2, "idle": 1, "need": 2}


def test_search_name_and_description_case_insensitive():
    assert names(projects.query(q="BILLING")["rest"]) == ["alpha", "gamma"]
    assert names(projects.query(q="  garden ")["rest"]) == ["beta"]
    assert names(projects.query(q="delt")["rest"]) == ["delta"]
    assert projects.query(q="nothing")["total"] == 0


@pytest.mark.parametrize("status,expected", [("run", ["gamma"]), ("fail", ["delta", "zeta"]), ("idle", ["alpha"]),
                                             ("need", ["beta", "eps"]), ("all", ["alpha", "beta", "delta", "eps", "gamma", "zeta"])])
def test_status_filter(status, expected):
    r = projects.query(status=status)
    assert names(r["rest"]) == expected and r["total"] == len(expected)


def test_counts_ignore_status_but_follow_search():
    r = projects.query(q="billing", status="run")
    assert names(r["rest"]) == ["gamma"] and r["total"] == 1
    assert r["counts"] == {"all": 2, "run": 1, "fail": 0, "idle": 1, "need": 0}


def test_owner_filter():
    assert names(projects.query(owner="acme")["rest"]) == ["alpha", "delta"]
    assert names(projects.query(owner="none")["rest"]) == ["beta", "eps", "zeta"]
    assert projects.query(owner="all")["total"] == 6
    assert projects.query(owner="nobody")["total"] == 0


def test_sort_active_most_recent_first_never_last():
    assert names(projects.query(sort="active")["rest"]) == ["eps", "beta", "gamma", "alpha", "delta", "zeta"]


def test_sort_size_largest_first_unmeasured_last():
    assert names(projects.query(sort="size")["rest"]) == ["beta", "alpha", "delta", "eps", "gamma", "zeta"]


def _folder(tmp_path, name, created, changed):
    """A project folder with a created date and one file changed at a known time."""
    import os
    folder = tmp_path / name
    (folder / ".phoenix").mkdir(parents=True)
    (folder / ".phoenix" / "project.json").write_text(json.dumps({"created": created}))
    f = folder / "code.txt"
    f.write_text("x")
    os.utime(f, (changed, changed))
    return {"name": name, "path": str(folder), "last_used_at": None}


def test_sort_created_and_modified_newest_first(tmp_path, monkeypatch):
    rows = [_folder(tmp_path, "old", "2026-01-01", 5_000_000_000), _folder(tmp_path, "new", "2026-06-01", 4_000_000_000)]
    monkeypatch.setattr(projects, "rows", lambda: [dict(r, description="", repo="", repo_owner=None, size=0,
                                                         needs_you=0, run=None) for r in rows])
    assert names(projects.query(sort="created")["rest"]) == ["new", "old"]
    assert names(projects.query(sort="modified")["rest"]) == ["old", "new"]


def test_modified_counts_last_run_and_changelog(tmp_path):
    import os
    row = _folder(tmp_path, "p", "2026-01-01", 1_000)
    assert projects.modified_at(row) >= 1_000
    (tmp_path / "p" / "notes").mkdir()
    log = tmp_path / "p" / "notes" / "changelog.md"
    log.write_text("- x")
    os.utime(log, (7_000_000_000, 7_000_000_000))
    assert projects.modified_at(row) == 7_000_000_000
    assert projects.modified_at({**row, "last_used_at": 8_000_000_000}) == 8_000_000_000


def test_created_falls_back_when_date_missing(tmp_path):
    row = _folder(tmp_path, "p", "", 1_000)
    assert projects.created_at(row) > 0
    assert projects.created_at({"path": str(tmp_path / "nope")}) == 0.0


def test_attention_splits_in_sort_order():
    r = projects.query(attention=True, sort="active")
    assert names(r["top"]) == ["eps", "beta"]
    assert names(r["rest"]) == ["gamma", "alpha", "delta", "zeta"]
    assert r["total"] == 6


def test_attention_with_filter_without_need_has_empty_top():
    r = projects.query(attention=True, status="idle")
    assert r["top"] == [] and names(r["rest"]) == ["alpha"]


@pytest.mark.parametrize("kw", [{"status": "bogus"}, {"sort": "bogus"}])
def test_bad_values_are_clear_errors(kw):
    with pytest.raises(common.OpsError, match="bogus"):
        projects.query(**kw)


def run_cmd(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_filtered_json(capsys, phoenix_env):
    code, out, _ = run_cmd(capsys, "project", "list", "--filter", "billing", "--attention", "--json")
    assert code == 0
    data = json.loads(out)
    data = data.get("data", data)
    assert names(data["rest"]) == ["alpha", "gamma"] and data["top"] == [] and data["total"] == 2


def test_cli_filtered_plain(capsys, phoenix_env):
    code, out, _ = run_cmd(capsys, "project", "list", "--status", "need", "--sort", "active")
    assert code == 0 and out.index("eps") < out.index("beta")


def test_cli_nothing_matches(capsys, phoenix_env):
    code, out, _ = run_cmd(capsys, "project", "list", "--filter", "zzz")
    assert code == 0 and "No projects match." in out


def test_cli_bad_status(capsys, phoenix_env):
    code, out, err = run_cmd(capsys, "project", "list", "--status", "bogus")
    assert code != 0 and "bogus" in out + err
