"""Root command wiring for the Ravenstash developer CLI."""

from __future__ import annotations

import typer

from .auth.commands import app as auth_app
from .ci.commands import app as ci_app
from .pkg.commands import app as pkg_app
from .repo.commands import app as repo_app
from .runtime.commands import app as runtime_app


app = typer.Typer(
    name="rvn",
    help="Ravenstash developer CLI.",
    no_args_is_help=False,
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)

app.add_typer(auth_app, name="auth")
app.add_typer(runtime_app, name="runtime")
app.add_typer(pkg_app, name="pkg")
app.add_typer(pkg_app, name="packages", help="Alias for `rvn pkg`.")
app.add_typer(repo_app, name="repo")
app.add_typer(ci_app, name="ci")


def _version_callback(value: bool) -> None:
    if value:
        from importlib.metadata import PackageNotFoundError, version

        try:
            v = version("rvn")
        except PackageNotFoundError:
            v = "dev"
        typer.echo(f"rvn {v}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Print version and exit.",
    ),
) -> None:
    """Ravenstash developer CLI."""
    if ctx.invoked_subcommand is None and not version:
        typer.echo(ctx.get_help())
        raise typer.Exit()
