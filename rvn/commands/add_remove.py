"""rvn add / rvn remove — universal dependency management.

rvn add requests>=2.28             # Python: adds to pyproject.toml / requirements.txt
rvn add --dev pytest               # Python: dev/optional dep
rvn add lodash@4                   # Node:   adds to package.json dependencies
rvn add --dev @types/node          # Node:   adds to devDependencies
rvn add com.google.guava:guava:33  # Java:   adds to pom.xml / build.gradle

rvn remove requests                # removes from whatever manifest is found
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
from .. import manifest as mf
from .. import output
from ..registries import npm as npm_reg
from ..registries import pypi as pypi_reg
from ..routing import RoutingMode, get_router


add_app = typer.Typer(name="add", help="Add a dependency to the project manifest and install it.")
remove_app = typer.Typer(name="remove", help="Remove a dependency from the project manifest.")


# ── credential helper ─────────────────────────────────────────────────────────


def _creds(kind: str, profile: str | None, repo_override: str | None) -> tuple | None:
    cfg = cfg_mod.load()
    p = cfg.active_profile(profile)
    token = auth_mod.get_token(profile or cfg.default_profile)
    slug = repo_override or cfg.registry_defaults(kind).default_repo  # type: ignore[arg-type]
    if not slug or not token:
        return None
    return p.api_url, slug, token


def _authed_pypi(api_url: str, slug: str, token: str) -> str:
    raw = pypi_reg.simple_index_url(api_url, slug)
    parsed = urlparse(raw)
    return urlunparse(parsed._replace(netloc=f"__token__:{token}@{parsed.netloc}"))


# ── install after add ─────────────────────────────────────────────────────────


def _install_python(spec: str, creds: tuple | None) -> None:
    env = {**os.environ}
    if creds:
        api_url, slug, token = creds
        authed = _authed_pypi(api_url, slug, token)
        env["UV_EXTRA_INDEX_URL"] = authed
        env["PIP_EXTRA_INDEX_URL"] = authed

    if shutil.which("uv"):
        subprocess.run(["uv", "add", spec], env=env, check=True)
    else:
        subprocess.run(["pip", "install", spec], env=env, check=True)


def _install_node(spec: str, dev: bool, creds: tuple | None) -> None:
    env = {**os.environ}
    cmd = ["npm", "install"]
    if dev:
        cmd.append("--save-dev")
    else:
        cmd.append("--save")

    if creds:
        api_url, slug, token = creds
        reg_url = npm_reg.registry_url(api_url, slug)
        host = urlparse(reg_url).netloc
        env[f"NPM_CONFIG_//{host}/:_authToken"] = token
        cmd.extend(["--registry", reg_url])

    cmd.append(spec)
    subprocess.run(cmd, env=env, check=True)


def _install_maven(coords: str, creds: tuple | None) -> None:
    import tempfile

    from ..registries import maven as maven_reg

    parts = coords.split(":")
    if len(parts) < 3:
        output.warn("Skipping auto-install: Maven coords need groupId:artifactId:version")
        return

    cmd = [
        "mvn",
        "dependency:get",
        f"-Dartifact={coords}",
        "-q",
    ]
    settings_path: str | None = None
    if creds:
        api_url, slug, token = creds
        repo_url = maven_reg.repo_url(api_url, slug)
        settings_xml = maven_reg._build_settings_xml(repo_url, token, "rvn-add")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", prefix="rvn-settings-", delete=False
        ) as f:
            f.write(settings_xml)
            settings_path = f.name
        cmd.extend(["--settings", settings_path])

    try:
        subprocess.run(cmd, check=True)
    finally:
        if settings_path:
            Path(settings_path).unlink(missing_ok=True)


# ── rvn add ───────────────────────────────────────────────────────────────────


@add_app.callback(invoke_without_command=True)
def add(
    spec: str = typer.Argument(
        ..., help="Package spec (e.g. requests>=2.28, lodash@4, com.example:lib:1.0)."
    ),
    dev: bool = typer.Option(False, "--dev", "-D", help="Add to dev / devDependencies."),
    no_sync: bool = typer.Option(False, "--no-sync", help="Update manifest only; skip install."),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Config profile."),
    repo: str | None = typer.Option(None, "--repo", "-r", help="Override repository slug."),
    directory: Path = typer.Option(Path("."), "--directory", "-C", help="Project root."),
    routing: RoutingMode = typer.Option(
        "canonical",
        "--routing",
        help="URL routing: canonical (default) | unified (not yet implemented).",
    ),
) -> None:
    """Add a dependency to the manifest and install it.

    \b
    Examples:
        rvn add requests>=2.28
        rvn add --dev pytest
        rvn add lodash@4
        rvn add --dev @types/node@18
        rvn add com.google.guava:guava:33.0.0-jre
    """
    cwd = directory.resolve()
    info = mf.detect(cwd)
    if info is None:
        output.fatal(
            "No project manifest found. "
            "Expected pyproject.toml, requirements.txt, package.json, or pom.xml."
        )

    # Validate routing mode — fails immediately if unified (not yet implemented).
    try:
        get_router(routing)
    except NotImplementedError as exc:
        output.fatal(str(exc))

    changed = mf.add_dep(info, spec, dev=dev)
    if changed:
        output.success(f"Added '{spec}' to {info.path.name}")
    else:
        output.info(f"'{spec}' already present in {info.path.name} — version updated if needed.")

    if no_sync:
        return

    eco_to_kind = {"python": "pypi", "node": "npm", "java": "maven"}
    kind = eco_to_kind[info.eco]
    creds = _creds(kind, profile, repo)
    if creds is None:
        output.warn("No registry credentials configured — installing without private registry.")

    output.info("Installing…")
    if info.eco == "python":
        _install_python(spec, creds)
    elif info.eco == "node":
        _install_node(spec, dev, creds)
    elif info.eco == "java":
        _install_maven(spec, creds)


# ── rvn remove ────────────────────────────────────────────────────────────────


@remove_app.callback(invoke_without_command=True)
def remove(
    name: str = typer.Argument(..., help="Package name (or groupId:artifactId for Maven)."),
    directory: Path = typer.Option(Path("."), "--directory", "-C", help="Project root."),
) -> None:
    """Remove a dependency from the project manifest.

    \b
    Examples:
        rvn remove requests
        rvn remove lodash
        rvn remove com.google.guava:guava
    """
    cwd = directory.resolve()
    info = mf.detect(cwd)
    if info is None:
        output.fatal("No project manifest found.")

    removed = mf.remove_dep(info, name)
    if removed:
        output.success(f"Removed '{name}' from {info.path.name}")
        output.info("Run `rvn sync` to update your environment.")
    else:
        output.warn(f"'{name}' not found in {info.path.name}")
        raise typer.Exit(1)
