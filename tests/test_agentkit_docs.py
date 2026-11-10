"""Checks that the new agent's docs show no dollar figures."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOLLAR = re.compile(r"\$\s?\d|\d\s?(?:USD|dollars?)\b|\bUSD\s?\d", re.I)


def _architecture_section() -> str:
    """Return the architecture section about the new agent."""
    text = (ROOT / "docs/architecture.md").read_text()
    start = text.index("## 8.7 The new agent")
    end = text.index("\n## ", start + 1)
    return text[start:end]


def test_try_it_exists_and_is_numbered():
    text = (ROOT / "agentkit/docs/try-it.md").read_text()
    assert len(re.findall(r"^\d+\. ", text, re.M)) >= 7


def test_what_to_click_mentions_key_card_and_alex_only_delete():
    """The merge-request list exists and covers the masked key card and the Alex-only delete."""
    text = (ROOT / "agentkit/docs/what-to-click.md").read_text().lower()
    assert "masked key card" in text
    assert "delete" in text and "alone" in text
    assert not DOLLAR.search(text)


def test_no_dollar_figures_in_docs():
    docs = {
        "try-it.md": (ROOT / "agentkit/docs/try-it.md").read_text(),
        "agentkit/README.md": (ROOT / "agentkit/README.md").read_text(),
        "deploy/agentkit/README.md": (ROOT / "deploy/agentkit/README.md").read_text(),
        "architecture section": _architecture_section(),
    }
    for name, text in docs.items():
        assert not DOLLAR.search(text), f"dollar figure in {name}"
