"""
Test suite.

A few examples for invoking `nox`:

    nox --list
    nox
    nox -s taplo
    nox -s taplo -- --fix
    nox -s format
    nox -s format -- --fix
    nox -s check
    nox -k "not pytest"
    nox -k "not mypy and not pytest"
"""

import nox  # type: ignore[import-not-found]

#: Files and directories of interest.
paths = [
    "noxfile.py",
    "tests",
    "llmbot",
]


@nox.session(python=False, name="format")
def ruff_format(session: nox.Session) -> None:
    """Format codebase and sort imports."""
    ## Do we want to fix the format issues?
    if "--fix" in session.posargs:
        session.run("ruff", "format", *paths, external=True)
        session.run("ruff", "check", "--select=I", "--fix", *paths, external=True)
    else:
        session.run("ruff", "format", "--check", *paths, external=True)
        session.run("ruff", "check", "--select=I", *paths, external=True)


@nox.session(python=False, name="check")
def ruff_check(session: nox.Session) -> None:
    """Lint and check codebase."""
    ## Define default arguments:
    args = []

    ## Do we want statistics?
    if "--stats" in session.posargs:
        args.append("--statistics")

    ## Do we want JSON output?
    if "--json" in session.posargs:
        args.extend(["--output-format", "json"])

    ## Do we want warning mode for faster iteration?
    if "--warn-only" in session.posargs:
        args.append("--exit-zero")

    ## All other arguments are passed as is:
    args.extend(
        arg
        for arg in session.posargs
        if arg not in ["--stats", "--json", "--warn-only"]
    )

    ## Run ruff:
    session.run("ruff", "check", *args, *paths, external=True)


@nox.session(python=False)
def mypy(session: nox.Session) -> None:
    """Type-check on the codebase."""
    args = ["--no-install-types"]

    ## Do we want warning mode for faster iteration?
    if "--warn-only" in session.posargs:
        args.append("--warn-unreachable")

    session.run("mypy", *args, *paths, external=True)


@nox.session(python=False)
def pytest(session: nox.Session) -> None:
    """Run the test suite."""
    session.run("pytest", external=True)


@nox.session(python=False)
def fix(session: nox.Session) -> None:
    """Fix all automatically fixable issues."""
    session.run("ruff", "format", *paths, external=True)
    session.run("ruff", "check", "--select=I", "--fix", *paths, external=True)
    session.run("ruff", "check", "--fix", *paths, external=True)
