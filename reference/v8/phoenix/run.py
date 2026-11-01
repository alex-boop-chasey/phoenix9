"""Starting and finishing a run: everything around the step loop (phoenix/loop.py).

`start_run` gets a queued run ready: Phoenix's clone and the run branch, the
plan commit, the allowed-hosts file, `2-plan/plan.json`, and one run of the
project's full test suite on main (a red main stops the run at once).

`finish_run` runs the full suite on the branch head (once more if it is red),
pushes the branch, opens the pull request, and writes the run record: the
final commit, the reports and screenshots under `3-product/`, and
`summary.md` / `summary.html` in the run folder.

`notify` sends a short message to the owner. `check_merged` notices when the
owner merged or closed a run's pull request.
"""
from __future__ import annotations

import dataclasses
import html
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from phoenix import checks, claude, config, docker, runs, verify
from phoenix import git as pgit
from phoenix import plan as pplan
from phoenix.log import log
from phoenix.state import atomic_write

SUITE_ROLE = "suite"
SUITE_FILE = "suite.txt"                      # the suite's own output, in its report folder
HTML_TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "summary.html"
PR_BODY_LIMIT = 60_000                        # GitHub refuses PR bodies over 65 536 characters
NOTIFY_TIMEOUT_S = 60
GH_TIMEOUT_S = 120
SCREENSHOT_SUFFIXES = (".png", ".jpg", ".jpeg")


