"""Tests for the TOML writer: everything written must read back identical."""
import tomllib

import pytest

from phoenix9 import tomlw


def rt(data):
    assert tomllib.loads(tomlw.dumps(data)) == data


def test_scalars():
    rt({"a": "x", "b": 3, "c": -2, "d": 1.5, "e": True, "f": False, "g": 1e100})


def test_string_escapes():
    rt({"s": 'q"uote \\ back\nnew\ttab \x00\x1f\x7f é 漢 😀 \r\b\f'})


def test_nested_three_deep():
    rt({"a": {"x": 1, "b": {"y": 2, "c": {"z": 3}}}})


def test_arrays_of_tables():
    rt({"step": [{"name": "a", "n": 1}, {"name": "b", "sub": {"k": "v"}, "deep": [{"q": 1}]}]})


def test_empty_table_and_list():
    rt({"t": {}, "l": [], "a": {"b": {}}})


def test_lists_of_scalars():
    rt({"l": ["a", "b"], "n": [1, 2], "f": [1.5], "b": [True]})


def test_quoted_keys_literal_vs_nested():
    literal = {"steps.builder": {"on": True}}
    nested = {"steps": {"builder": {"on": True}}}
    rt(literal)
    rt(nested)
    assert tomlw.dumps(literal) != tomlw.dumps(nested)
    rt({"weird key": 1, "": 2, "é": 3})


def test_key_order_and_alphabetical():
    text = tomlw.dumps({"b": 1, "a": 2, "z": 3, "m": 4}, key_order=["z", "m"])
    assert [l.split()[0] for l in text.splitlines()] == ["z", "m", "a", "b"]


def test_scalars_before_tables():
    text = tomlw.dumps({"t": {"x": 1}, "a": 1})
    assert text.index("a = 1") < text.index("[t]")


def test_header():
    text = tomlw.dumps({"a": 1}, header="line one\nline two")
    assert text.startswith("# line one\n# line two\n")
    assert tomllib.loads(text) == {"a": 1}


@pytest.mark.parametrize("bad", [
    {"d": __import__("datetime").datetime(2020, 1, 1)},
    {"l": [[1], [2]]},
    {"l": [1, {"a": 1}]},
    {"n": None},
    {1: "x"},
])
def test_unsupported_raises_typeerror(bad):
    with pytest.raises(TypeError):
        tomlw.dumps(bad)


def test_dump_writes_file(tmp_path):
    p = tmp_path / "sub" / "x.toml"
    tomlw.dump(p, {"a": "b"}, header="hi")
    assert tomllib.loads(p.read_text()) == {"a": "b"}


def test_phoenix_toml_round_trip():
    data = {
        "preset": "quick", "profile": "python-script", "merge": "auto", "max_tries": 3,
        "on_failure": "pause", "services": ["supabase"], "safety_files": [],
        "home_chat_may_answer": [],
        "diff": {"allow_extra": [], "deny_extra": []},
        "domains": {"allow": []},
        "steps": {"builder": {"on": True, "model": "x"}, "check": {"on": False}},
        "deploy": {"with": "none", "mode": "off", "preview": False},
    }
    order = ["preset", "profile", "merge", "max_tries", "on_failure", "services",
             "safety_files", "home_chat_may_answer", "diff", "domains", "steps", "deploy"]
    text = tomlw.dumps(data, header="Phoenix project settings", key_order=order)
    assert tomllib.loads(text) == data
    assert text.splitlines()[0] == "# Phoenix project settings"
    assert text.index("[diff]") < text.index("[domains]") < text.index("[steps.builder]") < text.index("[deploy]")
