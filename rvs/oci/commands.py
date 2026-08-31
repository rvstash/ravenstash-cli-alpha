"""Typer adapters for OCI-native passthrough commands."""

from __future__ import annotations

import typer

from . import runner


PASSTHROUGH_CONTEXT = {
    "allow_extra_args": True,
    "ignore_unknown_options": True,
    "help_option_names": ["-h", "--help"],
}


def _options(
    profile: str | None,
    repo: str | None,
    target: str | None,
    account: str | None,
    customer_id: str | None,
    kind: runner.OciRegistryKind | None,
) -> runner.OciOptions:
    return runner.OciOptions(
        profile=profile,
        repo=repo,
        target=target,
        account=account,
        customer_id=customer_id,
        kind=kind,
    )


def _run(
    tool: runner.OciTool,
    ctx: typer.Context,
    profile: str | None,
    repo: str | None,
    target: str | None,
    account: str | None,
    customer_id: str | None,
    kind: runner.OciRegistryKind | None,
) -> None:
    runner.run(tool, list(ctx.args), _options(profile, repo, target, account, customer_id, kind))


def docker(
    ctx: typer.Context,
    rvs_profile: str | None = typer.Option(None, "--rvs-profile"),
    rvs_repo: str | None = typer.Option(None, "--rvs-repo"),
    rvs_target: str | None = typer.Option(None, "--rvs-target"),
    rvs_account: str | None = typer.Option(None, "--rvs-account"),
    rvs_customer_id: str | None = typer.Option(None, "--rvs-customer-id"),
) -> None:
    _run(
        "docker",
        ctx,
        rvs_profile,
        rvs_repo,
        rvs_target,
        rvs_account,
        rvs_customer_id,
        "container",
    )


def helm(
    ctx: typer.Context,
    rvs_profile: str | None = typer.Option(None, "--rvs-profile"),
    rvs_repo: str | None = typer.Option(None, "--rvs-repo"),
    rvs_target: str | None = typer.Option(None, "--rvs-target"),
    rvs_account: str | None = typer.Option(None, "--rvs-account"),
    rvs_customer_id: str | None = typer.Option(None, "--rvs-customer-id"),
) -> None:
    _run("helm", ctx, rvs_profile, rvs_repo, rvs_target, rvs_account, rvs_customer_id, "helm")


def oras(
    ctx: typer.Context,
    rvs_kind: runner.OciRegistryKind = typer.Option(..., "--rvs-kind"),
    rvs_profile: str | None = typer.Option(None, "--rvs-profile"),
    rvs_repo: str | None = typer.Option(None, "--rvs-repo"),
    rvs_target: str | None = typer.Option(None, "--rvs-target"),
    rvs_account: str | None = typer.Option(None, "--rvs-account"),
    rvs_customer_id: str | None = typer.Option(None, "--rvs-customer-id"),
) -> None:
    _run("oras", ctx, rvs_profile, rvs_repo, rvs_target, rvs_account, rvs_customer_id, rvs_kind)


def oci_reference(
    kind: runner.OciRegistryKind = typer.Option(..., "--kind"),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    target: str | None = typer.Option(None, "--target"),
    account: str | None = typer.Option(None, "--account"),
    oci_path: str | None = typer.Option(None, "--oci-path"),
    reference_value: str | None = typer.Option(None, "--reference"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(None, "--customer-id"),
) -> None:
    """Print the readable customer-facing OCI root; never the internal /v2 route."""
    typer.echo(
        runner.reference(
            kind=kind,
            options=_options(profile, repo, target, account, customer_id, kind),
            oci_path=oci_path,
            reference_value=reference_value,
        )
    )
