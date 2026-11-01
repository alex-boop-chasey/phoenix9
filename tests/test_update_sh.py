"""deploy/update.sh runs a throwaway copy of the INSTALLED package; the unit file starts only on request."""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "deploy" / "update.sh"
UNIT = REPO / "deploy" / "phoenix9-update.service"

FAKE_PYTHON = """#!{python}
import json, os, sys
sys.path.insert(0, os.environ["PYTHONPATH"])
import phoenix9.marker as marker
copy = os.environ["PYTHONPATH"]
json.dump({{"cwd": os.getcwd(), "pythonpath": copy, "argv": sys.argv[1:], "marker": marker.MARK,
           "listing": sorted(os.listdir(os.path.join(copy, "phoenix9")))}}, open({out!r}, "w"))
"""


def package(folder: Path, mark: str) -> None:
    pkg = folder / "phoenix9"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "updater.py").write_text("")
    (pkg / "marker.py").write_text(f"MARK = {mark!r}\n")


def run(tmp_path, install: Path) -> tuple[subprocess.CompletedProcess, Path]:
    out = tmp_path / "seen.json"
    fake = tmp_path / "fake-python"
    fake.write_text(FAKE_PYTHON.format(python=sys.executable, out=str(out)))
    fake.chmod(0o755)
    (tmp_path / "run").mkdir(exist_ok=True)
    env = {**os.environ, "PHOENIX_INSTALL": str(install), "PHOENIX_UPDATER_PYTHON": str(fake),
           "PHOENIX_UPDATER_TMP": str(tmp_path / "run")}
    env.pop("PYTHONPATH", None)
    p = subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=30,
                       cwd=str(tmp_path))
    return p, out


# 10
def test_update_sh_runs_installed_copy(tmp_path):
    install = tmp_path / "opt" / "phoenix9"
    package(install, "installed")
    package(Path(f"{install}-next"), "next")
    p, out = run(tmp_path, install)
    assert p.returncode == 0, p.stderr
    seen = json.loads(out.read_text())
    assert seen["marker"] == "installed"
    assert seen["argv"] == ["-m", "phoenix9.updater", "run-request"]
    copy = Path(seen["pythonpath"])
    assert seen["cwd"] == str(copy) and copy.parent == tmp_path / "run"
    assert copy != install and "-next" not in str(copy)
    assert "marker.py" in seen["listing"]
    assert not copy.exists()                                 # the copy is removed afterwards
    assert list((tmp_path / "run").iterdir()) == []


def test_update_sh_refuses_without_install(tmp_path):
    p, out = run(tmp_path, tmp_path / "opt" / "phoenix9")
    assert p.returncode == 1 and not out.exists()
    assert "not installed" in p.stderr and len(p.stderr.strip().splitlines()) == 1


def test_update_sh_passes_on_the_updater_exit_code_and_cleans_up(tmp_path):
    install = tmp_path / "opt" / "phoenix9"
    package(install, "installed")
    (install / "phoenix9" / "marker.py").write_text("raise SystemExit(3)\n")
    p, _ = run(tmp_path, install)
    assert p.returncode == 3
    assert list((tmp_path / "run").iterdir()) == []


def test_update_sh_is_plain_sh():
    text = SCRIPT.read_text()
    code = [x for x in text.splitlines() if not x.lstrip().startswith("#")]
    assert text.startswith("#!/bin/sh\n") and "set -eu" in code and not any("next" in x for x in code)
    assert os.access(SCRIPT, os.X_OK)


# 11
def test_update_unit_file():
    lines = [x.strip() for x in UNIT.read_text().splitlines() if x.strip() and not x.startswith("#")]
    assert "ExecStart=/opt/phoenix9/deploy/update.sh" in lines
    assert "Type=oneshot" in lines
    assert "Environment=PHOENIX_HOME=/var/lib/phoenix9" in lines
    assert "Environment=PHOENIX_INSTALL=/opt/phoenix9" in lines
    assert "TimeoutStartSec=5h" in lines
    assert "[Install]" not in lines
    assert "Environment=HOME=/root" in lines
    pre = [x for x in lines if x.startswith("ExecStartPre=")]
    assert pre == ["ExecStartPre=-/bin/sh -c 'test -e /opt/phoenix9 || mv /opt/phoenix9-prev /opt/phoenix9'"]
    assert "never symlink" in UNIT.read_text()


def test_unit_pre_start_restores_a_missing_install(tmp_path):
    """Run the ExecStartPre command on a temp layout: install missing + -prev present -> -prev put back;
    install present -> nothing moves."""
    line = next(x for x in UNIT.read_text().splitlines() if x.startswith("ExecStartPre="))
    script = line.split("-c ", 1)[1].strip().strip("'").replace("/opt/", f"{tmp_path}/opt/")
    opt = tmp_path / "opt"
    (opt / "phoenix9-prev").mkdir(parents=True)
    (opt / "phoenix9-prev" / "mark").write_text("prev")
    subprocess.run(["sh", "-c", script], check=True)
    assert (opt / "phoenix9" / "mark").read_text() == "prev" and not (opt / "phoenix9-prev").exists()
    (opt / "phoenix9-prev").mkdir()
    subprocess.run(["sh", "-c", script], check=True)
    assert (opt / "phoenix9-prev").exists() and (opt / "phoenix9" / "mark").read_text() == "prev"


def test_unit_timeout_exceeds_the_updaters_worst_case():
    """systemd must never kill a slow but healthy update: the unit's timeout beats the sum of the
    updater's own limits (checks + web build, idle wait, images, two health checks)."""
    sys.path.insert(0, str(REPO))
    from phoenix9 import updater
    line = next(x.strip() for x in UNIT.read_text().splitlines() if x.strip().startswith("TimeoutStartSec="))
    value = line.split("=", 1)[1]
    unit_s = int(value[:-1]) * {"h": 3600, "m": 60, "s": 1}[value[-1]]
    health = updater.HEALTH_TRIES * updater.DOCTOR_S + (updater.HEALTH_TRIES - 1) * updater.HEALTH_GAP_S
    worst = (2 * updater.PNPM_S + updater.CHECKS_S + updater.IDLE_TIMEOUT_MIN * 60 + updater.IMAGES_S
             + 2 * health)
    assert unit_s > worst, (unit_s, worst)
