"""Release tags: the next tag number, tagging from the merge step, and `phoenix update release`."""
import json

import pytest

from phoenix9 import paths, release
from phoenix9.__main__ import main
from phoenix9.ops import common
from test_step_merge import URL, ask, gh, gh_calls, world  # noqa: F401  (world is a fixture)

SHA = "a" * 40
MERGE_SHA = "b" * 40
REFS = "repos/alex-boop-chasey/phoenix9/git/matching-refs/tags/v9."


def refs(*names, sha="1" * 40):
    return json.dumps([{"ref": f"refs/tags/{n}", "object": {"sha": sha}} for n in names])


def make_self(ctx):
    """Make the test project 'proj' the one that is Phoenix 9 itself."""
    paths.config().mkdir(parents=True, exist_ok=True)
    (paths.config() / "global.toml").write_text('[update]\nproject = "proj"\n')


def posts(ctx):
    return [c for c in gh_calls(ctx) if "POST" in c]


@pytest.mark.parametrize("existing,expected", [
    ([], "v9.0"), (["v9.0"], "v9.1"), (["v9.9", "v9.2"], "v9.10"),
    ([f"v9.{n}" for n in range(11)], "v9.11"), (["pre-v9.3", "v8.4", "v9.1"], "v9.2"), (["pre-v9.3", "v8.4"], "v9.0")])
def test_next_tag(existing, expected):
    assert release.next_tag(existing, "v9.") == expected


def approved(ctx, mod):
    gh(ctx, ["pr", "create"], out=URL + "\n")
    mod.run(ctx)
    return mod.on_approved(ctx, {})


def test_merge_of_self_project_tags_release(world):
    ctx, code, origin, mod = ask(world)
    make_self(ctx)
    gh(ctx, ["pr", "view"], out=MERGE_SHA + "\n")
    gh(ctx, ["api", REFS], out=refs("v9.0", "v9.1"))
    extra = approved(ctx, mod)
    assert extra["release"] == "v9.2"
    assert ["gh", "pr", "view", URL, "--json", "mergeCommit", "--jq", ".mergeCommit.oid"] in gh_calls(ctx)
    post = posts(ctx)[0]
    assert "ref=refs/tags/v9.2" in post and f"sha={MERGE_SHA}" in post
    assert "Phoenix 9 v9.2 is ready to install" in ctx.adapters.notify.messages


def test_merge_of_other_project_does_not_tag(world):
    ctx, code, origin, mod = ask(world)
    extra = approved(ctx, mod)
    assert "release" not in extra and not posts(ctx)
    assert not any(c[:2] == ["gh", "api"] for c in gh_calls(ctx))


def test_tag_failure_keeps_merge_and_notifies(world):
    ctx, code, origin, mod = ask(world)
    make_self(ctx)
    gh(ctx, ["pr", "view"], out=MERGE_SHA + "\n")
    gh(ctx, ["api", REFS], out=refs("v9.0"))
    gh(ctx, ["api", "-X", "POST"], rc=1, err="HTTP 403\n")
    extra = approved(ctx, mod)
    assert extra["merged"] and "release" not in extra and "not tagged" in extra["note"]
    assert any("phoenix update release" in m for m in ctx.adapters.notify.messages)


@pytest.fixture
def cli(tmp_path, monkeypatch, adapters):
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    return adapters


def test_release_command_skips_already_tagged_main(cli, capsys):
    cli.host.script(["gh", "api", "repos/alex-boop-chasey/phoenix9/commits/main"], out=SHA + "\n")
    cli.host.script(["gh", "api", REFS], out=refs("v9.0", "v9.3", sha=SHA))
    assert main(["update", "release", "--yes"]) == 0
    assert "already tagged" in capsys.readouterr().out
    assert not [c for c in cli.host.calls if "POST" in c]


def test_release_command_tags_untagged_main(cli, capsys):
    cli.host.script(["gh", "api", "repos/alex-boop-chasey/phoenix9/commits/main"], out=SHA + "\n")
    cli.host.script(["gh", "api", REFS], out=refs("v9.0", sha="2" * 40))
    assert main(["update", "release", "--yes"]) == 0
    post = [c for c in cli.host.calls if "POST" in c][0]
    assert "ref=refs/tags/v9.1" in post and f"sha={SHA}" in post
    assert main(["update", "release"]) == 1
