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
    rvs_profile: str | None = typer.Option(None, "--rvs-profile", help="rvs auth profile."),
    rvs_repo: str | None = typer.Option(
        None,
        "--rvs-repo",
        help="Ravenstash PyPI repository override.",
    ),
    rvs_customer_pid: str | None = typer.Option(
        None,
        "--rvs-customer-pid",
        help="Customer public ID override.",
    ),
    rvs_native_config: str = typer.Option(
        _native_config_option(),
        "--rvs-native-config",
        help="Native config policy: respect, override, or isolate.",
    ),
) -> None:
    _run("pip", ctx, _options(rvs_profile, rvs_repo, rvs_customer_pid, rvs_native_config))


def uv(
    ctx: typer.Context,
    rvs_profile: str | None = typer.Option(None, "--rvs-profile", help="rvs auth profile."),
    rvs_repo: str | None = typer.Option(
        None,
        "--rvs-repo",
        help="Ravenstash PyPI repository override.",
    ),
    rvs_customer_pid: str | None = typer.Option(
        None,
        "--rvs-customer-pid",
        help="Customer public ID override.",
    ),
    rvs_native_config: str = typer.Option(
        _native_config_option(),
        "--rvs-native-config",
        help="Native config policy: respect, override, or isolate.",
    ),
) -> None:
    _run("uv", ctx, _options(rvs_profile, rvs_repo, rvs_customer_pid, rvs_native_config))


def twine(
    ctx: typer.Context,
    rvs_profile: str | None = typer.Option(None, "--rvs-profile", help="rvs auth profile."),
    rvs_repo: str | None = typer.Option(
        None,
        "--rvs-repo",
        help="Ravenstash PyPI repository override.",
    ),
    rvs_customer_pid: str | None = typer.Option(
        None,
        "--rvs-customer-pid",
        help="Customer public ID override.",
    ),
    rvs_native_config: str = typer.Option(
        _native_config_option(),
        "--rvs-native-config",
        help="Native config policy: respect, override, or isolate.",
    ),
) -> None:
    _run("twine", ctx, _options(rvs_profile, rvs_repo, rvs_customer_pid, rvs_native_config))


def npm(
    ctx: typer.Context,
    rvs_profile: str | None = typer.Option(None, "--rvs-profile", help="rvs auth profile."),
    rvs_repo: str | None = typer.Option(
        None,
        "--rvs-repo",
        help="Ravenstash npm repository override.",
    ),
    rvs_customer_pid: str | None = typer.Option(
        None,
        "--rvs-customer-pid",
        help="Customer public ID override.",
    ),
    rvs_native_config: str = typer.Option(
        _native_config_option(),
        "--rvs-native-config",
        help="Native config policy: respect, override, or isolate.",
    ),
) -> None:
    _run("npm", ctx, _options(rvs_profile, rvs_repo, rvs_customer_pid, rvs_native_config))


def mvn(
    ctx: typer.Context,
    rvs_profile: str | None = typer.Option(None, "--rvs-profile", help="rvs auth profile."),
    rvs_repo: str | None = typer.Option(
        None,
        "--rvs-repo",
        help="Ravenstash Maven repository override.",
    ),
    rvs_customer_pid: str | None = typer.Option(
        None,
        "--rvs-customer-pid",
        help="Customer public ID override.",
    ),
    rvs_native_config: str = typer.Option(
        _native_config_option(),
        "--rvs-native-config",
        help="Native config policy: respect, override, or isolate.",
    ),
) -> None:
    _run("mvn", ctx, _options(rvs_profile, rvs_repo, rvs_customer_pid, rvs_native_config))
