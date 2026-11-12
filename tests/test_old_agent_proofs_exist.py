"""Every proof in the old-agent checklist named with ::test_name is a real test function in that file."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKLIST = ROOT / "agentkit/docs/old-agent-checklist.md"


def test_named_proofs_exist_as_functions():
    seen = 0
    for path, name in re.findall(r"`?([\w./-]+\.py)::(\w+)`?", CHECKLIST.read_text()):
        assert re.search(rf"^(async )?def {name}\(", (ROOT / path).read_text(), re.M), (path, name)
        seen += 1
    assert seen