def default_gh(args: list[str]) -> subprocess.CompletedProcess:
    """Run the GitHub CLI with GH_TOKEN from config/github.env (never written to a log)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GH_", "GITHUB_"))}
    token_file = config.paths().config / "github.env"
    if token_file.is_file():
        token = claude.read_env_file(token_file).get("GH_TOKEN", "")
        if token:
            env["GH_TOKEN"] = token
    env["GH_PROMPT_DISABLED"] = "1"
    return subprocess.run(["gh", *args], env=env, capture_output=True, text=True, timeout=GH_TIMEOUT_S)


@dataclass
class Hands:
    """The outside pieces start_run / finish_run use. Tests swap them for fakes."""

    container: Callable = docker.run_check_container    # the full suite's check container
    gh: Callable = default_gh                            # gh(args) -> CompletedProcess
    push: Callable = pgit.push
    notify: Callable | None = None                       # None = notify() with the settings


# ------------------------------------------------------------- notifications
def notify(text: str, settings: dict | None = None) -> None:
    """Tell the owner something: run `telegram_script <text>` when it is set in phoenix.toml, else print.

    Never raises: a lost notification must not stop a run.
    """
    s = settings or config.load()
    script = str(s.get("telegram_script") or "").strip()
    if not script:
        print(f"NOTIFY: {text}", flush=True)
        return
    try:
        r = subprocess.run([script, text], capture_output=True, text=True, timeout=NOTIFY_TIMEOUT_S)
        if r.returncode != 0:
            print(f"NOTIFY FAILED (exit {r.returncode}): {text}", flush=True)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"NOTIFY FAILED ({e}): {text}", flush=True)


def _notify(hands: Hands, s: dict) -> Callable[[str], None]:
    """Return the notify function to use (the fake one in tests)."""
    return hands.notify or (lambda text: notify(text, s))


# ------------------------------------------------------------- run.json helpers
def note_run(run_id: str, **fields) -> dict:
    """Set top-level fields in run.json and save it. Returns the record."""
    record = runs.load_run(run_id)
    record.update(fields)
    runs.save_run(record)
    return record


def note_suite(run_id: str, **fields) -> dict:
    """Set fields in run.json `full_suite` (created when missing). Returns the record."""
    record = runs.load_run(run_id)
    suite = record.get("full_suite") if isinstance(record.get("full_suite"), dict) else {}
    suite.update(fields)
    record["full_suite"] = suite
    runs.save_run(record)
    return record


def plan_json(plan: pplan.Plan) -> str:
    """The parsed plan as JSON text (for 2-plan/plan.json)."""
    return json.dumps(dataclasses.asdict(plan), indent=2, ensure_ascii=False) + "\n"


# ------------------------------------------------------------- the full suite
def suite_command(checkout: Path) -> str | None:
    """The project's full test command: `pnpm run test:all` if package.json has it, else `pnpm test`.

    None when package.json has neither (or only npm's "no test specified" stub).
    """
    try:
        scripts = json.loads((Path(checkout) / "package.json").read_text()).get("scripts") or {}
    except (OSError, ValueError, AttributeError):
        return None
    if not isinstance(scripts, dict):
        return None

    def real(name: str) -> bool:
        value = scripts.get(name)
        return isinstance(value, str) and bool(value.strip()) and value.strip() != verify.NPM_DEFAULT_TEST

    if real("test:all"):
        return "pnpm run test:all"
    if real("test"):
        return "pnpm test"
    return None


def suite_shell(cmd: str) -> str:
    """The whole shell command for the suite container: install, then the suite (its exit code is the result).

    The install's own exit code is ignored (pnpm 12 exits non-zero over
    ignored build scripts even when everything is installed; see Step 6).
    """
    out = f"{checks.OUT_MOUNT}/{SUITE_FILE}"
    return ("[ -f package.json ] && pnpm install --frozen-lockfile; "
            f"echo '### Phoenix: full suite: {cmd.replace(chr(39), '')}'; "
            f"( {cmd} ) 2>&1 < /dev/null | tee {out}; exit ${{PIPESTATUS[0]}}")


def suite_report_dir(run_id: str, label: str, try_no: int) -> Path:
    """The folder for one full-suite run: runs/<id>/3-product/reports/suite-<label>-<try>/."""
    return config.paths().runs / run_id / "3-product" / "reports" / f"suite-{label}-{try_no}"


def run_full_suite(run: dict, sha: str, label: str, try_no: int, hands: Hands, s: dict) -> dict:
    """Run the project's full test suite once on commit `sha` in a check container.

    Returns {"result": "green" | "red" | "none", "test": <first failing test>, "command": ...}.
    Only the container's exit code decides green or red (hard rule 3). Output:
    runs/<id>/logs/suite-<try>-<label>.txt; screenshots and reports in the
    suite's report folder.
    """
    run_id, repo = run["run_id"], run["repo"]
    env_file = checks.project_env_file(repo)
    checkout = pgit.fresh_checkout(repo, sha)
    try:
        cmd = suite_command(checkout)
        if not cmd:
            log(run_id, f"full suite ({label}): the project has no test script")
            return {"result": "none", "test": "", "command": ""}
        out_dir = suite_report_dir(run_id, label, try_no)
        pgit.rmtree(out_dir)
        out_dir.mkdir(parents=True)
        docker.hand_to_agent(out_dir)
        mounts = [docker.Mount(out_dir, checks.OUT_MOUNT, ro=False)]
        rc, _ = hands.container(run_id, label, try_no, checkout, suite_shell(cmd), env_file,
                                checks.domains_file(repo), s["checker_timeout_min"], role=SUITE_ROLE,
                                mounts=mounts, settings=s)
        verify.save_project_artifacts(checkout, out_dir)
        verify.redact_reports(out_dir, env_file)
    finally:
        pgit.remove_workspace(checkout)
    if rc == 0:
        log(run_id, f"full suite ({label}, try {try_no}): green")
        return {"result": "green", "test": "", "command": cmd}
    if rc == docker.TIMEOUT_RC:
        name = f"timed out after {s['checker_timeout_min']:g} minutes"
    else:
        try:
            output = (out_dir / SUITE_FILE).read_text(errors="replace")
        except OSError:
            output = ""
        name = verify.first_failing_test(output) or f"`{cmd}` failed with exit {rc} (no failing test name found)"
    log(run_id, f"full suite ({label}, try {try_no}): red: {name}")
    return {"result": "red", "test": name, "command": cmd}


# ------------------------------------------------------------- start_run
def git_problem(e: Exception) -> str:
    """A git error in plain words: git's own `fatal:` message without the command line in front of it."""
    text = str(e)
    return "fatal:" + text.split("fatal:", 1)[1].rstrip() if "fatal:" in text else text


def fail_run(run_id: str, reason: str, hands: Hands, s: dict) -> str:
    """Mark a run failed with a plain-English reason, write its summary, and tell the owner."""
    note_run(run_id, status="failed", reason=reason, current_step=None, finished_at=runs.now_iso())
    log(run_id, f"run failed: {reason}")
    record = runs.load_run(run_id)
    if record.get("repo"):
        write_summary(record)
    _notify(hands, s)(f"Phoenix run {run_id} failed: {reason}")
    return "failed"


