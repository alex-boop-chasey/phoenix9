"""Running planning sessions (a safety file): the runner service picks up queued plans and runs each one in a
sealed step container, exactly like the Planner step. Nothing here starts Claude on the host (rule 1).

The container: firewall on (only api.anthropic.com), no-new-privileges, the non-root session user, no Docker
socket, no GitHub token, no project keys, no key proxy; its env is the claude env file only.
Mounts: /workspace read-only = a standalone copy of the project's repo (HOME/work/plan-<id>/code, never the
live code/ folder), /project/CLAUDE.md and /project/notes read-only, /out writable = HOME/plans/<id>/out/,
HOME/plans/<id>/claude/ as the session user's ~/.claude/projects (so `--resume` works; cwd is always /workspace).
Phoenix then checks /out/spec.md itself (spec.check, up to 2 fix rounds in the same session) and files it at
notes/specs/plan-<id>.md, a path Phoenix picks.
"""
from __future__ import annotations

import os
import stat
import sys
import tomllib
from pathlib import Path

from phoenix9 import atomic, docker as docker_mod, events, git, hold, paths, pause, plans, scrub, settings, spec
from phoenix9 import claude as claude_mod

STEP = "_plan-session"
ROLE = "plan"
MAX_FIX_ROUNDS = 2
SPEC_MAX_BYTES = 1_000_000
FALLBACK_PROFILE = "python-script"
DOMAINS = ("api.anthropic.com",)


class PlanFailed(Exception):
    """The planning session could not finish; the message is plain words for Alex."""


def step_dir() -> Path:
    """The library step folder of the planning session (steps/_plan-session/)."""
    return paths.library() / "steps" / STEP


def step_ai(model: str) -> dict:
    """The step's [ai] block with the plan's model first (the step's own models become fallbacks)."""
    data = tomllib.loads((step_dir() / "step.toml").read_text(encoding="utf-8"))
    ai = dict(data.get("ai") or {})
    models = [m for m in [model, ai.get("model"), *(ai.get("fallback_models") or [])] if m]
    ai["model"] = models[0]
    ai["fallback_models"] = [m for i, m in enumerate(models) if m not in models[:i]][1:]
    return ai


def image_for(project: str) -> str:
    """The step image: the project's profile image, else the python-script profile's."""
    from phoenix9.library import load_library
    try:
        values = settings.effective(paths.projects() / project, load_library(paths.library())).values
        name = values.get("profile") or ""
        image = settings.load_profile(paths.library(), name).get("image") if name else ""
    except Exception:            # noqa: BLE001 - a broken phoenix.toml only means the fallback image
        image = ""
    if not image:
        image = settings.load_profile(paths.library(), FALLBACK_PROFILE).get("image") or ""
    return image


def next_queued() -> dict | None:
    """The oldest queued planning session, or None."""
    queued = [r for r in plans.list_plans() if r.get("status") == "queued"]
    return min(queued, key=lambda r: ((r.get("job") or {}).get("queued") or r["started"], r["id"])) if queued else None


def requeue_stale() -> list[str]:
    """Plans left `running` by a runner that stopped (its container is gone): queue their job again."""
    moved = []
    for rec in plans.list_plans():
        if rec.get("status") == "running":
            plans.update(rec["id"], lambda r: r.update(status="queued") if r["status"] == "running" else None)
            moved.append(rec["id"])
    return moved


def run_next(adapters) -> str | None:
    """Run the oldest queued planning session to its end (one at a time); returns its id, or None."""
    if hold.hold_requested():
        return None                  # an update holds the harness: nothing new starts
    rec = next_queued()
    if rec is None:
        return None
    claimed = []

    def claim(r):
        if r["status"] == "queued":
            r.update(status="running", last_activity=plans._now())
            claimed.append(True)
    rec = plans.update(rec["id"], claim)
    if not claimed:
        return None
    events.emit("plan.started", project=rec["project"], plan=rec["id"], model=rec.get("model"), who=rec.get("who"))
    try:
        run_job(adapters, rec)
    except PlanFailed as err:
        _finish(rec["id"], "failed", str(err))
    except Exception as err:  # noqa: BLE001 - the runner loop must keep going
        print(f"phoenix runner: planning session {rec['id']} crashed: {type(err).__name__}: {err}",
              file=sys.stderr, flush=True)
        _finish(rec["id"], "failed", scrub.scrub(f"Phoenix hit an error: {type(err).__name__}: {err}")[:300])
    return rec["id"]


