"""Tests for phoenix9.git on real temp git repos."""
import os
import subprocess

import pytest

from phoenix9 import git as g
from phoenix9.git import Change, GitError


def sh(cwd, *args):
    """Run plain git in a test repo."""
    return g.git(cwd, *args)


@pytest.fixture
def repo(tmp_path):
    """A small repo on main with a few files."""
    d = tmp_path / "code"
    d.mkdir()
    sh(d, "init", "-q", "-b", "main")
    (d / "a.txt").write_text("one\ntwo\nthree\nfour\nfive\n")
    (d / "run.sh").write_text("echo hi\n")
    (d / "old.txt").write_text("a long enough file body\nline two\nline three\nline four\n")
    (d / "gone.txt").write_text("bye\n")
    sh(d, "add", "-A")
    sh(d, *g.IDENT, "commit", "-q", "-m", "first")
    return d


@pytest.fixture
def wt(repo, tmp_path):
    """A worktree for run 'r1' plus the base sha."""
    base = g.head(repo)
    return g.make_worktree(repo, "r1", tmp_path / "work" / "r1"), base


def by_path(changes):
    return {c.path: c for c in changes}


def test_worktree_create_and_remove_keeps_branch(repo, tmp_path):
    w = g.make_worktree(repo, "20260101-000000-demo", tmp_path / "w")
    assert (w / "a.txt").exists()
    assert sh(w, "symbolic-ref", "--short", "HEAD").strip() == "phoenix/20260101-000000-demo"
    g.remove_worktree(repo, w)
    assert not w.exists()
    assert "phoenix/20260101-000000-demo" in sh(repo, "branch", "--list")
    assert "w" not in sh(repo, "worktree", "list").split("\n")[-1].split("/")[-1:]


def test_worktree_reuses_existing_branch_and_uses_current_default(repo, tmp_path):
    sh(repo, "branch", "-m", "main", "trunk")
    w = g.make_worktree(repo, "r2", tmp_path / "w2")
    assert g.head(w) == g.head(repo)
    g.remove_worktree(repo, w)
    w = g.make_worktree(repo, "r2", tmp_path / "w3")
    assert w.exists()


@pytest.mark.parametrize("bad", ["main", "HEAD", "../x", "a b", "", "-x", "Master"])
def test_bad_run_ids_refused(repo, tmp_path, bad):
    with pytest.raises(GitError):
        g.make_worktree(repo, bad, tmp_path / "w")


def test_refuses_existing_folder(repo, tmp_path):
    (tmp_path / "w").mkdir()
    with pytest.raises(GitError):
        g.make_worktree(repo, "r1", tmp_path / "w")


def test_safe_flags_on_every_call(monkeypatch, tmp_path):
    seen = []

    def fake_run(argv, **kw):
        seen.append((argv, kw["env"]))
        return subprocess.CompletedProcess(argv, 0, b"", b"")
    monkeypatch.setenv("GIT_SSH_COMMAND", "evil")
    monkeypatch.setattr(subprocess, "run", fake_run)
    g.run_git(tmp_path, "status")
    g.git(tmp_path, "log")
    for argv, env in seen:
        assert argv[:6] == ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", argv[5]]
        assert "GIT_SSH_COMMAND" not in env
    assert g.git_argv("x")[1:5] == list(g.SAFE)


def test_change_listing(wt):
    w, base = wt
    (w / "new.txt").write_text("new\n")
    (w / "a.txt").write_text("one\nTWO\nthree\nfour\nfive\n")
    (w / "gone.txt").unlink()
    (w / "old.txt").rename(w / "renamed.txt")
    os.symlink("a.txt", w / "link")
    os.chmod(w / "run.sh", 0o755)
    (w / "blob.bin").write_bytes(b"\0\1\2\3" * 10)
    c = by_path(g.diff_changes(w, base))
    assert c["new.txt"].status == "A"
    assert c["a.txt"].status == "M"
    assert c["gone.txt"].status == "D"
    assert c["renamed.txt"].status == "R" and c["renamed.txt"].old_path == "old.txt"
    assert c["link"].mode == g.SYMLINK
    assert c["run.sh"].status == "M" and (c["run.sh"].old_mode, c["run.sh"].mode) == ("100644", "100755")
    assert c["blob.bin"].binary and not c["new.txt"].binary
    assert "+TWO" in g.diff_text(w, base)


