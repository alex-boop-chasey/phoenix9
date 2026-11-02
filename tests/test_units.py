"""The systemd unit files for the API and the runner."""
from pathlib import Path

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"


def lines(name: str) -> list[str]:
    """Return the non-comment lines of a unit file."""
    return [x for x in (DEPLOY / name).read_text().splitlines() if x and not x.startswith("#")]


def test_units_content():
    api = lines("phoenix-api.service")
    runner = lines("phoenix-runner.service")
    for unit in (api, runner):
        assert "Environment=PHOENIX_HOME=/var/lib/phoenix9" in unit
        assert "Environment=PHOENIX_INSTALL=/opt/phoenix9" in unit
        assert "Environment=PYTHONUNBUFFERED=1" in unit
        assert "WorkingDirectory=/opt/phoenix9" in unit
        assert unit.count("[Install]") == 1 and "WantedBy=multi-user.target" in unit
    assert ("ExecStart=/opt/phoenix9/bin/phoenix api serve --port ${PHOENIX_API_PORT} --host 127.0.0.1"
            in api)
    assert "EnvironmentFile=-/var/lib/phoenix9/config/api.env" in api
    assert "ExecStart=/opt/phoenix9/bin/phoenix runner serve" in runner
    assert "After=docker.service network.target" in runner and "Wants=docker.service" in runner
    assert "KillMode=mixed" in runner and "TimeoutStopSec=60" in runner
    assert "[Install]" not in lines("phoenix9-update.service")


def test_self_project_lists_new_safety_files():
    text = (DEPLOY / "self-project.toml").read_text()
    for name in ("deploy/install.sh", "deploy/phoenix-api.service", "deploy/phoenix-runner.service"):
        assert f'"{name}"' in text
