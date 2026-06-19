"""rvn pkg — universal publish/install with auto-detection of registry kind.

This command group is the top-level universal surface.  It detects whether
the project / package spec is PyPI, npm, or Maven and delegates to the
correct registry adapter automatically.

Kind detection order
--------------------
1. ``--kind`` flag (explicit override — always wins)
2. ``detect_kind_from_project(directory)``   (for publish)
3. ``detect_kind_from_package_spec(name)``   (for install, per first package)
4. Project-context fallback                  (for install when spec is ambiguous)

Aliases
-------
``rvn python`` and ``rvn java`` are registered as aliases for ``rvn pypi``
and ``rvn mvn`` respectively in ``cli.py``; they are NOT aliases of ``rvn
pkg`` because they force a specific kind and skip auto-detection.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Annotated

import typer

from .. import auth as auth_mod
from .. import config as cfg_mod
from .. import output
from ..detect import detect_kind_from_package_spec, detect_kind_from_project, kind_label
from ..registries import maven as maven_reg
from ..registries import npm as npm_reg
from ..registries import pypi as pypi_reg


app = typer.Typer(
    help="Universal package commands — kind is auto-detected from project or package spec.",
    no_args_is_help=True,
)


# ── Shared helpers ────────────────────────────────────────────────────────────


def _resolve(kind: str, repo_override: str | None, profile: str | None) -> tuple[str, str, str]:
    """Return (api_url, repo_slug, token) or call output.fatal()."""
    cfg = cfg_mod.load()
    p = cfg.active_profile(profile)
    token = auth_mod.get_token(profile or cfg.default_profile)
    if not token:
        output.fatal("No token found. Run: rvn auth login")
    slug = repo_override or cfg.registry_defaults(kind).default_repo  # type: ignore[arg-type]
    if not slug:
        output.fatal(
            f"No default {kind} repository configured.\n"
            f"  Use --repo <slug>  or  rvn auth add-registry --kind {kind} --repo <slug>"
        )
    return p.api_url, slug, token  # type: ignore[return-value]


def _announce_kind(kind: str) -> None:
    output.info(f"Detected registry kind: [bold]{kind_label(kind)}[/bold]")


# ── publish ───────────────────────────────────────────────────────────────────


@app.command("publish")
def publish(
    directory: Annotated[
        Path,
        typer.Argument(help="Project directory to publish (default: current directory)"),
    ] = Path("."),
    kind: Annotated[
        str | None,
        typer.Option("--kind", "-k", help="Force registry kind: pypi | npm | maven"),
    ] = None,
    repo: Annotated[str | None, typer.Option("--repo", "-r", help="Repository slug")] = None,
    profile: Annotated[str | None, typer.Option("--profile", "-p")] = None,
) -> None:
    """Publish the package in a directory, auto-detecting the registry kind.

    Detection priority: --kind > package.json > pom.xml/build.gradle > pyproject.toml

    \b
    Examples:
        rvn pkg publish                   # auto-detect in current directory
        rvn pkg publish ./my-lib          # auto-detect in ./my-lib
        rvn pkg publish --kind npm        # force npm even if pyproject.toml exists
        rvn pkg publish --repo my-pypi    # target a specific repository
    """
    resolved_dir = directory.resolve()
    resolved_kind = kind or detect_kind_from_project(resolved_dir)
    if not resolved_kind:
        output.fatal(
            f"Could not detect package type in {resolved_dir}.\n"
            "  Hint: use --kind pypi | npm | maven"
        )

    if not kind:
        _announce_kind(resolved_kind)

    api_url, slug, token = _resolve(resolved_kind, repo, profile)

    if resolved_kind == "pypi":
        _publish_pypi(resolved_dir, api_url, slug, token)
    elif resolved_kind == "npm":
        _publish_npm(resolved_dir, api_url, slug, token)
    elif resolved_kind == "maven":
        _publish_maven(resolved_dir, api_url, slug, token)
    else:
        output.fatal(f"Unsupported kind '{resolved_kind}'.")


def _publish_pypi(directory: Path, api_url: str, slug: str, token: str) -> None:
    dist_dir = directory / "dist"
    if not dist_dir.is_dir():
        output.fatal(
            f"No dist/ directory in {directory}. Build your package first (e.g. uv build)."
        )
    files = sorted(dist_dir.glob("*.whl")) + sorted(dist_dir.glob("*.tar.gz"))
    if not files:
        output.fatal("No wheels or sdists found in dist/.")
    upload_url = f"{api_url.rstrip('/')}/pypi/r/{slug}"
    output.info(f"Publishing {len(files)} file(s) to [{slug}] ...")
    results = pypi_reg.publish(upload_url=upload_url, token=token, files=files)
    for r in results:
        (output.success if r.ok else output.error)(
            f"{r.filename} ({r.version})" if r.ok else f"{r.filename}: {r.detail}"
        )
    if any(not r.ok for r in results):
        raise typer.Exit(1)


def _publish_npm(directory: Path, api_url: str, slug: str, token: str) -> None:
    registry = npm_reg.registry_url(api_url, slug)
    output.info(f"Publishing to [{slug}] ...")
    results = npm_reg.publish(registry_url=registry, token=token, package_dir=directory)
    for r in results:
        (output.success if r.ok else output.error)(
            f"{r.filename} ({r.version})" if r.ok else f"{r.filename}: {r.detail}"
        )
    if any(not r.ok for r in results):
        raise typer.Exit(1)


def _publish_maven(directory: Path, api_url: str, slug: str, token: str) -> None:
    pom = directory / "pom.xml"
    if not pom.exists():
        output.fatal(
            f"No pom.xml found in {directory}.\n"
            "  For manual artifact uploads use: rvn mvn deploy <files> --group ... --artifact ... --version ..."
        )

    ns = {"m": "http://maven.apache.org/POM/4.0.0"}
    try:
        root = ET.parse(str(pom)).getroot()

        def _text(tag: str) -> str | None:
            el = root.find(f"m:{tag}", ns) or root.find(tag)
            return el.text.strip() if el is not None and el.text else None

        group_id = _text("groupId") or ""
        artifact_id = _text("artifactId") or ""
        version = _text("version") or ""
    except Exception as exc:
        output.fatal(f"Could not parse pom.xml: {exc}")

    if not (group_id and artifact_id and version):
        output.fatal(
            "Missing groupId / artifactId / version in pom.xml.\n"
            "  Use 'rvn mvn deploy' for manual uploads."
        )

    target = directory / "target"
    jar_files = list(target.glob(f"{artifact_id}-{version}.jar")) if target.is_dir() else []
    if not jar_files:
        output.fatal(
            f"No built JAR at target/{artifact_id}-{version}.jar.\n"
            "  Run 'mvn package' or 'gradle jar' first."
        )

    files = [*jar_files, pom]
    repo_url = maven_reg.repo_url(api_url, slug)
    output.info(f"Deploying {group_id}:{artifact_id}:{version} to [{slug}] ...")
    results = maven_reg.publish(
        upload_url=repo_url,
        token=token,
        group_id=group_id,
        artifact_id=artifact_id,
        version=version,
        files=files,
    )
    for r in results:
        (output.success if r.ok else output.error)(
            f"{r.filename}" if r.ok else f"{r.filename}: {r.detail}"
        )
    if any(not r.ok for r in results):
        raise typer.Exit(1)


# ── install ───────────────────────────────────────────────────────────────────


@app.command("install")
def install(
    packages: Annotated[list[str], typer.Argument(help="Package specs to install")],
    kind: Annotated[
        str | None,
        typer.Option("--kind", "-k", help="Force registry kind: pypi | npm | maven"),
    ] = None,
    repo: Annotated[str | None, typer.Option("--repo", "-r", help="Repository slug")] = None,
    profile: Annotated[str | None, typer.Option("--profile", "-p")] = None,
    tool: Annotated[
        str,
        typer.Option("--tool", "-t", help="Installer: auto | uv | pip  (PyPI only)"),
    ] = "auto",
) -> None:
    """Install packages from a private registry, auto-detecting the kind.

    \b
    Kind detection (per first package argument):
        com.example:mylib:1.0   → Maven
        @scope/pkg              → npm
        requests>=2.28          → PyPI  (default fallback)

    \b
    Examples:
        rvn pkg install requests numpy            # → PyPI
        rvn pkg install @my-scope/utils           # → npm
        rvn pkg install com.example:mylib:1.0     # → Maven
        rvn pkg install lodash --kind npm         # force npm
        rvn pkg install mylib --repo my-pypi      # specific repository
    """
    if not packages:
        output.fatal("Specify at least one package.")

    resolved_kind = (
        kind
        or detect_kind_from_package_spec(packages[0])
        or detect_kind_from_project(Path.cwd())
        or "pypi"
    )

    if not kind:
        _announce_kind(resolved_kind)

    api_url, slug, token = _resolve(resolved_kind, repo, profile)

    if resolved_kind == "pypi":
        index_url = pypi_reg.simple_index_url(api_url, slug)
        output.info(f"Installing from [{slug}] ...")
        try:
            pypi_reg.install(index_url=index_url, token=token, packages=packages, tool=tool)
        except Exception as exc:
            output.fatal(str(exc))

    elif resolved_kind == "npm":
        registry = npm_reg.registry_url(api_url, slug)
        output.info(f"Installing from [{slug}] ...")
        try:
            npm_reg.install(registry_url=registry, token=token, packages=packages)
        except Exception as exc:
            output.fatal(str(exc))

    elif resolved_kind == "maven":
        repo_url = maven_reg.repo_url(api_url, slug)
        for pkg in packages:
            output.info(f"Fetching {pkg} from [{slug}] ...")
            try:
                maven_reg.install(repo_url=repo_url, token=token, coords=pkg)
                output.success(f"{pkg} fetched.")
            except Exception as exc:
                output.error(f"{pkg}: {exc}")
                raise typer.Exit(1) from exc

    else:
        output.fatal(f"Unsupported kind '{resolved_kind}'.")


# ── info ──────────────────────────────────────────────────────────────────────


@app.command("info")
def info(
    package: Annotated[str, typer.Argument(help="Package name (auto-detects kind)")],
    repo: Annotated[str | None, typer.Option("--repo", "-r")] = None,
    profile: Annotated[str | None, typer.Option("--profile", "-p")] = None,
    kind: Annotated[str | None, typer.Option("--kind", "-k")] = None,
) -> None:
    """Show metadata for a package (auto-detects registry kind).

    \b
    Examples:
        rvn pkg info requests
        rvn pkg info @scope/utils
        rvn pkg info com.example:mylib
    """
    from ..client import ApiClient, ApiError

    resolved_kind = kind or detect_kind_from_package_spec(package) or "pypi"
    if not kind:
        _announce_kind(resolved_kind)

    api_url, slug, token = _resolve(resolved_kind, repo, profile)
    client = ApiClient(api_url=api_url, token=token)

    try:
        p = client.get(f"/webapp/repositories/{slug}/packages/{package}/").json()
    except ApiError as exc:
        output.fatal(str(exc))

    output.kv(
        {
            "Name": p.get("name", ""),
            "Kind": resolved_kind,
            "Latest": p.get("latest_version", "—"),
            "Downloads": str(p.get("download_count", "—")),
            "Summary": p.get("summary") or "—",
            "License": p.get("license") or "—",
        },
        title=f"{package} @ {slug}",
    )
