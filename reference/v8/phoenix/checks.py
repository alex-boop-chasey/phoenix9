"""Turning a step's Done-when list into locked automatic checks.

Before any builder starts on a step, a separate check-writer session writes
one check per Done-when bullet into `tests/phoenix/step-<nn>/` (unit checks
`*.test.ts` run by Vitest, browser checks `*.spec.ts` run by Playwright).
Phoenix commits them and records each file's sha256 in
`tests/phoenix/manifest.json` (the lock, hard rule 4). From then on every
snapshot of the builder's work is checked against the manifest, and any
changed or missing check file throws the whole snapshot away.

Then the checks are run once on the current branch head (the "red check"):
they should fail, because the step is not built yet. If they all pass, the
step is noted as `vacuous checks` in run.json and the run carries on.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path

from phoenix import claude, config, docker, runs
from phoenix import git as pgit
from phoenix import plan as pplan
from phoenix.log import log
from phoenix.state import atomic_write

CHECKS_ROOT = "tests/phoenix"
MANIFEST = pgit.LOCK_MANIFEST              # tests/phoenix/manifest.json
PROMPT_TEMPLATE = Path(__file__).resolve().parent.parent / "prompts" / "check-writer.md"
TESTCONFIG_DIR = Path(__file__).resolve().parent.parent / "image" / "testconfig"
TESTCONFIG_MOUNT = "/phoenix/testconfig"
OUT_MOUNT = "/out"
WRITER_ROLE = "checker"
WRITER_MAX_TURNS = 60
WRITER_TRIES = 2                       # the first try, plus one retry after a rejection
RED_TRY = 0                            # try number used for the red check's container and log
TREE_LINES = 400
EXISTING_CHECKS_CHARS = 60_000
CHECK_FILE = re.compile(r"^(\d+)-[A-Za-z0-9._-]*\.(test|spec)\.ts$")
WRITTEN = re.compile(r"^CHECKS WRITTEN:\s*(\d+)\s*$")
CANNOT = re.compile(r"^CANNOT CHECK:\s*(.+)$")


class LockBroken(Exception):
    """A locked check file was changed, removed, or is not a plain file. `path` names it."""

    def __init__(self, path: str, why: str = "changed"):
        self.path = path
        super().__init__(f"Locked check {path} was {why}.")


class CheckWriterFailed(Exception):
    """The check writer did not produce an acceptable set of checks, even after a retry."""


class CannotCheck(Exception):
    """The check writer said a Done-when bullet cannot be checked automatically (the plan needs a fix)."""


# ------------------------------------------------------------- names and the check command
def step_folder(step: int) -> str:
    """Return the repo folder holding a step's checks, like `tests/phoenix/step-03`."""
    return f"{CHECKS_ROOT}/step-{int(step):02d}"


def check_command(step: int, has_spec: bool = True) -> str:
    """Return the shell command that runs one step's checks inside a check container.

    Reports go to /out (vitest.json, playwright.json). The configs are
    Phoenix's own, mounted read-only from image/testconfig/, never the repo's.
    The Playwright half is left out when the step has no `*.spec.ts` file.
    Vitest writes a temporary file next to its config while loading it, so
    its config is first copied from the read-only mount into a fresh temp
    folder (right before Vitest starts, after the install has run).
    """
    folder = step_folder(step)
    cmd = (f"vc=$(mktemp -d) && cp {TESTCONFIG_MOUNT}/vitest.config.mjs \"$vc/\" && "
           f"npx vitest run {folder} --config \"$vc/vitest.config.mjs\" "
           f"--reporter=json --outputFile={OUT_MOUNT}/vitest.json")
    if has_spec:
        cmd += (f"; npx playwright test {folder} --config {TESTCONFIG_MOUNT}/playwright.config.mjs "
                f"--reporter=json > {OUT_MOUNT}/playwright.json")
    return cmd


