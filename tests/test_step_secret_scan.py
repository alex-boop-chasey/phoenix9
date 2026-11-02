"""The Secret scan step: values and key shapes must never land in the code (real step, temp git repo)."""
import base64

import pytest

from helpers.stepunit import load, make_ctx, make_work, write
from phoenix9 import paths

mod = load("secret-scan")
VALUE = "Zq7-fake-test-value-1234"   # made up for tests


@pytest.fixture
def work(tmp_path):
    return make_work(tmp_path)


@pytest.fixture
def secret_file():
    paths.secrets().mkdir(parents=True, exist_ok=True)
    (paths.secrets() / "svc.env").write_text(f"API_TOKEN={VALUE}\nSHORT=abc\n")


def scan(tmp_path, adapters, work):
    return mod.run(make_ctx(tmp_path, adapters, work, "secret-scan"))


def test_finds_project_secret_raw_and_base64(tmp_path, adapters, work, secret_file):
    enc = base64.b64encode(VALUE.encode()).decode()
    write(work, {"a.py": f'x = 1\nTOKEN = "{VALUE}"\n', "b.py": f'B = "{enc}"\n'})
    result = scan(tmp_path, adapters, work)
    text = "\n".join(result.reasons)
    assert result.status == "fail" and "A secret was written into a.py (line 2)" in text
    assert "b.py (line 1)" in text


def test_finds_generic_private_key(tmp_path, adapters, work):
    write(work, {"k.pem": "-----BEGIN RSA PRIVATE KEY-----\nabc\n"})
    result = scan(tmp_path, adapters, work)
    assert result.status == "fail" and "k.pem (line 1)" in result.reasons[0]


@pytest.mark.parametrize("line", ["t = 'ghp_" + "a" * 30 + "'", "k = 'sk-ant-" + "b" * 20 + "'"])
def test_finds_token_shapes(tmp_path, adapters, work, line):
    write(work, {"t.py": line + "\n"})
    assert scan(tmp_path, adapters, work).status == "fail"


def test_reason_never_contains_value(tmp_path, adapters, work, secret_file):
    enc = base64.b64encode(VALUE.encode()).decode()
    write(work, {"a.py": f'T = "{VALUE}"\nU = "{enc}"\nK = "ghp_{"c" * 30}"\n'})
    result = scan(tmp_path, adapters, work)
    text = "\n".join(result.reasons)
    assert result.status == "fail"
    assert VALUE not in text and enc not in text and "c" * 30 not in text


def test_clean_diff_passes(tmp_path, adapters, work, secret_file):
    write(work, {"a.py": "x = 1\n"})
    assert scan(tmp_path, adapters, work).status == "pass"


def test_non_secret_key_value_allowed(tmp_path, adapters, work, secret_file):
    write(work, {"cfg.py": 'SHORT = "abc"\nAPI_TOKEN = os.environ["API_TOKEN"]\n', ".env.example": f"API_TOKEN={VALUE}\n"})
    assert scan(tmp_path, adapters, work).status == "pass"


def test_only_added_lines_count(tmp_path, adapters, work, secret_file):
    write(work, {"old.py": f'T = "{VALUE}"\n'})
    from helpers.stepunit import git
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "older")
    ctx = make_ctx(tmp_path, adapters, work, "secret-scan")
    assert mod.run(ctx).status == "pass"
