"""This package provides various resources for our package."""

import importlib.resources
from pathlib import Path

PACKAGE_NAME = "llmbot.resources"


def read_help_text() -> str:
    """Read the help text from the resources."""
    with _find_resource_path("help.txt").open("r") as file:
        return file.read()


def _find_resource_path(name: str) -> Path:
    """Find a resource in the package."""
    ref = importlib.resources.files(PACKAGE_NAME) / name

    with importlib.resources.as_file(ref) as path:
        return path
