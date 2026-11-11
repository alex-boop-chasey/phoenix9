"""A seeded temp HOME for search tests: two projects with notes, research, a run and a log."""
from phoenix9 import atomic, keys, paths, settings

SECRET = "fake-secret-value-12345"
RUN = "20261108-073122-moon-landing"


def make_project(name: str, about: str):
    """A project folder with a CLAUDE.md and an empty notes folder."""
    folder = paths.projects() / name
    (folder / "notes" / "research").mkdir(parents=True)
    (folder / "CLAUDE.md").write_text(f"# {name}\n\n{about}\n\n- Profile: python-script\n- Repo: (none yet)\n")
    settings.save_project(folder, {"profile": "python-script"})
    return folder


def seed() -> dict:
    """Two projects; alpha has a note, research, a run with a spec and a log holding a secret; beta has a note."""
    alpha = make_project("alpha", "A telescope booking site.")
    beta = make_project("beta", "A garden planner.")
    (alpha / "notes" / "ideas.md").write_text("# Ideas\n\nWe could add a zebra mode later.\n")
    (alpha / "notes" / "research" / "tides.md").write_text("# Tide tables\n\nOcean tides follow the moon.\n")
    (beta / "notes" / "plan.txt").write_text("compost bin layout\n")
    run_dir = paths.runs("alpha") / RUN
    (run_dir / "logs").mkdir(parents=True)
    atomic.write_json(run_dir / "state.json", {"run_id": RUN, "project": "alpha", "status": "failed",
                                               "created": "2026-11-08T07:31:22", "updated": "2026-11-08T07:40:00",
                                               "tasks": {}})
    (run_dir / "spec.md").write_text("# Lunar landing page\n\nBuild it.\n")
    keys.set_key("alpha", "TOKEN", SECRET, secret=True)
    (run_dir / "logs" / "build.log").write_text(f"started\nquokka crashed with token {SECRET}\nended\n")
    return {"alpha": alpha, "beta": beta, "run": RUN}
