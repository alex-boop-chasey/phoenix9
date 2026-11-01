"""deploy/install.sh run with bash against temp folders, a temp origin repo and fake tools."""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "deploy" / "install.sh"
SENTINEL = "SENTINEL-do-not-print-9f3a"


def git(*args, cwd=None):
    """Run git for test setup."""
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                   cwd=cwd, check=True, capture_output=True)


@pytest.fixture(scope="module")
def origin(tmp_path_factory):
    """A bare repo holding the current files, tagged v9.0."""
    base = tmp_path_factory.mktemp("origin")
    work = base / "work"
    work.mkdir()
    files = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=REPO,
                           capture_output=True, text=True, check=True).stdout.split("\0")
    for name in filter(None, files):
        src = REPO / name
        if src.is_file() and not src.is_symlink():
            (work / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, work / name)
    git("init", "-q", "-b", "main", cwd=work)
    git("add", "-A", cwd=work)
    git("commit", "-q", "-m", "release", cwd=work)
    git("tag", "v9.0", cwd=work)
    bare = base / "origin.git"
    git("clone", "-q", "--bare", str(work), str(bare))
    return bare


@pytest.fixture
def box(tmp_path, origin):
    """Temp folders, fake tools and the env for one install run."""
    tools = tmp_path / "tools"
    tools.mkdir()
    log = tmp_path / "systemctl.log"
    (tools / "systemctl").write_text(f'#!/bin/sh\necho "$@" >> {log}\n')
    for name in ("gh", "pnpm"):
        (tools / name).write_text("#!/bin/sh\nexit 0\n")
    for f in tools.iterdir():
        f.chmod(0o755)
    v8 = tmp_path / "v8"
    v8.mkdir()
    (v8 / "claude.env").write_text(f"CLAUDE_CODE_OAUTH_TOKEN={SENTINEL}-claude\n")
    tele = tmp_path / "telegram.env"
    tele.write_text(f"TELEGRAM_TOKEN={SENTINEL}-tele\n")
    (tmp_path / "units").mkdir()
    env = {**os.environ, "PATH": f"{tools}:{os.environ['PATH']}",
           "PHOENIX_INSTALL": str(tmp_path / "opt"), "PHOENIX_HOME": str(tmp_path / "home"),
           "PHOENIX_SYSTEMD_DIR": str(tmp_path / "units"), "PHOENIX_SYSTEMCTL": str(tools / "systemctl"),
           "PHOENIX_BIN_LINK": str(tmp_path / "phoenix-link"), "PHOENIX_INSTALL_ALLOW_NONROOT": "1"}
    env.pop("PHOENIX_API_PORT", None)
    args = ["--tag", "v9.0", "--repo", str(origin), "--v8-config", str(v8),
            "--telegram-env", str(tele), "--skip-checks", "--skip-web"]
    return {"root": tmp_path, "env": env, "args": args, "log": log, "v8": v8, "tele": tele}


def install(box, extra=(), args=None):
    """Run install.sh; return the finished process."""
    return subprocess.run(["bash", str(SCRIPT), *(args or box["args"]), *extra], env=box["env"],
                          capture_output=True, text=True, timeout=120)


def mode(path: Path) -> int:
    """Permission bits of a path."""
    return stat.S_IMODE(path.stat().st_mode)


def test_install_sh_syntax():
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0


def test_fresh_install_layout_and_modes(box):
    p = install(box)
    assert p.returncode == 0, p.stderr
    opt, home = box["root"] / "opt", box["root"] / "home"
    head = subprocess.run(["git", "-C", str(opt), "describe", "--tags", "--exact-match"],
                          capture_output=True, text=True).stdout.strip()
    assert head == "v9.0"
    assert subprocess.run(["git", "-C", str(opt), "symbolic-ref", "-q", "HEAD"]).returncode != 0
    for name in ("config", "secrets", "keys", "runs", "logs", "update"):
        assert (home / name).is_dir()
    assert mode(home / "secrets") == 0o700 and mode(home / "keys") == 0o700
    api_env = (home / "config" / "api.env").read_text()
    assert "PHOENIX_API_PORT=8095" in api_env
    assert "PHOENIX_API_ORIGINS=https://files.rebirthwebdesign.com.au" in api_env


def test_custom_api_port(box):
    assert install(box, ["--api-port", "8090"]).returncode == 0
    assert "PHOENIX_API_PORT=8090" in (box["root"] / "home" / "config" / "api.env").read_text()


def test_secrets_copied_0600_and_never_printed(box):
    p = install(box)
    assert p.returncode == 0
    secrets = box["root"] / "home" / "secrets"
    for dest, src in ((secrets / "claude.env", box["v8"] / "claude.env"), (secrets / "telegram.env", box["tele"])):
        assert mode(dest) == 0o600
        assert dest.read_text() == src.read_text()
    assert SENTINEL not in p.stdout and SENTINEL not in p.stderr


def test_existing_secrets_kept(box):
    secrets = box["root"] / "home" / "secrets"
    secrets.mkdir(parents=True)
    (secrets / "claude.env").write_text("KEEP=me\n")
    assert install(box).returncode == 0
    assert (secrets / "claude.env").read_text() == "KEEP=me\n"
    assert (secrets / "telegram.env").exists()


def test_missing_v8_secret_warns_and_continues(box):
    (box["v8"] / "claude.env").unlink()
    p = install(box)
    assert p.returncode == 0
    assert "claude.env" in p.stderr and "WARNING" in p.stderr
    assert not (box["root"] / "home" / "secrets" / "claude.env").exists()
    assert (box["root"] / "home" / "secrets" / "telegram.env").exists()


def test_units_installed_and_services_enabled(box):
    assert install(box).returncode == 0
    for unit in ("phoenix-api.service", "phoenix-runner.service", "phoenix9-update.service"):
        target = box["root"] / "units" / unit
        assert target.is_file() and not target.is_symlink()
    calls = box["log"].read_text().splitlines()
    assert "daemon-reload" in calls
    assert "enable --now phoenix-runner.service phoenix-api.service" in calls
    assert not any("phoenix9-update" in c for c in calls)


def test_no_start_flag(box):
    assert install(box, ["--no-start"]).returncode == 0
    calls = box["log"].read_text().splitlines()
    assert calls == ["daemon-reload"]
    assert (box["root"] / "units" / "phoenix-api.service").exists()


def test_refuses_when_already_installed(box):
    (box["root"] / "opt").mkdir()
    p = install(box)
    assert p.returncode != 0
    assert "already installed" in p.stderr and "phoenix update" in p.stderr
    assert not (box["root"] / "home").exists()


@pytest.mark.parametrize("tag", ["v9", "v9.01", "9.1", "v10.1", "v9.1;x", ""])
def test_bad_tag_refused(box, tag):
    args = list(box["args"])
    args[args.index("--tag") + 1] = tag
    p = install(box, args=args)
    assert p.returncode != 0 and "--tag" in p.stderr
    assert not (box["root"] / "opt").exists()


def test_bin_link_created(box):
    assert install(box).returncode == 0
    link = box["root"] / "phoenix-link"
    assert link.is_symlink()
    assert os.readlink(link) == str(box["root"] / "opt" / "bin" / "phoenix")
