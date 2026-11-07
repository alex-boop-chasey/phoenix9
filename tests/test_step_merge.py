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


def branches(repo):
    return git(repo, "branch", "--list", "--format=%(refname:short)").split()


def test_auto_merge_deletes_the_branch_here_and_on_origin(world):
    ctx, code, origin = world
    result = load("merge").run(ctx)
    assert result.status == "pass" and result.reasons == []
    assert "phoenix/r" not in branches(code) and "phoenix/r" not in branches(origin)
    assert not ctx.worktree.exists()


def test_auto_merge_reports_a_failed_remote_delete(world):
    ctx, code, origin = world
    real = ctx.adapters.host.run

    def run(argv, timeout=60):
        if "--delete" in argv:
            return 1, "", "remote: denied\n"
        return real(argv, timeout)
    ctx.adapters.host.run = run
    result = load("merge").run(ctx)
    assert result.status == "pass" and "not deleted on GitHub: remote: denied" in result.reasons[0]
    assert "phoenix/r" not in branches(code)


def test_ask_mode_keeps_the_branch(world):
    ctx, code, origin = world
    ctx.project.settings["merge"] = "ask"
    gh(ctx, ["pr", "create"], out=URL + "\n")
    assert load("merge").run(ctx).status == "gate"
    assert "phoenix/r" in branches(code) and "phoenix/r" in branches(origin)


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


def test_merge_flags_safety_change_for_self_project(world):
    import tomllib
    from pathlib import Path
    ctx, _, _ = world
    config = tomllib.loads((Path(__file__).resolve().parents[1] / "deploy" / "self-project.toml").read_text())
    (ctx.worktree / "phoenix9").mkdir()
    (ctx.worktree / "phoenix9" / "proxy.py").write_text("x = 1\n")
    git(ctx.worktree, "add", "-A")
    git(ctx.worktree, "commit", "-q", "-m", "proxy")
    ctx.project.settings["safety_files"] = config["safety_files"]
    gh(ctx, ["pr", "create"], out=URL + "\n")
    result = load("merge").run(ctx)
    assert result.status == "gate" and "changes safety code" in result.gate["flags"]
    assert "phoenix9/proxy.py" in result.gate["why"]


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
    git(code, "branch", "phoenix/r", "HEAD^2")   # the first merge deleted it and its worktree
    git(code, "worktree", "add", "-q", str(ctx.worktree), "phoenix/r")
    git(code, "reset", "-q", "--hard", "HEAD~1")
    ctx2.project.settings["merge"] = "ask"
    mod = load("merge")
    result = mod.run(ctx2)
    assert result.status == "gate" and result.gate["why"].startswith("local only: approve merges into code/ main")
    assert all(l["label"] != "Merge request" for l in result.gate["links"])
    mod.on_approved(ctx2, {})
    assert (code / "b.txt").exists()


def test_push_without_a_github_login_says_run_doctor(world):
    ctx, _, _ = world
    real = ctx.adapters.host.run

    def run(argv, timeout=60):
        if "push" in argv:
            return 128, "", "fatal: could not read Username for 'https://github.com': No such device or address\n"
        return real(argv, timeout)
    ctx.adapters.host.run = run
    result = load("merge").run(ctx)
    assert result.status == "fail"
    assert result.reasons == ["Phoenix's worker can't reach your GitHub login: run `phoenix doctor`"]


def spy_git(ctx, fail_on=None):
    """Wrap the git adapter so tests can see each call (and make `worktree remove` fail on request)."""
    real, seen = ctx.adapters.git, []

    class Spy:
        def git(self, cwd, *args, **kw):
            seen.append(list(args))
            if fail_on and list(args[:2]) == fail_on:
                raise RuntimeError("worktree is locked\nmore")
            return real.git(cwd, *args, **kw)

        def __getattr__(self, name):
            return getattr(real, name)
    ctx.adapters.git = Spy()
    return seen


def test_auto_merge_removes_the_worktree(world):
    ctx, code, _ = world
    seen = spy_git(ctx)
    assert load("merge").run(ctx).status == "pass"
    assert ["worktree", "remove", "--force", str(ctx.worktree)] in seen
    assert not ctx.worktree.exists() and str(ctx.worktree) not in git(code, "worktree", "list")


def test_worktree_removal_uses_the_safety_flags(world, monkeypatch):
    from phoenix9 import git as gitmod
    ctx, code, _ = world
    argvs = []
    real = gitmod.subprocess.run
    monkeypatch.setattr(gitmod.subprocess, "run", lambda argv, **kw: (argvs.append(argv), real(argv, **kw))[1])
    load("merge").run(ctx)
    remove = next(a for a in argvs if "remove" in a)
    assert remove[:5] == ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null"]


def test_local_only_approve_removes_the_worktree(world):
    ctx, code, _ = world
    git(code, "remote", "remove", "origin")
    ctx.project.settings["merge"] = "ask"
    mod = load("merge")
    assert mod.run(ctx).status == "gate"
    seen = spy_git(ctx)
    mod.on_approved(ctx, {})
    assert ["worktree", "remove", "--force", str(ctx.worktree)] in seen
    assert not ctx.worktree.exists() and (code / "b.txt").exists()


def test_failed_worktree_removal_is_a_note_not_a_failure(world):
    ctx, code, _ = world
    spy_git(ctx, fail_on=["worktree", "remove"])
    result = load("merge").run(ctx)
    assert result.status == "pass"
    assert any("worktree was not removed: worktree is locked" in r for r in result.reasons)
    assert "phoenix/r" not in branches(code)


def test_merge_left_to_github_keeps_the_worktree(world):
    ctx, code, _ = world
    ctx.project.settings["merge"] = "ask"
    gh(ctx, ["pr", "create"], out=URL + "\n")
    seen = spy_git(ctx)
    assert load("merge").run(ctx).status == "gate"
    gh(ctx, ["pr", "merge"])
    load("merge").on_approved(ctx, {})
    assert ctx.worktree.exists() and ["worktree", "remove", "--force", str(ctx.worktree)] not in seen


def test_failed_merge_keeps_the_worktree(world):
    ctx, code, _ = world
    (code / "a.txt").write_text("conflict\n")
    git(code, "commit", "-qam", "main moves")
    (ctx.worktree / "a.txt").write_text("other\n")
    git(ctx.worktree, "commit", "-qam", "branch moves")
    spy_git(ctx)
    with pytest.raises(Exception):
        load("merge").run(ctx)
    assert ctx.worktree.exists()
