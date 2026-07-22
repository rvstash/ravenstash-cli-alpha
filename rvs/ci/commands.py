"""Placeholder `rvs ci` command group."""

from __future__ import annotations

import typer

from .. import output


app = typer.Typer(
    name="ci",
    help="Manage Ravenstash CI. Not implemented yet.",
    no_args_is_help=True,
)


def _not_implemented() -> None:
    output.fatal("rvs ci is not implemented yet.")


@app.command("list")
def list_pipelines() -> None:
    """List CI pipelines."""
    _not_implemented()


@app.command("run")
def run(
    pipeline: str | None = typer.Argument(None, help="Pipeline name."),
) -> None:
    """Run a CI pipeline."""
    del pipeline
    _not_implemented()


@app.command("status")
def status(
    run_id: str | None = typer.Argument(None, help="Run ID."),
) -> None:
    """Show CI status."""
    del run_id
    _not_implemented()


@app.command("logs")
def logs(
    run_id: str = typer.Argument(..., help="Run ID."),
) -> None:
    """Show CI logs."""
    del run_id
    _not_implemented()
