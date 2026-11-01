"""check-browser.sh must use the demo server and never touch the real server folders."""
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "check-browser.sh"


def test_script_never_mentions_real_paths():
    """The script text has no /srv/projects or /var/lib/phoenix9."""
    text = SCRIPT.read_text()
    assert "/srv/projects" not in text
    assert "/var/lib/phoenix9" not in text


def test_script_uses_demo_server_not_real_api():
    """The API it starts is the demo server on fake adapters, never `phoenix api serve`."""
    text = SCRIPT.read_text()
    assert "tests/demo_server.py" in text
    assert "tests/seed_demo.py" in text
    assert "api serve" not in text


def test_script_fails_plainly_without_browser(tmp_path):
    """With no browser folder the script exits 1 and says where the browser should be."""
    env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=str(tmp_path))
    done = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 1
    assert f"Playwright's browser is not installed at {tmp_path}" in done.stdout
