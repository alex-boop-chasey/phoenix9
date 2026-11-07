"""The updater: installs a release tag v9.<n> over the installed copy, health-checks it, rolls back on failure.

It is run by systemd (`phoenix9-update.service` -> the INSTALLED copy's `deploy/update.sh`, which runs a
throwaway copy of this package), never by the new code. Every update is a job that walks a fixed list of
phases, and the phase is saved in HOME/update/status.json before each step that changes something
(docs/architecture.md section 15):

  install:  preparing -> waiting -> swapping -> swapped -> restarted [-> restoring]
  rollback: waiting -> staged -> swapping -> swapped -> restarted [-> staged -> swapping -> ... (swap back)]

Every folder move is written so that running it again finishes a half-done move. If the updater dies
at any point, the next run calls `recover()` first: it finishes the interrupted folder move, then puts
back the version that was installed when the job started (the last one known to work), restarts the
services if anything moved, releases the hold and clears the job.
"""
import contextlib
import fcntl
import json
import os
import re
import shutil
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from phoenix9 import adapters as adapters_mod
from phoenix9 import atomic, events, hold, paths, scrub

TAG_RE = r"^v9\.(0|[1-9][0-9]*)$"
_TAG = re.compile(TAG_RE)
SERVICES = ("phoenix-runner", "phoenix-api")
UNIT = "phoenix9-update.service"
UNIT_FILES = ("phoenix-api.service", "phoenix-runner.service", UNIT)   # the ones install.sh copies
DEFAULT_SYSTEMD_DIR = "/etc/systemd/system"
CRED = ("-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential")   # host gh login
CHECKS_S, PNPM_S, IMAGES_S, DOCTOR_S = 30 * 60, 15 * 60, 60 * 60, 5 * 60
HEALTH_TRIES, HEALTH_GAP_S, POLL_S, LOG_TAIL = 3, 10, 5, 40
IDLE_TIMEOUT_MIN = 120                 # default wait for the harness to reach a task boundary
LOCK_WAIT_S, LOCK_GAP_S = 2.0, 0.05    # ride out a status check's brief shared lock before refusing
NEEDS_PERSON = "recovery needs a person: could not read the installed version"
RESULTS = ("installed", "already-installed", "tests-failed", "images-failed", "harness-busy", "rolled-back",
           "rolled-back-unhealthy", "rolled-back-manual", "refused", "recovered", "needs-person")

# The only phase changes a job may make (None = the job is starting). Ending a job is allowed anywhere.
TRANSITIONS = {
    "install": {None: ("preparing",), "preparing": ("waiting",), "waiting": ("swapping",),
                "swapping": ("swapped",), "swapped": ("restarted",), "restarted": ("restoring",),
                "restoring": ()},
    "rollback": {None: ("waiting",), "waiting": ("staged",), "staged": ("swapping",),
                 "swapping": ("swapped",), "swapped": ("restarted",), "restarted": ("staged",)},
}


class Refused(Exception):
    """The update cannot start; the message says why in plain words."""


class NeedsPerson(Exception):
    """Recovery cannot tell which copy to put back; it moves nothing and leaves the job for a person."""


# ------------------------------------------------------------------ files and folders
def _dir() -> Path:
    return paths.home() / "update"


def folders() -> dict:
    """The installed copy and its three neighbours: -next (candidate), -prev (rollback), -failed."""
    inst = paths.install()
    return {"install": inst, "next": Path(f"{inst}-next"), "prev": Path(f"{inst}-prev"),
            "failed": Path(f"{inst}-failed")}


def _read_status() -> dict:
    try:
        data = atomic.read_json(_dir() / "status.json", {})
    except (OSError, ValueError):
        data = {}
    return data if isinstance(data, dict) else {}


def _write_status(**changes) -> dict:
    """Change keys of status.json (None removes a key). Only called while holding the update lock."""
    st = _read_status()
    for key, value in changes.items():
        if value is None:
            st.pop(key, None)
        else:
            st[key] = value
    atomic.write_json(_dir() / "status.json", st)
    return st


def _refused_file() -> Path:
    """HOME/update/refused.json: a run_request refused because the lock was busy. Written on its own
    (never status.json, which only the lock holder writes); status() shows it as `last` until the
    next locked result replaces it."""
    return _dir() / "refused.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _history_file() -> Path:
    return _dir() / "history.jsonl"


