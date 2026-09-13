"""Typer adapters for OCI-native passthrough commands."""

from __future__ import annotations

import typer

from .. import output
from . import runner


PASSTHROUGH_CONTEXT = {
    "allow_extra_args": True,
    "ignore_unknown_options": True,
    "help_option_names": ["-h", "--help"],
}


def _options(
    profile: str | None,
    target: str | None,
    account: str | None,
    customer_id: str | None,
    yes: bool = False,
) -> runner.OciOptions:
    return runner.OciOptions(
        yes=yes,
        profile=profile,
        target=target,
        account=account,
        customer_id=customer_id,
    )


def _run(
    tool: runner.OciTool,
    ctx: typer.Context,
    profile: str | None,
    target: str | None,
    account: str | None,
    customer_id: str | None,
    yes: bool = False,
) -> None:
    if any(arg == "--rvs-repo" or arg.startswith("--rvs-repo=") for arg in ctx.args):
        output.fatal("Unknown option '--rvs-repo'. Use --rvs-target.")
    if any(arg.split("=", 1)[0].startswith("--rvs-") for arg in ctx.args):
        output.fatal("Unknown rvs option. Use --rvs-target for the target.")
    runner.run(tool, list(ctx.args), _options(profile, target, account, customer_id, yes))


def docker(
    ctx: typer.Context,
    rvs_yes: bool = typer.Option(False, "--rvs-yes", help="Skip publishing confirmation."),
    rvs_profile: str | None = typer.Option(None, "--rvs-profile"),
    rvs_target: str | None = typer.Option(None, "--rvs-target"),
    rvs_account: str | None = typer.Option(None, "--rvs-account"),
    rvs_customer_id: str | None = typer.Option(None, "--rvs-account-ref", hidden=True),
) -> None:
    _run(
        "docker",
        ctx,
        rvs_profile,
        rvs_target,
        rvs_account,
        rvs_customer_id,
        rvs_yes,
    )


def helm(
    ctx: typer.Context,
    rvs_yes: bool = typer.Option(False, "--rvs-yes", help="Skip publishing confirmation."),
    rvs_profile: str | None = typer.Option(None, "--rvs-profile"),
    rvs_target: str | None = typer.Option(None, "--rvs-target"),
    rvs_account: str | None = typer.Option(None, "--rvs-account"),
    rvs_customer_id: str | None = typer.Option(None, "--rvs-account-ref", hidden=True),
) -> None:
    _run("helm", ctx, rvs_profile, rvs_target, rvs_account, rvs_customer_id, rvs_yes)


def oras(
    ctx: typer.Context,
    rvs_yes: bool = typer.Option(False, "--rvs-yes", help="Skip publishing confirmation."),
    rvs_profile: str | None = typer.Option(None, "--rvs-profile"),
    rvs_target: str | None = typer.Option(None, "--rvs-target"),
    rvs_account: str | None = typer.Option(None, "--rvs-account"),
    rvs_customer_id: str | None = typer.Option(None, "--rvs-account-ref", hidden=True),
) -> None:
    _run("oras", ctx, rvs_profile, rvs_target, rvs_account, rvs_customer_id, rvs_yes)