def start_run(run_id: str, *, hands: Hands | None = None, settings: dict | None = None) -> str:
    """Get a queued run ready for the step loop. Returns "ready" or "failed".

    Clone, run branch and plan commit (Step 5), the allowed-hosts file
    (Step 4), `2-plan/plan.json`, then for `Type: change` the full suite once
    on main: a red main fails the run ("main is already red: <test>").
    `Type: new` skips the suite (the repo is empty). Safe to call again.
    """
    hands = hands or Hands()
    s = settings or config.load()
    record = runs.load_run(run_id)
    plan = checks.load_plan(record)
    repo = record["repo"]
    log(run_id, f"starting run for plan '{plan.name}' on {repo}")
    try:
        pgit.ensure_clone(repo)
        base = pgit.start_branch(repo, run_id)
        record = note_run(run_id, base_sha=record.get("base_sha") or base, branch=pgit.branch_name(run_id))
        pgit.commit_plan(repo, run_id, Path(record["plan_path"]))
    except pgit.GitError as e:
        return fail_run(run_id, f"could not get the repo ready: {git_problem(e)}", hands, s)
    docker.write_domains_file(plan)
    atomic_write(runs.run_dir(run_id) / "2-plan" / "plan.json", plan_json(plan))
    if plan.type != "change":
        note_suite(run_id, start="skipped", start_test="")
        return "ready"
    result = run_full_suite(record, record["base_sha"], "start", 1, hands, s)
    note_suite(run_id, start=result["result"], start_test=result["test"], command=result["command"])
    if result["result"] == "red":
        return fail_run(run_id, f"main is already red: {result['test']}", hands, s)
    return "ready"


# ------------------------------------------------------------- finish_run
def open_pr(record: dict, plan: pplan.Plan, hands: Hands) -> tuple[str, str]:
    """Open the run's pull request with `gh pr create`. Returns (url, problem); problem is "" on success.

    When a PR for the branch already exists (a restart), its URL is used.
    """
    run_id, repo = record["run_id"], record["repo"]
    branch = pgit.branch_name(run_id)
    body = runs.run_dir(run_id) / "pr-body.md"
    atomic_write(body, summary_markdown(record, plan, pr_text="this pull request")[:PR_BODY_LIMIT])
    title = f"Phoenix run {run_id}: {plan.name or 'plan'}"
    r = hands.gh(["pr", "create", "--repo", repo, "--base", pgit.MAIN, "--head", branch,
                  "--title", title, "--body-file", str(body)])
    url = _url_in(r.stdout)
    if r.returncode == 0 and url:
        return url, ""
    v = hands.gh(["pr", "view", branch, "--repo", repo, "--json", "url"])
    try:
        url = json.loads(v.stdout or "{}").get("url", "") if v.returncode == 0 else ""
    except ValueError:
        url = ""
    if url:
        return url, ""
    problem = (r.stderr or r.stdout or "").strip().splitlines()
    return "", f"could not open the pull request: {problem[-1] if problem else f'gh exit {r.returncode}'}"


