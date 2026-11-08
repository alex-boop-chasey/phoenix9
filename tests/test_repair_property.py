"""Property test for repair notes: random valid notes on several fixture runs either pass the check or change nothing."""
import hashlib
import json
import random
import shutil

import pytest
from helpers.repair_runs import RUN, make_run, sh

from phoenix9 import atomic, gates, git, paths, resolve, settings, state
from phoenix9.library import load_library
from phoenix9.repair import apply, check, snapshot
from phoenix9.repair.snapshot import RepairRefused

SPEC = "# Demo\n\nProject: demo\n\n## About\nA test project.\n\n## Task 1: One\nDo one.\n\nDone when:\n- page one shows its heading\n"
SKIP_TOP = ("repairs", "events.jsonl", "run.lock", "stop-request.json")
SEEDS = range(40)
KINDS = ("failed", "waiting", "stopped")


def make(tmp_path, kind):
    """A healthy run of this kind with three tasks, real settings and plan, commits and a dirty worktree."""
    r = make_run(tmp_path, status="failed" if kind == "failed" else kind)
    run_dir, work = r["run_dir"], r["work"]
    shutil.rmtree(run_dir / "gates")
    shutil.rmtree(run_dir / "tasks")
    lib = load_library(paths.library())
    eff = settings.effective(paths.projects() / r["project"], lib)
    atomic.write_json(run_dir / "settings.json", eff.values)
    atomic.write_json(run_dir / "plan.json", resolve.resolve(lib, settings.enabled_map(eff)).to_json())
    shas = [git.head(work)]
    for n in (1, 2):
        (work / f"f{n}.txt").write_text(f"{n}\n")
        sh(work, "add", "-A")
        sh(work, "commit", "-qm", f"task {n}")
        shas.append(git.head(work))
    tasks = {"1": dict(state.new_task("One"), status="passed", tries=1, attempt_base=shas[0]),
             "2": dict(state.new_task("Two", [1]), status="failed", tries=2, attempt_base=shas[1], failures=["bad"]),
             "3": dict(state.new_task("Three", [2]), status="skipped", note="depends on task 2, which failed")}
    atomic.write_json(run_dir / "spec.json", {"title": "Demo", "tasks": [
        {"number": int(n), "title": t["title"], "depends_on": t["depends_on"]} for n, t in tasks.items()]})

    def change(s):
        s["tasks"] = tasks
        s["steps"] = [{"group": "task", "task": 2, "step": "builder", "status": "failed", "attempt": 2, "note": ""}]
        s["current"] = {"group": None, "task": 2, "step": None, "attempt": None, "gate": None}
    state.update(run_dir, change)
    for n, k, status in ((2, 1, "failed"), (2, 2, "failed"), (1, 1, "passed")):
        (run_dir / f"tasks/{n}/attempt-{k}").mkdir(parents=True)
        atomic.write_json(run_dir / f"tasks/{n}/attempt-{k}/result.json", {"attempt": k, "status": status})
    if kind == "waiting":
        def wait(s):
            s["tasks"]["2"].update(status="waiting", tries=2)
            s["steps"] = [{"group": "task", "task": 2, "step": "ask", "status": "waiting", "attempt": 2, "note": ""}]
        state.update(run_dir, wait)
        gate = gates.open_gate(run_dir, kind="escalation", title="stuck", why="tries used up", task=2, step="ask")
        state.update(run_dir, lambda s: s["current"].update(gate=gate["id"]))
        atomic.write_json(run_dir / "tasks/2/attempt-2/result.json", {"attempt": 2, "status": "waiting"})
        r["gate"] = gate
    if kind == "stopped":
        state.update(run_dir, lambda s: s["tasks"]["2"].update(status="failed"))
    (work / "f2.txt").write_text("dirty\n")                    # uncommitted work in the worktree
    (work / "stray.txt").write_text("untracked\n")
    spec_dir = paths.projects() / r["project"] / "notes"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "new-spec.md").write_text(SPEC)
    r.update(shas=shas)
    return r


def fingerprint(r):
    """Hash of every run file (except the repair bookkeeping) and gates/, plus the worktree HEAD and all its content."""
    out = {}
    run_dir = r["run_dir"]
    for p in sorted(run_dir.rglob("*")):
        rel = p.relative_to(run_dir)
        if rel.parts[0] in SKIP_TOP or not p.is_file():
            continue
        out[f"run/{rel}"] = hashlib.sha256(p.read_bytes()).hexdigest()
    work = r["work"]
    out["head"] = git.head(work)
    out["branches"] = sh(work, "branch", "--list")
    out["status"] = sh(work, "status", "--porcelain", "--untracked-files=all")
    for p in sorted(work.rglob("*")):
        rel = p.relative_to(work)
        if rel.parts[0] != ".git" and p.is_file():
            out[f"work/{rel}"] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def random_steps(rng, r):
    """2 to 6 steps from the vocabulary, with task numbers, shas and settings from the fixture."""
    n = lambda: rng.choice((1, 2, 3, 4))
    sha = lambda: rng.choice(r["shas"] + ["deadbeef"])
    forms = [
        lambda: f"redo task {n()} from scratch",
        lambda: f"mark task {n()} done because someone checked",
        lambda: f"mark task {n()} skipped because not needed",
        lambda: f"retry task {n()}",
        lambda: f"clear failures of task {n()}",
        lambda: f"add a note to task {n()}: try the other way",
        lambda: f"set {rng.choice(['max_tries', 'on_failure', 'nonsense'])}={rng.choice(['3', '5', '\"continue\"', '\"stop\"'])} for this run",
        lambda: f"turn off step {rng.choice(['reviewer', 'diff-rules', 'nothing'])} for this run",
        lambda: "replace the spec with notes/new-spec.md",
        lambda: 'keep my hand fix with message "hand fix"',
        lambda: f"reset the worktree to {sha()}",
        lambda: "rebuild the worktree",
        lambda: f"close question {r.get('gate', {}).get('id', RUN + '.9')} as {rng.choice(['closed', 'approve', 'skip', 'odd'])}",
        lambda: f"rewrite the checks of task {n()} because the bullet is wrong",
        lambda: "rerun finish step summary",
        lambda: "resume",
    ]
    return [rng.choice(forms)() for _ in range(rng.randint(2, 6))]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("seed", SEEDS)
def test_random_notes_pass_or_change_nothing(tmp_path, kind, seed):
    r = make(tmp_path, kind)
    assert check.run_checks(r["run_dir"]) == []
    rng = random.Random(f"{kind}-{seed}")
    lines = random_steps(rng, r)
    note = tmp_path / "note.md"
    note.write_text(f"# Repair {r['run']}\n\nWhy: random {seed}\n\n## Steps\n\n" + "\n".join(f"- {s}" for s in lines) + "\n")
    before = fingerprint(r)
    try:
        info = apply.apply(note, "property")
    except RepairRefused:
        assert fingerprint(r) == before, lines
        return
    if info["rolled_back"] or info["refused"]:
        assert info["rolled_back"], lines
        assert fingerprint(r) == before, lines
    else:
        assert check.run_checks(r["run_dir"]) == [], lines
