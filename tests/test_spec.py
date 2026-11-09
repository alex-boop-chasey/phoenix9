"""Tests for phoenix9.spec: parsing, checking, ordering and JSON."""
import pytest

from phoenix9 import spec

HEADER = """# Test

Project: demo

## About
A test project.
"""

TASK1 = """
## Task 1: Set up the project
Scaffold the app.

Done when:
- pnpm build finishes cleanly with no errors
"""


def errors_for(text):
    return spec.check(text)


def one_error(text):
    errors = errors_for(text)
    assert len(errors) == 1, errors
    return errors[0]


def task(n, deps=None, title=None):
    dep = f"Depends on: {deps}\n" if deps is not None else ""
    return f"\n## Task {n}: {title or 'T' + str(n)}\n{dep}Do {n}.\n\nDone when:\n- page {n} shows its heading\n"


def test_parse_basics():
    s = spec.parse(HEADER.replace("Project: demo", "Project: demo\nPreset: quick") + TASK1)
    assert (s.title, s.project, s.preset) == ("Test", "demo", "quick")
    assert s.about == "A test project."
    assert spec.check(HEADER + TASK1) == []
    t = s.tasks[0]
    assert t.number == 1 and t.title == "Set up the project" and t.goal == "Scaffold the app."
    assert t.depends_on == [] and not t.for_you


def test_v8_plan_title_and_step_heading_and_ignored_keys():
    text = ("# Plan: Old\n\nType: new\nRepo: me/site\nStack: x\n\n## About\nHi.\n"
            + TASK1.replace("Task", "Step"))
    s = spec.parse(text)
    assert s.title == "Old" and [t.number for t in s.tasks] == [1]
    assert spec.check(text) == []


def test_command_bullet_extracted():
    t = spec.parse(HEADER + TASK1 + "- `pnpm test`\n- `a` and `b` both pass\n").tasks[0]
    assert t.done_when[0].command is None
    assert t.done_when[1].command == "pnpm test"
    assert t.done_when[2].command is None
    assert spec.check(HEADER + TASK1 + "- `pnpm test`\n") == []


def test_for_you_task():
    text = HEADER + TASK1 + "\n## Task 2: Keys\nFor you: yes\nGet a key.\n"
    s = spec.parse(text)
    assert s.tasks[1].for_you and s.tasks[1].done_when == []
    assert spec.check(text) == []


def test_default_depends_on_previous():
    s = spec.parse(HEADER + TASK1 + task(2) + task(3, "none"))
    assert [t.depends_on for t in s.tasks] == [[], [1], []]


def test_gap_in_numbers():
    errors = errors_for(HEADER + TASK1 + task(3))
    assert errors[0].startswith("Task 3 (line 14)") and "no gaps" in errors[0]


def test_duplicate_numbers():
    msg = one_error(HEADER + TASK1 + TASK1.replace("Set up the project", "Again"))
    assert msg.startswith("Task 1 (line 14)") and "used twice" in msg and "line 8" in msg


def test_no_tasks():
    assert any("no tasks" in e for e in errors_for(HEADER))


def test_61_tasks_rejected():
    body = "".join(task(n) for n in range(1, 62))
    errors = errors_for(HEADER + body)
    assert len(errors) == 1 and "61 tasks" in errors[0] and "60" in errors[0]
    assert errors_for(HEADER + "".join(task(n) for n in range(1, 61))) == []


def test_missing_title_goal_and_done_when():
    assert "no title" in one_error(HEADER + TASK1.replace(": Set up the project", ""))
    assert "no description" in one_error(
        HEADER + "\n## Task 1: A\nDone when:\n- page one shows its heading\n")
    msg = one_error(HEADER + "\n## Task 1: A\nDo it.\n")
    assert msg.startswith("Task 1 (line 8)") and "Done when" in msg


def test_depends_on_later_task_and_itself_and_missing():
    msg = one_error(HEADER + TASK1.replace("none", "") + "\n## Task 2: M\nDepends on: 3\nAdd.\n\n"
                    "Done when:\n- the menu page lists items\n" + task(3, "1"))
    assert msg.startswith("Task 2 (line 15)") and "task 3" in msg and "earlier" in msg
    assert one_error(HEADER + TASK1 + task(2, "2")).startswith("Task 2 (line 15)")
    assert "not in the spec" in one_error(HEADER + task(1, "none") + task(2, "0"))


