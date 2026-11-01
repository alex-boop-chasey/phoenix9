"""The hidden `phoenix runner serve` command that the systemd service runs."""


def serve() -> int:
    """Run the runner service loop with the real adapters."""
    from phoenix9 import adapters, paths, watch
    from phoenix9.runner import Runner
    real = adapters.real()
    watch.watch_forever(real, Runner(real, paths.library()))
    return 0