def _url_in(text: str) -> str:
    """The last https:// line of gh's output (gh pr create prints the new PR's address)."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip().startswith("https://")]
    return lines[-1] if lines else ""


def suite_at_end(record: dict, sha: str, hands: Hands, s: dict) -> None:
    """Run the full suite on the head, once more if it is red, and save the result in run.json."""
    run_id = record["run_id"]
    result = run_full_suite(record, sha, "end", 1, hands, s)
    tries = 1
    if result["result"] == "red":
        log(run_id, "full suite red at the end; running it once more")
        result = run_full_suite(record, sha, "end", 2, hands, s)
        tries = 2
    note_suite(run_id, end=result["result"], end_test=result["test"], end_tries=tries,
               command=result["command"] or (record.get("full_suite") or {}).get("command", ""))


def finish_run(run_id: str, *, hands: Hands | None = None, settings: dict | None = None) -> str:
    """Finish a run after the step loop: full suite, push, PR, run record, summary, notification.

    A red suite does not change the status (core has no fix loop): the run
    stays `done` (or `failed` when a step failed) with `full_suite.end = red`
    and the failing test named. Returns the run's status.
    """
    hands = hands or Hands()
    s = settings or config.load()
    record = runs.load_run(run_id)
    plan = checks.load_plan(record)
    repo = record["repo"]
    pgit.start_branch(repo, run_id)
    sha = pgit.head(pgit.clone_dir(repo))
    note_run(run_id, final_commit=sha)
    suite_at_end(runs.load_run(run_id), sha, hands, s)
    problem = ""
    try:
        hands.push(repo, run_id)
        log(run_id, f"pushed {pgit.branch_name(run_id)} ({sha[:12]})")
    except pgit.GitError as e:
        problem = f"could not push the branch: {e}"
    record = runs.load_run(run_id)
    if not problem and not record.get("pr_url"):
        url, problem = open_pr(record, plan, hands)
        if url:
            record = note_run(run_id, pr_url=url)
            log(run_id, f"opened {url}")
    if problem:
        log(run_id, problem)
        record = note_run(run_id, reason=problem)
    save_product(run_id, sha)
    record = note_run(run_id, current_step=None, finished_at=runs.now_iso())
    write_summary(record, plan)
    _notify(hands, s)(finish_message(record))
    return record["status"]


def finish_message(record: dict) -> str:
    """The notification text for a finished run."""
    suite = record.get("full_suite") or {}
    steps = [e for e in record.get("steps", []) if isinstance(e, dict)]
    passed = sum(1 for e in steps if e.get("status") == "passed")
    text = f"Phoenix run {record['run_id']} {record.get('status')}: {passed} of {len(steps)} steps passed"
    if suite.get("end") == "red":
        text += f"; full suite red: {suite.get('end_test')}"
    if record.get("reason"):
        text += f"; {record['reason']}"
    return text + (f". {record['pr_url']}" if record.get("pr_url") else ".")


# ------------------------------------------------------------- the run record
def save_product(run_id: str, sha: str) -> None:
    """Fill 3-product/: final-commit.txt, and every screenshot from the report folders in screenshots/.

    The report folders themselves (Step 7's verify reports, the red checks,
    the full-suite runs) are already in 3-product/reports/.
    """
    product = runs.run_dir(run_id) / "3-product"
    atomic_write(product / "final-commit.txt", sha + "\n")
    shots = product / "screenshots"
    pgit.rmtree(shots)
    reports = product / "reports"
    if not reports.is_dir():
        return
    for p in sorted(reports.rglob("*")):
        if p.is_file() and not p.is_symlink() and p.suffix.lower() in SCREENSHOT_SUFFIXES:
            rel = p.relative_to(reports)
            shots.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, shots / "--".join(rel.parts), follow_symlinks=False)


def session_count(run_id: str) -> int:
    """How many Claude sessions the run used (one line per session in usage.jsonl, Step 3)."""
    p = runs.run_dir(run_id) / "usage.jsonl"
    try:
        return sum(1 for ln in p.read_text().splitlines() if ln.strip())
    except OSError:
        return 0


def suite_line(suite: dict, when: str) -> str:
    """One line about the full suite at the start or the end of a run."""
    result = suite.get(when) or "not run"
    words = {"green": "green (all tests passed)", "skipped": "skipped (new project)",
             "none": "no test script in package.json", "not run": "not run"}
    if result == "red":
        text = f"red: {suite.get(f'{when}_test') or 'unknown test'}"
        if when == "end" and suite.get("end_tries", 1) > 1:
            text += f" (still red after {suite['end_tries']} runs)"
        return text
    return words.get(result, result)


def step_lines(record: dict) -> list[str]:
    """One line per step: status, tries and reason."""
    lines = []
    for e in record.get("steps", []):
        if not isinstance(e, dict):
            continue
        tries = e.get("tries", 0)
        line = (f"Step {e.get('number')}: {e.get('title', '')} — {e.get('status', 'pending')}, "
                f"{tries} {'try' if tries == 1 else 'tries'}")
        reason = (e.get("reason") or "").replace("\n", " ").strip()
        lines.append(line + (f" ({reason})" if reason else ""))
    return lines


def for_you_items(plan: pplan.Plan | None) -> list[tuple[str, list[str]]]:
    """The `For you: yes` steps: (heading, the things to do) for each."""
    if plan is None:
        return []
    items = []
    for step in pplan.plan_order(plan):
        if step.for_you:
            what = [ln.strip() for ln in step.description.strip().splitlines() if ln.strip()]
            items.append((f"Step {step.number}: {step.title}", what + [f"Done when: {b}" for b in step.done_when]))
    return items


def summary_facts(record: dict, plan: pplan.Plan | None, pr_text: str | None = None) -> dict:
    """Everything the summary shows, as plain values (shared by summary.md and summary.html)."""
    suite = record.get("full_suite") if isinstance(record.get("full_suite"), dict) else {}
    return {
        "name": (plan.name if plan else "") or record.get("plan_name") or "(no name)",
        "run_id": record["run_id"],
        "status": record.get("status", ""),
        "reason": record.get("reason") or "",
        "repo": record.get("repo", ""),
        "branch": record.get("branch") or "",
        "pr": pr_text if pr_text is not None else (record.get("pr_url") or "none"),
        "suite_start": suite_line(suite, "start"),
        "suite_end": suite_line(suite, "end"),
        "steps": step_lines(record),
        "cost": f"${float(record.get('cost_usd') or 0):.2f}",
        "sessions": str(session_count(record["run_id"])),
        "for_you": for_you_items(plan),
    }


def summary_markdown(record: dict, plan: pplan.Plan | None = None, pr_text: str | None = None) -> str:
    """The run summary as Markdown (summary.md, and the PR body)."""
    f = summary_facts(record, plan, pr_text)
    out = [f"# Phoenix run {f['run_id']}: {f['name']}", "",
           f"- Status: {f['status']}" + (f" ({f['reason']})" if f["reason"] else ""),
           f"- Repo: {f['repo']}", f"- Branch: {f['branch'] or 'none'}", f"- Pull request: {f['pr']}",
           f"- Full suite at the start: {f['suite_start']}", f"- Full suite at the end: {f['suite_end']}",
           f"- Cost: {f['cost']} in {f['sessions']} Claude session(s)", "", "## Steps", ""]
    out += [f"- {line}" for line in f["steps"]] or ["- (no steps were run)"]
    out += ["", "## Things only you can do", ""]
    if not f["for_you"]:
        out.append("Nothing.")
    for heading, what in f["for_you"]:
        out.append(f"- {heading}")
        out += [f"  - {w}" for w in what]
    return "\n".join(out) + "\n"


def summary_html(record: dict, plan: pplan.Plan | None = None) -> str:
    """The same summary as plain HTML (no JavaScript), from templates/summary.html."""
    f = summary_facts(record, plan)
    e = html.escape
    pr = f["pr"]
    pr_html = f'<a href="{e(pr)}">{e(pr)}</a>' if pr.startswith("https://") else e(pr)
    steps = "\n".join(f"<li>{e(line)}</li>" for line in f["steps"]) or "<li>(no steps were run)</li>"
    if f["for_you"]:
        for_you = "\n".join(f"<li>{e(h)}<ul>" + "".join(f"<li>{e(w)}</li>" for w in what) + "</ul></li>"
                            for h, what in f["for_you"])
        for_you = f"<ul>\n{for_you}\n</ul>"
    else:
        for_you = "<p>Nothing.</p>"
    values = {
        "title": e(f"Phoenix run {f['run_id']}: {f['name']}"),
        "status": e(f["status"] + (f" ({f['reason']})" if f["reason"] else "")),
        "repo": e(f["repo"]), "branch": e(f["branch"] or "none"), "pr": pr_html,
        "suite_start": e(f["suite_start"]), "suite_end": e(f["suite_end"]),
        "cost": e(f["cost"]), "sessions": e(f["sessions"]), "steps": steps, "for_you": for_you,
    }
    text = HTML_TEMPLATE.read_text()
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def write_summary(record: dict, plan: pplan.Plan | None = None) -> None:
    """Write summary.md and summary.html in the run folder."""
    if plan is None and record.get("plan_path"):
        try:
            plan = checks.load_plan(record)
        except OSError:
            plan = None
    folder = runs.run_dir(record["run_id"])
    atomic_write(folder / "summary.md", summary_markdown(record, plan))
    atomic_write(folder / "summary.html", summary_html(record, plan))


# ------------------------------------------------------------- merge detection
def pr_state(record: dict, hands: Hands) -> str:
    """The PR's state from GitHub: MERGED, CLOSED, OPEN, or "" when gh could not tell."""
    r = hands.gh(["pr", "view", record["pr_url"], "--json", "state"])
    if r.returncode != 0:
        return ""
    try:
        return str(json.loads(r.stdout or "{}").get("state", "")).upper()
    except ValueError:
        return ""


