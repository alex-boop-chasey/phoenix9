"""Tests for `phoenix choice` and `phoenix confirm`."""
import json

from phoenix9.__main__ import main
from test_ops_logs import proj  # noqa: F401  (fixture)


def _block_json(out):
    lines = out.strip().split("\n")
    assert lines[0] == "```phoenix-choice" or lines[0] == "```phoenix-confirm"
    assert lines[2] == "```"
    return json.loads(lines[1]), lines[3]


def test_choice_plain(proj, capsys):
    args = ["choice", "--id", "db", "--question", "Which db?", "--option", "pg=Postgres::solid",
            "--option", "lite=SQLite", "--recommended", "lite", "--other", "--mode", "multi"]
    assert main(args) == 0
    body, fallback = _block_json(capsys.readouterr().out)
    assert body["mode"] == "multi" and body["other"] is True
    assert body["options"] == [{"key": "pg", "label": "Postgres", "detail": "solid"},
                               {"key": "lite", "label": "SQLite", "recommended": True}]
    assert fallback == "Which db? 1) Postgres 2) SQLite"


def test_choice_json_and_bad(proj, capsys):
    assert main(["choice", "--id", "x", "--question", "Q", "--option", "a=A", "--option", "b=B", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["block"].startswith("```phoenix-choice\n") and "1) A 2) B" in data["fallback"]
    assert main(["choice", "--id", "x", "--question", "Q", "--option", "a=A"]) == 1
    assert main(["choice", "--id", "x", "--question", "Q", "--option", "a"]) == 1
    assert main(["choice", "--id", "bad id", "--question", "Q", "--option", "a=A", "--option", "b=B"]) == 1
    assert main(["choice", "--id", "x", "--question", "Q", "--option", "a=A", "--option", "b=B",
                 "--recommended", "zz"]) == 1


def test_confirm(proj, capsys):
    assert main(["confirm", "--id", "go", "--action", "Delete old runs", "--command", "phoenix gc --yes",
                 "--danger"]) == 0
    body, fallback = _block_json(capsys.readouterr().out)
    assert body == {"v": 1, "id": "go", "action": "Delete old runs", "command": "phoenix gc --yes", "danger": True}
    assert fallback == "Delete old runs: reply yes to run `phoenix gc --yes`"
    assert main(["confirm", "--id", "", "--action", "A", "--command", "c"]) == 1
