"""Tests for the affected-test picker."""
from phoenix9 import affected, settings

T = {"affected_cmd": "python3 -m pytest -q {files}", "test_globs": "tests/test_*.py",
     "affected_all_globs": "conftest.py requirements*.txt check.sh"}


def tree(tmp_path, files):
    """Write files (path -> text) and return the list of paths."""
    for name, text in files.items():
        f = tmp_path / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    return list(files)


def test_no_settings_gives_all(tmp_path):
    out = affected.pick({"cmd": "pytest"}, ["a.py"], ["a.py"], tmp_path)
    assert out["mode"] == "all" and out["command"] == ""


def test_all_globs_force_all(tmp_path):
    allf = tree(tmp_path, {"requirements.txt": "", "tests/test_a.py": ""})
    assert affected.pick(T, ["requirements.txt"], allf, tmp_path)["mode"] == "all"
    assert affected.pick(T, ["sub/conftest.py"], allf, tmp_path)["mode"] == "all"


def test_changed_test_file_picked(tmp_path):
    allf = tree(tmp_path, {"tests/test_a.py": "", "tests/test_b.py": ""})
    out = affected.pick(T, ["tests/test_a.py"], allf, tmp_path)
    assert out["mode"] == "some" and out["files"] == ["tests/test_a.py"]
    assert out["command"] == "python3 -m pytest -q tests/test_a.py"


def test_deleted_test_file_not_picked(tmp_path):
    allf = tree(tmp_path, {"tests/test_b.py": ""})
    assert affected.pick(T, ["tests/test_gone.py"], allf, tmp_path)["mode"] == "none"


def test_source_change_picks_tests_that_mention_it(tmp_path):
    allf = tree(tmp_path, {"pkg/widget.py": "", "tests/test_a.py": "from pkg import widget\n",
                           "tests/test_b.py": "import other\n", "tests/test_c.py": "import pkg.widget\n"})
    out = affected.pick(T, ["pkg/widget.py"], allf, tmp_path)
    assert out["files"] == ["tests/test_a.py", "tests/test_c.py"]


def test_stem_is_whole_word(tmp_path):
    allf = tree(tmp_path, {"widget.py": "", "tests/test_a.py": "import widgetry\n"})
    assert affected.pick(T, ["widget.py"], allf, tmp_path)["mode"] == "none"


def test_nothing_picked_is_none_with_why(tmp_path):
    allf = tree(tmp_path, {"README.md": "", "tests/test_a.py": ""})
    out = affected.pick(T, ["README.md"], allf, tmp_path)
    assert out["mode"] == "none" and out["why"]


def test_sources_mode_passes_sources(tmp_path):
    prof = {**T, "affected_takes": "sources", "affected_cmd": "vitest related {files}"}
    allf = tree(tmp_path, {"src/a.ts": "", "tests/test_x.py": ""})
    out = affected.pick(prof, ["src/a.ts"], allf, tmp_path)
    assert out["mode"] == "some" and out["command"] == "vitest related src/a.ts"


def test_quoting_paths_with_spaces(tmp_path):
    allf = tree(tmp_path, {"tests/test_my file.py": ""})
    out = affected.pick(T, ["tests/test_my file.py"], allf, tmp_path)
    assert out["command"] == "python3 -m pytest -q 'tests/test_my file.py'"


def test_newline_in_path_falls_back_to_all(tmp_path):
    out = affected.pick(T, ["tests/test_a\n.py"], ["tests/test_a\n.py"], tmp_path)
    assert out["mode"] == "all"


def test_too_many_falls_back_to_all(tmp_path):
    names = {f"tests/test_{i}.py": "" for i in range(5)}
    allf = tree(tmp_path, names)
    assert affected.pick({**T, "affected_max": 3}, list(names), allf, tmp_path)["mode"] == "all"
    assert affected.pick({**T, "affected_max": 5}, list(names), allf, tmp_path)["mode"] == "some"


def test_settings_have_defaults():
    for key in ("affected_cmd", "affected_takes", "affected_max", "test_globs", "affected_all_globs"):
        assert f"test.{key}" in settings.PROFILE_SCHEMA
    assert settings.PROFILE_SCHEMA["test.affected_max"].default == 40
