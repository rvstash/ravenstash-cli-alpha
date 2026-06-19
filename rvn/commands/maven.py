"""rvn mvn — read-only Maven registry commands.

These commands handle GET / read operations only.  They do NOT deploy,
upload, or modify the registry.  For write operations use
``rvn java deploy`` (or ``rvn pkg publish``).

Commands closely mirror the mvn dependency plugin interface, but the
private repository and settings.xml are injected automatically.

    rvn mvn get com.google.guava:guava:33.0.0-jre
    rvn mvn resolve
    rvn mvn list
    rvn mvn tree
    rvn mvn tree --depth 2
    rvn mvn repo-url
    rvn mvn settings-xml

Unknown flags are forwarded verbatim to mvn.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import typer

from .. import auth as auth_mod
from .. import config as cfg_mod
from .. import output
from ..registries import maven as maven_reg


app = typer.Typer(
    help="Read-only Maven commands — GET operations only.  No deploy.",
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
    slug = repo or cfg.registry_defaults("maven").default_repo
    if not slug:
        output.fatal(
            "No repository specified.  Pass --repo or set a default:\n"
            "  rvn auth add-registry --kind maven --repo <slug>"
        )
    return p.api_url, slug, token  # type: ignore[return-value]


def _settings_file(repo_url: str, token: str | None) -> str | None:
    """Write a temporary settings.xml and return its path, or None if no token."""
    if not token:
        return None
    xml = maven_reg._build_settings_xml(repo_url, token, "rvn")
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".xml", prefix="rvn-settings-", delete=False
    ) as f:
        f.write(xml)
        return f.name


def _run_mvn(goal: str, extra_args: list[str], settings_path: str | None) -> None:
    cmd = ["mvn", goal]
    if settings_path:
        cmd.extend(["--settings", settings_path])
    cmd.extend(extra_args)
    output.info(f"Running: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
    finally:
        if settings_path:
            Path(settings_path).unlink(missing_ok=True)


# ── get ───────────────────────────────────────────────────────────────────────


@app.command(
    "get",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def mvn_get(
    ctx: typer.Context,
    coords: str = typer.Argument(
        ..., help="Maven GAV: groupId:artifactId:version[:packaging[:classifier]]"
    ),
    repo: str | None = typer.Option(None, "--repo", "-r", help="Repository slug."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Fetch a Maven artifact from the private registry (mvn dependency:get).

    \b
    Examples:
        rvn mvn get com.google.guava:guava:33.0.0-jre
        rvn mvn get org.junit.jupiter:junit-jupiter:5.10.0
        rvn mvn get com.example:mylib:1.0 -Dtransitive=false
    """
    api_url, slug, token = _resolve(repo, profile)
    repo_url = maven_reg.repo_url(api_url, slug)
    settings = _settings_file(repo_url, token)
    _run_mvn(f"dependency:get -Dartifact={coords}", ctx.args, settings)


# ── resolve ───────────────────────────────────────────────────────────────────


@app.command(
    "resolve",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def mvn_resolve(
    ctx: typer.Context,
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Resolve and download all project dependencies (mvn dependency:resolve).

    Must be run in a directory containing a pom.xml.

    \b
    Examples:
        rvn mvn resolve
        rvn mvn resolve -Dclassifier=sources
    """
    api_url, slug, token = _resolve(repo, profile)
    repo_url = maven_reg.repo_url(api_url, slug)
    settings = _settings_file(repo_url, token)
    _run_mvn("dependency:resolve", ctx.args, settings)


# ── list ──────────────────────────────────────────────────────────────────────


@app.command(
    "list",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def mvn_list(
    ctx: typer.Context,
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """List resolved dependencies (mvn dependency:list).

    \b
    Examples:
        rvn mvn list
        rvn mvn list -DincludeScope=compile
    """
    api_url, slug, token = _resolve(repo, profile)
    repo_url = maven_reg.repo_url(api_url, slug)
    settings = _settings_file(repo_url, token)
    _run_mvn("dependency:list", ctx.args, settings)


# ── tree ──────────────────────────────────────────────────────────────────────


@app.command(
    "tree",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def mvn_tree(
    ctx: typer.Context,
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Show the full dependency tree (mvn dependency:tree).

    \b
    Examples:
        rvn mvn tree
        rvn mvn tree -Dverbose
        rvn mvn tree -Dincludes=com.google.guava:guava
    """
    api_url, slug, token = _resolve(repo, profile)
    repo_url = maven_reg.repo_url(api_url, slug)
    settings = _settings_file(repo_url, token)
    _run_mvn("dependency:tree", ctx.args, settings)


# ── repo-url ──────────────────────────────────────────────────────────────────


@app.command("repo-url")
def repo_url(
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Print the private Maven repository URL.

    \b
    Examples:
        rvn mvn repo-url
        mvn install --settings <(rvn mvn settings-xml)
    """
    api_url, slug, _ = _resolve(repo, profile)
    typer.echo(maven_reg.repo_url(api_url, slug))


# ── settings-xml ──────────────────────────────────────────────────────────────


@app.command("settings-xml")
def settings_xml(
    repo: str | None = typer.Option(None, "--repo", "-r"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    server_id: str = typer.Option("rvn", "--server-id", help="Maven <server> id."),
) -> None:
    """Print a Maven settings.xml snippet for the private registry.

    \b
    Examples:
        rvn mvn settings-xml > /tmp/rvn-settings.xml
        mvn install --settings /tmp/rvn-settings.xml
        rvn mvn settings-xml >> ~/.m2/settings.xml
    """
    api_url, slug, _token = _resolve(repo, profile)
    repo_url_str = maven_reg.repo_url(api_url, slug)
    typer.echo(
        maven_reg._build_settings_xml(repo_url_str, "${RVN_TOKEN}", server_id),
        nl=False,
    )
