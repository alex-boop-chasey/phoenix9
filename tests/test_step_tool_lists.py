"""The AI steps name their tools explicitly, and those lists reach Claude's command line."""
import tomllib
from pathlib import Path

import pytest

from phoenix9 import claude

ROOT = Path(__file__).resolve().parent.parent
NAMES = [name for name, _label, _why in claude.SUPPORTED_TOOLS]
STEPS = ["builder", "check-writer", "reviewer", "planner"]


def ai_block(step: str) -> dict:
    """The default ai block of a library step."""
    return tomllib.loads((ROOT / "steps" / step / "step.toml").read_text())["ai"]


@pytest.mark.parametrize("step", STEPS)
def test_tools_are_listed_and_supported(step):
    ai = ai_block(step)
    assert ai["tools"], f"{step} must list its tools"
    assert set(ai["tools"]) <= set(NAMES)
    assert set(ai["tools_denied"]) <= set(NAMES)
    assert not set(ai["tools"]) & set(ai["tools_denied"])


def test_builder_lists_every_tool():
    ai = ai_block("builder")
    assert sorted(ai["tools"]) == sorted(NAMES)
    assert ai["tools_denied"] == []


@pytest.mark.parametrize("step", ["check-writer", "reviewer"])
def test_check_writer_and_reviewer_do_not_browse(step):
    denied = ai_block(step)["tools_denied"]
    assert "WebFetch" in denied and "WebSearch" in denied


def test_check_writer_tools():
    ai = ai_block("check-writer")
    assert ai["tools"] == ["Read", "Glob", "Grep", "Write", "Edit", "Bash"]


def test_reviewer_does_not_edit_but_writes_its_verdict():
    ai = ai_block("reviewer")
    assert "Edit" in ai["tools_denied"]
    assert "Write" in ai["tools"]
    assert "/out/verdict.json" in (ROOT / "steps" / "reviewer" / "prompt.md").read_text()


@pytest.mark.parametrize("step", STEPS)
def test_build_command_passes_the_lists(step):
    ai = ai_block(step)
    cmd = claude.build_command(ai, "/p.md", "/r")
    i = cmd.index("--allowedTools")
    assert cmd[i + 1] == ",".join(ai["tools"])
    if ai["tools_denied"]:
        j = cmd.index("--disallowedTools")
        assert cmd[j + 1] == ",".join(ai["tools_denied"])
    else:
        assert "--disallowedTools" not in cmd
