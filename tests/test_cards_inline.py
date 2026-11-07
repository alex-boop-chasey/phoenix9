"""Tests for the inline cards: settings-preview, table and chart."""
import pytest

from phoenix9 import paths
from phoenix9.ops import cards as ops_cards, common
from test_ops_logs import proj  # noqa: F401  (fixture)


def _files(folder):
    """Every file under the project folder with its bytes."""
    return {str(p): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


def test_settings_preview_good_change(proj):
    before = _files(proj)
    card = ops_cards.build("settings-preview", {"project": "demo", "set": {"max_tries": 5, "steps.builder.timeout": 30}})
    assert card["inline"] is True and card["data"]["footer"] == "proposed by the agent"
    rows = {r["key"]: r for r in card["data"]["rows"]}
    assert rows["max_tries"] == {"key": "max_tries", "before": 3, "after": 5, "ok": True, "reason": ""}
    assert rows["steps.builder.timeout"]["before"] == 45
    (apply,) = card["actions"]
    assert apply["kind"] == "op" and apply["op"]["method"] == "POST"
    assert apply["op"]["path"] == "/api/projects/demo/settings"
    assert apply["op"]["body"] == {"set": {"max_tries": 5, "steps.builder.timeout": 30}}
    assert "max_tries" in apply["confirm"]
    assert _files(proj) == before  # dry validation writes nothing


def test_settings_preview_bad_row_has_no_apply(proj):
    before = _files(proj)
    card = ops_cards.build("settings-preview", {"project": "demo", "set": {"max_tries": 5, "nope.key": 1}})
    rows = {r["key"]: r for r in card["data"]["rows"]}
    assert rows["max_tries"]["ok"] is True
    assert rows["nope.key"]["ok"] is False and "nope.key" in rows["nope.key"]["reason"]
    assert card["actions"] == []
    assert _files(proj) == before


@pytest.mark.parametrize("query", [
    {"project": "demo"}, {"project": "demo", "set": {}},
    {"project": "demo", "set": {f"k{i}": 1 for i in range(21)}}, {"set": {"max_tries": 2}}])
def test_settings_preview_refuses_bad_shapes(proj, query):
    with pytest.raises(common.OpsError):
        ops_cards.build("settings-preview", query)


def test_table_card():
    card = ops_cards.build("table", {"columns": ["a", "b"], "rows": [["x" * 300, 2], ["y", 3.5]]})
    assert card["inline"] is True and card["data"]["footer"] == "proposed by the agent"
    assert card["data"]["rows"][0] == ["x" * 200, 2]


@pytest.mark.parametrize("query", [
    {"columns": [], "rows": []}, {"columns": [str(i) for i in range(9)], "rows": []},
    {"columns": ["a"], "rows": [["x"]] * 51}, {"columns": ["a"], "rows": ["x"]},
    {"columns": ["a"], "rows": [[None]]}, {"columns": ["a", "b"], "rows": [["x"]]},
    {"columns": ["a"], "rows": [[{"x": 1}]]}])
def test_table_refuses_bad_shapes(query):
    with pytest.raises(common.OpsError):
        ops_cards.build("table", query)


def test_chart_card():
    series = [{"label": "a", "value": 1}, {"label": "b", "value": 2.5}]
    card = ops_cards.build("chart", {"kind": "bars", "series": series})
    assert card["data"]["series"] == series and card["data"]["kind"] == "bars"
    spark = ops_cards.build("chart", {"kind": "spark", "series": [{"label": str(i), "value": i} for i in range(60)]})
    assert len(spark["data"]["series"]) == 60


@pytest.mark.parametrize("query", [
    {"kind": "pie", "series": [{"label": "a", "value": 1}]}, {"kind": "bars", "series": []},
    {"kind": "bars", "series": [{"label": str(i), "value": i} for i in range(21)]},
    {"kind": "spark", "series": [{"label": str(i), "value": i} for i in range(61)]},
    {"kind": "bars", "series": [{"label": "a", "value": "1"}]},
    {"kind": "bars", "series": [{"label": "a", "value": True}]},
    {"kind": "bars", "series": [{"label": "a"}]}, {"kind": "bars", "series": ["a"]}])
def test_chart_refuses_bad_shapes(query):
    with pytest.raises(common.OpsError):
        ops_cards.build("chart", query)
