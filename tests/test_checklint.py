"""checklint: checks must set every env variable they read; Red check refuses checks that crash in their own setup."""
from pathlib import Path

from phoenix9 import checklint

DATA = Path(__file__).parent / "data" / "checks"
# agent build 1b, task 6: the locked check that read PHOENIX_PROJECTS / PHOENIX_HOME and never set them
REAL = (DATA / "1b-task-6-unset-env.sh").read_text()
CHECK = "tests/phoenix/r/task-6/1-chat-open.sh"


def py_check(setup: str) -> str:
    return f"""#!/bin/sh
set -u
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
{setup}
cat >"$TMP/check.py" <<'PY'
import os
from pathlib import Path
root = Path(os.environ["PHOENIX_PROJECTS"])
home = os.environ.get("PHOENIX_HOME")
name = f"{{os.getenv('USER_NAME')}}-$NOT_SHELL"
PY
python3 -I "$TMP/check.py" || {{ echo "FAIL: $WHY"; exit 1; }}
"""


# ---------------------------------------------------------------- reads without a set
def test_real_1b_check_is_refused():
    assert checklint.unset_env(CHECK, REAL) == ["PHOENIX_PROJECTS", "PHOENIX_HOME"]


def test_check_reading_env_without_export_is_refused():
    text = py_check('WHY="behaviour"')
    assert checklint.unset_env(CHECK, text) == ["PHOENIX_PROJECTS", "PHOENIX_HOME", "USER_NAME"]


def test_same_check_with_export_passes():
    text = py_check('WHY="behaviour"\nexport PHOENIX_HOME="$TMP/home" PHOENIX_PROJECTS="$TMP/projects"\n'
                    'export USER_NAME=tester')
    assert checklint.unset_env(CHECK, text) == []


def test_real_1b_check_with_export_passes():
    fixed = REAL.replace('TMP="$(mktemp -d)"\n',
                         'TMP="$(mktemp -d)"\nmkdir -p "$TMP/home" "$TMP/projects"\n'
                         'export PHOENIX_HOME="$TMP/home" PHOENIX_PROJECTS="$TMP/projects"\n')
    assert checklint.unset_env(CHECK, fixed) == []


def test_shell_reads():
    text = "#!/bin/sh\n# $IN_COMMENT\necho \"$A ${B} ${C:-x} ${D-y} ${E:=z}\" '$SINGLE' \\$ESCAPED $1 $? $@\n" \
           "awk '{print $NF}' f\nfor F in a b; do echo \"$F\"; done\nread -r LINE; echo \"$LINE ${#G}\"\n" \
           "ls | while IFS= read -r -d '' f; do echo \"$f\"; done\n"
    assert checklint.unset_env("x.sh", text) == ["A", "B", "G"]


def test_unquoted_heredoc_body_is_shell_quoted_is_not():
    text = "cat <<EOF\nit's $OPEN\nEOF\ncat <<'EOF'\n$QUOTED\nEOF\n"
    assert checklint.unset_env("x.sh", text) == ["OPEN"]


def test_allowlist_container_env_keys_and_proxy():
    text = "echo $PATH $HOME $TMPDIR $PWD $CI $npm_config_store_dir $STRIPE_KEY $PHOENIX_PROXY_STRIPE\n"
    allowed = checklint.container_env_names() | {"STRIPE_KEY"}
    assert "CI" in allowed and not any(n.startswith("CLAUDE_") for n in allowed)
    assert checklint.unset_env("x.sh", text, allowed) == []
    assert checklint.unset_env("x.sh", text) == ["CI", "npm_config_store_dir", "STRIPE_KEY"]


def test_python_check_file_sets_and_defaults():
    text = ('import os\nos.environ["A"] = "1"\nos.environ.setdefault("B", "2")\nos.environ["A"]\n'
            'os.environ.get("B")\nos.environ.get("C", "")\nos.getenv("D", "x")\n'
            'def test_x(monkeypatch):\n    monkeypatch.setenv("E", "1")\n    os.environ["E"]\n'
            'os.environ["F"] == "x"\n')
    assert checklint.unset_env("test_1.py", text) == ["F"]


