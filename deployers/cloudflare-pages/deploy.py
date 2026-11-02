"""The Cloudflare Pages deployer: a stub that says it is not yet supported."""
from phoenix9.deploy import DeployError

NOT_YET = "Cloudflare Pages is not yet supported"


def deploy(dctx) -> dict:
    """Not built yet."""
    raise DeployError(NOT_YET)


def health(dctx, result) -> tuple[bool, str]:
    """Not built yet."""
    raise DeployError(NOT_YET)


def rollback(dctx, result, previous) -> dict:
    """Not built yet."""
    raise DeployError(NOT_YET)
