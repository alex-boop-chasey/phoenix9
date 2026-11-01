"""The Merge step: auto and ask modes, safety files, the merge gate's answers, GitHub errors."""
import subprocess

import pytest

from helpers.stepunit import git, load, make_ctx
from phoenix9 import state

URL = "https://github.com/alex/proj/pull/7"


class GitHost:
    """The fake host, except that `git` commands really run (so pushes reach a temp bare origin)."""

    def __init__(self, fake):
        self.fake = fake

    def run(self, argv, timeout=60):
        if argv[0] == "git":
            self.fake.calls.append(list(argv))
            p = subprocess.run(argv, capture_output=True, text=True)
            return p.returncode, p.stdout, p.stderr
        return self.fake.run(argv, timeout)

    def gh(self, *args):
        return self.run(["gh", *args])

    def __getattr__(self, name):
        return getattr(self.fake, name)


@pytest.fixture
def world(tmp_path, adapters):
    """A code repo on main with a bare origin and a run branch phoenix/r holding one commit."""
    code = tmp_path / "code"
    code.mkdir()
    git(code, "init", "-q", "-b", "main")
    (code / "a.txt").write_text("a\n")
    git(code, "add", "-A")
    git(code, "commit", "-q", "-m", "first")
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    git(code, "remote", "add", "origin", str(origin))
    git(code, "push", "-q", "origin", "main")
    git(code, "branch", "phoenix/r")
    work = tmp_path / "work"
    git(code, "worktree", "add", "-q", str(work), "phoenix/r")
    (work / "b.txt").write_text("b\n")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "second")
    adapters.host = GitHost(adapters.host)
    ctx = make_ctx(tmp_path, adapters, work, "merge", {"merge": "auto"})
    ctx.project.code_dir = code
    ctx.run.spec["title"] = "Tiny"
    state.set_task(ctx.run.folder, 1, status="passed")
    (ctx.run.folder / "summary.md").write_text("# Summary\n")
    return ctx, code, origin


def gh(ctx, prefix, rc=0, out="", err=""):
    ctx.adapters.host.fake.script(["gh", *prefix], rc, out, err)


def gh_calls(ctx):
    return [c for c in ctx.adapters.host.fake.calls if c[0] == "gh"]


def origin_log(origin):
    return git(origin, "log", "main", "--format=%s")


def test_auto_merges_and_pushes_main(world):
    ctx, code, origin = world
    result = load("merge").run(ctx)
    assert result.status == "pass" and result.produces["merged"] == git(code, "rev-parse", "HEAD").strip()
    assert "Merge run r: Tiny" in origin_log(origin)
    assert git(origin, "rev-parse", "main").strip() == result.produces["merged"]
    assert git(origin, "rev-parse", "phoenix/r").strip()


def test_auto_updates_clean_code_dir(world):
    ctx, code, _ = world
    load("merge").run(ctx)
    assert (code / "b.txt").exists()


def test_auto_leaves_dirty_code_dir_with_note(world):
    ctx, code, _ = world
    (code / "a.txt").write_text("changed\n")
    gh(ctx, ["pr", "create"], out=URL + "\n")
    result = load("merge").run(ctx)
    assert result.status == "gate" and "code/ has local changes" in result.gate["flags"]
    assert not (code / "b.txt").exists() and (code / "a.txt").read_text() == "changed\n"


def test_no_commits_skips(world):
    ctx, code, _ = world
    git(ctx.worktree, "reset", "-q", "--hard", "main")
    result = load("merge").run(ctx)
    assert result.status == "skip" and result.reasons == ["No changes to merge"]


def test_safety_file_switches_auto_to_ask_with_flag(world):
    ctx, _, _ = world
    (ctx.worktree / "image").mkdir()
    (ctx.worktree / "image" / "init-firewall.sh").write_text("x\n")
    git(ctx.worktree, "add", "-A")
    git(ctx.worktree, "commit", "-q", "-m", "fw")
    ctx.project.settings["safety_files"] = ["image/*"]
    gh(ctx, ["pr", "create"], out=URL + "\n")
    result = load("merge").run(ctx)
    assert result.status == "gate" and "changes safety code" in result.gate["flags"]
    assert "image/init-firewall.sh" in result.gate["why"]


def test_failed_task_forces_ask(world):
    ctx, _, _ = world
    state.set_task(ctx.run.folder, 1, status="failed")
    gh(ctx, ["pr", "create"], out=URL + "\n")
    result = load("merge").run(ctx)
    assert result.status == "gate" and "1 tasks failed" in result.gate["flags"]


def ask(world):
    ctx, code, origin = world
    ctx.project.settings["merge"] = "ask"
    gh(ctx, ["pr", "create"], out="Creating...\n" + URL + "\n")
    return ctx, code, origin, load("merge")


def test_ask_opens_gate_with_pr_link(world):
    ctx, _, origin, mod = ask(world)
    result = mod.run(ctx)
    gate = result.gate
    assert result.status == "gate" and gate["kind"] == "merge" and gate["title"] == "Merge Tiny?"
    assert {"label": "Merge request", "url": URL} in gate["links"]
    assert gate["actions"] == ["approve", "back", "skip", "stop"]
    create = gh_calls(ctx)[0]
    assert "--body-file" in create and "phoenix/r" in create
    assert git(origin, "rev-parse", "phoenix/r").strip()


def test_ask_approve_merges_via_gh(world):
    ctx, code, _, mod = ask(world)
    mod.run(ctx)
    extra = mod.on_approved(ctx, {})
    assert ["gh", "pr", "merge", URL, "--merge"] in gh_calls(ctx)
    assert any(c[-2:] == ["pull", "--ff-only"] for c in ctx.adapters.host.fake.calls)
    assert "merged" in extra


def test_ask_back_comments_and_passes(world):
    ctx, _, _, mod = ask(world)
    mod.run(ctx)
    ctx.answer = {"action": "back", "note": "rename it"}
    result = mod.run(ctx)
    assert result.status == "pass" and result.reasons == ["sent back: rename it"]
    assert "rename it" in (ctx.run.folder / "merge-note.md").read_text()
    assert any(c[:3] == ["gh", "pr", "comment"] for c in gh_calls(ctx))
    assert not any(c[:3] == ["gh", "pr", "merge"] for c in gh_calls(ctx))


def test_ask_skip_leaves_open(world):
    ctx, _, _, mod = ask(world)
    mod.run(ctx)
    assert not any(c[:3] == ["gh", "pr", "merge"] for c in gh_calls(ctx))


def test_gh_error_fails_with_plain_reason(world):
    ctx, _, _ = world
    ctx.project.settings["merge"] = "ask"
    gh(ctx, ["pr", "create"], rc=1, err="boom: no permission\nmore\n")
    result = load("merge").run(ctx)
    assert result.status == "fail" and result.reasons == ["GitHub refused the merge request: boom: no permission"]


def test_local_only_project_merges_into_code(world):
    ctx, code, _ = world
    git(code, "remote", "remove", "origin")
    assert load("merge").run(ctx).status == "pass"
    assert (code / "b.txt").exists()
    ctx2 = ctx
    git(code, "reset", "-q", "--hard", "HEAD~1")
    ctx2.project.settings["merge"] = "ask"
    mod = load("merge")
    result = mod.run(ctx2)
    assert result.status == "gate" and result.gate["why"].startswith("local only: approve merges into code/ main")
    assert all(l["label"] != "Merge request" for l in result.gate["links"])
    mod.on_approved(ctx2, {})
    assert (code / "b.txt").exists()