def check_mounts(out_dir: Path) -> list[docker.Mount]:
    """The extra mounts a check container needs: the test configs (read-only) and the report folder."""
    return [docker.Mount(TESTCONFIG_DIR, TESTCONFIG_MOUNT), docker.Mount(Path(out_dir), OUT_MOUNT, ro=False)]


def step_check_files(checkout: Path, step: int) -> list[str]:
    """Return the check files (`*.test.ts`, `*.spec.ts`) in a step's folder, as repo paths, sorted."""
    folder = Path(checkout) / step_folder(step)
    if not folder.is_dir() or folder.is_symlink():
        return []
    return sorted(f"{step_folder(step)}/{p.name}" for p in folder.iterdir()
                  if p.name.endswith((".test.ts", ".spec.ts")) and p.is_file() and not p.is_symlink())


# ------------------------------------------------------------- 1. the lock
def file_sha256(path: Path) -> str:
    """Return the sha256 (hex) of a plain file. Raises OSError for a symlink or a missing file."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    h = hashlib.sha256()
    with os.fdopen(fd, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def read_manifest(checkout: Path) -> dict[str, str]:
    """Return the manifest of a checkout as {repo path: sha256}; empty when there is none."""
    p = Path(checkout) / MANIFEST
    if not p.exists():
        return {}
    return parse_manifest(p.read_bytes())


def parse_manifest(data: bytes) -> dict[str, str]:
    """Read manifest.json contents. A broken manifest raises LockBroken."""
    try:
        files = json.loads(data.decode("utf-8"))["files"]
        if not isinstance(files, dict) or not all(isinstance(v, str) for v in files.values()):
            raise ValueError
        return dict(files)
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        raise LockBroken(MANIFEST, "unreadable") from None


def _repo_path(clone: Path, path) -> str:
    """Turn a path (inside the clone, or already relative to it) into a repo path like tests/phoenix/x."""
    p = Path(path)
    if p.is_absolute():
        p = p.resolve().relative_to(clone.resolve())
    rel = p.as_posix()
    if rel.startswith("../") or not rel.startswith(CHECKS_ROOT + "/"):
        raise ValueError(f"{rel} is not under {CHECKS_ROOT}/; only check files can be locked")
    return rel


def lock(repo: str, step: int, paths) -> str:
    """Add each check file's sha256 to tests/phoenix/manifest.json in Phoenix's clone and commit. Return HEAD.

    `paths` are repo paths (or paths inside the clone). The commit message is
    `Step <n>: lock checks`; it has no Phoenix-Step trailer, so it does not
    count as the step passing.
    """
    d = pgit.clone_dir(repo)
    if not pgit.git(d, "symbolic-ref", "-q", "HEAD", check=False).strip().startswith("refs/heads/" + pgit.BRANCH_PREFIX):
        raise pgit.GitError(f"Phoenix's clone of {repo} is not on a phoenix/<run-id> branch; refusing to lock checks.")
    files = read_manifest(d)
    for path in paths:
        rel = _repo_path(d, path)
        if rel == MANIFEST:
            raise ValueError("the manifest cannot lock itself")
        files[rel] = file_sha256(d / rel)
    manifest = d / MANIFEST
    manifest.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(manifest, json.dumps({"files": dict(sorted(files.items()))}, indent=2) + "\n")
    pgit.git(d, "add", "--", MANIFEST, *sorted(files))
    if pgit.git(d, "diff", "--cached", "--name-only").strip():
        pgit.git(d, *pgit.IDENT, "commit", "-q", "--no-verify", "-m", f"Step {int(step)}: lock checks")
    return pgit.head(d)


def verify_lock(checkout: Path, manifest: dict[str, str] | None = None) -> None:
    """Recompute the hash of every file in the manifest. Raise LockBroken naming the first bad file.

    The manifest is read from the checkout unless a trusted one is given
    (snapshot passes the one committed at HEAD, so the builder cannot
    rewrite it). A missing manifest means nothing is locked yet.
    """
    files = read_manifest(checkout) if manifest is None else manifest
    for rel, want in sorted(files.items()):
        p = Path(checkout) / rel
        try:
            got = file_sha256(p)
        except FileNotFoundError:
            raise LockBroken(rel, "removed") from None
        except OSError:
            raise LockBroken(rel, "replaced by something that is not a plain file") from None
        if got != want:
            raise LockBroken(rel, "changed")


def committed_manifest(clone: Path) -> dict[str, str] | None:
    """Return the manifest as committed at HEAD in Phoenix's clone, or None when HEAD has none."""
    p = pgit.run_git(clone, "show", f"HEAD:{MANIFEST}", check=False)
    if p.returncode != 0:
        return None
    return parse_manifest(p.stdout)


