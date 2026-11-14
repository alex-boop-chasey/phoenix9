"""Format of the old-agent checklist: six cells per row, honest status, real proof files, no job left out."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKLIST = ROOT / "agentkit/docs/old-agent-checklist.md"
HEAD = ["#", "Old-agent job", "Where it lives today", "New-agent equivalent", "Shown working by", "Status"]


def rows() -> list[list[str]]:
    """The table rows of the checklist, each a list of six stripped cells."""
    out = []
    for line in CHECKLIST.read_text().splitlines():
        if line.startswith("|") and not set(line) <= set("|- "):
            out.append([c.strip() for c in line.strip().strip("|").split("|")])
    assert out[0] == HEAD
    return out[1:]


def proof_files(cell: str) -> list[str]:
    """The test file paths named in a proof cell (without ::test_name or backticks)."""
    return [p.split("::")[0] for p in re.findall(r"[\w./-]+\.py(?:::\w+)?", cell)]


def test_every_row_has_six_cells_and_a_known_status():
    found = rows()
    assert found
    for row in found:
        assert len(row) == 6 and all(row), row
        assert row[5] in ("working", "gap"), row
    assert [int(r[0]) for r in found] == list(range(1, len(found) + 1))


def test_working_rows_name_a_proof_that_exists():
    for row in rows():
        names = proof_files(row[4])
        if row[5] == "working":
            assert names, row
        for name in names:
            assert (ROOT / name.strip("`")).is_file(), (row[0], name)


def test_the_checklist_mentions_every_route_command_and_rules_heading():
    """Before the retirement, every old route, command and rules heading is a row; after it, the old sources are gone."""
    import json
    if json.loads((ROOT / "tests/data/retirement.json").read_text())["done"]:
        api = (ROOT / "docs/api.md").read_text()
        assert not re.findall(r"`(/api/agent/[a-z]+)", api)
        assert not (ROOT / "phoenix9/cli/agent.py").exists() and not (ROOT / "deploy/agent/agent-rules.md").exists()
        return
    text = CHECKLIST.read_text()
    api = (ROOT / "docs/api.md").read_text()
    for route in set(re.findall(r"`(/api/agent/[a-z]+)", api)):
        assert route in text, route
    cli = (ROOT / "phoenix9/cli/agent.py").read_text()
    for sub in re.findall(r'cmds\.add_parser\("(\w+)"', cli):
        assert f"phoenix agent {sub}" in text, sub
    rules = (ROOT / "deploy/agent/agent-rules.md").read_text()
    for heading in re.findall(r"^## (.+)$", rules, re.M):
        assert f"## {heading}" in text or f"`## {heading}`" in text or heading in text, heading
