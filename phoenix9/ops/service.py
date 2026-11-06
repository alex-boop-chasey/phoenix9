"""Ops for Phoenix's own two services (phoenix-api, phoenix-runner): restart them safely, then check health.

Restarting the runner first holds the harness (the update hold, phoenix9/hold.py) and waits until no run is
mid-task, so no step is cut off; the API restart is immediate. Both go through the host adapter's systemctl
and end with `phoenix doctor --quick` (docs/architecture.md section 15, "Restarting a service").
"""
from phoenix9 import doctor, hold, scrub, updater
from phoenix9.ops import common
from phoenix9.ops.common import OpsError

UNITS = {"api": "phoenix-api", "runner": "phoenix-runner"}
WAIT_MIN = 30          # how long a runner restart waits for running builds to reach a task boundary
POLL_S = 5
API_WAIT_S = 20        # how long to wait for a restarted API to answer /api/health before the doctor runs


def _unit(name: str) -> str:
    if name not in UNITS:
        raise OpsError(f"'{name}' is not a Phoenix service. Use api or runner.")
    return UNITS[name]


def restart_unit(adapters, name: str, no_block: bool = False) -> tuple[bool, str]:
    """Run `systemctl restart` for one Phoenix service through the host adapter; (ok, error text)."""
    args = ["restart", "--no-block", _unit(name)] if no_block else ["restart", _unit(name)]
    rc, _, err = adapters.host.systemctl(*args)
    return rc == 0, scrub.scrub(err.strip())


def _wait_for_boundary(adapters, why: str, wait_min: int, say) -> tuple[bool, str]:
    """Hold the harness and wait (polling) until no run is mid-task; (True, "") or (False, what is still busy)."""
    hold.request_hold(why)
    start = adapters.clock.now()
    told = False
    while True:
        busy, reason = hold.harness_busy()
        if not busy:
            return True, ""
        if adapters.clock.now() - start >= wait_min * 60:
            return False, reason
        if not told:
            say(f"Waiting for running builds to reach a task boundary ({reason}) ...")
            told = True
        adapters.clock.sleep(POLL_S)


def _wait_for_api(adapters) -> None:
    """Give a restarted API a moment to answer /api/health (the doctor then reports what it finds)."""
    url = f"http://127.0.0.1:{doctor.api_port()}/api/health"
    start = adapters.clock.now()
    while adapters.clock.now() - start < API_WAIT_S:
        try:
            if adapters.http.request("GET", url, timeout=3)[0] == 200:
                return
        except Exception:  # noqa: BLE001 - not up yet
            pass
        adapters.clock.sleep(1)


def restart(name: str, who: str = "cli", yes: bool = False, wait_min: int = WAIT_MIN, say=None) -> dict:
    """Restart phoenix-api or phoenix-runner (needs yes); the runner waits for builds to reach a task boundary
    (up to wait_min minutes, then refuses and restarts nothing). Returns {service, restarted, waited, doctor}."""
    unit = _unit(name)
    if not yes:
        raise OpsError(f"This restarts {unit}. Add --yes to go ahead.")
    say = say or (lambda line: None)
    adapters = common.make_adapters()
    waited = False
    if name == "runner":
        with updater._lock(wait_s=0) as got:      # the hold only counts while this lock is held
            if not got:
                raise OpsError("An update of Phoenix is running; it restarts the runner itself. Try again later.")
            try:
                ok, reason = _wait_for_boundary(adapters, f"restart of {unit} asked by {who}", wait_min, say)
                if not ok:
                    raise OpsError(f"The runner was not restarted: a build was still mid-task after {wait_min} "
                                   f"minutes ({reason}). Try again later.")
                waited = True
                done, err = restart_unit(adapters, name)
            finally:
                hold.release_hold()
    else:
        done, err = restart_unit(adapters, name)
        if done:
            _wait_for_api(adapters)
    common.record_command(who, f"service restart {name}")
    if not done:
        raise OpsError(f"systemctl could not restart {unit}: {err or 'no reason given'}. "
                       f"Read `journalctl -u {unit}`.")
    return {"service": unit, "restarted": True, "waited": waited,
            "doctor": doctor.run_checks(adapters, "quick")}


def restart_api_soon(who: str) -> dict:
    """Ask systemd to restart phoenix-api without waiting (used from inside the API, which the restart stops)."""
    adapters = common.make_adapters()
    done, err = restart_unit(adapters, "api", no_block=True)
    common.record_command(who, "service restart api")
    if not done:
        raise OpsError(f"systemctl could not restart phoenix-api: {err or 'no reason given'}.")
    return {"service": UNITS["api"], "restarted": True, "queued": True}
