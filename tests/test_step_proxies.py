"""Key proxies around a step: started before it, stopped after it, and what a container is given."""
import shutil
import subprocess
from pathlib import Path

import pytest

from phoenix9 import docker, keys, paths, runs, services, state
from phoenix9.ops import common
from phoenix9.ops import services as ops_services
from phoenix9.runner import Runner

from helpers import scripted

REPO = Path(__file__).resolve().parent.parent
SENTINEL = "sk-SENTINEL-ACCOUNT-KEY"
SPEC = "# Spec: Proxy test\n\n## Task 1: First\nGoal: do it.\nDone when:\n- it is done fine\n"
AI_TOML = ('name = "builder"\ntitle = "Builder"\nkind = "ai"\nlevel = "task"\norder = 30\n'
           'needs = ["task", "worktree"]\nproduces = ["diff"]\ndefault = "always"\n{proxy}\n[ai]\nmodel = "m"\ntimeout = 5\n')


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                   check=True, capture_output=True)


@pytest.fixture
def project():
    code = paths.projects() / "proj" / "code"
    code.mkdir(parents=True)
    git(code, "init", "-q", "-b", "main")
    (code / "README.md").write_text("hello\n")
    git(code, "add", "-A")
    git(code, "commit", "-q", "-m", "first")
    (paths.projects() / "proj" / "phoenix.toml").write_text('services = ["supabase", "resend", "stripe"]\n')
    return paths.projects() / "proj"


@pytest.fixture
def connected(adapters, monkeypatch):
    """Supabase connected with a sentinel key (the connect check is answered by the fake http)."""
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    adapters.http.script("GET", "http://proxy.fake/supabase/v1/projects", 200, body=b"[]")
    ops_services.connect("supabase", {"SUPABASE_ACCESS_TOKEN": SENTINEL}, who="test")
    adapters.proxy.started.clear()
    adapters.proxy.handles.clear()
    adapters.proxy.stopped.clear()


def make_lib(root, proxy=None, kind="script"):
    """The scripted library; its builder step carries `proxy` (a toml list text) and may be an ai step."""
    scripted.make_library(root)
    shutil.copytree(REPO / "services", root / "services")
    line = f"proxy = {proxy}\n" if proxy else ""
    folder = root / "steps" / "builder"
    if kind == "ai":
        (folder / "step.toml").write_text(AI_TOML.format(proxy=line))
        (folder / "prompt.md").write_text("Do {{task}}.\n")
        (folder / "run.py").unlink()
    elif line:
        with open(folder / "step.toml", "a") as f:
            f.write(line)
    return root


def start(tmp_path):
    f = tmp_path / "spec.md"
    f.write_text(SPEC)
    return runs.create_run("proj", f, {"max_tries": 1, "on_failure": "continue"})


@pytest.fixture(autouse=True)
def clean_script():
    scripted.reset()
    yield
    scripted.reset()


def drive(tmp_path, adapters, proxy=None, kind="script"):
    run_dir = start(tmp_path)
    status = Runner(adapters, make_lib(tmp_path / "lib", proxy, kind)).drive(run_dir)
    return run_dir, status


def test_step_without_proxy_starts_none(tmp_path, project, adapters):
    drive(tmp_path, adapters)
    assert adapters.proxy.started == []


def test_script_step_gets_loopback_proxy_and_ctx_proxies(tmp_path, project, adapters, connected):
    seen = {}
    scripted.on("builder", None, None, lambda ctx: (seen.update(ctx.proxies), scripted.StepResult("pass"))[1])
    run_dir, status = drive(tmp_path, adapters, '["supabase"]')
    assert status == "done"
    (start_,) = adapters.proxy.started
    assert start_["service"] == "supabase" and start_["bind"] == "127.0.0.1" and start_["step"] == "builder"
    assert start_["rules"] and start_["log_path"] == str(run_dir / "logs" / "proxy-supabase.jsonl")
    assert seen["supabase"]["url"] == "http://proxy.fake/supabase" and seen["supabase"]["token"]
    assert adapters.proxy.running() == [] and adapters.proxy.stopped == ["supabase"]
    log = (run_dir / "logs" / "builder.log").read_text()
    assert "proxy: started supabase on 127.0.0.1" in log and "proxy: stopped supabase" in log
    assert SENTINEL not in log


def test_ai_step_gets_bridge_proxy_env_and_allow_file(tmp_path, project, adapters, connected):
    run_dir, status = drive(tmp_path, adapters, '["supabase"]', "ai")
    assert status == "done"
    (call,) = [c for c in adapters.claude.calls if c[0] == "launch"]
    kw = call[2]
    port = adapters.proxy.handles[0].port
    assert adapters.proxy.started[0]["bind"] == "172.17.0.1"
    assert kw["extra_env"] == {"PHOENIX_PROXY_SUPABASE": "http://proxy.fake/supabase",
                               "PHOENIX_PROXY_TOKEN_SUPABASE": "fake-proxy-token"}
    (mount,) = [m for m in kw["extra_mounts"] if m.dst == docker.ALLOWED_PROXY_MOUNT]
    assert mount.ro and Path(mount.src).read_text() == f"172.17.0.1 {port}\n"
    assert Path(mount.src).parent == run_dir and Path(mount.src).name == "proxy-allow-builder.txt"
    assert adapters.proxy.running() == []


