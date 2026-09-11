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
    kind: runner.OciRegistryKind | None,
    yes: bool = False,
) -> runner.OciOptions:
    return runner.OciOptions(
        yes=yes,
        profile=profile,
        target=target,
        account=account,
        customer_id=customer_id,
        kind=kind,
    )


def _run(
    tool: runner.OciTool,
    ctx: typer.Context,
    profile: str | None,
    target: str | None,
    account: str | None,
    customer_id: str | None,
    kind: runner.OciRegistryKind | None,
    yes: bool = False,
) -> None:
    if any(arg == "--rvs-repo" or arg.startswith("--rvs-repo=") for arg in ctx.args):
        output.fatal("Unknown option '--rvs-repo'. Use --rvs-target.")
    runner.run(tool, list(ctx.args), _options(profile, target, account, customer_id, kind, yes))


def docker(
    ctx: typer.Context,
    rvs_yes: bool = typer.Option(False, "--rvs-yes", help="Skip publishing confirmation."),
    rvs_profile: str | None = typer.Option(None, "--rvs-profile"),
    rvs_target: str | None = typer.Option(None, "--rvs-target"),
    rvs_account: str | None = typer.Option(None, "--rvs-account"),
    rvs_customer_id: str | None = typer.Option(None, "--rvs-customer-id", hidden=True),
) -> None:
    _run(
        "docker",
        ctx,
        rvs_profile,
        rvs_target,
        rvs_account,
        rvs_customer_id,
        "container",
        rvs_yes,
    )


def helm(
    ctx: typer.Context,
    rvs_yes: bool = typer.Option(False, "--rvs-yes", help="Skip publishing confirmation."),
    rvs_profile: str | None = typer.Option(None, "--rvs-profile"),
    rvs_target: str | None = typer.Option(None, "--rvs-target"),
    rvs_account: str | None = typer.Option(None, "--rvs-account"),
    rvs_customer_id: str | None = typer.Option(None, "--rvs-customer-id", hidden=True),
) -> None:
    _run("helm", ctx, rvs_profile, rvs_target, rvs_account, rvs_customer_id, "helm", rvs_yes)


def oras(
    ctx: typer.Context,
    rvs_yes: bool = typer.Option(False, "--rvs-yes", help="Skip publishing confirmation."),
    rvs_kind: runner.OciRegistryKind = typer.Option(..., "--rvs-kind"),
    rvs_profile: str | None = typer.Option(None, "--rvs-profile"),
    rvs_target: str | None = typer.Option(None, "--rvs-target"),
    rvs_account: str | None = typer.Option(None, "--rvs-account"),
    rvs_customer_id: str | None = typer.Option(None, "--rvs-customer-id", hidden=True),
) -> None:
    _run("oras", ctx, rvs_profile, rvs_target, rvs_account, rvs_customer_id, rvs_kind, rvs_yes)


def oci_reference(
    kind: runner.OciRegistryKind = typer.Option(..., "--kind"),
    target: str | None = typer.Option(None, "--target"),
    account: str | None = typer.Option(None, "--account"),
    oci_path: str | None = typer.Option(None, "--oci-path"),
    reference_value: str | None = typer.Option(None, "--reference"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(None, "--customer-id", hidden=True),
) -> None:
    """Print the permanent Ravenstash address for an image or chart."""
    typer.echo(
        runner.reference(
            kind=kind,
            options=_options(profile, target, account, customer_id, kind),
            oci_path=oci_path,
            reference_value=reference_value,
        )
    )
