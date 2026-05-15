"""rvn pypi — read-only PyPI registry commands.

These commands handle GET / read operations only.  They do NOT publish,
upload, or modify anything in the registry.  For write operations use
``rvn python publish`` (or ``rvn pkg publish``).

Commands closely mirror pip's own interface, but the private index URL is
pre-injected so you never have to copy-paste it.

    rvn pypi install requests boto3
    rvn pypi install -r requirements.txt
    rvn pypi install requests --no-deps --upgrade
    rvn pypi download requests --dest ./wheels
    rvn pypi show requests
    rvn pypi list --outdated
    rvn pypi freeze
    rvn pypi index-url
    rvn pypi index-url --auth          # with token embedded

Unknown flags are forwarded verbatim to pip / uv pip.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import typer

from .. import auth as auth_mod
from .. import config as cfg_mod
from .. import output
from ..registries import pypi as pypi_reg


app = typer.Typer(
    help="Read-only PyPI commands — GET operations only.  No publish/upload.",
    no_args_is_help=True,
)


# ── credential helper (token optional for read-only ops) ─────────────────────


def _resolve(
    repo: str | None,
    profile: str | None,
) -> tuple[str, str, str | None]:
    """Return (api_url, slug, token_or_None).

    Token is *optional* — callers embed it for auth but still try without it
    (for future public-read repos).  Only slug is required.
    """
    cfg = cfg_mod.load()
    p = cfg.active_profile(profile)
    token = auth_mod.get_token(profile or cfg.default_profile) or p.token
    slug = repo or cfg.registry_defaults("pypi").default_repo
    if not slug:
        output.fatal(
            "No repository specified.  Pass --repo or set a default:\n"
            "  rvn config set-default-repo pypi <slug>"
        )
    return p.api_url, slug, token  # type: ignore[return-value]


def _authed_index(api_url: str, slug: str, token: str | None) -> str:
    url = pypi_reg.simple_index_url(api_url, slug)
    if token:
        parsed = urlparse(url)
        url = urlunparse(parsed._replace(netloc=f"__token__:{token}@{parsed.netloc}"))
    return url


def _env_with_index(api_url: str, slug: str, token: str | None) -> dict:
    authed = _authed_index(api_url, slug, token)
    env = {**os.environ}
    existing = env.get("UV_EXTRA_INDEX_URL", "")
    env["UV_EXTRA_INDEX_URL"] = (existing + " " + authed).strip()
    env["PIP_EXTRA_INDEX_URL"] = authed
    return env


def _pip_cmd() -> list[str]:
    """Prefer 'uv pip' when uv is available."""
    return ["uv", "pip"] if shutil.which("uv") else ["pip"]


# ── install ───────────────────────────────────────────────────────────────────


@app.command(
    "install",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def pip_install(
    ctx: typer.Context,
    repo: str | None = typer.Option(None, "--repo", "-r", help="Repository slug."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Install packages from the private index.  All pip/uv-pip flags accepted.

    \b
    Examples:
        rvn pypi install requests
        rvn pypi install requests boto3 --no-deps
        rvn pypi install -r requirements.txt --upgrade
        rvn pypi install 'numpy>=1.24' --pre
    """
    api_url, slug, token = _resolve(repo, profile)
    env = _env_with_index(api_url, slug, token)
    cmd = [*_pip_cmd(), "install", *ctx.args]
    output.info(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, env=env, check=True)


# ── download ──────────────────────────────────────────────────────────────────


@app.command(
    "download",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def pip_download(
    ctx: typer.Context,
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    dest: Path = typer.Option(
        Path("wheelhouse"), "--dest", "-d", help="Download destination directory."
    ),
) -> None:
    """Download wheels/sdists from the private index without installing them.

    \b
    Examples:
        rvn pypi download requests numpy
        rvn pypi download requests --dest ./wheels --no-deps
        rvn pypi download -r requirements.txt --only-binary :all:
    """
    api_url, slug, token = _resolve(repo, profile)
    env = _env_with_index(api_url, slug, token)
    dest.mkdir(parents=True, exist_ok=True)
    cmd = [*_pip_cmd(), "download", "--dest", str(dest), *ctx.args]
    output.info(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, env=env, check=True)


# ── show ──────────────────────────────────────────────────────────────────────


@app.command("show")
def pip_show(
    packages: list[str] = typer.Argument(..., help="Package names to inspect."),
) -> None:
    """Show metadata for installed packages (delegates to pip show / uv pip show).

    \b
    Examples:
        rvn pypi show requests
        rvn pypi show requests boto3
    """
    cmd = [*_pip_cmd(), "show", *packages]
    subprocess.run(cmd, check=True)


# ── list ──────────────────────────────────────────────────────────────────────


@app.command(
    "list",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def pip_list(
    ctx: typer.Context,
) -> None:
    """List installed packages (delegates to pip list / uv pip list).

    \b
    Examples:
        rvn pypi list
        rvn pypi list --outdated
        rvn pypi list --format json
    """
    cmd = [*_pip_cmd(), "list", *ctx.args]
    subprocess.run(cmd, check=True)


# ── freeze ────────────────────────────────────────────────────────────────────


@app.command("freeze")
def pip_freeze() -> None:
    """Print installed packages in requirements.txt format.

    \b
    Examples:
        rvn pypi freeze
        rvn pypi freeze > requirements.txt
    """
    cmd = [*_pip_cmd(), "freeze"]
    subprocess.run(cmd, check=True)


# ── index-url ─────────────────────────────────────────────────────────────────


@app.command("index-url")
def index_url(
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    auth: bool = typer.Option(
        False, "--auth", help="Embed token in URL (for pip.conf / pyproject.toml)."
    ),
) -> None:
    """Print the simple index URL for the private PyPI repository.

    \b
    Examples:
        rvn pypi index-url
        rvn pypi index-url --auth           # with __token__:<token> embedded
        pip install requests --extra-index-url $(rvn pypi index-url --auth)
    """
    api_url, slug, token = _resolve(repo, profile)
    url = pypi_reg.simple_index_url(api_url, slug)
    if auth and token:
        parsed = urlparse(url)
        url = urlunparse(parsed._replace(netloc=f"__token__:{token}@{parsed.netloc}"))
    typer.echo(url)
