"""Top-level native package-manager passthrough commands."""

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
    native_config: str,
) -> runner.NativeOptions:
    return runner.NativeOptions(
        profile=profile,
        repo=repo,
        target=target,
        account=account,
        customer_id=customer_id,
        native_config=runner.normalize_policy(native_config),
    )


def _run(tool: runner.NativeTool, ctx: typer.Context, options: runner.NativeOptions) -> None:
    runner.run(tool, list(ctx.args), options)


def _native_config_option() -> str:
    return "respect"


def pip(
    ctx: typer.Context,
    rvs_profile: str | None = typer.Option(None, "--rvs-profile", help="rvs auth profile."),
    rvs_repo: str | None = typer.Option(
        None,
        "--rvs-repo",
        help="Ravenstash PyPI repository override.",
    ),
    rvs_target: str | None = typer.Option(None, "--rvs-target", help="Ravenstash target override."),
    rvs_account: str | None = typer.Option(None, "--rvs-account", help="Acting account override."),
    rvs_customer_id: str | None = typer.Option(
        None,
        "--rvs-customer-id",
        help="Customer disambiguation override.",
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
        _options(
            rvs_profile, rvs_repo, rvs_target, rvs_account, rvs_customer_id, rvs_native_config
        ),
    )


def uv(
    ctx: typer.Context,
    rvs_profile: str | None = typer.Option(None, "--rvs-profile", help="rvs auth profile."),
    rvs_repo: str | None = typer.Option(
        None,
        "--rvs-repo",
        help="Ravenstash PyPI repository override.",
    ),
    rvs_target: str | None = typer.Option(None, "--rvs-target", help="Ravenstash target override."),
    rvs_account: str | None = typer.Option(None, "--rvs-account", help="Acting account override."),
    rvs_customer_id: str | None = typer.Option(
        None,
        "--rvs-customer-id",
        help="Customer disambiguation override.",
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
        _options(
            rvs_profile, rvs_repo, rvs_target, rvs_account, rvs_customer_id, rvs_native_config
        ),
    )


def twine(
    ctx: typer.Context,
    rvs_profile: str | None = typer.Option(None, "--rvs-profile", help="rvs auth profile."),
    rvs_repo: str | None = typer.Option(
        None,
        "--rvs-repo",
        help="Ravenstash PyPI repository override.",
    ),
    rvs_target: str | None = typer.Option(None, "--rvs-target", help="Ravenstash target override."),
    rvs_account: str | None = typer.Option(None, "--rvs-account", help="Acting account override."),
    rvs_customer_id: str | None = typer.Option(
        None,
        "--rvs-customer-id",
        help="Customer disambiguation override.",
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
        _options(
            rvs_profile, rvs_repo, rvs_target, rvs_account, rvs_customer_id, rvs_native_config
        ),
    )


def npm(
    ctx: typer.Context,
    rvs_profile: str | None = typer.Option(None, "--rvs-profile", help="rvs auth profile."),
    rvs_repo: str | None = typer.Option(
        None,
        "--rvs-repo",
        help="Ravenstash npm repository override.",
    ),
    rvs_target: str | None = typer.Option(None, "--rvs-target", help="Ravenstash target override."),
    rvs_account: str | None = typer.Option(None, "--rvs-account", help="Acting account override."),
    rvs_customer_id: str | None = typer.Option(
        None,
        "--rvs-customer-id",
        help="Customer disambiguation override.",
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
        _options(
            rvs_profile, rvs_repo, rvs_target, rvs_account, rvs_customer_id, rvs_native_config
        ),
    )


def mvn(
    ctx: typer.Context,
    rvs_profile: str | None = typer.Option(None, "--rvs-profile", help="rvs auth profile."),
    rvs_repo: str | None = typer.Option(
        None,
        "--rvs-repo",
        help="Ravenstash Maven repository override.",
    ),
    rvs_target: str | None = typer.Option(None, "--rvs-target", help="Ravenstash target override."),
    rvs_account: str | None = typer.Option(None, "--rvs-account", help="Acting account override."),
    rvs_customer_id: str | None = typer.Option(
        None,
        "--rvs-customer-id",
        help="Customer disambiguation override.",
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
        _options(
            rvs_profile, rvs_repo, rvs_target, rvs_account, rvs_customer_id, rvs_native_config
        ),
    )
