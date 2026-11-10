"""The committed controls.json matches the controls registry."""
import json
import re

from phoenix9 import controlsgen
from phoenix9.ops.controls import CONTROLS


def committed() -> list:
    """The committed description file."""
    return json.loads(controlsgen.PATH.read_text())


def test_file_matches_registry():
    assert committed() == json.loads(json.dumps(controlsgen.describe())), \
        "controls.json is stale: run `phoenix docs generate`"


def test_every_entry_and_nothing_else():
    assert [e["name"] for e in committed()] == sorted(c.name for c in CONTROLS)


def test_alex_only_entries_are_marked():
    by_name = {e["name"]: e for e in committed()}
    for name in ("project-delete", "project-delete-repo"):
        assert by_name[name]["agent"] == "alex-only" and by_name[name]["risk"] == "alex-only"


def test_no_dollar_amounts():
    for e in committed():
        text = e["description"] + " ".join(i["description"] for i in e["inputs"])
        assert not re.search(r"\$\s*\d|\bdollars?\b|\bUSD\b", text, re.I), e["name"]


def test_every_description_is_filled():
    assert all(e["description"] for e in committed())


def test_write_uses_given_path(tmp_path):
    out = controlsgen.write(tmp_path / "x" / "c.json")
    assert json.loads(out.read_text()) == json.loads(json.dumps(controlsgen.describe()))
