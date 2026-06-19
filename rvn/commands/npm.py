"""rvn npm — read-only npm registry commands.

These commands handle GET / read operations only.  They do NOT publish,
upload, or modify the registry.  For write operations use
``rvn node publish`` (or ``rvn pkg publish``).

Commands closely mirror npm's own interface, but the private registry URL
and auth token are pre-injected so you never have to copy-paste them.

    rvn npm install lodash
    rvn npm install                       # install from package.json
    rvn npm install lodash --save-dev
    rvn npm ci
    rvn npm view lodash
    rvn npm view lodash version
    rvn npm ls
    rvn npm ls --depth 1
    rvn npm outdated
    rvn npm registry-url
    rvn npm npmrc

Unknown flags are forwarded verbatim to npm.
"""

from __future__ import annotations

import os
import subprocess
from urllib.parse import urlparse

import typer

from .. import auth as auth_mod
from .. import config as cfg_mod
from .. import output
from ..registries import npm as npm_reg
from ..runtimes import tools


app = typer.Typer(
    help="Read-only npm commands — GET operations only.  No publish.",
    no_args_is_help=True,
)


# ── credential helper (token optional for read-only ops) ─────────────────────


def _resolve(
    repo: str | None,
    profile: str | None,
) -> tuple[str, str, str | None]:
    """Return (api_url, slug, token_or_None)."""
    cfg = cfg_mod.load()
    p = cfg.active_profile(profile)
    token = auth_mod.get_token(profile or cfg.default_profile)
    slug = repo or cfg.registry_defaults("npm").default_repo
    if not slug:
        output.fatal(
            "No repository specified.  Pass --repo or set a default:\n"
            "  rvn auth add-registry --kind npm --repo <slug>"
        )
    return p.api_url, slug, token  # type: ignore[return-value]


def _inject_env(env: dict, reg_url: str, token: str | None) -> None:
    host = urlparse(reg_url).netloc
    if token:
        env[f"NPM_CONFIG_//{host}/:_authToken"] = token


# ── install ───────────────────────────────────────────────────────────────────


@app.command(
    "install",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def npm_install(
    ctx: typer.Context,
    repo: str | None = typer.Option(None, "--repo", "-r", help="Repository slug."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Install packages from the private npm registry.  All npm flags accepted.

    \b
    Examples:
        rvn npm install                    # install from package.json
        rvn npm install lodash
        rvn npm install lodash@4 --save
        rvn npm install @scope/pkg --save-dev
        rvn npm install lodash --ignore-scripts
    """
    api_url, slug, token = _resolve(repo, profile)
    reg_url = npm_reg.registry_url(api_url, slug)
    env = {**os.environ}
    _inject_env(env, reg_url, token)
    cmd = [tools.npm(), "install", "--registry", reg_url, *ctx.args]
    output.info(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, env=env, check=True)


# ── ci ────────────────────────────────────────────────────────────────────────


@app.command(
    "ci",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def npm_ci(
    ctx: typer.Context,
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Clean install from lock file (npm ci) with private registry injected.

    \b
    Examples:
        rvn npm ci
        rvn npm ci --ignore-scripts
    """
    api_url, slug, token = _resolve(repo, profile)
    reg_url = npm_reg.registry_url(api_url, slug)
    env = {**os.environ}
    _inject_env(env, reg_url, token)
    cmd = [tools.npm(), "ci", "--registry", reg_url, *ctx.args]
    output.info(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, env=env, check=True)


# ── view ──────────────────────────────────────────────────────────────────────


@app.command(
    "view",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def npm_view(
    ctx: typer.Context,
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Show package metadata from the private registry (npm view / npm info).

    \b
    Examples:
        rvn npm view lodash
        rvn npm view lodash version
        rvn npm view lodash --json
        rvn npm view @scope/pkg
    """
    api_url, slug, token = _resolve(repo, profile)
    reg_url = npm_reg.registry_url(api_url, slug)
    env = {**os.environ}
    _inject_env(env, reg_url, token)
    cmd = [tools.npm(), "view", "--registry", reg_url, *ctx.args]
    subprocess.run(cmd, env=env, check=True)


# ── ls ────────────────────────────────────────────────────────────────────────


@app.command(
    "ls",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def npm_ls(
    ctx: typer.Context,
) -> None:
    """List installed packages (npm ls — does not contact the registry).

    \b
    Examples:
        rvn npm ls
        rvn npm ls --depth 0
        rvn npm ls --json
    """
    cmd = [tools.npm(), "ls", *ctx.args]
    subprocess.run(cmd, check=True)


# ── outdated ──────────────────────────────────────────────────────────────────


@app.command(
    "outdated",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def npm_outdated(
    ctx: typer.Context,
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Check for outdated packages against the private registry.

    \b
    Examples:
        rvn npm outdated
        rvn npm outdated --json
    """
    api_url, slug, token = _resolve(repo, profile)
    reg_url = npm_reg.registry_url(api_url, slug)
    env = {**os.environ}
    _inject_env(env, reg_url, token)
    cmd = [tools.npm(), "outdated", "--registry", reg_url, *ctx.args]
    subprocess.run(cmd, env=env, check=False)  # npm outdated exits 1 when outdated


# ── registry-url ──────────────────────────────────────────────────────────────


@app.command("registry-url")
def registry_url(
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Print the private npm registry URL.

    \b
    Examples:
        rvn npm registry-url
        npm install lodash --registry $(rvn npm registry-url)
    """
    api_url, slug, _ = _resolve(repo, profile)
    typer.echo(npm_reg.registry_url(api_url, slug))


# ── npmrc ─────────────────────────────────────────────────────────────────────


@app.command("npmrc")
def print_npmrc(
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Print an .npmrc snippet — redirect to append to your project's .npmrc.

    \b
    Examples:
        rvn npm npmrc
        rvn npm npmrc >> .npmrc
    """
    api_url, slug, _token = _resolve(repo, profile)
    reg_url = npm_reg.registry_url(api_url, slug)
    host = urlparse(reg_url).netloc
    typer.echo(f"registry={reg_url}")
    typer.echo(f"//{host}/:_authToken=${{RVN_TOKEN}}")