def test_reset_attempt(wt):
    w, base = wt
    (w / "a.txt").write_text("changed\n")
    (w / "junk.txt").write_text("x")
    g.reset_attempt(w, base)
    assert g.diff_changes(w, base) == []
    assert not (w / "junk.txt").exists()


def test_commit_trailers(wt):
    w, base = wt
    (w / "n.txt").write_text("n\n")
    sha = g.commit(w, "Add n\n\nPhoenix-Run: forged", {"Phoenix-Run": "r1", "Phoenix-Step": 3})
    msg = sh(w, "log", "-1", "--format=%B", sha)
    assert "Phoenix-Run: r1" in msg and "Phoenix-Step: 3" in msg and "forged" not in msg
    assert sh(w, "log", "-1", "--format=%(trailers:key=Phoenix-Step,valueonly)").strip() == "3"
    assert "n.txt" in sh(w, "show", "--name-only", "--format=", sha)


def ch(path, status="A", mode="100644", **kw):
    return Change(status, path, mode, **kw)


@pytest.mark.parametrize("path", [".git/config", "sub/.git/x", ".github/workflows/ci.yml", ".env", "app/.env.local",
                                  "CLAUDE.md", "sub/CLAUDE.md", ".claude/settings.json", "x/.claude/a", ".mcp.json"])
def test_default_denies(path):
    assert len(g.check_changes([ch(path)])) == 1


def test_symlink_and_submodule_denied():
    assert g.check_changes([ch("link", mode=g.SYMLINK)])
    assert g.check_changes([ch("sub", mode=g.SUBMODULE)])


def test_allowed_by_default():
    ok = ["README.md", "docs/guide.md", ".vscode/settings.json", ".env.example", ".env.sample",
          ".github/CODEOWNERS", "src/app.py"]
    assert g.check_changes([ch(p) for p in ok]) == []


def test_rename_checked_at_both_ends():
    assert g.check_changes([ch("ci.yml", "R", old_path=".github/workflows/ci.yml")])


def test_allow_extra_widens_but_not_git_or_symlinks():
    assert g.check_changes([ch("CLAUDE.md")], allow_extra=["CLAUDE.md"]) == []
    assert g.check_changes([ch(".github/workflows/ci.yml")], allow_extra=[".github/workflows/*"]) == []
    assert g.check_changes([ch(".git/hooks/x")], allow_extra=["*", ".git/*"])
    assert g.check_changes([ch("link", mode=g.SYMLINK)], allow_extra=["*"])
    assert g.check_changes([ch("sub", mode=g.SUBMODULE)], allow_extra=["*"])
    assert g.check_changes([ch("t.py")], allow_extra=["*"], locked=["t.py"])


def test_deny_extra_and_locked():
    assert g.check_changes([ch("secrets/x.txt")], deny_extra=["secrets/*"])
    r = g.check_changes([ch("tests/check.py", "M"), ch("tests/locked/a.py")],
                        locked=["tests/check.py", "tests/locked/"])
    assert len(r) == 2 and "locked" in r[0]


def test_scan_secrets(wt):
    w, base = wt
    (w / "cfg.py").write_text('KEY = "AKIAABCDEFGHIJKLMNOP"\n')
    (w / "id_rsa").write_text("-----BEGIN RSA PRIVATE KEY-----\nabc\n")
    (w / ".env.example").write_text("AWS=AKIAABCDEFGHIJKLMNOP\nSTRIPE=sk_live_xxx\n")
    (w / "fine.txt").write_text("nothing here\n")
    found = g.scan_secrets(g.diff_text(w, base))
    text = "\n".join(found)
    assert "cfg.py" in text and "AWS" in text
    assert "id_rsa" in text and "private key" in text
    assert ".env.example" not in text and "fine.txt" not in text
    assert "AKIAABCDEFGHIJKLMNOP" not in text


def test_scan_ignores_removed_lines():
    d = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +0,0 @@\n-sk_live_abc\n"
    assert g.scan_secrets(d) == []
