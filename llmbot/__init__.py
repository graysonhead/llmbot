"""This is a Python package that provides a CLI tool."""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("llmbot")
except importlib.metadata.PackageNotFoundError:
    # Fallback for development mode when package is not installed
    __version__ = "0.0.0-dev"
