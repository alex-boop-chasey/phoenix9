"""Checks the Phoenix pack's help topics and the phoenix_help tool that reads them."""
import re

import pytest
from pydantic import ValidationError

from agentkit.packs.phoenix import build_pack
from agentkit.packs.phoenix.controls import load_controls
from agentkit.packs.phoenix.help import HELP_DIR, TOPICS, HelpInputs, help_tool, read_topic
from fake_phoenix import FakePhoenix

LIMIT = 12_000
TOOL_LIKE = re.compile(r"[a-z]+(-[a-z]+)+")


def texts():
    """Each topic's file text, by topic."""
    return {t: (HELP_DIR / f"{t}.md").read_text() for t in TOPICS}


def test_every_topic_file_exists_is_not_empty_and_under_the_limit():
    assert sorted(p.stem for p in HELP_DIR.glob("*.md")) == sorted(TOPICS)
    for topic, text in texts().items():
        assert text.strip(), topic
        assert len(text) < LIMIT, topic


def test_no_old_reply_blocks_server_paths_or_money():
    for topic, text in texts().items():
        for word in ("phoenix-card", "phoenix-choice", "phoenix-confirm", "phoenix-nav", "/srv/"):
            assert word not in text, (topic, word)
        assert not re.search(r"\$\s*\d", text), topic
        assert not re.search(r"\bphoenix [a-z]+ ", text), topic   # no old `phoenix ...` commands


def test_every_tool_like_word_in_backticks_is_a_real_tool():
    pack = build_pack(FakePhoenix().client())
    real = {e["name"] for e in load_controls() if e["agent"] == "tool"}
    real |= {t.name for t in pack.server_tools} | {t.name for t in pack.browser_tools}
    for topic, text in texts().items():
        for word in re.findall(r"`([^`]+)`", text):
            if TOOL_LIKE.fullmatch(word):
                assert word in real, (topic, word)


def test_the_tool_reads_a_topic_and_is_a_read():
    tool = help_tool()
    assert tool.risk == "read"
    assert all(t in tool.description for t in TOPICS)
    got = tool.function(topic="failures")
    assert got == {"topic": "failures", "text": texts()["failures"]}


def test_unknown_topic_refused():
    assert "error" in read_topic("commands") and "text" not in read_topic("cards")
    assert "error" in read_topic("../controls")
    with pytest.raises(ValidationError):
        HelpInputs(topic="commands")
    with pytest.raises(ValidationError):
        HelpInputs(topic="settings", extra="x")


def test_pack_carries_the_tool():
    pack = build_pack(FakePhoenix().client())
    assert {t.name: t.risk for t in pack.server_tools}["phoenix_help"] == "read"
