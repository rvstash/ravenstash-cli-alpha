"""Placeholder `rvn repo` command group for future source repositories."""

from __future__ import annotations

import typer

from .. import output


app = typer.Typer(
    name="repo",
    help="Manage Ravenstash source repositories. Not implemented yet.",
    no_args_is_help=True,
)


def _not_implemented() -> None:
    output.fatal("rvn repo is not implemented yet.")


@app.command("list")
def list_repos() -> None:
    """List source repositories."""
    _not_implemented()


@app.command("create")
def create(name: str = typer.Argument(..., help="Repository name.")) -> None:
    """Create a source repository."""
    del name
    _not_implemented()


@app.command("clone")
def clone(repo: str = typer.Argument(..., help="Repository name or URL.")) -> None:
    """Clone a source repository."""
    del repo
    _not_implemented()


@app.command("show")
def show(repo: str = typer.Argument(..., help="Repository name.")) -> None:
    """Show source repository details."""
    del repo
    _not_implemented()


@app.command("delete")
def delete(repo: str = typer.Argument(..., help="Repository name.")) -> None:
    """Delete a source repository."""
    del repo
    _not_implemented()
