"""Tests for the log, diff and update cards."""
import pytest

from phoenix9 import keys, paths
from phoenix9.ops import cards as ops_cards, common
from test_ops_logs import RUN, proj  # noqa: F401  (fixture)
from test_api_update_deploy import upd  # noqa: F401  (fixture)
from test_api_server import api, dist  # noqa: F401  (fixtures)
from test_updater import layout  # noqa: F401  (fixture)

LOG = f"{RUN}/logs/builder.log"
DIFF = f"{RUN}/tasks/1/attempt-1/diff.patch"


def test_log_card_defaults_and_action(proj):
    (paths.runs("demo") / RUN / "logs/builder.log").write_text("".join(f"line {i}\n" for i in range(80)))
    card = ops_cards.build("log", {"project": "demo", "id": LOG})
    assert len(card["data"]["lines"]) == 50 and card["data"]["lines"][-1] == "line 79"
    assert card["data"]["truncated"] is True
    assert card["actions"][0]["route"] == {"to": "p/demo/logs", "params": {"log": LOG}}
    assert ops_cards.build("log", {"project": "demo", "id": LOG, "tail": 5})["data"]["lines"][0] == "line 75"


def test_log_card_caps_at_200_lines(proj):
    (paths.runs("demo") / RUN / "logs/builder.log").write_text("".join(f"line {i}\n" for i in range(500)))
    for key in ("tail", "lines"):
        card = ops_cards.build("log", {"project": "demo", "id": LOG, key: 9999})
        assert len(card["data"]["lines"]) == 200 and card["data"]["truncated"] is True


def test_log_card_scrubs_secrets(proj):
    keys.set_key("demo", "TOKEN", "sekrit-value-12345", secret=True)
    (paths.runs("demo") / RUN / "logs/builder.log").write_text("the key is sekrit-value-12345 ok\n")
    card = ops_cards.build("log", {"project": "demo", "id": LOG})
    assert "sekrit-value-12345" not in repr(card)


def test_log_card_refuses_bad_input(proj):
    with pytest.raises(common.OpsError):
        ops_cards.build("log", {"project": "demo"})
    with pytest.raises(common.OpsError):
        ops_cards.build("log", {"project": "demo", "id": LOG, "tail": "5"})
    with pytest.raises(common.OpsError):
        ops_cards.build("log", {"project": "demo", "id": "../../etc/passwd"})


def test_diff_card_splits_files(proj):
    (paths.runs("demo") / RUN / "tasks/1/attempt-1/diff.patch").write_text(
        "diff --git a/x b/x\n--- a/x\n+++ b/x\n+one\n+two\n-old\ndiff --git a/y b/y\n+new\n")
    card = ops_cards.build("diff", {"project": "demo", "id": DIFF})
    files = {f["name"]: f for f in card["data"]["files"]}
    assert (files["x"]["added"], files["x"]["removed"]) == (2, 1)
    assert (files["y"]["added"], files["y"]["removed"]) == (1, 0)
    assert card["actions"][0]["route"]["to"] == "p/demo/logs"


def test_diff_card_caps_lines_and_scrubs(proj):
    keys.set_key("demo", "TOKEN", "sekrit-value-12345", secret=True)
    body = "diff --git a/x b/x\n+sekrit-value-12345\n" + "+a\n" * 3000
    (paths.runs("demo") / RUN / "tasks/1/attempt-1/diff.patch").write_text(body)
    card = ops_cards.build("diff", {"project": "demo", "id": DIFF})
    assert sum(len(f["lines"]) for f in card["data"]["files"]) == 2000 and card["data"]["truncated"] is True
    assert "sekrit-value-12345" not in repr(card)


def test_diff_card_refuses_non_diff(proj):
    with pytest.raises(common.OpsError, match="not a diff"):
        ops_cards.build("diff", {"project": "demo", "id": LOG})


def test_update_card_with_install(api, upd):
    card = ops_cards.build("update")
    assert card["data"]["update_available"] is True and card["watch"]["types"] == ["update"]
    route, install = card["actions"]
    assert route["route"]["to"] == "settings"
    assert install["op"] == {"method": "POST", "path": "/api/update/install", "body": {"yes": True, "tag": "v9.2"}}
    assert install["danger"] is True and install["confirm"]


def test_update_card_refuses_query(upd):
    with pytest.raises(common.OpsError):
        ops_cards.build("update", {"x": 1})
