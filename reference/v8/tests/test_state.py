import pytest

from phoenix import state


def test_atomic_write_leaves_no_partial_file(tmp_path, monkeypatch):
    target = tmp_path / "data.txt"
    target.write_text("old")

    def boom(src, dst):
        raise OSError("disk died")

    monkeypatch.setattr(state.os, "replace", boom)
    with pytest.raises(OSError):
        state.atomic_write(target, "new content")
    # The real file is untouched: old content, never half-new.
    assert target.read_text() == "old"


def test_atomic_write_replaces_and_cleans_up(tmp_path):
    target = tmp_path / "data.txt"
    state.atomic_write(target, "one")
    state.atomic_write(target, "two")
    assert target.read_text() == "two"
    assert [p.name for p in tmp_path.iterdir()] == ["data.txt"]


def test_load_json_default_and_roundtrip(tmp_path):
    p = tmp_path / "x.json"
    assert state.load_json(p, {"a": 1}) == {"a": 1}
    p.write_text("")
    assert state.load_json(p, []) == []
    state.save_json(p, {"b": [1, 2]})
    assert state.load_json(p, None) == {"b": [1, 2]}


def test_lock_held(tmp_path):
    p = tmp_path / "lock"
    assert not state.Lock.held(p)
    with state.Lock(p):
        assert state.Lock.held(p)
    assert not state.Lock.held(p)
