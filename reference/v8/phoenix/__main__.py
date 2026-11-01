"""Command line: python -m phoenix <command>."""
from __future__ import annotations

import argparse
import subprocess
import sys

from pathlib import Path

from phoenix import __version__, config, docker, hostpaths, loop, plan, runs, watch
from phoenix.state import Lock


def cmd_version(args: argparse.Namespace) -> int:
    """Print the Phoenix version."""
    print(f"phoenix {__version__}")
    return 0


def cmd_paths(args: argparse.Namespace) -> int:
    """Create the Phoenix folders if needed and print where they are."""
    p = config.paths()
    p.create()
    for name, path in p.all().items():
        print(f"{name:<7} {path}")
    return 0


def cmd_plan_check(args: argparse.Namespace) -> int:
    """Check a plan.md file and print either 'Plan OK' or the list of problems."""
    path = Path(args.file)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(f"Cannot read {path}: {e}")
        return 1
    parsed = plan.parse(text)
    errors = plan.check(parsed)
    if errors:
        print(f"Plan has {len(errors)} problem(s):")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Plan OK: {len(parsed.steps)} steps")
    return 0


def load_host_paths() -> bool:
    """When Phoenix runs in its own container, look up where its volumes are on the host.

    Done once at the start of every command that starts step containers.
    Prints the problem and returns False when the volumes cannot be found.
    """
    try:
        config.paths().create()
        for inside, host in hostpaths.load():
            print(f"host path: {inside} -> {host}", flush=True)
    except (hostpaths.HostPathError, OSError, subprocess.SubprocessError) as e:
        print(f"FAILED: cannot find Phoenix's volumes on the Docker host: {e}", flush=True)
        return False
    return True


def cmd_doctor(args: argparse.Namespace) -> int:
    """Start a firewalled step container and print OK, or what is wrong with the firewall."""
    if not load_host_paths():
        return 1
    try:
        failures = docker.probe_firewall()
    except (OSError, subprocess.SubprocessError) as e:
        print(f"FAILED: could not run the probe container: {e}")
        return 1
    if failures:
        print("FAILED: the step container firewall is not right:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("OK: firewall blocks example.com, allows api.anthropic.com")
    return 0


def _existing_run(run_id: str) -> dict | None:
    """Return a run's run.json record, or print why it cannot be used and return None."""
    if not (config.paths().runs / run_id / "run.json").is_file():
        print(f"No run called {run_id} (no {config.paths().runs / run_id / 'run.json'}).")
        return None
    record = runs.load_run(run_id)
    if not record.get("repo") or not record.get("plan_path"):
        print(f"Run {run_id} has no repo or plan yet in its run.json.")
        return None
    return record


def cmd_run(args: argparse.Namespace) -> int:
    """Take a run through its steps (or carry on after a restart). Exit 0 only when it is done."""
    if _existing_run(args.run_id) is None or not load_host_paths():
        return 1
    with Lock(runs.run_dir(args.run_id) / "loop.lock"):
        status = loop.run_plan(args.run_id)
    print(f"run {args.run_id}: {status}")
    return 0 if status == "done" else 1


def cmd_status(args: argparse.Namespace) -> int:
    """Print one line per step of a run: number, title, status, tries, reason."""
    record = _existing_run(args.run_id)
    if record is None:
        return 1
    print(f"run {args.run_id}: {record.get('status')}")
    for line in loop.status_lines(args.run_id):
        print(line)
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    """Pick up plans from plans/ and run them one at a time, forever (stop with Ctrl-C)."""
    if not load_host_paths():
        return 1
    print(f"watching {config.paths().plans} every {watch.INTERVAL_S} seconds", flush=True)
    try:
        watch.watch_forever()
    except KeyboardInterrupt:
        print("stopped")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Set up the commands Phoenix understands."""
    parser = argparse.ArgumentParser(prog="phoenix", description="Phoenix v8 core")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version", help="print the version").set_defaults(func=cmd_version)
    sub.add_parser("paths", help="print (and create) the Phoenix folders").set_defaults(func=cmd_paths)
    sub.add_parser("doctor", help="check the step container firewall").set_defaults(func=cmd_doctor)
    run_cmd = sub.add_parser("run", help="build a run's steps (resumes after a restart)")
    run_cmd.add_argument("run_id", help="the run id, like 20261030-1405-qmzt")
    run_cmd.set_defaults(func=cmd_run)
    sub.add_parser("watch", help="pick up plans and run them, forever").set_defaults(func=cmd_watch)
    status_cmd = sub.add_parser("status", help="show a run's steps")
    status_cmd.add_argument("run_id", help="the run id, like 20261030-1405-qmzt")
    status_cmd.set_defaults(func=cmd_status)
    plan_cmd = sub.add_parser("plan", help="work with plan.md files")
    plan_sub = plan_cmd.add_subparsers(dest="plan_command", required=True)
    check = plan_sub.add_parser("check", help="check a plan.md against the plan rules")
    check.add_argument("file", help="path to the plan.md file")
    check.set_defaults(func=cmd_plan_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one command and return its exit code."""
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