def _finish(plan_id: str, status: str, report: str, **fields) -> dict:
    """Set the plan's final status for this job, drop the job, and emit plan.<status>."""
    def change(r):
        r.update(status=status, report=report, last_activity=plans._now(), **fields)
        r.pop("job", None)
    rec = plans.update(plan_id, change)
    events.emit(f"plan.{status}", project=rec["project"], plan=plan_id, spec=rec.get("spec"),
                open_questions=rec.get("open_questions"))
    return rec


def _read_regular(path: Path, what: str) -> str:
    """The text of a regular file, never following a link; PlanFailed when it is a link, missing or too big."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise PlanFailed(f"{what} is missing or is a link.") from None
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise PlanFailed(f"{what} is not a plain file.")
        data = f.read(SPEC_MAX_BYTES + 1)
    if len(data) > SPEC_MAX_BYTES:
        raise PlanFailed(f"{what} is too big.")
    return data.decode("utf-8", errors="replace")


def _specs_dir(project: str) -> Path:
    """The project's notes/specs folder (made when missing); PlanFailed when any part is a link or leaves the project."""
    root = paths.projects() / project
    real_root = root.resolve()
    for part in (root / "notes", root / "notes" / "specs"):
        if part.is_symlink():
            raise PlanFailed(f"{part} is a link, so Phoenix will not write the spec there.")
        part.mkdir(exist_ok=True)
    folder = root / "notes" / "specs"
    if not folder.resolve().is_relative_to(real_root):
        raise PlanFailed(f"{folder} is outside the project folder.")
    return folder


def spec_target(rec: dict) -> Path:
    """Where Phoenix files this plan's spec (notes/specs/plan-<id>.md); PlanFailed on a link."""
    target = _specs_dir(rec["project"]) / Path(plans.spec_name(rec["id"])).name
    if target.is_symlink():
        raise PlanFailed(f"{target} is a link, so Phoenix will not write the spec there.")
    return target


def _seed_out(rec: dict, out: Path, kind: str) -> None:
    """A fresh /out folder; on continue it holds the current filed spec (with Alex's answers) as /out/spec.md."""
    git.rmtree(out)
    out.mkdir(parents=True)
    if kind == "continue":
        target = spec_target(rec)
        if target.is_file():
            atomic.write_text(out / "spec.md", _read_regular(target, "The filed spec"), mode=0o644)


def _context_mounts(project: str) -> list:
    """The project's CLAUDE.md and notes/ read-only at /project (links are never mounted)."""
    root = paths.projects() / project
    mounts = []
    for name in ("CLAUDE.md", "notes"):
        src = root / name
        if src.exists() and not src.is_symlink() and src.resolve().is_relative_to(root.resolve()):
            mounts.append(docker_mod.Mount(src, f"/project/{name}", ro=True))
    return mounts


def _workspace(project: str, work: Path) -> Path:
    """A standalone copy of the project's repo (never the live code/ folder); an empty folder when there is none."""
    git.rmtree(work)
    code = paths.projects() / project / "code"
    dest = work / "code"
    if (code / ".git").exists() and not code.is_symlink():
        try:
            return git.snapshot_clone(code, dest)
        except git.GitError:
            git.rmtree(dest)
    dest.mkdir(parents=True)
    return dest


def _spent(rec: dict) -> float:
    return float((rec.get("usage") or {}).get("cost_usd") or 0.0)


