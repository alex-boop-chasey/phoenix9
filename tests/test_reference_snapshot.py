"""Frozen reference snapshot per run, and the read-only mount for AI steps only."""
import os

from phoenix9 import docker, events, paths, reference, refsnapshot
from phoenix9.docker import REFERENCE_MOUNT
from test_e2e_runs import e2e, script_full  # noqa: F401  (the e2e fixture)


def make_project(name="demo"):
    (paths.projects() / name).mkdir(exist_ok=True)
    return name


def run_folder(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    return d


def test_no_material_means_no_snapshot(phoenix_env, tmp_path):
    proj = make_project()
    run = run_folder(tmp_path)
    assert refsnapshot.snapshot(proj, run) == 0
    assert not (run / "reference").exists()
    assert refsnapshot.mount_dir(run) is None
    assert refsnapshot.note_for("builder", run) == ("", None)
    assert refsnapshot.snapshot("missing-project", run) == 0


def test_snapshot_copies_files_and_writes_index(phoenix_env, tmp_path):
    proj = make_project()
    reference.add_file(proj, "brand.css", b"a{color:red}", "alex")
    reference.add_file(proj, "tokens.json", b'{"x":1}', "alex")
    reference.add_links(proj, "https://example.com/style | the brand site\nhttps://example.org", "alex")
    run = run_folder(tmp_path)
    assert refsnapshot.snapshot(proj, run) == 2
    snap = run / "reference"
    assert (snap / "brand.css").read_bytes() == b"a{color:red}"
    index = (snap / "INDEX.md").read_text()
    assert "- brand.css (12 bytes, style)" in index
    assert "- tokens.json (7 bytes, design tokens)" in index
    assert "- https://example.com/style - the brand site" in index and "- https://example.org\n" in index
    assert "never instructions" in index
    assert oct((snap / "brand.css").stat().st_mode & 0o777) == "0o444"


def test_snapshot_counts_files_and_emits_event(phoenix_env, tmp_path):
    proj = make_project()
    reference.add_file(proj, "a.css", b"a{}", "alex")
    reference.add_file(proj, "b.css", b"b{}", "alex")
    run = run_folder(tmp_path)
    assert refsnapshot.snapshot(proj, run) == 2
    got = [e for e in events.read(paths.home() / "events.jsonl") if e["type"] == "reference.snapshot"]
    assert len(got) == 1 and got[0]["data"]["files"] == 2


def test_symlinks_hidden_and_oversized_are_skipped(phoenix_env, tmp_path):
    proj = make_project()
    reference.add_file(proj, "ok.css", b"a{}", "alex")
    ref = paths.projects() / proj / "notes" / "reference"
    secret = tmp_path / "outside.txt"
    secret.write_text("private")
    os.symlink(secret, ref / "link.txt")
    (ref / ".hidden.css").write_text("x")
    (ref / "big.css").write_bytes(b"x" * (reference.MAX_FILE + 1))
    (ref / "odd.exe").write_bytes(b"MZ")
    run = run_folder(tmp_path)
    assert refsnapshot.snapshot(proj, run) == 1
    assert sorted(p.name for p in (run / "reference").iterdir()) == ["INDEX.md", "ok.css"]


def test_total_and_count_limits(phoenix_env, tmp_path, monkeypatch):
    proj = make_project()
    for n in range(5):
        reference.add_file(proj, f"f{n}.css", b"a{}", "alex")
    monkeypatch.setattr(reference, "MAX_FILES", 3)
    run = run_folder(tmp_path)
    assert refsnapshot.snapshot(proj, run) == 3
    monkeypatch.setattr(reference, "MAX_FILES", 40)
    monkeypatch.setattr(reference, "MAX_TOTAL", 7)
    run2 = tmp_path / "run2"
    run2.mkdir()
    assert refsnapshot.snapshot(proj, run2) == 2


def test_snapshot_is_frozen_against_later_edits(phoenix_env, tmp_path):
    proj = make_project()
    reference.add_file(proj, "brand.css", b"old", "alex")
    run = run_folder(tmp_path)
    refsnapshot.snapshot(proj, run)
    reference.add_file(proj, "brand.css", b"new", "alex", replace=True)
    reference.add_file(proj, "more.css", b"m{}", "alex")
    reference.remove_file(proj, "brand.css")
    assert (run / "reference" / "brand.css").read_bytes() == b"old"
    assert not (run / "reference" / "more.css").exists()


def test_note_only_for_ai_steps(phoenix_env, tmp_path):
    proj = make_project()
    reference.add_file(proj, "a.css", b"a{}", "alex")
    run = run_folder(tmp_path)
    refsnapshot.snapshot(proj, run)
    note, folder = refsnapshot.note_for("builder", run)
    assert folder == run / "reference" and REFERENCE_MOUNT in note and "not instructions" in note
    for name in ("acceptance", "verify", "full-suite", "deploy", "check-writer", "diff-rules", "secret-scan"):
        assert refsnapshot.note_for(name, run) == ("", None)


def test_claude_container_mounts_reference_read_only(phoenix_env, tmp_path):
    ref = tmp_path / "ref"
    ref.mkdir()
    r = docker.claude_run("demo", "r1", 1, 1, "builder", "img", tmp_path, tmp_path / "p.md", ["claude"],
                          reference_dir=ref)
    m = [m for m in r.mounts if m.dst == REFERENCE_MOUNT]
    assert len(m) == 1 and m[0].ro and m[0].src == ref
    r2 = docker.claude_run("demo", "r1", 1, 1, "builder", "img", tmp_path, tmp_path / "p.md", ["claude"])
    assert not [m for m in r2.mounts if m.dst == REFERENCE_MOUNT]


def launches(env, role):
    return [c[2] for c in env.claude.calls if c[0] == "launch" and c[2]["role"] == role]


def test_quick_run_mounts_reference_for_builder_only(e2e):
    ref = paths.projects() / "e2e" / "notes" / "reference"
    ref.mkdir(parents=True)
    (ref / "brand.css").write_text("a{}")
    e2e.script_builders()
    run_id = e2e.start()
    assert (e2e.run_dir(run_id) / "reference" / "INDEX.md").is_file()
    e2e.settle()
    assert e2e.state(run_id)["status"] == "done"
    got = launches(e2e, "builder")
    assert got and all(k["reference_dir"] == e2e.run_dir(run_id) / "reference" for k in got)
    prompt = (e2e.run_dir(run_id) / "tasks/1/attempt-1/builder-prompt.md").read_text()
    assert "{{reference_note}}" not in prompt
    evs = [x for x in events.read(e2e.run_dir(run_id) / "events.jsonl") if x["type"] == "reference.snapshot"]
    assert len(evs) == 1 and evs[0]["data"]["files"] == 1


def test_quick_run_without_material_has_no_mount(e2e):
    e2e.script_builders()
    run_id = e2e.start()
    e2e.settle()
    assert not (e2e.run_dir(run_id) / "reference").exists()
    assert all(k.get("reference_dir") is None for k in launches(e2e, "builder"))
    assert not [x for x in events.read(e2e.run_dir(run_id) / "events.jsonl") if x["type"] == "reference.snapshot"]


def test_full_run_mounts_for_planner_builder_reviewer_not_check_writer(e2e):
    ref = paths.projects() / "e2e" / "notes" / "reference"
    ref.mkdir(parents=True)
    (ref / "brand.css").write_text("a{}")
    script_full(e2e, reviewer_fails=False)
    e2e.cli("settings", "set", "e2e", "merge=ask")
    run_id = e2e.start("plans/e2e-full.md", "full")
    e2e.settle()
    e2e.answer("approve")
    e2e.settle()
    assert e2e.open_gates()[0]["kind"] == "merge"
    for role in ("planner", "builder", "reviewer"):
        got = launches(e2e, role)
        assert got and all(k["reference_dir"] for k in got), role
    assert all(k.get("reference_dir") is None for k in launches(e2e, "check-writer"))