def test_python_file_dollar_is_not_shell():
    assert checklint.unset_env("test_1.py", 'x = "$NOT_SHELL"\n') == []


# ---------------------------------------------------------------- red check: broken or proper red
REAL_RED = """Traceback (most recent call last):
  File "/tmp/tmp.8NE2nprqOu/check.py", line 10, in <module>
    root = Path(os.environ["PHOENIX_PROJECTS"])
                ~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^
  File "<frozen os>", line 717, in __getitem__
KeyError: '[secret]'
FAIL: chat open behaviour
"""


def test_keyerror_in_check_file_is_broken():
    why = checklint.broken_reason(REAL_RED, [CHECK])
    assert why and "KeyError" in why and "/tmp/tmp.8NE2nprqOu/check.py line 10" in why


def test_normal_assertion_is_a_proper_red():
    out = """Traceback (most recent call last):
  File "/tmp/tmp.X/check.py", line 40, in <module>
    assert data["state"] == "live", data
AssertionError: {'state': 'off'}
FAIL: chat open behaviour
"""
    assert checklint.broken_reason(out, [CHECK]) is None
    assert checklint.broken_reason("FAIL: tests/test_chat_cli.py missing\n", [CHECK]) is None


def test_crash_in_project_code_is_a_proper_red():
    out = """Traceback (most recent call last):
  File "/tmp/tmp.X/check.py", line 3, in <module>
    main()
  File "/workspace/phoenix9/chat.py", line 9, in main
    x = undefined_name
NameError: name 'undefined_name' is not defined
"""
    assert checklint.broken_reason(out, [CHECK]) is None


def test_other_own_crashes():
    def tb(src, err, path="<stdin>"):
        return f'Traceback (most recent call last):\n  File "{path}", line 2, in <module>\n    {src}\n{err}\n'
    assert "NameError" in checklint.broken_reason(tb("x", "NameError: name 'x' is not defined"), [CHECK])
    assert "ImportError" in checklint.broken_reason(
        tb("from os import nope", "ImportError: cannot import name 'nope' from 'os' (/usr/lib/python3.12/os.py)"), [CHECK])
    assert checklint.broken_reason(tb("import json.nope", "ModuleNotFoundError: No module named 'json.nope'"), [CHECK])
    # the project's own module or a package the builder adds: not built yet is a proper red
    assert checklint.broken_reason(tb("import myapp", "ModuleNotFoundError: No module named 'myapp'"), [CHECK]) is None
    assert checklint.broken_reason(tb("open(p)", "FileNotFoundError: [Errno 2] No such file or directory: '/tmp/x/a'"), [CHECK])
    assert checklint.broken_reason(tb("open(p)", "FileNotFoundError: [Errno 2] No such file or directory: 'out.txt'"), [CHECK]) is None
    assert checklint.broken_reason(tb("d['k']", "KeyError: 'k'"), [CHECK]) is None       # data the code returned
    syntax = '  File "/tmp/t/check.py", line 3\n    x = (\n        ^\nSyntaxError: \'(\' was never closed\n'
    assert "SyntaxError" in checklint.broken_reason(syntax, [CHECK])
    own_py = f'Traceback (most recent call last):\n  File "/workspace/{CHECK[:-3]}.py", line 2, in <module>\n    x\nNameError: x\n'
    assert checklint.broken_reason(own_py, [CHECK[:-3] + ".py"])


def test_shell_crashes():
    assert "PHOENIX_HOME is not set" in checklint.broken_reason(f"{CHECK}: 7: PHOENIX_HOME: parameter not set\n", [CHECK])
    assert "PHOENIX_HOME" in checklint.broken_reason(f"/workspace/{CHECK}: line 7: PHOENIX_HOME: unbound variable\n", [CHECK])
    assert "jqq" in checklint.broken_reason(f"{CHECK}: 9: jqq: not found\n", [CHECK])
    assert "jqq" in checklint.broken_reason(f"/workspace/{CHECK}: line 9: jqq: command not found\n", [CHECK])
    # someone else's message that only looks similar
    assert checklint.broken_reason("FAIL: key: not found\n", [CHECK]) is None
