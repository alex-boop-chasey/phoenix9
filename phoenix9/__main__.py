"""The phoenix command line. Command groups are added during the build (see docs/architecture.md)."""
import sys

from phoenix9 import __version__


def main(argv: list[str] | None = None) -> int:
    """Print a short help text; real commands come in phase 1 step 13."""
    print(f"phoenix {__version__}: no commands yet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
