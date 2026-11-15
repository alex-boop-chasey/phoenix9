"""`phoenix spec check` with the check-writer off (O78): which settings decide, the sentence, and run start."""
import json

import pytest

from phoenix9 import paths
from phoenix9.__main__ import main
from phoenix9.ops import common
from phoenix9.ops import runs as ops_runs

PROSE = """# Pricing page
Project: demo
{preset}
## Task 1: Add the page
Write the pricing page.
Done when:
- the pricing page lists all three plans
"""

COMMANDS = PROSE.replace("- the pricing page lists all three plans",
                         "- the pricing page lists all three plans\n- `python3 -m pytest -q`")


def write(tmp_path, text=PROSE, preset_line=""):
    p = tmp_path / "spec.md"
    p.write_text(text.format(preset=preset_line + "\n" if preset_line else ""))
    return p


def heading_line(path) -> int:
    return path.read_text().splitlines().index("## Task 1: Add the page") + 1


def run_cmd(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture
def demo(phoenix_env):
    """A project called demo whose own settings use the given preset."""
    def make(preset="quick"):
        folder = phoenix_env["projects"] / "demo"
        folder.mkdir(exist_ok=True)
        (folder / "CLAUDE.md").write_text("# Demo\n")
        (folder / "phoenix.toml").write_text(f'preset = "{preset}"\nprofile = "python-script"\n')
        return folder
    return make


def test_preset_with_the_check_writer_off_refuses_prose_with_the_line(capsys, tmp_path):
    f = write(tmp_path)
    code, out, _ = run_cmd(capsys, "spec", "check", str(f), "--preset", "quick")
    assert code == 1
    assert "Checked for the quick preset: the check-writer is off, so every task needs a command." in out
    assert f"Line {heading_line(f)}: task 1 has no 'Done when' item Phoenix can run." in out


def test_preset_with_the_check_writer_on_accepts_prose(capsys, tmp_path):
    code, out, _ = run_cmd(capsys, "spec", "check", str(write(tmp_path)), "--preset", "full")
    assert code == 0
    assert "Checked for the full preset: the check-writer is on." in out and "Spec is valid." in out


def test_preset_wins_over_the_project_and_the_spec_line(capsys, tmp_path, demo):
    demo("full")
    f = write(tmp_path, preset_line="Preset: full")
    code, out, _ = run_cmd(capsys, "spec", "check", str(f), "--preset", "simple", "--project", "demo")
    assert code == 1 and "Checked for the simple preset" in out


def test_project_settings_decide_when_no_preset_is_given(capsys, tmp_path, demo):
    demo("quick")
    f = write(tmp_path, preset_line="Preset: full")
    code, out, _ = run_cmd(capsys, "spec", "check", str(f), "--project", "demo", "--json")
    data = json.loads(out)
    assert code == 1 and data["needs_commands"] is True and data["checked_for"] == {"project": "demo"}
    assert data["basis"] == "Checked for demo's settings: the check-writer is off, so every task needs a command."
    demo("full")
    code, out, _ = run_cmd(capsys, "spec", "check", str(f), "--project", "demo")
    assert code == 0 and "Checked for demo's settings: the check-writer is on." in out


def test_the_specs_own_preset_line_decides_last(capsys, tmp_path):
    for preset in ("quick", "simple"):
        f = write(tmp_path, preset_line=f"Preset: {preset}")
        code, out, _ = run_cmd(capsys, "spec", "check", str(f), "--json")
        data = json.loads(out)
        assert code == 1 and data["ok"] is False and data["needs_commands"] is True
        assert data["checked_for"] == {"spec_preset": preset}
        assert data["basis"] == f"Checked for the {preset} preset: the check-writer is off, so every task needs a command."
        assert data["problems"][0].startswith(f"Line {heading_line(f)}: task 1 has no")
    code, out, _ = run_cmd(capsys, "spec", "check", str(write(tmp_path, preset_line="Preset: full")))
    assert code == 0 and "the check-writer is on" in out


def test_no_preset_anywhere_keeps_the_old_check(capsys, tmp_path):
    code, out, _ = run_cmd(capsys, "spec", "check", str(write(tmp_path)), "--json")
    data = json.loads(out)
    assert code == 0 and data["ok"] is True and data["needs_commands"] is False and data["problems"] == []
    code, out, _ = run_cmd(capsys, "spec", "check", str(write(tmp_path)))
    assert code == 0 and out.strip() == "Spec is valid."


def test_a_command_bullet_passes_with_the_check_writer_off(capsys, tmp_path):
    code, out, _ = run_cmd(capsys, "spec", "check", str(write(tmp_path, COMMANDS)), "--preset", "quick")
    assert code == 0 and "Spec is valid." in out


def test_unknown_preset_and_project_are_refused(capsys, tmp_path):
    f = write(tmp_path)
    code, _, err = run_cmd(capsys, "spec", "check", str(f), "--preset", "fast")
    assert code == 1 and "'fast' is not a preset" in err and "Traceback" not in err
    code, _, err = run_cmd(capsys, "spec", "check", str(f), "--project", "ghost")
    assert code == 1 and "Traceback" not in err


# ---- run start: refused before the run is queued ----

@pytest.fixture
def adapters_for_ops(monkeypatch, adapters):
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    return adapters


def test_quick_start_with_a_prose_only_spec_is_refused_before_queueing(tmp_path, demo, adapters_for_ops):
    demo("quick")
    f = write(tmp_path)
    with pytest.raises(common.OpsError) as err:
        ops_runs.start("demo", f)
    assert f"Line {heading_line(f)}: task 1 has no 'Done when' item Phoenix can run." in str(err.value)
    assert not paths.runs("demo").exists() or not any(paths.runs("demo").iterdir())


def test_start_with_the_check_writer_on_or_a_command_is_queued(tmp_path, demo, adapters_for_ops):
    demo("quick")
    assert ops_runs.start("demo", write(tmp_path), {"preset": "full"})["status"] == "queued"
    assert ops_runs.start("demo", write(tmp_path, COMMANDS))["status"] == "queued"


CHAIN = "# Steps\nProject: demo\n" + "".join(
    f"## Task {n}: Step {n}\nDo step {n}.\nDone when:\n- `true`\n" for n in range(1, 7))


def test_cli_shows_chain_warnings_after_valid_and_exits_0(capsys, tmp_path):
    f = tmp_path / "spec.md"
    f.write_text(CHAIN)
    code, out, _ = run_cmd(capsys, "spec", "check", str(f))
    assert code == 0
    assert out.index("Spec is valid.") < out.index("Worth a look:")
    assert "- Tasks 1 -> 2 -> 3 -> 4 -> 5 -> 6 depend on each other in one line: if task 1 fails, 5 tasks" in out


def test_cli_json_has_warnings(capsys, tmp_path):
    f = tmp_path / "spec.md"
    f.write_text(CHAIN)
    code, out, _ = run_cmd(capsys, "spec", "check", str(f), "--json")
    data = json.loads(out)
    assert code == 0 and data["ok"] is True and len(data["warnings"]) == 1


def test_cli_without_warnings_has_no_worth_a_look(capsys, tmp_path):
    f = tmp_path / "spec.md"
    f.write_text(CHAIN.replace("Do step 3.", "Depends on: none\nDo step 3.").replace("Do step 5.", "Depends on: none\nDo step 5."))
    code, out, _ = run_cmd(capsys, "spec", "check", str(f), "--json")
    assert code == 0 and json.loads(out)["warnings"] == []
    code, out, _ = run_cmd(capsys, "spec", "check", str(f))
    assert "Worth a look" not in out


def test_cli_shows_warnings_after_the_problems(capsys, tmp_path):
    f = tmp_path / "spec.md"
    f.write_text(CHAIN.replace("- `true`\n## Task 2", "- short\n## Task 2"))
    code, out, _ = run_cmd(capsys, "spec", "check", str(f))
    assert code == 1 and "Worth a look:" in out and "Spec is valid." not in out
