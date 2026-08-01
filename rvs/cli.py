"""Root command wiring for the Ravenstash developer CLI."""

from __future__ import annotations

import typer

from .auth.commands import app as auth_app
from .ci.commands import app as ci_app
from .native import commands as native_commands
from .pkg.commands import app as pkg_app
from .repo.commands import app as repo_app
from .runtime.commands import app as runtime_app
from .update import update, upgrade


app = typer.Typer(
    name="rvs",
    help="Ravenstash developer CLI.",
    no_args_is_help=False,
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)

app.add_typer(auth_app, name="auth")
app.add_typer(runtime_app, name="runtime")
app.add_typer(pkg_app, name="pkg")
app.add_typer(pkg_app, name="packages", help="Alias for `rvs pkg`.")
app.add_typer(repo_app, name="repo")
app.add_typer(ci_app, name="ci")
app.command("update")(update)
app.command("upgrade")(upgrade)
app.command(
    "pip",
    context_settings=native_commands.PASSTHROUGH_CONTEXT,
    help="Run pip with ephemeral Ravenstash auth for Ravenstash indexes.",
)(native_commands.pip)
app.command(
    "uv",
    context_settings=native_commands.PASSTHROUGH_CONTEXT,
    help="Run uv with ephemeral Ravenstash auth for Ravenstash indexes.",
)(native_commands.uv)
app.command(
    "twine",
    context_settings=native_commands.PASSTHROUGH_CONTEXT,
    help="Run twine with ephemeral Ravenstash auth for Ravenstash uploads.",
)(native_commands.twine)
app.command(
    "npm",
    context_settings=native_commands.PASSTHROUGH_CONTEXT,
    help="Run npm with ephemeral Ravenstash auth for Ravenstash registries.",
)(native_commands.npm)
app.command(
    "mvn",
    context_settings=native_commands.PASSTHROUGH_CONTEXT,
    help="Run Maven with ephemeral Ravenstash auth for Ravenstash repositories.",
)(native_commands.mvn)


def _version_callback(value: bool) -> None:
    if value:
        from importlib.metadata import PackageNotFoundError, version

        try:
            v = version("ravenstash-cli")
        except PackageNotFoundError:
            v = "dev"
        typer.echo(f"Ravenstash CLI {v}")
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
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit rvs-owned output as JSON.",
    ),
) -> None:
    """Ravenstash developer CLI."""
    from . import output

    output.set_json(json_output)
    if ctx.invoked_subcommand is None and not version:
        typer.echo(ctx.get_help())
        raise typer.Exit()
