"""Root command wiring for the Ravenstash developer CLI."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 - Typer resolves command annotations at runtime.

import typer

from .account.commands import app as account_app
from .artifacts.commands import app as artifacts_app
from .auth.commands import app as auth_app
from .auth.commands import profile_app
from .context.commands import app as context_app
from .installations import Installation, write_receipt
from .native import commands as native_commands
from .oci import commands as oci_commands
from .runtime.commands import app as runtime_app
from .update import update


app = typer.Typer(
    name="rvs",
    help="Ravenstash developer CLI.",
    no_args_is_help=False,
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)

app.add_typer(auth_app, name="auth")
app.add_typer(profile_app, name="profile")
app.add_typer(account_app, name="account")
app.add_typer(context_app, name="context")
app.add_typer(runtime_app, name="runtime")
app.add_typer(artifacts_app, name="art")
app.command("update")(update)


@app.command("_record-install", hidden=True)
def _record_install(
    output_path: Path = typer.Option(..., "--output"),
    scope: str = typer.Option(..., "--scope"),
    version: str = typer.Option(..., "--version"),
    channel: str = typer.Option(..., "--channel"),
    target: str = typer.Option(..., "--target"),
    install_root: Path = typer.Option(..., "--install-root"),
    bin_directory: Path = typer.Option(..., "--bin-directory"),
) -> None:
    """Write the validated, non-secret receipt used by the portable updater."""

    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as package_version

    from .installations import platform_target

    try:
        running_version = package_version("ravenstash-cli")
    except PackageNotFoundError:
        running_version = "dev"
    if version != running_version:
        raise typer.BadParameter("receipt version does not match the running rvs executable")
    if target != platform_target():
        raise typer.BadParameter("receipt target does not match the running rvs executable")
    write_receipt(
        output_path,
        Installation(
            schema=1,
            method="portable",
            scope=scope,
            version=version,
            channel=channel,
            target=target,
            install_root=str(install_root.resolve()),
            bin_directory=str(bin_directory.resolve()),
        ),
    )


app.command(
    "pip",
    context_settings=native_commands.PASSTHROUGH_CONTEXT,
    help="Run pip with temporary access to a Ravenstash PyPI repository.",
)(native_commands.pip)
app.command(
    "uv",
    context_settings=native_commands.PASSTHROUGH_CONTEXT,
    help="Run uv with temporary access to a Ravenstash PyPI repository.",
)(native_commands.uv)
app.command(
    "twine",
    context_settings=native_commands.PASSTHROUGH_CONTEXT,
    help="Run Twine with temporary access to publish to Ravenstash.",
)(native_commands.twine)
app.command(
    "npm",
    context_settings=native_commands.PASSTHROUGH_CONTEXT,
    help="Run npm with temporary access to a Ravenstash npm repository.",
)(native_commands.npm)
app.command(
    "mvn",
    context_settings=native_commands.PASSTHROUGH_CONTEXT,
    help="Run Maven with temporary access to a Ravenstash Maven repository.",
)(native_commands.mvn)
app.command(
    "docker",
    context_settings=oci_commands.PASSTHROUGH_CONTEXT,
    help="Run Docker with temporary access; push, pull, and tag accept private image paths.",
)(oci_commands.docker)
app.command(
    "helm",
    context_settings=oci_commands.PASSTHROUGH_CONTEXT,
    help="Run Helm with temporary access and selected-repository chart paths.",
)(oci_commands.helm)
app.command(
    "oras",
    context_settings=oci_commands.PASSTHROUGH_CONTEXT,
    help="Run ORAS with temporary access to an OCI-enabled repository.",
)(oci_commands.oras)


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
        help="Print output from rvs as JSON.",
    ),
) -> None:
    """Ravenstash developer CLI."""
    from . import output

    output.set_json(json_output)
    if ctx.invoked_subcommand is None and not version:
        typer.echo(ctx.get_help())
        raise typer.Exit()
