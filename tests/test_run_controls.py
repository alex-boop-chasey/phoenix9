"""Run controls: the spec's Preset line (B5) and `phoenix run discard` (B1)."""
import json
import subprocess

import pytest

from phoenix9 import atomic, events, paths, state
from phoenix9.__main__ import main
from phoenix9.ops import common
from phoenix9.ops import runs as ops_runs

SPEC = """# Add a hello script
Project: demo
{preset}
## Task 1: Hello
Make a script called hello.py that prints hello.
Done when:
- `python3 hello.py`
"""


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          check=True, capture_output=True, text=True).stdout


@pytest.fixture
def demo(phoenix_env, tmp_path, monkeypatch, adapters):
    """A project called demo (code/ is a git repo) and fake adapters for ops."""
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    folder = phoenix_env["projects"] / "demo"
    (folder / "code").mkdir(parents=True)
    (folder / "CLAUDE.md").write_text("# Demo\n")
    (folder / "phoenix.toml").write_text('preset = "quick"\nprofile = "python-script"\n')
    code = folder / "code"
    git(code, "init", "-q", "-b", "main")
    (code / "README.md").write_text("hi\n")
    git(code, "add", "-A")
    git(code, "commit", "-q", "-m", "first")
    return {"folder": folder, "code": code, "adapters": adapters}


def spec_file(tmp_path, preset_line=""):
    p = tmp_path / "spec.md"
    p.write_text(SPEC.format(preset=preset_line + "\n" if preset_line else ""))
    return p


def run_cmd(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


# ---- B5: the spec's Preset line ----

def test_spec_preset_is_used_when_no_override(demo, tmp_path):
    r = ops_runs.start("demo", spec_file(tmp_path, "Preset: full"))
    assert atomic.read_json(paths.runs("demo") / r["run_id"] / "overrides.json") == {"preset": "full"}


def test_explicit_preset_beats_the_spec(demo, tmp_path):
    r = ops_runs.start("demo", spec_file(tmp_path, "Preset: full"), {"preset": "simple"})
    assert atomic.read_json(paths.runs("demo") / r["run_id"] / "overrides.json") == {"preset": "simple"}


def test_no_preset_line_means_no_override(demo, tmp_path):
    r = ops_runs.start("demo", spec_file(tmp_path))
    assert atomic.read_json(paths.runs("demo") / r["run_id"] / "overrides.json") is None
