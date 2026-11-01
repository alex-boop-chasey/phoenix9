"""The step library loader: reads step folders, validates them, reports broken ones without crashing."""
import shutil
from pathlib import Path

import pytest

from phoenix9.library import load_library

DATA = Path(__file__).parent / "data" / "library"


def copy_library(tmp_path: Path) -> Path:
    """A writable copy of the test library, so a test can add broken folders to it."""
    root = tmp_path / "lib"
    shutil.copytree(DATA, root)
    return root


def add_step(root: Path, folder: str, text: str) -> None:
    """Write steps/<folder>/step.toml with the given text."""
    (root / "steps" / folder).mkdir(parents=True, exist_ok=True)
    (root / "steps" / folder / "step.toml").write_text(text)


GOOD = """
name = "{name}"
title = "T"
kind = "script"
level = "task"
order = {order}
"""


# Criterion 1
def test_loads_test_library_sorted_by_group_and_order():
    lib = load_library(DATA)
    assert lib.problems == []
    assert [s.name for s in lib.steps] == [
        "pick-up", "planner",
        "check-writer", "red-check", "builder", "commit", "acceptance",
        "full-suite",
    ]
    assert [s.group for s in lib.steps] == ["run-start"] * 2 + ["task"] * 5 + ["run-finish"]
    assert lib.step("builder").needs == ("task", "worktree", "failures", "plan")
    assert lib.step("builder").settings == {"max_tries": 3}
    assert [s.name for s in lib.steps_in("run", "start")] == ["pick-up", "planner"]
    assert [s.name for s in lib.steps_in("task")] == [
        "check-writer", "red-check", "builder", "commit", "acceptance"]
    assert lib.things["diff"].fallback == "" and lib.things["checks"].fallback == "spec-done-when"
    assert lib.things["task"].provided == "task"


def test_unknown_step_name_is_keyerror():
    with pytest.raises(KeyError, match="no step called 'nope'"):
        load_library(DATA).step("nope")


# Criterion 2
@pytest.mark.parametrize("folder,text,expect", [
    ("extra-key", GOOD.format(name="extra-key", order=91) + 'colour = "red"\n', "unknown key 'colour'"),
    ("bad-kind", GOOD.format(name="bad-kind", order=92).replace('"script"', '"robot"'),
     "'kind' is 'robot'"),
    ("task-phase", GOOD.format(name="task-phase", order=93) + 'phase = "start"\n',
     "'phase' is only for run-level steps"),
    ("wrong-folder", GOOD.format(name="other-name", order=94),
     "name is 'other-name' but the folder is 'wrong-folder'"),
])
def test_broken_step_reported_and_skipped(tmp_path, folder, text, expect):
    root = copy_library(tmp_path)
    add_step(root, folder, text)
    lib = load_library(root)
    assert len(lib.problems) == 1
    assert expect in lib.problems[0]
    assert f"steps/{folder}/step.toml" in lib.problems[0]
    assert not lib.has_step(folder) and not lib.has_step("other-name")
    assert len(lib.steps) == 8                     # every good step still loads


def test_all_problems_reported_together(tmp_path):
    root = copy_library(tmp_path)
    add_step(root, "a", 'name = "a"\nkind = "robot"\nlevel = "task"\norder = 1\nwho = 1\n')
    add_step(root, "b", "this is not toml [")
    (root / "steps" / "c").mkdir()
    lib = load_library(root)
    text = "\n".join(lib.problems)
    assert "steps/a/step.toml: unknown key 'who'" in text
    assert "steps/a/step.toml: missing required key 'title'" in text
    assert "steps/a/step.toml: 'kind' is 'robot'" in text
    assert "steps/b/step.toml: not valid TOML" in text
    assert "steps/c/step.toml: file is missing" in text
    assert len(lib.steps) == 8


def test_underscore_and_dot_folders_ignored(tmp_path):
    root = copy_library(tmp_path)
    add_step(root, "_draft", "broken")
    add_step(root, ".hidden", "broken")
    assert load_library(root).problems == []


def test_run_step_without_phase_and_order_as_bool(tmp_path):
    root = copy_library(tmp_path)
    add_step(root, "no-phase", 'name = "no-phase"\ntitle = "T"\nkind = "gate"\nlevel = "run"\norder = 5\n')
    add_step(root, "bool-order", GOOD.format(name="bool-order", order="true"))
    text = "\n".join(load_library(root).problems)
    assert "run-level steps need phase" in text
    assert "'order' must be a whole number" in text