def test_extra_env_becomes_dash_e_flags(tmp_path):
    env = {"PHOENIX_PROXY_SUPABASE": "http://172.17.0.1:5000", "PHOENIX_PROXY_TOKEN_SUPABASE": "tok"}
    work, prompt = tmp_path / "w", tmp_path / "p.md"
    work.mkdir()
    prompt.write_text("x")
    r = docker.claude_run("proj", "r1", 1, 1, "builder", "img", work, prompt, ["claude"], extra_env=env)
    argv = docker.build_argv(r)
    for k, v in env.items():
        assert ["-e", f"{k}={v}"] == argv[argv.index(f"{k}={v}") - 1:argv.index(f"{k}={v}") + 1]
    c = docker.check_run("proj", "r1", 1, 1, "check", "img", work, "true", None, None, "vol", extra_env=env)
    assert c.env["PHOENIX_PROXY_SUPABASE"] == env["PHOENIX_PROXY_SUPABASE"]
    with pytest.raises(ValueError):
        docker.claude_run("proj", "r1", 1, 1, "builder", "img", work, prompt, ["claude"],
                          extra_env={"SUPABASE_ACCESS_TOKEN": SENTINEL})


def test_proxy_stopped_when_step_raises(tmp_path, project, adapters, connected):
    scripted.on("builder", None, None, RuntimeError("boom"))
    run_dir, status = drive(tmp_path, adapters, '["supabase"]')
    assert status == "failed" and adapters.proxy.running() == []
    scripted.on("builder", None, None, KeyboardInterrupt())
    (tmp_path / "again").mkdir()
    with pytest.raises(KeyboardInterrupt):
        drive(tmp_path / "again", adapters, '["supabase"]')
    assert adapters.proxy.running() == []


def test_proxy_stopped_on_timeout_and_stop(tmp_path, project, adapters, connected):
    adapters.claude.sessions.append({"kind": "timeout"})
    run_dir, status = drive(tmp_path, adapters, '["supabase"]', "ai")
    assert status == "failed" and adapters.proxy.running() == [] and adapters.proxy.stopped == ["supabase"]
    scripted.on("builder", None, None, SystemExit(1))      # a stop that unwinds the runner
    (tmp_path / "two").mkdir()
    with pytest.raises(SystemExit):
        drive(tmp_path / "two", adapters, '["supabase"]')
    assert adapters.proxy.running() == []


def test_unconnected_service_fails_step_before_start(tmp_path, project, adapters):
    run_dir, status = drive(tmp_path, adapters, '["supabase"]')
    assert status == "failed" and adapters.proxy.started == []
    assert "Supabase is not connected in Global settings" in state.load(run_dir)["tasks"]["1"]["failures"][0]
    assert not [c for c in scripted.calls("builder")]


def test_at_project_resolves_connected_store_and_wire_only(tmp_path, project, adapters, connected):
    run_dir, status = drive(tmp_path, adapters, '["@project"]')
    assert status == "done"
    assert [s["service"] for s in adapters.proxy.started] == ["supabase"]
    log = (run_dir / "logs" / "builder.log").read_text()
    assert "Resend is not connected, so it is left out" in log


def test_unknown_proxy_name_is_a_library_problem(tmp_path):
    lib = make_lib(tmp_path / "lib", '["nonesuch"]')
    from phoenix9.library import load_library
    problems = load_library(lib).problems
    assert any("proxy 'nonesuch'" in p for p in problems)
    assert not any("proxy '@project'" in p for p in load_library(make_lib(tmp_path / "l2", '["@project"]')).problems)


def test_no_account_key_or_service_env_file_reaches_container(tmp_path, project, adapters, connected):
    run_dir, status = drive(tmp_path, adapters, '["supabase"]', "ai")
    assert status == "done"
    text = repr([c[2] for c in adapters.claude.calls if c[0] == "launch"])
    assert SENTINEL not in text and "service-supabase" not in text
    for k in [m for c in adapters.claude.calls if c[0] == "launch" for m in c[2]["extra_mounts"]]:
        assert Path(k.src).name == "proxy-allow-builder.txt"
        assert SENTINEL not in Path(k.src).read_text()
    # the real argv path: build the container the launch would make and look at everything in it
    work, prompt = tmp_path / "w", tmp_path / "p.md"
    work.mkdir()
    prompt.write_text("x")
    call = [c for c in adapters.claude.calls if c[0] == "launch"][0][2]
    r = docker.claude_run("proj", "r", 1, 1, "builder", "img", work, prompt, ["claude"],
                          mounts=call["extra_mounts"], extra_env=call["extra_env"])
    argv = docker.build_argv(r)
    assert SENTINEL not in " ".join(argv)
    assert all(not Path(f).name.startswith("service-") and Path(f).name != "github.env" for f in r.env_files)
    assert SENTINEL not in " ".join(adapters.docker.argvs[0] if adapters.docker.argvs else [])
    secret = keys.secrets_dir() / "service-supabase.env"
    assert secret.exists()
    with pytest.raises(ValueError):
        docker.build_argv(docker.claude_run("proj", "r", 1, 1, "b", "img", work, prompt, ["claude"],
                                            mounts=[docker.Mount(secret, "/x")]))


@pytest.mark.parametrize("name", ["github.env", "service-supabase.env", "telegram.env"])
def test_forbidden_env_files_refused(name, tmp_path):
    f = tmp_path / name
    f.write_text("K=v\n")
    with pytest.raises(ValueError):
        docker.check_env_file(f)
    work, prompt = tmp_path / "w", tmp_path / "p.md"
    work.mkdir()
    prompt.write_text("x")
    r = docker.claude_run("proj", "r", 1, 1, "b", "img", work, prompt, ["claude"], env_files=[f])
    with pytest.raises(ValueError):
        docker.build_argv(r)