# ------------------------------------------------------------- 2. the check-writer prompt
def repo_tree(clone: Path, cap: int = TREE_LINES) -> str:
    """Return `git ls-files` of Phoenix's clone, cut to `cap` lines."""
    files = [f for f in pgit.git(clone, "ls-files").splitlines() if f]
    if not files:
        return "(the repo has no files yet)"
    shown = files[:cap]
    if len(files) > cap:
        shown.append(f"... and {len(files) - cap} more files")
    return "\n".join(shown)


def existing_checks(clone: Path, step: int, cap: int = EXISTING_CHECKS_CHARS) -> str:
    """Return the locked checks of other steps (path and contents), cut to about `cap` characters."""
    own = step_folder(step) + "/"
    parts, size = [], 0
    for rel in sorted(read_manifest(clone)):
        if rel.startswith(own):
            continue
        try:
            text = (clone / rel).read_text(errors="replace")
        except OSError:
            continue
        block = f"### {rel}\n```ts\n{text.rstrip()}\n```\n"
        if size + len(block) > cap:
            parts.append("(more checks left out to keep this prompt short)")
            break
        parts.append(block)
        size += len(block)
    return "\n".join(parts) or "(none yet)"


def render_prompt(plan: pplan.Plan, step: pplan.Step, tree: str, existing: str) -> str:
    """Fill in prompts/check-writer.md for one step."""
    bullets = "\n".join(f"{i}. {b}" for i, b in enumerate(step.done_when, 1))
    values = {
        "about": plan.about.strip() or "(none)",
        "every_step": plan.every_step.strip() or "(none)",
        "step_number": str(step.number),
        "step_title": step.title,
        "step_description": step.description.strip() or "(no description)",
        "done_when": bullets or "(none)",
        "step_folder": step_folder(step.number),
        "repo_tree": tree,
        "existing_checks": existing,
    }
    text = PROMPT_TEMPLATE.read_text()
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def finish_line(text: str) -> tuple[str, str]:
    """Read the session's last line: ("written", n), ("cannot", what) or ("", "") when it has neither.

    The line is only a hint: what counts is the files Phoenix finds (hard rule 3).
    """
    lines = [ln.strip().strip("`").strip() for ln in (text or "").strip().splitlines() if ln.strip()]
    last = lines[-1] if lines else ""
    if m := WRITTEN.match(last):
        return "written", m.group(1)
    if m := CANNOT.match(last):
        return "cannot", m.group(1).strip()
    return "", ""


# ------------------------------------------------------------- 3. write_checks
def load_plan(run: dict) -> pplan.Plan:
    """Read and parse the run's plan file (run.json `plan_path`)."""
    return pplan.parse(Path(run["plan_path"]).read_text())


def project_env_file(repo: str) -> Path | None:
    """Return config/projects/<repo-name>.env when it exists (the project's test keys)."""
    p = config.paths().config / "projects" / f"{pgit.repo_name(repo)}.env"
    return p if p.is_file() else None


def domains_file(repo: str) -> Path | None:
    """Return config/projects/<repo-name>.domains when it exists (the allowed hosts)."""
    p = docker.domains_file_path(repo)
    return p if p.is_file() else None