def merged_into_main(record: dict) -> bool:
    """True when the run's final commit is in origin/main (after a fetch of Phoenix's own clone)."""
    sha = record.get("final_commit") or ""
    if not sha:
        return False
    clone = pgit.ensure_clone(record["repo"])
    r = pgit.run_git(clone, "merge-base", "--is-ancestor", sha, f"refs/remotes/origin/{pgit.MAIN}", check=False)
    return r.returncode == 0


def check_merged(run_id: str, *, hands: Hands | None = None) -> str:
    """For a `done` run with a PR: `merged` when the owner merged it, `abandoned` when closed unmerged.

    Only the status changes. Returns the (possibly new) status.
    """
    hands = hands or Hands()
    record = runs.load_run(run_id)
    if record.get("status") != "done" or not record.get("pr_url"):
        return record.get("status", "")
    try:
        merged = merged_into_main(record)
    except pgit.GitError as e:
        log(run_id, f"merge check: could not fetch: {e}")
        merged = False
    state = "MERGED" if merged else pr_state(record, hands)
    new = {"MERGED": "merged", "CLOSED": "abandoned"}.get(state)
    if not new:
        return "done"
    note_run(run_id, status=new)
    log(run_id, f"pull request {record['pr_url']} is {state.lower()}: run {new}")
    return new
