"""Test deployer: every call is handed to the functions the test registers as sys.modules['deploy_script']."""
import sys


def _s():
    return sys.modules["deploy_script"]


def deploy(dctx):
    """Scripted."""
    return _s().deploy(dctx)


def health(dctx, result):
    """Scripted."""
    return _s().health(dctx, result)


def rollback(dctx, result, previous):
    """Scripted."""
    return _s().rollback(dctx, result, previous)


def preview(dctx):
    """Scripted."""
    return _s().preview(dctx)


def stop_preview(dctx, record):
    """Scripted."""
    return _s().stop_preview(dctx, record)