def accept_checks(changes: list[pgit.Change], step: pplan.Step) -> list[str]:
    """Check what the check writer changed. Return the reasons to reject it ([] means accepted).

    Every change must add or change a file directly in the step's own folder,
    named `<bullet number>-<slug>.test.ts` or `.spec.ts`, and there must be
    exactly one such file for each Done-when bullet.
    """
    folder = step_folder(step.number) + "/"
    bad, numbers = [], []
    for c in changes:
        name = c.path[len(folder):] if c.path.startswith(folder) else ""
        m = CHECK_FILE.match(name) if "/" not in name else None
        if c.status == "D" or not m:
            bad.append(f"{c.status} {c.path}: the check writer may only add check files "
                       f"named <bullet>-<slug>.test.ts or .spec.ts directly in {folder}")
        else:
            numbers.append(int(m.group(1)))
    if not bad:
        want = list(range(1, len(step.done_when) + 1))
        if sorted(numbers) != want:
            bad.append(f"expected one check file for each of bullets {want}, got files for {sorted(numbers)}")
    return bad


def write_checks(run: dict, step: pplan.Step, *, container=docker.run_claude_container,
                 settings: dict | None = None) -> list[Path]:
    """Have a check-writer session write the step's checks; commit them as "Step <n>: checks".

    Each try gets a fresh workspace and a firewalled `checker` container (60
    turns, `check_writer_timeout_min`). The work is snapshotted back like a
    builder's, but only check files in the step's own folder are accepted;
    anything else rejects the try. One retry, then CheckWriterFailed.
    A `CANNOT CHECK` answer raises CannotCheck at once (the plan needs a fix).
    Returns the committed check files as repo paths.
    """
    s = settings or config.load()
    run_id, repo = run["run_id"], run["repo"]
    plan = load_plan(run)
    clone = pgit.clone_dir(repo)
    env_file = project_env_file(repo)
    prompt = render_prompt(plan, step, repo_tree(clone), existing_checks(clone, step.number))
    problems: list[str] = []
    for try_no in range(1, WRITER_TRIES + 1):
        prompt_file = runs.run_dir(run_id) / "prompts" / f"{step.number}-{try_no}-{WRITER_ROLE}.md"
        atomic_write(prompt_file, prompt)
        workspace = pgit.fresh_workspace(repo, run_id, step.number, try_no)
        try:
            result = container(run_id, step.number, try_no, WRITER_ROLE, workspace, prompt_file,
                               [env_file] if env_file else [], domains_file(repo),
                               s["check_writer_timeout_min"], max_turns=WRITER_MAX_TURNS, settings=s)
            claude.record_usage(run_id, result, role=WRITER_ROLE, step=step.number, try_no=try_no)
            kind, what = finish_line(result.text)
            if result.kind == "ok" and kind == "cannot":
                raise CannotCheck(f"Step {step.number}: the check writer cannot check: {what}")
            if result.kind != "ok":
                problems = [f"the check-writer session ended with '{result.kind}': {result.text[-300:]}"]
            else:
                problems = _take_snapshot(workspace, repo, step, env_file)
        finally:
            pgit.remove_workspace(workspace)
        if not problems:
            paths = step_check_files(clone, step.number)
            pgit.git(clone, *pgit.IDENT, "commit", "-q", "--no-verify", "-m", f"Step {step.number}: checks")
            log(run_id, f"step {step.number}: {len(paths)} checks written")
            return [Path(p) for p in paths]
        log(run_id, f"step {step.number}: check writer try {try_no} rejected: {'; '.join(problems)}")
    raise CheckWriterFailed(f"Step {step.number}: the check writer failed twice: {'; '.join(problems)}")


def _take_snapshot(workspace: Path, repo: str, step: pplan.Step, env_file: Path | None) -> list[str]:
    """Snapshot the check writer's workspace and keep it staged only if it passes accept_checks."""
    try:
        changes = pgit.snapshot(workspace, repo, env_file=env_file)
    except pgit.Rejected as e:
        return e.reasons
    bad = accept_checks(changes, step)
    if bad:
        pgit.clean(pgit.clone_dir(repo))
    return bad