def _append_history(row: dict) -> None:
    """Add one line to HOME/update/history.jsonl (what the Updates tab lists); a write problem is ignored."""
    try:
        _dir().mkdir(parents=True, exist_ok=True)
        with open(_history_file(), "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        pass


def read_history(limit: int = 50) -> list[dict]:
    """The recorded installs and roll-backs, newest first."""
    try:
        lines = _history_file().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows[::-1][:limit]


def _rm(path: Path) -> None:
    """Delete a folder (never follows a symlink)."""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _rename(src: Path, dst: Path) -> None:
    """Rename one folder (one atomic step; tests make it fail to simulate a crash)."""
    os.rename(src, dst)


def systemd_dir() -> Path:
    """Where the unit files are installed (PHOENIX_SYSTEMD_DIR, same default as deploy/install.sh)."""
    return Path(os.environ.get("PHOENIX_SYSTEMD_DIR") or DEFAULT_SYSTEMD_DIR)


def _valid_tag(tag) -> bool:
    return isinstance(tag, str) and _TAG.fullmatch(tag) is not None


def _tag_number(tag: str) -> int:
    return int(tag.split(".")[1])


@contextlib.contextmanager
def _lock(wait_s: float | None = None):
    """Hold HOME/update/lock; yields False when another update holds it. Retries for `wait_s` seconds
    (default LOCK_WAIT_S) in short sleeps, because a status check (hold.lock_held) takes a shared lock
    for a moment and must not make a starting update refuse."""
    path = hold.lock_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = open(path, "a")
    deadline = time.monotonic() + (LOCK_WAIT_S if wait_s is None else wait_s)
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    yield False
                    return
                time.sleep(LOCK_GAP_S)
        try:
            yield True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        fd.close()


def _lock_held() -> bool:
    """True while an update is running (someone holds the lock; read-only probe, see hold.lock_held)."""
    return hold.lock_held()


# ------------------------------------------------------------------ one update's context
class _Update:
    """One updater call: the adapters, the log lines it wrote and the job it drives."""

    def __init__(self, adapters, who: str):
        self.ad = adapters
        self.who = who
        self.lines: list[str] = []
        self.job: dict | None = None

    # ---- log, notify, result
    def log(self, text: str) -> None:
        """One timestamped, scrubbed line in HOME/logs/updater.log."""
        line = scrub.scrub(f"{_now()} {text}".replace("\n", " "))
        self.lines.append(line)
        path = paths.logs() / "updater.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def notify(self, text: str) -> None:
        """Tell Alex (scrubbed)."""
        try:
            self.ad.notify.send(scrub.scrub(text))
        except Exception as err:  # noqa: BLE001 - a lost message must not stop the update
            self.log(f"could not notify: {err}")

    def result(self, ok: bool, result: str, *, tag=None, previous=None, reason: str = "",
               action: str = "install", record: bool = True) -> dict:
        """The plain dict every public function returns; also saved as status.json `last`."""
        reason = scrub.scrub(reason)
        if record:
            _write_status(last={"action": action, "tag": tag, "result": result, "reason": reason,
                                "at": _now(), "who": self.who}, waiting=None)
            _refused_file().unlink(missing_ok=True)
            _append_history({"at": _now(), "action": action, "tag": tag, "result": result, "reason": reason,
                             "who": self.who})
        self.log(f"{action} {tag or ''}: {result}{' - ' + reason if reason else ''}")
        return {"ok": ok, "result": result, "tag": tag, "previous": previous, "reason": reason,
                "log": list(self.lines)}

    # ---- the job (persisted phase)
    def start(self, kind: str, tag: str, frm: dict, to: dict, first: str) -> None:
        """Begin a job and save its first phase."""
        self.job = {"kind": kind, "tag": tag, "who": self.who, "from": frm, "to": to, "phase": None,
                    "reverting": False, "started": _now()}
        self.phase(first)

    def phase(self, name: str, **extra) -> None:
        """Move the job to the next phase (checked against TRANSITIONS) and save it before acting."""
        job = self.job
        if name not in TRANSITIONS[job["kind"]].get(job["phase"], ()):
            raise RuntimeError(f"updater bug: a {job['kind']} job cannot go from {job['phase']} to {name}")
        job.update(phase=name, at=_now(), **extra)
        _write_status(job=job)
        self.log(f"{job['kind']} {job['tag']}: phase {name}")

    def end(self) -> None:
        """Forget the job (it finished, or was recovered)."""
        self.job = None
        _write_status(job=None)

    # ---- outside tools
    def git(self, cwd: Path, *args: str) -> str:
        """One git command through the git adapter (safe flags, safe.directory); raises on failure."""
        return self.ad.git.git(Path(cwd), *args)

    def try_git(self, cwd: Path, *args: str) -> str | None:
        """Like git(), but None when it fails."""
        try:
            return self.git(cwd, *args)
        except Exception:  # noqa: BLE001 - the git adapter raises GitError; the caller decides
            return None

    def version(self, folder: Path) -> dict | None:
        """{tag, commit} checked out in a folder (tag `unknown` when HEAD is not a release), or None."""
        if not (folder / ".git").exists():
            return None
        commit = (self.try_git(folder, "rev-parse", "HEAD") or "").strip()
        if not commit:
            return None
        tags = [t for t in (self.try_git(folder, "tag", "--points-at", "HEAD") or "").split() if _valid_tag(t)]
        return {"tag": max(tags, key=_tag_number) if tags else "unknown", "commit": commit}

    def sync_units(self) -> None:
        """Copy the installed copy's unit files that differ from the ones in the systemd folder, then
        `systemctl daemon-reload`. Called before every restart, so an install brings in the new units and
        a rollback, failed health check or recovery puts the previous copy's units back."""
        source, target = folders()["install"] / "deploy", systemd_dir()
        changed = []
        names = sorted(set(UNIT_FILES) | {f.name for f in source.glob("*.service")}) if source.is_dir() else UNIT_FILES
        for name in names:            # every unit Phoenix ships (e.g. claude-rc-chat@.service), not a fixed list
            try:
                text = (source / name).read_text(encoding="utf-8")
            except OSError:
                continue                 # an old copy without this unit: leave the installed one alone
            try:
                same = (target / name).read_text(encoding="utf-8") == text
            except OSError:
                same = False
            if not same:
                atomic.write_text(target / name, text, 0o644)
                self.log(f"unit file {name} updated in {target} from {source}")
                changed.append(name)
        if changed:
            rc, _, err = self.ad.host.systemctl("daemon-reload")
            self.log(f"systemctl daemon-reload: exit {rc}{' ' + err.strip() if rc and err else ''}")

    def restart(self) -> None:
        """Bring the unit files in line with the installed copy, then restart the Phoenix services
        (systemctl only; nothing is ever stopped by name or pattern)."""
        try:
            self.sync_units()
        except OSError as err:          # a unit problem must not stop the restart (health check decides)
            self.log(f"could not update the unit files: {err}")
        rc, _, err = self.ad.host.systemctl("restart", *SERVICES)
        self.log(f"restart {' '.join(SERVICES)}: exit {rc}{' ' + err.strip() if rc and err else ''}")

    def healthy(self) -> tuple[bool, str]:
        """Run the installed copy's `phoenix doctor --for-update` up to 3 times, 10 s apart."""
        inst = folders()["install"]
        argv = [str(inst / "bin" / "phoenix"), "doctor", "--for-update", "--json"]
        reason = ""
        for n in range(HEALTH_TRIES):
            if n:
                self.ad.clock.sleep(HEALTH_GAP_S)
            rc, out, err = self.ad.host.run(argv, timeout=DOCTOR_S, cwd=str(inst))
            if rc == 0:
                self.log("health check passed")
                return True, ""
            reason = _failing_lines(out, err)
            self.log(f"health check {n + 1} failed: {reason}")
        return False, reason

    def migrate(self) -> None:
        """Run the NEW installed copy's one-time settings migrations (`phoenix settings global migrate`);
        they do nothing once done, and a failure is only a log line (the install stays)."""
        inst = folders()["install"]
        argv = [str(inst / "bin" / "phoenix"), "settings", "global", "migrate", "--json"]
        rc, out, err = self.ad.host.run(argv, timeout=DOCTOR_S, cwd=str(inst))
        self.log("post-install migration done" if rc == 0 else
                 f"post-install migration failed (exit {rc}): {_failing_lines(out, err)}")

    def wait_idle(self, why: str, timeout_min: int) -> tuple[bool, str]:
        """Hold the harness and wait (polling every 5 s) until no run is mid-task; False after the timeout."""
        hold.request_hold(why)
        start = self.ad.clock.now()
        while True:
            busy, reason = hold.harness_busy()
            if not busy:
                _write_status(waiting=None)
                return True, ""
            if self.ad.clock.now() - start >= timeout_min * 60:
                _write_status(waiting=None)
                return False, reason
            _write_status(waiting=scrub.scrub(f"waiting: {reason}"))
            self.ad.clock.sleep(POLL_S)


def _failing_lines(out: str, err: str) -> str:
    """The doctor's failing lines (or its last lines) as one short reason."""
    lines = [x.strip() for x in f"{out}\n{err}".splitlines() if x.strip()]
    bad = [x for x in lines if re.search(r"fail|error|down|not ", x, re.IGNORECASE)]
    return "; ".join((bad or lines[-3:])[:5]) or "the health check failed"


# ------------------------------------------------------------------ folder moves (each one re-runnable)
def _swap_in(d: dict) -> None:
    """Make -next the installed copy and the installed copy -prev. Running it again finishes a half swap."""
    if d["next"].exists() and d["install"].exists():
        if d["prev"].exists():
            _rm(d["prev"])
        _rename(d["install"], d["prev"])
    if d["next"].exists() and not d["install"].exists():
        _rename(d["next"], d["install"])


def _stage(d: dict) -> None:
    """Rollback: move -prev to -next so the same swap can bring it in."""
    if d["prev"].exists() and not d["next"].exists():
        _rename(d["prev"], d["next"])


def _unstage(d: dict) -> None:
    """Undo _stage (a rollback stopped before its swap)."""
    if d["next"].exists() and not d["prev"].exists():
        _rename(d["next"], d["prev"])


def _restore(d: dict) -> None:
    """A failed install: the new copy goes to -failed, -prev comes back. Running it again finishes it."""
    if d["prev"].exists():
        if d["install"].exists():
            if d["failed"].exists():
                _rm(d["failed"])
            _rename(d["install"], d["failed"])
        _rename(d["prev"], d["install"])


# ------------------------------------------------------------------ recovery
def _recover(u: _Update, error: str = "") -> dict | None:
    """Put things right after an updater that died mid-job (lock held by the caller).

    `error` is set when called straight after an error or stop signal in this process: if recovery then
    had to move no folders (the install was never touched), the result is `refused` with the error."""
    d = folders()
    job = _read_status().get("job")
    if not job:
        if not d["install"].exists() and d["prev"].exists():
            _rename(d["prev"], d["install"])
            u.restart()
            hold.release_hold()
            return u.result(False, "recovered", reason="the installed copy was missing; -prev was put back",
                            action="recover")
        if hold.hold_requested():
            hold.release_hold()
            u.log("released a hold left behind by an earlier update")
        return None
    u.job = job
    kind, phase, tag = job["kind"], job["phase"], job["tag"]
    u.log(f"recovering a {kind} {tag} job stopped at phase {phase}")
    try:
        moved = _RECOVERY[kind](u, d, job)
    except NeedsPerson as err:       # nothing moved; the job stays so status shows `interrupted`
        hold.release_hold()
        u.notify(f"Phoenix 9 updater: the {kind} of {tag} stopped at '{phase}' and {err}. Nothing was "
                 f"moved; please check {d['install']} by hand.")
        return u.result(False, "needs-person", tag=tag, previous=(job.get("from") or {}).get("tag"),
                        reason=str(err), action="recover")
    if moved:
        u.restart()
    hold.release_hold()
    u.end()
    frm = (job.get("from") or {}).get("tag")
    if error and not moved:
        if kind == "install":
            events.emit("update.failed", project=None, tag=tag, result="refused", reason=scrub.scrub(error))
        u.notify(f"Phoenix 9 {kind} of {tag} stopped: {error}. Nothing was changed.")
        return u.result(False, "refused", tag=tag, previous=frm, reason=error, action=kind)
    reason = f"the {kind} of {tag} stopped at '{phase}'; {frm} is installed again"
    if error:
        reason += f" (error: {error})"
    u.notify(f"Phoenix 9 updater: {reason}.")
    return u.result(False, "recovered", tag=tag, previous=frm, reason=reason, action="recover")


def _recover_install(u: _Update, d: dict, job: dict) -> bool:
    """Install job: before the swap drop -next; from the swap on, put the old copy back. True if it moved."""
    if job["phase"] in ("preparing", "waiting"):
        _rm(d["next"])
        return False
    if job["phase"] == "swapping":
        _swap_in(d)                  # finish the half move first, so every copy is in a known place
    _restore(d)                      # swapped / restarted / restoring: the new copy was never confirmed
    _rm(d["next"])
    return True


def _recover_rollback(u: _Update, d: dict, job: dict) -> bool:
    """Rollback job: end with the copy we came from installed (checked by commit). True if it moved.

    Before the first swap (waiting / staged, not reverting) the installed copy was never touched, so
    recovery only undoes the staging, whatever git says. From the swap on, the direction is decided by
    the installed copy's commit; if that cannot be read (or the job has no `from` commit) nothing is
    moved and NeedsPerson is raised: guessing could put the unconfirmed version in place."""
    if job["phase"] in ("waiting", "staged") and not job.get("reverting"):
        _unstage(d)
        return False
    if not d["install"].exists():    # finish a half swap (the unit's ExecStartPre does the same)
        if d["next"].exists():
            _rename(d["next"], d["install"])
        elif d["prev"].exists():
            _rename(d["prev"], d["install"])
    here = (u.version(d["install"]) or {}).get("commit") or ""
    came_from = (job.get("from") or {}).get("commit") or ""
    if not here or not came_from:
        raise NeedsPerson(NEEDS_PERSON)
    if here == came_from:
        _unstage(d)                  # the copy we came from is installed; put a staged -next back as -prev
    else:
        _stage(d)                    # the rollback target is installed but never confirmed: swap back
        _swap_in(d)
    return True


_RECOVERY = {"install": _recover_install, "rollback": _recover_rollback}


# ------------------------------------------------------------------ install
def _checks(u: _Update, nxt: Path, tag: str) -> bool:
    """Web install + build (when web/ exists), then ./check.sh, in -next; output to the checks file."""
    out_file = paths.logs() / f"update-{tag}-checks.txt"
    cmds = []
    if (nxt / "web" / "package.json").exists():
        cmds += [(["pnpm", "-C", "web", "install", "--frozen-lockfile"], PNPM_S),
                 (["pnpm", "-C", "web", "build"], PNPM_S)]
    cmds.append((["./check.sh"], CHECKS_S))
    text, ok = "", True
    for argv, timeout in cmds:
        rc, out, err = u.ad.host.run(argv, timeout=timeout, cwd=str(nxt))
        text += f"$ {' '.join(argv)}\n{out}{err}\n[exit {rc}]\n\n"
        u.log(f"{' '.join(argv)}: exit {rc}")
        if rc != 0:
            ok = False
            break
    atomic.write_text(out_file, scrub.scrub(text))
    return ok


def _images(u: _Update, nxt: Path, frm: str, tag: str) -> bool:
    """Rebuild step images when image/ or profiles/ changed between the installed commit and the tag."""
    changed = u.git(nxt, "diff", "--name-only", frm, tag, "--", "image", "profiles").strip()   # raises: never guess
    if not changed:
        return True
    rc, out, err = u.ad.host.run([str(nxt / "bin" / "phoenix"), "images", "build", "--changed", "--json"],
                                 timeout=IMAGES_S, cwd=str(nxt))
    u.log(f"images build: exit {rc}")
    with open(paths.logs() / f"update-{tag}-checks.txt", "a", encoding="utf-8") as f:
        f.write(scrub.scrub(f"$ phoenix images build --changed --json\n{out}{err}\n[exit {rc}]\n"))
    return rc == 0


def _prepare(u: _Update, d: dict, tag: str) -> None:
    """Fresh clone of the installed repo in -next, checked out at the tag (raises Refused on failure)."""
    _rm(d["next"])
    url = (u.try_git(d["install"], "config", "--get", "remote.origin.url") or "").strip()
    u.git(d["install"], "clone", "--quiet", "--no-hardlinks", str(d["install"]), str(d["next"]))
    u.git(d["next"], "checkout", "--quiet", "--detach", f"refs/tags/{tag}")
    if url:
        u.git(d["next"], "remote", "set-url", "origin", url)
    if u.git(d["next"], "rev-parse", "HEAD").strip() != u.job["to"]["commit"]:
        raise Refused(f"-next is not at {tag} after checkout")


def _failed_before_swap(u: _Update, d: dict, tag: str, frm: dict, result: str, why: str) -> dict:
    """Stop with the install untouched: drop -next, tell Alex."""
    _rm(d["next"])
    u.end()
    events.emit("update.failed", project=None, tag=tag, result=result, reason=scrub.scrub(why))
    u.notify(f"Phoenix 9 update to {tag} stopped ({result}): {why}. Nothing was changed.")
    return u.result(False, result, tag=tag, previous=frm["tag"], reason=why)


def _tag_commit(u: _Update, repo: Path, tag: str) -> str:
    """The commit a local release tag points at, or ""."""
    return (u.try_git(repo, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}") or "").strip()


def _remote_tag_commit(u: _Update, repo: Path, tag: str) -> str:
    """The commit origin's release tag points at (peeled), or "" when unknown."""
    out = u.try_git(repo, *CRED, "ls-remote", "--tags", "origin", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}")
    found = {}
    for line in (out or "").splitlines():
        parts = line.split()
        if len(parts) == 2:
            found[parts[1]] = parts[0]
    return found.get(f"refs/tags/{tag}^{{}}") or found.get(f"refs/tags/{tag}", "")


def _install(u: _Update, tag: str, idle_timeout_min: int) -> dict:
    """Install steps 2-13 (docs/architecture.md section 15); the caller holds the lock."""
    d = folders()
    frm = u.version(d["install"])
    if frm is None:
        raise Refused(f"Phoenix 9 is not installed at {d['install']}")
    local = _tag_commit(u, d["install"], tag)
    if local and local == frm["commit"]:          # compared by commit: an untagged HEAD can already be it
        return u.result(True, "already-installed", tag=tag, previous=frm["tag"], reason=f"{tag} is installed")
    ref = f"refs/tags/{tag}"        # tag already checked against TAG_RE (install())
    if u.try_git(d["install"], *CRED, "fetch", "--quiet", "--no-tags", "origin", f"{ref}:{ref}") is None:
        # Only the requested tag is fetched (another moved tag must not block updates). No --force: if
        # THIS tag moved on origin the fetch fails; say so plainly.
        remote = _remote_tag_commit(u, d["install"], tag)
        if remote and local and remote != local:
            raise Refused(f"release {tag} changed on origin")
        raise Refused("could not fetch releases from origin")
    commit = _tag_commit(u, d["install"], tag)
    if not commit:
        raise Refused(f"no release {tag}")
    if commit == frm["commit"]:
        return u.result(True, "already-installed", tag=tag, previous=frm["tag"], reason=f"{tag} is installed")

    events.emit("update.started", project=None, tag=tag, previous=frm["tag"], who=u.who)
    u.start("install", tag, frm, {"tag": tag, "commit": commit}, "preparing")
    u.git(d["install"], "tag", "-f", f"pre-{tag}", "HEAD")
    _prepare(u, d, tag)
    if not _checks(u, d["next"], tag):
        return _failed_before_swap(u, d, tag, frm, "tests-failed",
                                   f"the tests or web build failed (see update-{tag}-checks.txt)")

    u.phase("waiting")
    idle, busy = u.wait_idle(f"update to {tag}", idle_timeout_min)
    if not idle:
        hold.release_hold()
        _rm(d["next"])
        u.end()
        return u.result(False, "harness-busy", tag=tag, previous=frm["tag"],
                        reason=f"the harness stayed busy for {idle_timeout_min} min ({busy})")
    # Images are rebuilt only once no run is mid-task, so a running step never sees its image change.
    if not _images(u, d["next"], frm["commit"], tag):
        hold.release_hold()
        return _failed_before_swap(u, d, tag, frm, "images-failed", "rebuilding the step images failed")

    u.phase("swapping")
    _swap_in(d)
    u.phase("swapped")
    u.restart()
    u.phase("restarted")
    ok, why = u.healthy()
    if ok:
        u.migrate()
        hold.release_hold()
        u.end()
        events.emit("update.installed", project=None, tag=tag, previous=frm["tag"], who=u.who)
        u.notify(f"Phoenix 9 is now {tag}.")
        return u.result(True, "installed", tag=tag, previous=frm["tag"])

    u.phase("restoring")
    _restore(d)
    u.restart()
    back, why2 = u.healthy()
    hold.release_hold()
    u.end()
    result = "rolled-back" if back else "rolled-back-unhealthy"
    reason = f"{tag} failed its health check ({why})" + ("" if back else f"; {frm['tag']} is unhealthy too ({why2})")
    events.emit("update.rolledback", project=None, tag=tag, previous=frm["tag"], result=result,
                reason=scrub.scrub(reason))
    if back:
        u.notify(f"Phoenix 9 update to {tag} failed its health check and was rolled back to {frm['tag']}: {why}")
    else:
        u.notify(f"URGENT: Phoenix 9 may be down. The update to {tag} failed ({why}) and the rollback to "
                 f"{frm['tag']} is unhealthy too ({why2}). The new copy is kept in {d['failed']}.")
    return u.result(False, result, tag=tag, previous=frm["tag"], reason=reason)


# ------------------------------------------------------------------ rollback
def _rollback(u: _Update, idle_timeout_min: int) -> dict:
    """Swap the installed copy and -prev (through -next), restart, health check; swap back if unhealthy."""
    d = folders()
    to = u.version(d["prev"])
    if to is None or not d["install"].exists():
        raise Refused("nothing to roll back to")
    frm = u.version(d["install"])
    if frm is None:                   # recovery could not tell which way to swap back
        raise Refused("could not read the installed version")
    _rm(d["next"])        # a stale candidate; -next is about to hold the copy we roll back to
    u.start("rollback", to["tag"], frm, to, "waiting")
    idle, busy = u.wait_idle(f"rollback to {to['tag']}", idle_timeout_min)
    if not idle:
        hold.release_hold()
        u.end()
        return u.result(False, "harness-busy", tag=to["tag"], previous=frm["tag"], action="rollback",
                        reason=f"the harness stayed busy for {idle_timeout_min} min ({busy})")
    _exchange(u, d)
    ok, why = u.healthy()
    if ok:
        hold.release_hold()
        u.end()
        events.emit("update.rolledback", project=None, tag=to["tag"], previous=frm["tag"],
                    result="rolled-back-manual", who=u.who)
        u.notify(f"Phoenix 9 was rolled back to {to['tag']} (from {frm['tag']}).")
        return u.result(True, "rolled-back-manual", tag=to["tag"], previous=frm["tag"], action="rollback")
    u.job["reverting"] = True
    _exchange(u, d)
    hold.release_hold()
    u.end()
    reason = f"{to['tag']} failed its health check ({why}); {frm['tag']} is installed again"
    u.notify(f"Phoenix 9 rollback refused: {reason}.")
    return u.result(False, "refused", tag=to["tag"], previous=frm["tag"], reason=reason, action="rollback")


def _exchange(u: _Update, d: dict) -> None:
    """Swap the installed copy with -prev (stage, swap, restart), saving each phase first."""
    u.phase("staged")
    _stage(d)
    u.phase("swapping")
    _swap_in(d)
    u.phase("swapped")
    u.restart()
    u.phase("restarted")


# ------------------------------------------------------------------ public API
def _recover_after_error(u: _Update, error: str) -> dict | None:
    """Recovery straight after an error or stop signal in this process (tests replace it to act out
    a process that was killed outright, where nothing runs)."""
    return _recover(u, error)


def _protected(u: _Update, action: str, tag, fn) -> dict:
    """Run fn (the caller holds the lock): refusals become `refused`; any error or stop signal
    (SIGTERM arrives as SystemExit) is recovered at once, then a stop signal is passed on."""
    try:
        return fn()
    except Refused as err:
        if u.job:                # only ever raised before any folder moved
            hold.release_hold()
            if u.job["kind"] == "install":
                _rm(folders()["next"])
            u.end()
        return u.result(False, "refused", tag=tag, reason=str(err), action=action)
    except BaseException as err:  # noqa: BLE001 - the updater must leave a working install behind
        error = f"{type(err).__name__}: {err}"
        rec = None
        try:
            u.log(f"error: {error}")
            rec = _recover_after_error(u, error)
        except Exception as again:  # noqa: BLE001 - still pass the first problem on
            u.log(f"recovery failed: {type(again).__name__}: {again}")
        finally:
            hold.release_hold()
        if not isinstance(err, Exception):
            raise                # SystemExit / KeyboardInterrupt: stop, now that things are put right
        return rec or u.result(False, "refused", tag=tag, reason=error, action=action)


def _locked(u: _Update, action: str, tag, fn) -> dict:
    """Run fn under the update lock (refused when another update holds it)."""
    with _lock() as got:
        if not got:
            return u.result(False, "refused", tag=tag, reason="another update is running", action=action,
                            record=False)
        return _protected(u, action, tag, fn)


def _install_job(u: _Update, tag: str, idle_timeout_min: int):
    def go():
        rec = _recover(u)
        if rec and rec["result"] == "needs-person":
            return rec               # never install over a job nobody could recover
        return _with_recovery(_install(u, tag, idle_timeout_min), rec)
    return go


def _rollback_job(u: _Update, idle_timeout_min: int):
    def go():
        rec = _recover(u)
        if rec and rec["result"] == "needs-person":
            return rec
        return _with_recovery(_rollback(u, idle_timeout_min), rec)
    return go


def install(tag: str, adapters, *, who: str, idle_timeout_min: int = IDLE_TIMEOUT_MIN) -> dict:
    """Install release `tag` (v9.<n>) over the installed copy; health check; roll back on failure."""
    _load_secrets()
    u = _Update(adapters, who)
    if not _valid_tag(tag):
        return u.result(False, "refused", tag=None, reason="not a release tag (use v9.<n>)", record=False)
    return _locked(u, "install", tag, _install_job(u, tag, idle_timeout_min))


def rollback(adapters, *, who: str, idle_timeout_min: int = IDLE_TIMEOUT_MIN) -> dict:
    """Swap back to the previous installed version (-prev); rolling back twice returns to where it was."""
    _load_secrets()
    u = _Update(adapters, who)
    return _locked(u, "rollback", None, _rollback_job(u, idle_timeout_min))


def recover(adapters) -> dict | None:
    """Repair a half-done update (a crash mid-swap); None when there was nothing to repair."""
    _load_secrets()
    u = _Update(adapters, "updater")
    with _lock() as got:
        if not got:
            return u.result(False, "refused", reason="another update is running", action="recover", record=False)
        return _recover(u)


def _with_recovery(out: dict, rec: dict | None) -> dict:
    """Mention a recovery that happened first in the result's reason."""
    if rec:
        out["reason"] = (f"recovered first: {rec['reason']}. " + out["reason"]).strip()
    return out


ACTIONS = ("install", "rollback", "recover")


def request(action: str, tag: str | None, who: str, adapters) -> dict:
    """Queue an install, rollback or recover for the update unit and start it without waiting."""
    _load_secrets()
    u = _Update(adapters, who)
    base = {"ok": False, "result": "refused", "tag": tag, "previous": None, "log": [], "queued": False}
    if action not in ACTIONS:
        return {**base, "reason": "action must be install, rollback or recover"}
    if action == "install" and not _valid_tag(tag):
        return {**base, "tag": None, "reason": "not a release tag (use v9.<n>)"}
    if action != "install":
        tag = None
    if _lock_held():
        return {**base, "tag": tag, "reason": "another update is running"}
    atomic.write_json(_dir() / "request.json", {"action": action, "tag": tag, "who": who, "at": _now()})
    rc, _, err = adapters.host.systemctl("start", "--no-block", UNIT)
    if rc != 0:
        (_dir() / "request.json").unlink(missing_ok=True)
        return {**base, "tag": tag, "reason": scrub.scrub(f"could not start {UNIT}: {err.strip()}")}
    u.log(f"{who} asked for {action} {tag or ''}")
    return {**base, "ok": True, "result": None, "tag": tag, "reason": "", "queued": True}


def run_request(adapters) -> dict:
    """What update.sh runs: under the lock, take request.json, repair a half-done update, then do it."""
    _load_secrets()
    u = _Update(adapters, "updater")
    with _lock() as got:
        if not got:
            return _refuse_request(u)
        path = _dir() / "request.json"
        try:
            req = atomic.read_json(path)
        except (OSError, ValueError):
            req = None
        path.unlink(missing_ok=True)
        req = req if isinstance(req, dict) else {}
        u.who = str(req.get("who") or "updater")
        action, tag = req.get("action"), req.get("tag")
        if action == "install" and _valid_tag(tag):
            return _protected(u, "install", tag, _install_job(u, tag, IDLE_TIMEOUT_MIN))
        if action == "rollback":
            return _protected(u, "rollback", None, _rollback_job(u, IDLE_TIMEOUT_MIN))
        rec = _protected(u, "recover", None, lambda: _recover(u))
        if rec:
            return rec
        if action == "recover":
            return u.result(True, "recovered", reason="nothing needed repairing", action="recover")
        return u.result(False, "refused", tag=None, reason="no valid update request was waiting",
                        action=str(action or "request"), record=False)


def _refuse_request(u: _Update) -> dict:
    """run_request could not get the lock: leave request.json (not ours to take while another updater
    runs) but record the refusal in refused.json, so the app shows it instead of `queued` forever."""
    try:
        req = atomic.read_json(_dir() / "request.json")
    except (OSError, ValueError):
        req = None
    req = req if isinstance(req, dict) else {}
    action = str(req.get("action") or "request")
    tag = req.get("tag") if _valid_tag(req.get("tag")) else None
    u.who = str(req.get("who") or "updater")
    reason = "another update is running"
    try:
        atomic.write_json(_refused_file(), {"action": action, "tag": tag, "result": "refused",
                                            "reason": reason, "at": _now(), "who": u.who})
    except OSError as err:
        u.log(f"could not record the refusal: {err}")
    return u.result(False, "refused", tag=tag, reason=reason, action=action, record=False)


def _newest(u: _Update, install_dir: Path) -> str | None:
    """The highest v9.<n> tag on origin (git ls-remote), or None."""
    out = u.try_git(install_dir, *CRED, "ls-remote", "--tags", "origin", "v9.*")
    if out is None:
        return None
    tags = {line.split("refs/tags/")[-1].removesuffix("^{}") for line in out.splitlines() if "refs/tags/" in line}
    tags = [t for t in tags if _valid_tag(t)]
    return max(tags, key=_tag_number) if tags else None


def _log_tail(n: int = LOG_TAIL) -> list[str]:
    try:
        return (paths.logs() / "updater.log").read_text(encoding="utf-8").splitlines()[-n:]
    except FileNotFoundError:
        return []


def off_release_note(installed: dict) -> str:
    """The sentence `update status` shows when the installed copy is not on a release tag."""
    return (f"Installed copy is on commit {installed['commit'][:10]}, not a release. "
            "Run `phoenix update release` then `phoenix update install`.")


def status(adapters, *, refresh: bool = False) -> dict:
    """Installed / previous / newest version, whether an update or rollback is possible, and the log tail.
    `interrupted` = a job is recorded but no updater holds the lock (it died; request "recover")."""
    _load_secrets()
    u = _Update(adapters, "status")
    d = folders()
    st = _read_status()
    installed, previous = u.version(d["install"]), u.version(d["prev"])
    newest = st.get("newest")
    if refresh and installed:
        found = _newest(u, d["install"])
        if found:
            newest = found
            try:
                with _lock(wait_s=0) as got:    # status.json is only ever written under the lock
                    if got:
                        _write_status(newest=found, checked=_now())
            except OSError:             # e.g. the API, not root, cannot write HOME/update: just don't cache
                pass
    running = _lock_held()
    busy, why = hold.harness_busy()
    update_available = bool(newest and installed and (installed["tag"] == "unknown"
                                                       or _tag_number(newest) > _tag_number(installed["tag"])))
    job = st.get("job") or {}
    last = st.get("last")
    try:
        refused = atomic.read_json(_refused_file(), None)
    except (OSError, ValueError):
        refused = None
    if isinstance(refused, dict):    # a refusal newer than any locked result (see _refuse_request)
        last = refused
    off = bool(installed and installed["tag"] == "unknown")
    return {"supported": True, "installed": installed, "previous": previous, "newest": newest,
            "off_release": off, "off_release_note": off_release_note(installed) if off else "",
            "update_available": update_available, "can_rollback": previous is not None and not running,
            "busy": busy, "busy_reason": why, "running": running,
            "waiting": (st.get("waiting") or "") if running else "", "phase": job.get("phase"),
            "interrupted": bool(job) and not running,
            "last": last, "log_tail": _log_tail()}


def _load_secrets() -> None:
    """Teach the scrubber every global secret value, so none reaches the log or a message."""
    folder = paths.secrets()
    try:
        files = sorted(folder.glob("*.env")) if folder.is_dir() else []
        scrub.add_secrets(scrub.secrets_from(files))
    except OSError:
        pass


def main(argv) -> int:
    """`python3 -m phoenix9.updater run-request` (from update.sh) or `status`; prints JSON."""
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))   # SystemExit: recovery runs, then it stops
    args = list(argv)
    if args[:1] == ["run-request"]:
        out = run_request(adapters_mod.real())
    elif args[:1] == ["status"]:
        out = status(adapters_mod.real(), refresh="--refresh" in args)
    else:
        print("usage: python3 -m phoenix9.updater run-request | status [--refresh]", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2))
    return 0 if out.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
