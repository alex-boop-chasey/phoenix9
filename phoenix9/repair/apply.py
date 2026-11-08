"""The apply engine: check a repair note, snapshot, apply its steps under the run lock, check again, roll back on failure."""
import re
import tempfile
from pathlib import Path

from phoenix9 import atomic, events, runend, runs as core, scrub
from phoenix9.repair import check, notes, snapshot, steps
from phoenix9.repair.snapshot import RepairRefused



def slug_of(text: str) -> str:
    """A short file-name-safe slug of a title."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].strip("-") or "repair"


def _read_note(note_path) -> tuple[Path, str, notes.Note]:
    """Read and parse the note file; refuse with a plain message when it cannot be read."""
    path = Path(note_path)
    try:
        text = path.read_text(encoding="utf-8")
        return path, text, notes.parse(text)
    except OSError:
        raise RepairRefused(f"I cannot read the note {path}.") from None
    except notes.NoteError as err:
        raise RepairRefused(f"The note cannot be read: {err}") from None


def _problems(found) -> list[str]:
    """The finding texts of a check, in words."""
    return [f.text for f in found]


def _do_steps(ctx, note) -> tuple[list[str], str | None]:
    """Apply each step in order; return what each did and the reason of the first refused step (or None)."""
    done = []
    for step in note.steps:
        try:
            done.append(steps.run_step(ctx, step))
        except steps.StepRefused as err:
            return done, f"line {step.line}: {err}"
    return done, None


def _result_lines(info: dict) -> list[str]:
    """The '## Result' section body for a finished (or dry) run of a note."""
    def checks(items):
        return "no problems" if not items else "; ".join(items)
    lines = ["Dry run: nothing was changed." if info["dry_run"] else
             ("Rolled back: nothing was kept." if info["rolled_back"] else "Applied.")]
    if info.get("refused"):
        lines.append(f"- Refused: {info['refused']}")
    if info["snapshot"]:
        lines.append(f"- Snapshot: {info['snapshot']}")
    lines += [f"- Step {i}: {s}" for i, s in enumerate(info["steps"], 1)]
    lines.append(f"- Check before: {checks(info['check_before'])}")
    lines.append(f"- Check after: {checks(info['check_after'])}" if info["check_after"] is not None else
                 "- Check after: not run")
    if info["forced"]:
        lines.append("- Forced: the result was kept although the check found problems.")
    return lines


def _write_result(paths_to_write, info: dict) -> None:
    """Put the result into the '## Result' section of each note file."""
    for path in paths_to_write:
        try:
            atomic.write_text(path, notes.render_result(Path(path).read_text(encoding="utf-8"), _result_lines(info)))
        except OSError:
            pass


def _dry_run(run_dir: Path, path: Path, note, approve_unlock: bool, who: str) -> dict:
    """Run the steps on a scratch copy of the run folder and report; the real run and worktree stay as they were."""
    with tempfile.TemporaryDirectory(prefix="phoenix-dry-") as tmp:
        scratch = Path(tmp) / run_dir.parent.name / run_dir.name
        snapshot.scratch_copy(run_dir, scratch)
        before = _problems(check.run_checks(scratch, as_run=run_dir))
        ctx = steps.Context(scratch, dry=True, approve_unlock=approve_unlock, who=who)
        done, refused = _do_steps(ctx, note)
        after = None if refused else _problems(check.run_checks(scratch, as_run=run_dir))
    new = [p for p in after or [] if p not in before]
    info = {"ok": not refused and (not new or note.force), "dry_run": True, "run_id": run_dir.name,
            "project": run_dir.parent.name, "snapshot": None, "steps": done, "refused": refused,
            "check_before": before, "check_after": after, "forced": note.force and bool(new),
            "rolled_back": False, "would_roll_back": bool(refused or (new and not note.force))}
    _write_result([path], info)
    return info


def _enter_lock(run_dir: Path):
    """Take the run lock, or refuse because the runner is walking the run."""
    try:
        lock = runend.lock(run_dir, wait=snapshot.LOCK_WAIT_S)
        lock.__enter__()
    except TimeoutError:
        raise RepairRefused(snapshot.WALKING_MESSAGE) from None
    return lock


def _record(run_dir: Path, who: str, copy: Path, note, info: dict) -> None:
    """Write the repair.applied event, the commands.jsonl line and the changelog line."""
    from phoenix9.ops import common
    project, run = run_dir.parent.name, run_dir.name
    events.emit("repair.applied", project=project, run=run, who=who, note=copy.name, title=note.why,
                steps=[s.text for s in note.steps], check_before=info["check_before"],
                check_after=info["check_after"], forced=info["forced"], rolled_back=info["rolled_back"],
                snapshot=info["snapshot"])
    outcome = "rolled back" if info["rolled_back"] else "applied"
    common.record_command(who, f"repair apply {copy.name}", project,
                          f"repair on run {run}: {scrub.scrub(note.why)} ({outcome}, snapshot {info['snapshot']})")


def _apply_locked(run_dir: Path, note, approve_unlock: bool, who: str) -> dict:
    """Under the run lock: apply the steps and check the result."""
    snapshot.refuse_if_walking(run_dir, lock_ok=True)
    ctx = steps.Context(run_dir, approve_unlock=approve_unlock, who=who)
    done, refused = _do_steps(ctx, note)
    after = None if refused else _problems(check.run_checks(run_dir))
    return {"steps": done, "refused": refused, "check_after": after}


def apply(note_path, who: str, dry_run: bool = False, approve_unlock: bool = False) -> dict:
    """Apply a repair note to its run (or, with dry_run, only report what it would do) and return the outcome."""
    path, _text, note = _read_note(note_path)
    run_dir = core.find_run(note.run)
    if run_dir is None:
        raise RepairRefused(f"There is no run called '{note.run}'.")
    if any(s.kind == "rerun-finish" and s.args.get("name") == "merge" for s in note.steps) and (
            len(note.steps) > 1 or note.force):
        raise RepairRefused("'rerun finish step merge' must be the only step of its note (and without force): "
                            "apply the other steps first, then merge in a note of its own.")
    if steps.is_chat(who) and (note.force or approve_unlock):
        what = "force a repair past its check" if note.force else "unlock locked checks"
        raise RepairRefused(f"Needs Alex: a chat session may not {what}. Ask Alex to apply this note from the dashboard.")
    snapshot.refuse_if_walking(run_dir)
    if dry_run:
        return _dry_run(run_dir, path, note, approve_unlock, who)
    n = snapshot.next_number(run_dir)
    copy = snapshot.repairs_dir(run_dir) / "notes" / f"{n}-{slug_of(note.why)}.md"
    atomic.write_text(copy, path.read_text(encoding="utf-8"))
    before = _problems(check.run_checks(run_dir))
    try:
        got = snapshot.take(run_dir, note.why)
    except snapshot.SnapshotError as err:
        raise RepairRefused(str(err)) from None
    lock = _enter_lock(run_dir)
    try:
        res = _apply_locked(run_dir, note, approve_unlock, who)
        new = [p for p in res["check_after"] or [] if p not in before]
        failed = bool(res["refused"] or new)
        rolled_back = failed and not (note.force and not res["refused"])
        if rolled_back:
            snapshot.roll_back(run_dir, got)
    finally:
        lock.__exit__(None, None, None)
    info = {"ok": not rolled_back, "dry_run": False, "run_id": run_dir.name, "project": run_dir.parent.name,
            "snapshot": got, "check_before": before, "forced": failed and not rolled_back,
            "rolled_back": rolled_back, "note": str(copy), **res}
    _record(run_dir, who, copy, note, info)
    _write_result([copy, path], info)
    return info