def test_bad_depends_value():
    msg = one_error(HEADER + TASK1 + task(2, "task one"))
    assert msg.startswith("Task 2 (line 15)") and "Depends on" in msg


def test_cycle_error():
    errors = errors_for(HEADER + task(1, "2") + task(2, "1"))
    assert any("cycle" in e for e in errors)
    assert not any("cycle" in e for e in errors_for(HEADER + TASK1 + task(2, "1")))


def test_short_bullet():
    msg = one_error(HEADER + TASK1 + "- it builds\n")
    assert msg.startswith("Task 1 (line 13)") and "too short" in msg


@pytest.mark.parametrize("ending", ["professional", "nice", "good", "clean", "modern", "works well"])
def test_vague_ending(ending):
    msg = one_error(HEADER + TASK1 + f"- the home page looks {ending}.\n")
    assert msg.startswith("Task 1 (line 13)") and "vague" in msg and ending in msg


def test_vague_word_inside_is_fine():
    assert errors_for(HEADER + TASK1 + "- good contrast on every button text\n") == []


def test_unknown_preset():
    msg = one_error(HEADER.replace("Project: demo", "Project: demo\nPreset: turbo") + TASK1)
    assert msg.startswith("Line 4") and "turbo" in msg


def test_unknown_header_and_stray_text():
    assert one_error(HEADER.replace("Project: demo", "Project: demo\nBudget: 1") + TASK1).startswith("Line 4")
    assert one_error(HEADER.replace("Project: demo", "Project: demo\nstray words") + TASK1).startswith("Line 4")


def test_first_line_must_be_title():
    assert any(e.startswith("Line 1") for e in errors_for("Project: x\n" + TASK1))


def test_unknown_section():
    assert "## Notes" in one_error(HEADER + TASK1 + "\n## Notes\nstuff\n")


def test_text_after_done_when_is_an_error():
    assert one_error(HEADER + TASK1 + "More description.\n").startswith("Task 1 (line 13)")


def test_wrapped_bullet_joins_previous():
    s = spec.parse(HEADER + TASK1 + "- the home page shows the bakery\n  name in the header\n")
    assert spec.check(HEADER + TASK1 + "- the home page shows the bakery\n  name in the header\n") == []
    assert s.tasks[0].done_when[-1].text == "the home page shows the bakery name in the header"


def test_order_and_dependents():
    text = HEADER + task(1, "none") + task(3, "2") + task(2, "1") + task(4, "1") + task(5, "3, 4")
    s = spec.parse(text)
    assert [t.number for t in spec.order(s)] == [1, 2, 3, 4, 5]
    assert [t.number for t in spec.dependents_of(s, 2)] == [3, 5]
    assert [t.number for t in spec.dependents_of(s, 1)] == [2, 3, 4, 5]
    assert spec.dependents_of(s, 5) == []


def test_order_survives_cycle():
    s = spec.parse(HEADER + task(1, "2") + task(2, "1"))
    assert sorted(t.number for t in spec.order(s)) == [1, 2]


def test_json_round_trip():
    s = spec.parse(HEADER.replace("Project: demo", "Project: demo\nPreset: full") + TASK1
                   + "- `pnpm test`\n" + "\n## Task 2: Keys\nFor you: yes\nGet a key.\n")
    d = spec.to_json(s)
    import json
    d = json.loads(json.dumps(d))
    back = spec.from_json(d)
    assert spec.to_json(back) == d
    assert back.tasks[0].done_when[1].command == "pnpm test"
    assert back.tasks[1].for_you


FREE = """# Recipe box

A small app for keeping family recipes. Text before the first heading.

## Non-negotiable: works offline
Recipes must load with no network → always.

## Stack (recommended)
Use `sqlite` and ```python``` scripts.

## Build order (MVP → full)
1. Add recipes → 2. Search → 3. Share
### Later
Photos.
"""


def test_free_form_description_fails_strict_but_passes_description_check():
    assert spec.check(FREE)                               # not in the task format
    assert spec.check_description(FREE) == []
    assert spec.description_title(FREE) == "Recipe box"
    assert spec.description_title("\n\nJust one line, no heading\n") == "Just one line, no heading"
    assert spec.description_title("", "fallback") == "fallback"


def test_description_check_refuses_empty_and_too_big():
    assert "empty" in spec.check_description("  \n\n")[0]
    big = "# Big\n" + "x" * (spec.MAX_DESCRIPTION_BYTES + 1)
    assert "200 KB" in spec.check_description(big)[0]
