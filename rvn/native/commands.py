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
    customer_pid: str | None,
    native_config: str,
) -> runner.NativeOptions:
    return runner.NativeOptions(
        profile=profile,
        repo=repo,
        customer_pid=customer_pid,
        native_config=runner.normalize_policy(native_config),
    )


def _run(tool: runner.NativeTool, ctx: typer.Context, options: runner.NativeOptions) -> None:
    runner.run(tool, list(ctx.args), options)


def _native_config_option() -> str:
    return "respect"


def pip(
    ctx: typer.Context,
    rvn_profile: str | None = typer.Option(None, "--rvn-profile", help="rvn auth profile."),
    rvn_repo: str | None = typer.Option(
        None,
        "--rvn-repo",
        help="Ravenstash PyPI repository override.",
    ),
    rvn_customer_pid: str | None = typer.Option(
        None,
        "--rvn-customer-pid",
        help="Customer public ID override.",
    ),
    rvn_native_config: str = typer.Option(
        _native_config_option(),
        "--rvn-native-config",
        help="Native config policy: respect, override, or isolate.",
    ),
) -> None:
    _run("pip", ctx, _options(rvn_profile, rvn_repo, rvn_customer_pid, rvn_native_config))


def uv(
    ctx: typer.Context,
    rvn_profile: str | None = typer.Option(None, "--rvn-profile", help="rvn auth profile."),
    rvn_repo: str | None = typer.Option(
        None,
        "--rvn-repo",
        help="Ravenstash PyPI repository override.",
    ),
    rvn_customer_pid: str | None = typer.Option(
        None,
        "--rvn-customer-pid",
        help="Customer public ID override.",
    ),
    rvn_native_config: str = typer.Option(
        _native_config_option(),
        "--rvn-native-config",
        help="Native config policy: respect, override, or isolate.",
    ),
) -> None:
    _run("uv", ctx, _options(rvn_profile, rvn_repo, rvn_customer_pid, rvn_native_config))


def twine(
    ctx: typer.Context,
    rvn_profile: str | None = typer.Option(None, "--rvn-profile", help="rvn auth profile."),
    rvn_repo: str | None = typer.Option(
        None,
        "--rvn-repo",
        help="Ravenstash PyPI repository override.",
    ),
    rvn_customer_pid: str | None = typer.Option(
        None,
        "--rvn-customer-pid",
        help="Customer public ID override.",
    ),
    rvn_native_config: str = typer.Option(
        _native_config_option(),
        "--rvn-native-config",
        help="Native config policy: respect, override, or isolate.",
    ),
) -> None:
    _run("twine", ctx, _options(rvn_profile, rvn_repo, rvn_customer_pid, rvn_native_config))


def npm(
    ctx: typer.Context,
    rvn_profile: str | None = typer.Option(None, "--rvn-profile", help="rvn auth profile."),
    rvn_repo: str | None = typer.Option(
        None,
        "--rvn-repo",
        help="Ravenstash npm repository override.",
    ),
    rvn_customer_pid: str | None = typer.Option(
        None,
        "--rvn-customer-pid",
        help="Customer public ID override.",
    ),
    rvn_native_config: str = typer.Option(
        _native_config_option(),
        "--rvn-native-config",
        help="Native config policy: respect, override, or isolate.",
    ),
) -> None:
    _run("npm", ctx, _options(rvn_profile, rvn_repo, rvn_customer_pid, rvn_native_config))


def mvn(
    ctx: typer.Context,
    rvn_profile: str | None = typer.Option(None, "--rvn-profile", help="rvn auth profile."),
    rvn_repo: str | None = typer.Option(
        None,
        "--rvn-repo",
        help="Ravenstash Maven repository override.",
    ),
    rvn_customer_pid: str | None = typer.Option(
        None,
        "--rvn-customer-pid",
        help="Customer public ID override.",
    ),
    rvn_native_config: str = typer.Option(
        _native_config_option(),
        "--rvn-native-config",
        help="Native config policy: respect, override, or isolate.",
    ),
) -> None:
    _run("mvn", ctx, _options(rvn_profile, rvn_repo, rvn_customer_pid, rvn_native_config))
