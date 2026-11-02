"""A deployer with no health check or rollback (must be refused)."""


def deploy(dctx):
    """Would deploy."""
    return {}
