"""The one starting test."""
import importlib


def test_greet():
    mod = importlib.import_module("{{module}}")
    assert mod.greet("Phoenix") == "Hello, Phoenix!"
