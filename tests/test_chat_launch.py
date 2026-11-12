"""deploy/chat-launch.sh run with bash against a temp projects folder and a fake `claude` that records its arguments."""
import os
import signal
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "chat-launch.sh"
ID = "cse_01AbCdEf-123_x"
CREATE = ["remote-control", "--name", "alpha", "--spawn", "same-dir", "--capacity", "3",
          "--create-session-in-dir", "--permission-mode", "bypassPermissions"]
REATTACH = ["remote-control", "--session-id", ID, "--permission-mode", "bypassPermissions"]

# The fake claude: appends one line (its arguments) per call to calls.txt; exits with the first line of
# exit-codes.txt (removing it), or 0. With `hang` as the code it says "ready" and waits to be stopped.
FAKE = """#!/usr/bin/env bash
dir="$(dirname "$0")"
echo "$PWD|$*" >> "$dir/calls.txt"
code="$(head -n 1 "$dir/exit-codes.txt" 2>/dev/null)"
sed -i 1d "$dir/exit-codes.txt" 2>/dev/null
if [ "$code" = hang ]; then
    trap 'echo stopped >> "$dir/calls.txt"; kill $SLEEPER; exit 143' TERM
    sleep 1000 >/dev/null 2>&1 &
    SLEEPER=$!
    echo ready
    wait
fi
exit "${code:-0}"
"""


@pytest.fixture
def box(tmp_path):
    """A projects folder with project `alpha` and a fake claude in tmp/bin."""
    projects = tmp_path / "projects"
    (projects / "alpha" / ".phoenix").mkdir(parents=True)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "claude"
    fake.write_text(FAKE)
    fake.chmod(0o755)
    env = {**os.environ, "PHOENIX_PROJECTS": str(projects), "PHOENIX_CLAUDE_BIN": str(fake)}
    return {"projects": projects, "bin": bindir, "env": env, "doc": projects / "alpha" / ".phoenix" / "chat.md"}


def write_doc(box, conv_id):
    """A chat document like projectchat writes, holding this conversation id."""
    box["doc"].write_text(f"# Chat: alpha\n\nProject: alpha\nDesktop app link: claude://x\n"
                          f"Web link: https://claude.ai/code/{conv_id}\nConversation id: {conv_id}\n"
                          f"Local session id: 1234\nCreated: 2026-11-01T10:00:00Z\n"
                          f"Last active: 2026-11-01T10:00:00Z\n")


def exits(box, *codes):
    """Tell the fake claude how to end on each call, in order."""
    (box["bin"] / "exit-codes.txt").write_text("".join(f"{c}\n" for c in codes))


def run(box, project="alpha"):
    """Run the launcher to the end."""
    return subprocess.run(["bash", str(SCRIPT), project], env=box["env"], capture_output=True, text=True)


def calls(box):
    """The fake claude's calls as (working folder, argument list)."""
    path = box["bin"] / "calls.txt"
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        cwd, _, args = line.partition("|")
        out.append((cwd, args.split() if args else []) if "|" in line else (line, None))
    return out


def test_syntax_and_executable():
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0
    assert SCRIPT.stat().st_mode & 0o111


def test_saved_id_reattaches_the_same_conversation(box):
    write_doc(box, ID)
    p = run(box)
    assert p.returncode == 0, p.stderr
    assert calls(box) == [(str(box["projects"] / "alpha"), REATTACH)]
    assert box["doc"].exists()


def test_no_doc_creates_a_conversation(box):
    p = run(box)
    assert p.returncode == 0, p.stderr
    assert calls(box) == [(str(box["projects"] / "alpha"), CREATE)]


@pytest.mark.parametrize("bad", ["", "has space", "semi;colon", "x" * 101, "$(touch pwned)"])
def test_bad_id_creates_a_conversation(box, bad):
    write_doc(box, bad)
    p = run(box)
    assert p.returncode == 0, p.stderr
    assert [a for _, a in calls(box)] == [CREATE]
    assert not (box["projects"] / "alpha" / "pwned").exists()


def test_quick_failure_moves_the_doc_and_creates_a_new_one(box):
    write_doc(box, ID)
    exits(box, 1, 0)
    p = run(box)
    assert p.returncode == 0, p.stderr
    assert [a for _, a in calls(box)] == [REATTACH, CREATE]
    assert not box["doc"].exists()
    assert f"Conversation id: {ID}" in (box["doc"].parent / "chat.old.md").read_text()
    assert "could not be re-attached" in p.stdout


def test_old_doc_is_overwritten(box):
    (box["doc"].parent / "chat.old.md").write_text("older\n")
    write_doc(box, ID)
    exits(box, 1, 0)
    assert run(box).returncode == 0
    assert "older" not in (box["doc"].parent / "chat.old.md").read_text()


def test_create_exit_code_is_passed_on(box):
    exits(box, 3)
    assert run(box).returncode == 3


@pytest.mark.parametrize("name", ["", "-rf", ".hidden", "../alpha", "a/b", "a b", "missing"])
def test_bad_project_refused(box, name):
    p = run(box, name)
    assert p.returncode == 2
    assert len(p.stderr.strip().splitlines()) == 1
    assert calls(box) == []


def test_stop_signal_reaches_claude_and_never_creates(box):
    write_doc(box, ID)
    exits(box, "hang", 0)
    p = subprocess.Popen(["bash", str(SCRIPT), "alpha"], env=box["env"], stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "ready"
    p.send_signal(signal.SIGTERM)
    p.wait()
    p.stdout.close()
    assert p.returncode != 0
    got = calls(box)
    assert [a for _, a in got] == [REATTACH, None] and got[1][0] == "stopped"
    assert box["doc"].exists()
