"""The phoenix command line. Command groups are added during the build (see docs/architecture.md)."""
import sys

from phoenix9 import __version__


def main(argv: list[str] | None = None) -> int:
    """Print a short help text; real commands come in phase 1 step 13."""
    argv = sys.argv[1:] if argv is None else argv
    if argv[:2] == ["runner", "serve"]:  # hidden: the systemd service runs this
        return serve()
    print(f"phoenix {__version__}: no commands yet.")
    return 0


def serve() -> int:
    """Run the runner service loop with the real adapters (hidden `phoenix runner serve`)."""
    from phoenix9 import adapters, paths, watch
    from phoenix9.runner import Runner
    real = adapters.real()
    watch.watch_forever(real, Runner(real, paths.library()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
