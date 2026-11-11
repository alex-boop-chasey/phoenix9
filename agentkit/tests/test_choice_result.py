"""Tests that a declared list-of-whole-numbers result field keeps only a valid short list."""
from agentkit.runs import limit_result

FIELDS = {"status": ("picked", "cancelled"), "picked": ("ints", 0, 30)}


def test_a_valid_list_passes():
    r = {"status": "picked", "picked": [0, 3, 30]}
    assert limit_result(FIELDS, r) == r
    assert limit_result(FIELDS, {"picked": []}) == {"picked": []}


def test_bad_lists_are_dropped():
    assert limit_result(FIELDS, {"status": "picked", "picked": [1, "two"]}) == {"status": "picked"}
    assert limit_result(FIELDS, {"picked": [31]}) == {}
    assert limit_result(FIELDS, {"picked": [-1]}) == {}
    assert limit_result(FIELDS, {"picked": [True]}) == {}
    assert limit_result(FIELDS, {"picked": [1.5]}) == {}
    assert limit_result(FIELDS, {"picked": 3}) == {}
    assert limit_result(FIELDS, {"picked": list(range(31)) + [0]}) == {}
    assert limit_result(FIELDS, {"picked": list(range(31))}) == {"picked": list(range(31))}


def test_stray_keys_are_dropped():
    r = {"status": "cancelled", "picked": [1], "note": "hi"}
    assert limit_result(FIELDS, r) == {"status": "cancelled", "picked": [1]}


def test_none_keeps_all():
    assert limit_result(None, {"a": [1, "x"]}) == {"a": [1, "x"]}