# ------------------------------------------------------------- 4. the red check
def read_counts(out_dir: Path, has_test: bool, has_spec: bool) -> dict | None:
    """Add up passed / failed / skipped from the reports in out_dir. None when a needed report is missing or broken.

    Vitest (read when the step has `*.test.ts`): numPassedTests, numFailedTests
    (+ numFailedTestSuites, files that did not even load), numPendingTests +
    numTodoTests. Playwright (when it has `*.spec.ts`): stats.expected,
    stats.unexpected + stats.flaky, stats.skipped, plus one failure for any
    top-level error (such as the site not starting). Step 7 judges these
    counts more strictly; here they only decide "vacuous or not".
    """
    total = {"passed": 0, "failed": 0, "skipped": 0}
    try:
        if has_test:
            v = json.loads((Path(out_dir) / "vitest.json").read_text())
            total["passed"] += int(v.get("numPassedTests", 0))
            total["failed"] += int(v.get("numFailedTests", 0)) + int(v.get("numFailedTestSuites", 0))
            total["skipped"] += int(v.get("numPendingTests", 0)) + int(v.get("numTodoTests", 0))
        if has_spec:
            report = json.loads((Path(out_dir) / "playwright.json").read_text())
            stats = report["stats"]
            total["passed"] += int(stats.get("expected", 0))
            total["failed"] += int(stats.get("unexpected", 0)) + int(stats.get("flaky", 0))
            total["skipped"] += int(stats.get("skipped", 0))
            total["failed"] += len(report.get("errors") or [])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    return total


def note_step(run_id: str, number: int, **fields) -> None:
    """Set fields on one step's entry in run.json `steps` (the entry is created when missing)."""
    record = runs.load_run(run_id)
    steps = record.setdefault("steps", [])
    entry = next((e for e in steps if isinstance(e, dict) and e.get("number") == number), None)
    if entry is None:
        entry = {"number": number}
        steps.append(entry)
    entry.update(fields)
    runs.save_run(record)


def red_check(run: dict, step: pplan.Step, *, container=docker.run_check_container,
              settings: dict | None = None) -> bool:
    """Run the step's locked checks on the branch head before any builder starts. True = the builder may start.

    At least one check should fail (the step is not built yet): run.json gets
    `red_check: "failing"`. When every check passes, it gets `"vacuous checks"`
    and the run still carries on (an earlier step may already have done the
    work). Returns False only when the step has no check files at all.
    """
    s = settings or config.load()
    run_id, repo = run["run_id"], run["repo"]
    clone = pgit.clone_dir(repo)
    checkout = pgit.fresh_checkout(repo, pgit.head(clone))
    try:
        verify_lock(checkout)
        files = step_check_files(checkout, step.number)
        if not files:
            note_step(run_id, step.number, red_check="no checks")
            log(run_id, f"step {step.number}: red check found no check files")
            return False
        has_spec = any(f.endswith(".spec.ts") for f in files)
        has_test = any(f.endswith(".test.ts") for f in files)
        out_dir = config.paths().runs / run_id / "3-product" / "reports" / f"{step.number}-red"
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True)
        docker.hand_to_agent(out_dir)
        command = "[ -f package.json ] && pnpm install --frozen-lockfile; " + check_command(step.number, has_spec)
        rc, _ = container(run_id, step.number, RED_TRY, checkout, command, project_env_file(repo),
                          domains_file(repo), s["checker_timeout_min"], role="red",
                          mounts=check_mounts(out_dir), settings=s)
        counts = read_counts(out_dir, has_test, has_spec)
    finally:
        pgit.remove_workspace(checkout)
    vacuous = counts is not None and counts["passed"] >= 1 and counts["failed"] == 0 and counts["skipped"] == 0
    status = "vacuous checks" if vacuous else "failing"
    note_step(run_id, step.number, red_check=status)
    log(run_id, f"step {step.number}: red check {status} (exit {rc}, counts {counts})")
    return True