def _check_budget(plan_id: str) -> None:
    rec = plans.load(plan_id)
    cap = float(rec.get("budget_usd") or plans.plan_budget())
    if _spent(rec) >= cap:
        raise PlanFailed(f"This planning session has used ${_spent(rec):.2f} of its ${cap:.2f} spending cap "
                         "(setting plan.budget_usd), so Phoenix stopped it.")


def run_job(adapters, rec: dict) -> dict:
    """Run the plan's queued job in step containers, check and file the spec; returns the final record."""
    plan_id, project = rec["id"], rec["project"]
    job = rec.get("job") or {}
    resume = job.get("resume")
    if resume is not None and not pause.valid_session_id(str(resume)):
        raise PlanFailed("The planning session's id is not a Claude session id, so it cannot be resumed.")
    image = image_for(project)
    if not image or not adapters.docker.image_exists(image):
        raise PlanFailed(f"The step image {image or '(none)'} is not built. Run `phoenix images build --all`.")
    folder = plans.plan_folder(plan_id)
    out, sessions = folder / "out", folder / "claude"
    sessions.mkdir(parents=True, exist_ok=True)
    work = paths.home() / "work" / f"plan-{plan_id}"
    domains = folder / "allowed-domains"
    atomic.write_text(domains, "".join(f"{d}\n" for d in DOMAINS), mode=0o644)
    prompt = plans.prompt_file(plan_id).read_text(encoding="utf-8")
    ai = step_ai(rec.get("model") or plans.plan_model())
    try:
        _seed_out(rec, out, job.get("kind") or "start")
        workspace = _workspace(project, work)
        mounts = [docker_mod.Mount(out, "/out", ro=False), *_context_mounts(project)]
        docker_mod.hand_writable_mounts(adapters.docker, mounts)
        problems: list[str] = []
        for round_no in range(1 + MAX_FIX_ROUNDS):
            _check_budget(plan_id)
            session_prompt = folder / "session-prompt.md"
            atomic.write_text(session_prompt, prompt, mode=0o644)
            result = adapters.claude.launch(
                adapters.docker, ai=ai, project=project, run_id=f"plan-{plan_id}", task=0, attempt=round_no + 1,
                role=ROLE, image=image, workspace=workspace, prompt_file=session_prompt, step_dir=step_dir(),
                project_dir=paths.projects() / project, domains_file=domains, workspace_ro=True,
                extra_mounts=mounts, resume_session=resume, session_dir=sessions,
                log_file=plans.session_file(plan_id))
            claude_mod.record_usage(None, result, update=lambda fn: plans.update(plan_id, fn))
            if result.kind != "ok":
                why = ("Claude's usage limit was hit; continue it later with `phoenix plan continue`."
                       if result.kind == "rate_limited" else f"The planning session ended before it finished ({result.kind}).")
                raise PlanFailed(why)
            if not pause.valid_session_id(result.session_id or ""):
                raise PlanFailed("The planning session gave no Claude session id, so it cannot be continued.")
            resume = result.session_id
            plans.update(plan_id, lambda r: r.update(session_id=resume, last_activity=plans._now()))
            try:
                text = _read_regular(out / "spec.md", "The session's /out/spec.md")
                problems = spec.check(text)
            except PlanFailed as err:
                text, problems = "", [str(err)]
            if not problems:
                break
            if round_no < MAX_FIX_ROUNDS:
                prompt = plans.problems_prompt(problems)
        else:
            shown = "; ".join(problems[:3]) + (" and more" if len(problems) > 3 else "")
            raise PlanFailed(f"The spec still has problems after {MAX_FIX_ROUNDS} rounds of fixes: {shown}"[:600])
        target = spec_target(rec)
        atomic.write_text(target, text, mode=0o644)
        rel = plans.spec_name(plan_id)
        n = plans.count_open(text)
        return _finish(plan_id, "waiting" if n else "done", f"{rel}, {n} open questions", spec=rel, open_questions=n)
    finally:
        git.rmtree(work)
