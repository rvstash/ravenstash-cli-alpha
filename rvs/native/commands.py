"""Top-level native package-manager passthrough commands."""

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
    native_config: str,
    yes: bool = False,
) -> runner.NativeOptions:
    return runner.NativeOptions(
        yes=yes,
        profile=profile,
        target=target,
        account=account,
        customer_id=customer_id,
        native_config=runner.normalize_policy(native_config),
    )


def _run(tool: runner.NativeTool, ctx: typer.Context, options: runner.NativeOptions) -> None:
    if any(arg == "--rvs-repo" or arg.startswith("--rvs-repo=") for arg in ctx.args):
        output.fatal("Unknown option '--rvs-repo'. Use --rvs-target.")
    runner.run(tool, list(ctx.args), options)


def _native_config_option() -> str:
    return "respect"


def pip(
    ctx: typer.Context,
    rvs_profile: str | None = typer.Option(None, "--rvs-profile", help="Local CLI profile."),
    rvs_target: str | None = typer.Option(
        None, "--rvs-target", help="Repository or mirror for this command."
    ),
    rvs_account: str | None = typer.Option(
        None, "--rvs-account", help="Username or organization handle."
    ),
    rvs_customer_id: str | None = typer.Option(
        None,
        "--rvs-customer-id",
        help="Account ID for advanced use.",
        hidden=True,
    ),
    rvs_native_config: str = typer.Option(
        _native_config_option(),
        "--rvs-native-config",
        help="Native config policy: respect, override, or isolate.",
    ),
) -> None:
    _run(
        "pip",
        ctx,
        _options(rvs_profile, rvs_target, rvs_account, rvs_customer_id, rvs_native_config),
    )


def uv(
    ctx: typer.Context,
    rvs_yes: bool = typer.Option(False, "--rvs-yes", help="Skip publishing confirmation."),
    rvs_profile: str | None = typer.Option(None, "--rvs-profile", help="Local CLI profile."),
    rvs_target: str | None = typer.Option(
        None, "--rvs-target", help="Repository or mirror for this command."
    ),
    rvs_account: str | None = typer.Option(
        None, "--rvs-account", help="Username or organization handle."
    ),
    rvs_customer_id: str | None = typer.Option(
        None,
        "--rvs-customer-id",
        help="Account ID for advanced use.",
        hidden=True,
    ),
    rvs_native_config: str = typer.Option(
        _native_config_option(),
        "--rvs-native-config",
        help="Native config policy: respect, override, or isolate.",
    ),
) -> None:
    _run(
        "uv",
        ctx,
        _options(rvs_profile, rvs_target, rvs_account, rvs_customer_id, rvs_native_config, rvs_yes),
    )


def twine(
    ctx: typer.Context,
    rvs_yes: bool = typer.Option(False, "--rvs-yes", help="Skip publishing confirmation."),
    rvs_profile: str | None = typer.Option(None, "--rvs-profile", help="Local CLI profile."),
    rvs_target: str | None = typer.Option(
        None, "--rvs-target", help="Repository or mirror for this command."
    ),
    rvs_account: str | None = typer.Option(
        None, "--rvs-account", help="Username or organization handle."
    ),
    rvs_customer_id: str | None = typer.Option(
        None,
        "--rvs-customer-id",
        help="Account ID for advanced use.",
        hidden=True,
    ),
    rvs_native_config: str = typer.Option(
        _native_config_option(),
        "--rvs-native-config",
        help="Native config policy: respect, override, or isolate.",
    ),
) -> None:
    _run(
        "twine",
        ctx,
        _options(rvs_profile, rvs_target, rvs_account, rvs_customer_id, rvs_native_config, rvs_yes),
    )


def npm(
    ctx: typer.Context,
    rvs_yes: bool = typer.Option(False, "--rvs-yes", help="Skip publishing confirmation."),
    rvs_profile: str | None = typer.Option(None, "--rvs-profile", help="Local CLI profile."),
    rvs_target: str | None = typer.Option(
        None, "--rvs-target", help="Repository or mirror for this command."
    ),
    rvs_account: str | None = typer.Option(
        None, "--rvs-account", help="Username or organization handle."
    ),
    rvs_customer_id: str | None = typer.Option(
        None,
        "--rvs-customer-id",
        help="Account ID for advanced use.",
        hidden=True,
    ),
    rvs_native_config: str = typer.Option(
        _native_config_option(),
        "--rvs-native-config",
        help="Native config policy: respect, override, or isolate.",
    ),
) -> None:
    _run(
        "npm",
        ctx,
        _options(rvs_profile, rvs_target, rvs_account, rvs_customer_id, rvs_native_config, rvs_yes),
    )


def mvn(
    ctx: typer.Context,
    rvs_yes: bool = typer.Option(False, "--rvs-yes", help="Skip publishing confirmation."),
    rvs_profile: str | None = typer.Option(None, "--rvs-profile", help="Local CLI profile."),
    rvs_target: str | None = typer.Option(
        None, "--rvs-target", help="Repository or mirror for this command."
    ),
    rvs_account: str | None = typer.Option(
        None, "--rvs-account", help="Username or organization handle."
    ),
    rvs_customer_id: str | None = typer.Option(
        None,
        "--rvs-customer-id",
        help="Account ID for advanced use.",
        hidden=True,
    ),
    rvs_native_config: str = typer.Option(
        _native_config_option(),
        "--rvs-native-config",
        help="Native config policy: respect, override, or isolate.",
    ),
) -> None:
    _run(
        "mvn",
        ctx,
        _options(rvs_profile, rvs_target, rvs_account, rvs_customer_id, rvs_native_config, rvs_yes),
    )