# Criterion 3
def test_duplicate_order_skips_both(tmp_path):
    root = copy_library(tmp_path)
    add_step(root, "twin", GOOD.format(name="twin", order=30))      # builder is task order 30
    lib = load_library(root)
    assert not lib.has_step("twin") and not lib.has_step("builder")
    assert len(lib.problems) == 1
    assert "builder, twin" in lib.problems[0] and "order 30" in lib.problems[0]


def test_same_order_in_different_groups_is_fine(tmp_path):
    root = copy_library(tmp_path)
    run_step = 'name = "late"\ntitle = "T"\nkind = "script"\nlevel = "run"\nphase = "{phase}"\norder = {order}\n'
    add_step(root, "late", run_step.format(phase="finish", order=30))   # task 30 is builder: fine
    assert load_library(root).problems == []
    add_step(root, "late", run_step.format(phase="finish", order=10))   # finish 10 is full-suite
    assert "order 10" in load_library(root).problems[0]


def test_unknown_thing_in_needs(tmp_path):
    root = copy_library(tmp_path)
    add_step(root, "greedy", GOOD.format(name="greedy", order=95) + 'needs = ["unicorn"]\n')
    lib = load_library(root)
    assert not lib.has_step("greedy")
    assert lib.problems == ["steps/greedy/step.toml: needs 'unicorn', which is not in steps/_things.toml"]


def test_unknown_thing_in_produces(tmp_path):
    root = copy_library(tmp_path)
    add_step(root, "maker", GOOD.format(name="maker", order=95) + 'produces = ["unicorn"]\n')
    assert "produces 'unicorn'" in load_library(root).problems[0]


def test_only_with_must_name_a_working_step(tmp_path):
    root = copy_library(tmp_path)
    add_step(root, "pal", GOOD.format(name="pal", order=96) + 'only_with = ["ghost"]\n')
    add_step(root, "pal2", GOOD.format(name="pal2", order=97) + 'only_with = ["pal"]\n')
    lib = load_library(root)
    assert not lib.has_step("pal") and not lib.has_step("pal2")    # pal2 falls with pal
    assert any("only_with names 'ghost'" in p for p in lib.problems)
    assert any("only_with names 'pal'" in p for p in lib.problems)


def test_ai_block_only_on_ai_steps(tmp_path):
    root = copy_library(tmp_path)
    add_step(root, "scripty", GOOD.format(name="scripty", order=98) + "[ai]\nmodel = 'x'\n")
    assert "[ai] block is only for" in load_library(root).problems[0]


def test_proxy_key_accepted(tmp_path):
    root = copy_library(tmp_path)
    add_step(root, "pusher", GOOD.format(name="pusher", order=99) + 'proxy = ["github"]\n')
    lib = load_library(root)
    assert lib.problems == [] and lib.step("pusher").proxy == ("github",)


def test_broken_things_file(tmp_path):
    root = copy_library(tmp_path)
    things = root / "steps" / "_things.toml"
    things.write_text(things.read_text() + '\n[odd]\nprovided = "always"\n[both]\nprovided = "run"\n'
                      'fallback = "x"\n[neither]\ndescription = "?"\n')
    text = "\n".join(load_library(root).problems)
    assert "[odd]: 'provided' is 'always'" in text
    assert "[both]: has both" in text
    assert "[neither]: needs 'provided' or 'fallback'" in text


def test_non_utf8_files_reported_not_raised(tmp_path):
    root = copy_library(tmp_path)
    (root / "steps" / "_things.toml").write_bytes(b'[spec]\nprovided = "\xff\xfe"\n')
    add_step(root, "bad-bytes", "")
    (root / "steps" / "bad-bytes" / "step.toml").write_bytes(b'name = "\xff"\n')
    text = "\n".join(load_library(root).problems)
    assert "_things.toml: is not UTF-8 text" in text
    assert "bad-bytes" in text and "is not UTF-8 text" in text


def test_missing_steps_folder_never_raises(tmp_path):
    lib = load_library(tmp_path / "empty")
    assert lib.steps == [] and len(lib.problems) == 2
