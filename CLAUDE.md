# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is `llmbot` - an LLM Gateway for Discord that connects Discord users to LLMs via OpenWebUI. It's a Python package built with Click for CLI functionality.

## Development Environment

This project uses Nix for development environment management. Enter the development shell:

```sh
nix develop
```

## Common Commands

### Testing and Quality Assurance
- Run all tests and checks: `nox`
- List available nox sessions: `nox --list` 
- Run specific test session: `nox -s pytest`
- Type checking: `nox -s mypy`
- Linting: `nox -s check`

### Code Formatting
- Format code: `nox -s format -- --fix`
- Check formatting: `nox -s format`
- Format TOML files: `nox -s taplo -- --fix`

### Building and Running
- Build package: `nix build`
- Run the CLI: `nix run`
- Run with arguments: `nix run . -- --name=there --count=3`

## Architecture

### Package Structure
- `llmbot/cli.py` - Main CLI entry point using Click
- `llmbot/utils.py` - Utility functions (currently contains safe_divide)
- `llmbot/resources/` - Package resources including help text
- `tests/` - Test suite with pytest

### Key Components
- **CLI Module** (`llmbot/cli.py:13`): Main command handler with name/count options
- **Resources System** (`llmbot/resources/__init__.py:9`): Handles loading of package resources like help text
- **Version Management** (`llmbot/__init__.py:5`): Uses importlib.metadata for dynamic versioning

### Configuration
- **Ruff**: Comprehensive linting with extensive rule set (AIR, ERA, FAST, etc.)
- **MyPy**: Type checking with no-install-types flag
- **Pytest**: Testing with doctest module support
- **Nox**: Task automation for development workflows

The project follows modern Python packaging standards with pyproject.toml configuration and uses setuptools as the build backend.