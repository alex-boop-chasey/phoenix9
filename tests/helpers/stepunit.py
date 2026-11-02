"""Shared set-up for tests that call one real step's run() on a temp git worktree."""
import importlib.util
import subprocess
from pathlib import Path

from phoenix9 import atomic, settings, state
from phoenix9.stepctx import ProjectInfo, RunInfo, StepContext, StepInfo

REPO = Path(__file__).resolve().parents[2]


def git(cwd, *args):
    """Run git in cwd (test identity) and return stdout."""
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          check=True, capture_output=True, text=True).stdout


def load(step):
    """Import steps/<step>/run.py as a module."""
    spec = importlib.util.spec_from_file_location(f"{step}_run", REPO / "steps" / step / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_work(tmp_path) -> Path:
    """A temp repo with one commit."""
    w = tmp_path / "work"
    w.mkdir()
    git(w, "init", "-q", "-b", "main")
    (w / "README.md").write_text("x\n")
    git(w, "add", "-A")
    git(w, "commit", "-q", "-m", "first")
    return w


def write(work, files):
    """Write {path: text} into the worktree."""
    for name, text in files.items():
        (work / name).parent.mkdir(parents=True, exist_ok=True)
        (work / name).write_text(text)


def make_ctx(tmp_path, adapters, work, step, project_settings=None, profile="python-script") -> StepContext:
    """A step context whose run folder has a state file with attempt_base = the worktree's HEAD."""
    run_dir = tmp_path / "run"
    atomic.write_json(run_dir / "state.json", state.new_state("r", "proj", {"1": state.new_task("T")}))
    state.set_task(run_dir, 1, attempt_base=git(work, "rev-parse", "HEAD").strip())
    task = {"number": 1, "title": "Add a", "goal": "g", "done_when": []}
    return StepContext(
        project=ProjectInfo("proj", tmp_path, tmp_path / "code", project_settings or {},
                            settings.load_profile(REPO, profile)),
        run=RunInfo("r", run_dir, {"title": "T"}), step=StepInfo(step, "script"), task=task, attempt=1,
        worktree=work, things={}, adapters=adapters, emit=lambda *a, **k: None, log=lambda t: None)
