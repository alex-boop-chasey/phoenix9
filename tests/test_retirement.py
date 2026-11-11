"""The retirement gate: nothing outside the retired list is removed, project chats stay, and the old agent goes only when ready."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAN = json.loads((ROOT / "tests/data/retirement.json").read_text())
KEEP = [p for p in (ROOT / "tests/data/retirement-keep.txt").read_text().splitlines() if p]
CHECKLIST = ROOT / "agentkit/docs/old-agent-checklist.md"
PROJECT_CHAT = ["phoenix9/projectchat.py", "phoenix9/chat.py", "phoenix9/chatlink.py", "deploy/claude-rc-chat@.service",
                "tests/test_projectchat.py", "tests/test_chat_cli.py", "tests/test_chatlink.py"]


def is_retired(path: str) -> bool:
    """True when path is one of the retired files or inside a retired folder."""
    return any(path == r or (r.endswith("/") and path.startswith(r)) for r in PLAN["retire"])


def checklist_rows() -> list[list[str]]:
    """The table rows of the old-agent checklist (six cells each, header and divider left out)."""
    out = []
    for line in CHECKLIST.read_text().splitlines():
        if line.startswith("|") and not set(line) <= set("|- "):
            out.append([c.strip() for c in line.strip().strip("|").split("|")])
    return out[1:]


def test_every_kept_file_still_exists():
    missing = [p for p in KEEP if not (ROOT / p).exists()]
    assert not missing, "removed but not on the retire list: %s" % missing


def test_keep_list_and_retire_list_do_not_overlap():
    assert not [p for p in KEEP if is_retired(p)]
    assert not [p for p in PLAN["edits"] if is_retired(p)]
    assert all((ROOT / p).exists() for p in PLAN["edits"])


def test_project_chat_code_is_kept():
    for path in PROJECT_CHAT:
        assert path in KEEP and not is_retired(path), path
    chat_buttons = [p for p in KEEP if p.startswith("web/src/") and "Chat" in Path(p).name]
    assert chat_buttons, "the web project Chat button code must be on the keep list"


def test_when_done_every_retired_path_is_gone():
    if not PLAN["done"]:
        return
    left = [p for p in PLAN["retire"] if (ROOT / p).exists()]
    assert not left, left


def test_ready_every_checklist_row_is_working_with_its_proof():
    rows = checklist_rows()
    assert rows
    gaps = [r[0] for r in rows if r[5] != "working"]
    assert not gaps, "old-agent jobs not covered yet (rows %s): do not retire the old agent" % ", ".join(gaps)
    for row in rows:
        for name in re.findall(r"[\w./-]+\.py", row[4]):
            assert (ROOT / name).is_file(), (row[0], name)
