"""Tests for the repair note parser."""
import pytest

from phoenix9.repair import notes

HEAD = "# Repair 20261108-1-demo\n\nWhy: it broke.\n\n## Steps\n\n"

FORMS = {
    "redo task 3 from scratch": ("redo", {"n": 3}),
    "mark task 2 done because I fixed it by hand": ("mark-done", {"n": 2, "why": "I fixed it by hand"}),
    "mark task 2 skipped because not needed": ("mark-skipped", {"n": 2, "why": "not needed"}),
    "retry task 4": ("retry", {"n": 4}),
    "clear failures of task 4": ("clear-failures", {"n": 4}),
    "add a note to task 5: use the v2 api": ("add-note", {"n": 5, "text": "use the v2 api"}),
    "set diff.max_files=20 for this run": ("set-setting", {"key": "diff.max_files", "value": "20"}),
    "turn off step lint for this run": ("turn-off-step", {"name": "lint"}),
    "replace the spec with notes/specs/new.md": ("replace-spec", {"path": "notes/specs/new.md"}),
    'keep my hand fix with message "hand fix"': ("keep-hand-fix", {"message": "hand fix"}),
    "reset the worktree to abc1234": ("reset-worktree", {"sha": "abc1234"}),
    "rebuild the worktree": ("rebuild-worktree", {}),
    "close question q-1 as answered": ("close-question", {"id": "q-1", "action": "answered"}),
    "rewrite the checks of task 6 because wrong": ("rewrite-checks", {"n": 6, "why": "wrong"}),
    "rerun finish step review": ("rerun-finish", {"name": "review"}),
    "resume": ("resume", {}),
}


@pytest.mark.parametrize("text", list(FORMS))
def test_every_step_form(text):
    note = notes.parse(HEAD + f"- {text}\n")
    kind, args = FORMS[text]
    assert note.run == "20261108-1-demo" and note.why == "it broke."
    assert [(s.kind, s.args, s.line) for s in note.steps] == [(kind, args, 7)]
    assert not note.force


@pytest.mark.parametrize("bad,line", [
    ("- retry task x", 7),
    ("- dance", 7),
    ("retry task 1", 7),
    ("- retry task 1\n- reset the worktree to xyz", 8),
    ("- retry task 1 please", 7),
])
def test_refusals_have_line_numbers(bad, line):
    with pytest.raises(notes.NoteError) as e:
        notes.parse(HEAD + bad + "\n")
    assert e.value.line == line and f"line {line}" in str(e.value)


@pytest.mark.parametrize("text", [
    "Why: x\n\n## Steps\n- resume\n",
    "# Repair r\n\n## Steps\n- resume\n",
    "# Repair r\nWhy: x\n",
    "# Repair r\nWhy: x\n## Steps\n",
    "# Something\nWhy: x\n## Steps\n- resume\n",
])
def test_missing_parts_refused(text):
    with pytest.raises(notes.NoteError):
        notes.parse(text)


def test_force_anywhere():
    note = notes.parse(HEAD + "- force\n- retry task 1\n- resume\n")
    assert note.force and [s.kind for s in note.steps] == ["retry", "resume"]
    assert notes.parse(HEAD + "- retry task 1\n- force\n").force


def test_result_round_trip():
    text = HEAD + "- retry task 1\n"
    out = notes.render_result(text, "all good")
    assert out.endswith("## Result\n\nall good\n")
    again = notes.render_result(out, "second")
    assert again.count("## Result") == 1 and "all good" not in again and again.endswith("second\n")
    assert notes.parse(again).steps[0].kind == "retry"
    mid = notes.render_result(out + "\n## Later\n\nx\n", "third")
    assert "third" in mid and "## Later" in mid and "all good" not in mid


def test_result_section_ignored_on_parse():
    text = HEAD + "- retry task 1\n\n## Result\n\n- not a step at all\n"
    assert len(notes.parse(text).steps) == 1
