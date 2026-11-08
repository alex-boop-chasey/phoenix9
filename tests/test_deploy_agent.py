"""Checks the files the agent folder is set up from (deploy/agent)."""
import json
from pathlib import Path

import pytest

AGENT = Path(__file__).resolve().parent.parent / "deploy" / "agent"
HELPERS = ["navigator", "editor", "checker"]


def test_files_exist():
    """All the agent setup files are there."""
    for name in ["agent-rules.md", "settings.json"] + [f"agents/{h}.md" for h in HELPERS]:
        assert (AGENT / name).is_file(), name


def test_no_claude_md_under_agent():
    """No file named CLAUDE.md exists under deploy/agent."""
    assert not [p for p in AGENT.rglob("*") if p.name == "CLAUDE.md"]


def test_settings_json_and_hook():
    """settings.json parses, sets the model and runs the brief on session start."""
    data = json.loads((AGENT / "settings.json").read_text())
    assert data["model"] == "claude-sonnet-5-5"
    hooks = data["hooks"]["SessionStart"][0]["hooks"]
    assert hooks[0]["command"] == "/opt/phoenix9/bin/phoenix agent brief"


def test_rules_mention_key_points():
    """The rulebook names the agent, its folder and the panel marker."""
    text = (AGENT / "agent-rules.md").read_text()
    for needle in ["/srv/projects/home", "Alex (Phoenix panel)", "[Phoenix panel", "notes/NOW.md"]:
        assert needle in text


def front_matter(path):
    """Read simple key: value front matter from a markdown file."""
    lines = path.read_text().splitlines()
    assert lines[0] == "---"
    end = lines.index("---", 1)
    return dict(l.split(": ", 1) for l in lines[1:end])


@pytest.mark.parametrize("helper", HELPERS)
def test_agent_front_matter(helper):
    """Each helper file has a name, description and model."""
    fm = front_matter(AGENT / "agents" / f"{helper}.md")
    assert fm["name"] == helper
    assert fm["description"]
    assert fm["model"]


def test_helper_models_and_tools():
    """Models match the plan; the navigator has only Read and Bash."""
    nav = front_matter(AGENT / "agents" / "navigator.md")
    assert nav["model"] == "claude-haiku-5-5" and nav["tools"] == "Read, Bash"
    assert front_matter(AGENT / "agents" / "editor.md")["model"] == "claude-sonnet-5-5"
    assert front_matter(AGENT / "agents" / "checker.md")["model"] == "claude-haiku-5-5"


def test_rules_teach_reply_blocks():
    """The rulebook shows the four block kinds, the make commands, the panel answers and the page rules."""
    text = (AGENT / "agent-rules.md").read_text()
    for kind in ["phoenix-card", "phoenix-choice", "phoenix-confirm", "phoenix-nav"]:
        assert f"```{kind}" in text
    for needle in ["follow every block with one plain fallback line",
                   "phoenix card", "phoenix choice", "phoenix confirm", "phoenix nav",
                   "[Phoenix panel · choice <id>]", "[Phoenix panel · confirm <id>]",
                   "numbers, labels or free text", "only after the yes",
                   "phoenix ui go", "a nav block otherwise", "Projects query, never your own"]:
        assert needle in text, needle
    assert "phoenix run pause" not in text
