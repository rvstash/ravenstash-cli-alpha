"""`rvn pkg` command group.

`rvn packages` is registered as an alias for the same app at the root.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import typer

from .. import auth as auth_mod
from .. import config as cfg_mod
from .. import output
from ..client import ApiClient, ApiError
from ..runtime import tools
from .registries import maven as maven_reg
from .registries import npm as npm_reg
from .registries import pypi as pypi_reg
from .routing import CanonicalRouter


app = typer.Typer(
    name="pkg",
    help="Manage Ravenstash package repositories and package-manager configuration.",
    no_args_is_help=True,
)

repo_app = typer.Typer(help="Manage remote Ravenstash package repositories.", no_args_is_help=True)
package_app = typer.Typer(help="Manage packages hosted in a repository.", no_args_is_help=True)
pypi_app = typer.Typer(help="PyPI package repository helpers.", no_args_is_help=True)
npm_app = typer.Typer(help="npm package repository helpers.", no_args_is_help=True)
maven_app = typer.Typer(help="Maven package repository helpers.", no_args_is_help=True)

app.add_typer(repo_app, name="repo")
app.add_typer(package_app, name="package")
app.add_typer(pypi_app, name="pypi")
app.add_typer(npm_app, name="npm")
app.add_typer(maven_app, name="maven")

_KINDS = ("pypi", "npm", "maven")
_ROUTER = CanonicalRouter()


def _profile_name(profile: str | None) -> str:
    cfg = cfg_mod.load()
    return profile or cfg_mod.current_profile_name(cfg)


def _profile(profile: str | None) -> tuple[str, cfg_mod.ProfileConfig]:
    cfg = cfg_mod.load()
    name = profile or cfg_mod.current_profile_name(cfg)
    return name, cfg.active_profile(name)


def _client(profile: str | None) -> ApiClient:
    return ApiClient.from_profile(profile)


def _customer_id(profile: str | None, explicit_customer_id: str | None = None) -> str:
    if explicit_customer_id:
        return explicit_customer_id
    _, p = _profile(profile)
    if not p.customer_id:
        output.fatal(
            "No customer_id is stored for this profile. "
            "Run `rvn auth login` again or pass --customer-id."
        )
    return p.customer_id


def _customer_public_id(
    profile: str | None,
    explicit_customer_pid: str | None = None,
) -> str:
    if explicit_customer_pid:
        return explicit_customer_pid
    env_customer_pid = os.environ.get("RVN_CUSTOMER_PID") or os.environ.get(
        "RVN_CUSTOMER_PUBLIC_ID"
    )
    if env_customer_pid:
        return env_customer_pid
    _, p = _profile(profile)
    if not p.customer_public_id:
        output.fatal(
            "No customer_public_id is stored for this profile. "
            "Run `rvn auth login` again, pass --customer-pid, or pass "
            "--repo <customer-pid>/<repo-pid>."
        )
    return p.customer_public_id


def _require_kind(kind: str) -> None:
    if kind not in _KINDS:
        output.fatal(f"Unknown package repository kind '{kind}'. Use: pypi, npm, maven")


def _split_repo_ref(repo_ref: str) -> tuple[str | None, str]:
    value = repo_ref.strip().strip("/")
    if not value:
        output.fatal("Repository id cannot be empty.")
    if "/" not in value:
        return None, value
    customer_pid, repo_pid = value.split("/", 1)
    customer_pid = customer_pid.strip()
    repo_pid = repo_pid.strip().strip("/")
    if not customer_pid or not repo_pid or "/" in repo_pid:
        output.fatal("Repository must be <repo-pid> or <customer-pid>/<repo-pid>.")
    return customer_pid, repo_pid


def _repo_ref_from_response(repo: dict, fallback_repo_pid: str) -> str:
    customer_pid = repo.get("customer_public_id")
    repo_pid = repo.get("repo_pid") or repo.get("repository_public_id") or fallback_repo_pid
    if customer_pid and repo_pid:
        return f"{customer_pid}/{repo_pid}"
    return repo_pid


def _repo_for_kind(kind: str, repo: str | None) -> tuple[str | None, str]:
    _require_kind(kind)
    cfg = cfg_mod.load()
    resolved = repo or cfg.registry_defaults(kind).default_repo  # type: ignore[arg-type]
    if not resolved:
        output.fatal(
            f"No {kind} package repository selected. "
            f"Pass --repo or run `rvn pkg repo set-default {kind} <repo-pid>`."
        )
    return _split_repo_ref(resolved)


def _token(profile: str | None) -> str | None:
    return auth_mod.get_token(_profile_name(profile))


def _require_token(profile: str | None) -> str:
    token = _token(profile)
    if not token:
        output.fatal("Not authenticated. Run `rvn auth login` or set RVN_TOKEN.")
    return token


def _api_url(profile: str | None) -> str:
    _, p = _profile(profile)
    return p.api_url


def _authed_url(url: str, token: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(netloc=f"__token__:{token}@{parsed.netloc}"))


def _npm_auth_token_key(registry_url: str) -> str:
    parsed = urlparse(registry_url)
    path = parsed.path or "/"
    if not path.endswith("/"):
        path += "/"
    return f"//{parsed.netloc}{path}:_authToken"


def _registry_context(
    kind: str,
    repo: str | None,
    profile: str | None,
    customer_pid: str | None = None,
) -> tuple[str, str, str, str | None]:
    repo_customer_pid, repo_pid = _repo_for_kind(kind, repo)
    resolved_customer_pid = repo_customer_pid or _customer_public_id(profile, customer_pid)
    return _api_url(profile), resolved_customer_pid, repo_pid, _token(profile)


# ── repo ─────────────────────────────────────────────────────────────────────


@repo_app.command("list")
def repo_list(
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(None, "--customer-id", help="Customer ID override."),
    kind: str | None = typer.Option(None, "--kind", "-k", help="Filter: pypi | npm | maven"),
) -> None:
    """List package repositories for the active customer."""
    if kind:
        _require_kind(kind)
    client = _client(profile)
    try:
        data = client.get(
            "/webapp/repository/",
            params={"customer_id": _customer_id(profile, customer_id)},
        ).json()
    except ApiError as exc:
        output.fatal(str(exc))

    items = data if isinstance(data, list) else data.get("items", [])
    if kind:
        items = [item for item in items if item.get("registry_kind") == kind]
    if not items:
        output.info("No package repositories found.")
        return

    output.table(
        ["ID", "Slug", "Kind", "Packages", "Storage"],
        [
            [
                item.get("id", ""),
                item.get("slug", ""),
                item.get("registry_kind", ""),
                str(item.get("package_count", "0")),
                str(item.get("storage_bytes", "0")),
            ]
            for item in items
        ],
    )


@repo_app.command("create")
def repo_create(
    slug: str = typer.Argument(..., help="Repository slug."),
    kind: str = typer.Option(..., "--kind", "-k", help="Repository kind: pypi | npm | maven"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(None, "--customer-id", help="Customer ID override."),
    set_default: bool = typer.Option(False, "--default", help="Set as default for this kind."),
) -> None:
    """Create a package repository."""
    _require_kind(kind)
    client = _client(profile)
    payload = {
        "customer_id": _customer_id(profile, customer_id),
        "slug": slug,
        "registry_kind": kind,
    }
    try:
        repo = client.post("/webapp/repository/", json=payload).json()
    except ApiError as exc:
        output.fatal(str(exc))

    repo_id = repo.get("id", "")
    output.success(f"Created {kind} package repository '{repo.get('slug', slug)}' ({repo_id}).")
    if set_default and repo_id:
        default_repo = _repo_ref_from_response(repo, repo_id)
        cfg_mod.set_registry_default_repo(kind, default_repo)  # type: ignore[arg-type]
        output.info(f"Default {kind} package repository set to {default_repo}.")


@repo_app.command("show")
def repo_show(
    repo: str = typer.Argument(..., help="Repository public ID."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Show package repository details."""
    client = _client(profile)
    try:
        item = client.get(f"/webapp/repository/{repo}").json()
    except ApiError as exc:
        output.fatal(str(exc))

    output.kv(
        {
            "ID": item.get("id", ""),
            "Slug": item.get("slug", ""),
            "Kind": item.get("registry_kind", ""),
            "Packages": str(item.get("package_count", "0")),
            "Storage bytes": str(item.get("storage_bytes", "0")),
            "Created": str(item.get("created_at", "")),
        },
        title=f"Package repository {repo}",
    )


@repo_app.command("delete")
def repo_delete(
    repo: str = typer.Argument(..., help="Repository public ID."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """Delete a package repository."""
    if not yes:
        typer.confirm(f"Delete package repository '{repo}' and its packages?", abort=True)
    client = _client(profile)
    try:
        client.delete(f"/webapp/repository/{repo}")
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Deleted package repository '{repo}'.")


@repo_app.command("set-default")
def repo_set_default(
    kind: str = typer.Argument(..., help="Repository kind: pypi | npm | maven"),
    repo: str = typer.Argument(..., help="Repository public ID."),
) -> None:
    """Set the default package repository for a kind."""
    _require_kind(kind)
    cfg_mod.set_registry_default_repo(kind, repo)  # type: ignore[arg-type]
    output.success(f"Default {kind} package repository set to {repo}.")


@repo_app.command("defaults")
def repo_defaults() -> None:
    """Show default package repositories."""
    cfg = cfg_mod.load()
    rows = [
        [kind, cfg.registry_defaults(kind).default_repo or "not set"]  # type: ignore[arg-type]
        for kind in _KINDS
    ]
    output.table(["Kind", "Default repository"], rows, title="Package repository defaults")


# ── package ──────────────────────────────────────────────────────────────────


@package_app.command("list")
def package_list(
    repo: str = typer.Option(..., "--repo", "-r", help="Repository public ID."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """List packages hosted in a package repository."""
    client = _client(profile)
    try:
        data = client.get(f"/webapp/repository/{repo}/packages").json()
    except ApiError as exc:
        output.fatal(str(exc))

    items = data if isinstance(data, list) else data.get("items", [])
    if not items:
        output.info(f"No packages found in '{repo}'.")
        return

    output.table(
        ["Name", "Latest", "Versions", "Size"],
        [
            [
                item.get("package_name") or item.get("normalized_name", ""),
                item.get("latest_version") or "",
                str(item.get("version_count", "")),
                str(item.get("total_size_bytes", "")),
            ]
            for item in items
        ],
        title=f"Packages in {repo}",
    )


@package_app.command("show")
def package_show(
    name: str = typer.Argument(..., help="Package name."),
    repo: str = typer.Option(..., "--repo", "-r", help="Repository public ID."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Show package metadata and versions."""
    client = _client(profile)
    try:
        item = client.get(f"/webapp/repository/{repo}/packages/{name}").json()
    except ApiError as exc:
        output.fatal(str(exc))

    output.kv(
        {
            "Repository": item.get("repository_id", repo),
            "Name": item.get("package_name") or item.get("normalized_name", name),
            "Latest": item.get("latest_version") or "",
            "Versions": str(item.get("version_count", "")),
            "Size": str(item.get("total_size_bytes", "")),
        },
        title=name,
    )

    versions = item.get("versions") or []
    if versions:
        output.table(
            ["Version", "Yanked", "Files", "Size"],
            [
                [
                    version.get("version", ""),
                    "yes" if version.get("yanked") else "no",
                    str(len(version.get("files") or [])),
                    str(version.get("total_size_bytes", "")),
                ]
                for version in versions
            ],
        )


@package_app.command("delete")
def package_delete(
    name: str = typer.Argument(..., help="Package name."),
    repo: str = typer.Option(..., "--repo", "-r", help="Repository public ID."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """Delete a package and all of its versions."""
    if not yes:
        typer.confirm(f"Delete package '{name}' from '{repo}'?", abort=True)
    client = _client(profile)
    try:
        client.delete(f"/webapp/repository/{repo}/packages/{name}")
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Deleted package '{name}' from '{repo}'.")


@package_app.command("delete-version")
def package_delete_version(
    name: str = typer.Argument(..., help="Package name."),
    version: str = typer.Argument(..., help="Version to delete."),
    repo: str = typer.Option(..., "--repo", "-r", help="Repository public ID."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """Delete one package version."""
    if not yes:
        typer.confirm(f"Delete {name}@{version} from '{repo}'?", abort=True)
    client = _client(profile)
    try:
        client.delete(f"/webapp/repository/{repo}/packages/{name}/versions/{version}")
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Deleted {name}@{version} from '{repo}'.")


@package_app.command("yank")
def package_yank(
    name: str = typer.Argument(..., help="Package name."),
    version: str = typer.Argument(..., help="Version to yank."),
    repo: str = typer.Option(..., "--repo", "-r", help="Repository public ID."),
    reason: str | None = typer.Option(None, "--reason", "-m", help="Yank reason."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Mark a package version as yanked."""
    client = _client(profile)
    body = {"reason": reason} if reason else None
    try:
        client.post(
            f"/webapp/repository/{repo}/packages/{name}/versions/{version}/yank",
            json=body,
        )
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Yanked {name}@{version} in '{repo}'.")


# ── PyPI ─────────────────────────────────────────────────────────────────────


@pypi_app.command("index-url")
def pypi_index_url(
    repo: str | None = typer.Option(None, "--repo", "-r", help="Repository public ID."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_pid: str | None = typer.Option(
        None, "--customer-pid", help="Customer public ID override."
    ),
) -> None:
    """Print the private PyPI simple-index URL."""
    api_url, customer_pid, repo_id, _ = _registry_context("pypi", repo, profile, customer_pid)
    typer.echo(_ROUTER.pypi_index_url(api_url, customer_pid, repo_id))


@pypi_app.command("upload-url")
def pypi_upload_url(
    repo: str | None = typer.Option(None, "--repo", "-r", help="Repository public ID."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_pid: str | None = typer.Option(
        None, "--customer-pid", help="Customer public ID override."
    ),
) -> None:
    """Print the private PyPI upload URL."""
    api_url, customer_pid, repo_id, _ = _registry_context("pypi", repo, profile, customer_pid)
    typer.echo(_ROUTER.pypi_upload_url(api_url, customer_pid, repo_id))


@pypi_app.command("install")
def pypi_install(
    packages: list[str] = typer.Argument(..., help="Package specs to install."),
    repo: str | None = typer.Option(None, "--repo", "-r", help="Repository public ID."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_pid: str | None = typer.Option(
        None, "--customer-pid", help="Customer public ID override."
    ),
) -> None:
    """Install Python packages using pip with Ravenstash credentials injected."""
    api_url, customer_pid, repo_id, token = _registry_context("pypi", repo, profile, customer_pid)
    index_url = _ROUTER.pypi_index_url(api_url, customer_pid, repo_id)
    env = {**os.environ}
    if token:
        env["PIP_EXTRA_INDEX_URL"] = _authed_url(index_url, token)
    else:
        output.warn("No credentials found; running pip without private repository auth.")

    cmd = [*tools.pip_cmd(), "install", *packages]
    subprocess.run(cmd, env=env, check=True)


@pypi_app.command("publish")
def pypi_publish(
    dist_dir: Path = typer.Argument(Path("dist"), help="Directory with wheels/sdists."),
    repo: str | None = typer.Option(None, "--repo", "-r", help="Repository public ID."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_pid: str | None = typer.Option(
        None, "--customer-pid", help="Customer public ID override."
    ),
) -> None:
    """Upload wheel and sdist files to a PyPI package repository."""
    api_url, customer_pid, repo_id, _ = _registry_context("pypi", repo, profile, customer_pid)
    token = _require_token(profile)
    files = list(dist_dir.glob("*.whl")) + list(dist_dir.glob("*.tar.gz"))
    if not files:
        output.fatal(f"No .whl or .tar.gz files found in {dist_dir}")
    results = pypi_reg.publish(
        upload_url=_ROUTER.pypi_upload_url(api_url, customer_pid, repo_id),
        token=token,
        files=files,
    )
    failed = False
    for result in results:
        if result.ok:
            output.success(f"Published {result.filename} ({result.version})")
        else:
            failed = True
            output.error(f"Failed {result.filename}: {result.detail}")
    if failed:
        raise typer.Exit(1)


@pypi_app.command("configure")
def pypi_configure(
    repo: str | None = typer.Option(None, "--repo", "-r", help="Repository public ID."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_pid: str | None = typer.Option(
        None, "--customer-pid", help="Customer public ID override."
    ),
) -> None:
    """Print pip configuration for the private PyPI repository."""
    api_url, customer_pid, repo_id, _ = _registry_context("pypi", repo, profile, customer_pid)
    index_url = _ROUTER.pypi_index_url(api_url, customer_pid, repo_id)
    typer.echo(f"[global]\nextra-index-url = {index_url}")


# ── npm ──────────────────────────────────────────────────────────────────────


@npm_app.command("registry-url")
def npm_registry_url(
    repo: str | None = typer.Option(None, "--repo", "-r", help="Repository public ID."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_pid: str | None = typer.Option(
        None, "--customer-pid", help="Customer public ID override."
    ),
) -> None:
    """Print the private npm registry URL."""
    api_url, customer_pid, repo_id, _ = _registry_context("npm", repo, profile, customer_pid)
    typer.echo(_ROUTER.npm_registry_url(api_url, customer_pid, repo_id))


@npm_app.command("npmrc")
def npmrc(
    repo: str | None = typer.Option(None, "--repo", "-r", help="Repository public ID."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_pid: str | None = typer.Option(
        None, "--customer-pid", help="Customer public ID override."
    ),
) -> None:
    """Print an .npmrc snippet for the private npm repository."""
    api_url, customer_pid, repo_id, _ = _registry_context("npm", repo, profile, customer_pid)
    registry_url = _ROUTER.npm_registry_url(api_url, customer_pid, repo_id)
    auth_key = _npm_auth_token_key(registry_url)
    typer.echo(f"registry={registry_url}\n{auth_key}=${{RVN_TOKEN}}")


@npm_app.command("install")
def npm_install(
    packages: list[str] = typer.Argument(..., help="Package specs to install."),
    repo: str | None = typer.Option(None, "--repo", "-r", help="Repository public ID."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_pid: str | None = typer.Option(
        None, "--customer-pid", help="Customer public ID override."
    ),
) -> None:
    """Install npm packages with Ravenstash credentials injected."""
    api_url, customer_pid, repo_id, token = _registry_context("npm", repo, profile, customer_pid)
    registry_url = _ROUTER.npm_registry_url(api_url, customer_pid, repo_id)
    env = {**os.environ}
    if token:
        env[f"NPM_CONFIG_{_npm_auth_token_key(registry_url)}"] = token
    else:
        output.warn("No credentials found; running npm without private repository auth.")
    subprocess.run(
        [tools.npm(), "install", "--registry", registry_url, *packages], env=env, check=True
    )


@npm_app.command("publish")
def npm_publish(
    package_dir: Path = typer.Argument(Path("."), help="Directory containing package.json."),
    repo: str | None = typer.Option(None, "--repo", "-r", help="Repository public ID."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_pid: str | None = typer.Option(
        None, "--customer-pid", help="Customer public ID override."
    ),
) -> None:
    """Publish an npm package to a Ravenstash npm repository."""
    api_url, customer_pid, repo_id, _ = _registry_context("npm", repo, profile, customer_pid)
    token = _require_token(profile)
    results = npm_reg.publish(
        registry_url=_ROUTER.npm_upload_registry_url(api_url, customer_pid, repo_id),
        token=token,
        package_dir=package_dir,
        download_registry_url=_ROUTER.npm_registry_url(api_url, customer_pid, repo_id),
    )
    failed = False
    for result in results:
        if result.ok:
            output.success(f"Published {result.filename} ({result.version})")
        else:
            failed = True
            output.error(f"Failed {result.filename}: {result.detail}")
    if failed:
        raise typer.Exit(1)


@npm_app.command("configure")
def npm_configure(
    repo: str | None = typer.Option(None, "--repo", "-r", help="Repository public ID."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_pid: str | None = typer.Option(
        None, "--customer-pid", help="Customer public ID override."
    ),
) -> None:
    """Print .npmrc configuration for the private npm repository."""
    npmrc(repo=repo, profile=profile, customer_pid=customer_pid)


# ── Maven ────────────────────────────────────────────────────────────────────


@maven_app.command("repo-url")
def maven_repo_url(
    repo: str | None = typer.Option(None, "--repo", "-r", help="Repository public ID."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_pid: str | None = typer.Option(
        None, "--customer-pid", help="Customer public ID override."
    ),
) -> None:
    """Print the private Maven repository URL."""
    api_url, customer_pid, repo_id, _ = _registry_context("maven", repo, profile, customer_pid)
    typer.echo(_ROUTER.maven_repo_url(api_url, customer_pid, repo_id))


def _settings_xml(repo_url: str, password_expr: str = "${env.RVN_TOKEN}") -> str:
    return f"""<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0">
  <servers>
    <server>
      <id>rvn-private</id>
      <username>__token__</username>
      <password>{password_expr}</password>
    </server>
  </servers>
  <profiles>
    <profile>
      <id>rvn</id>
      <repositories>
        <repository>
          <id>rvn-private</id>
          <url>{repo_url}</url>
          <releases><enabled>true</enabled></releases>
          <snapshots><enabled>true</enabled></snapshots>
        </repository>
      </repositories>
    </profile>
  </profiles>
  <activeProfiles>
    <activeProfile>rvn</activeProfile>
  </activeProfiles>
</settings>"""


@maven_app.command("settings")
def maven_settings(
    repo: str | None = typer.Option(None, "--repo", "-r", help="Repository public ID."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_pid: str | None = typer.Option(
        None, "--customer-pid", help="Customer public ID override."
    ),
) -> None:
    """Print a Maven settings.xml snippet for the private Maven repository."""
    api_url, customer_pid, repo_id, _ = _registry_context("maven", repo, profile, customer_pid)
    typer.echo(_settings_xml(_ROUTER.maven_repo_url(api_url, customer_pid, repo_id)))


@maven_app.command("install")
def maven_install(
    coords: str = typer.Argument(..., help="Maven coordinates: groupId:artifactId:version."),
    repo: str | None = typer.Option(None, "--repo", "-r", help="Repository public ID."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_pid: str | None = typer.Option(
        None, "--customer-pid", help="Customer public ID override."
    ),
) -> None:
    """Fetch a Maven artifact into the local Maven cache."""
    api_url, customer_pid, repo_id, _ = _registry_context("maven", repo, profile, customer_pid)
    token = _require_token(profile)
    repo_url = _ROUTER.maven_repo_url(api_url, customer_pid, repo_id)
    settings_xml = maven_reg._build_settings_xml(repo_url, token)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".xml", prefix="rvn-settings-", delete=False
    ) as settings_file:
        settings_file.write(settings_xml)
        settings_path = settings_file.name

    try:
        subprocess.run(
            [
                tools.require("mvn", install_kind="system"),
                f"--settings={settings_path}",
                "dependency:get",
                f"-Dartifact={coords}",
            ],
            check=True,
        )
    finally:
        Path(settings_path).unlink(missing_ok=True)


@maven_app.command("deploy")
def maven_deploy(
    artifact_file: Path = typer.Argument(..., help="Artifact file to deploy."),
    group: str = typer.Option(..., "--group", "-g", help="Maven groupId."),
    artifact: str = typer.Option(..., "--artifact", "-a", help="Maven artifactId."),
    version: str = typer.Option(..., "--version", "-v", help="Maven version."),
    repo: str | None = typer.Option(None, "--repo", "-r", help="Repository public ID."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_pid: str | None = typer.Option(
        None, "--customer-pid", help="Customer public ID override."
    ),
) -> None:
    """Deploy an artifact file to a Ravenstash Maven repository."""
    if not artifact_file.exists():
        output.fatal(f"Artifact file not found: {artifact_file}")
    api_url, customer_pid, repo_id, _ = _registry_context("maven", repo, profile, customer_pid)
    token = _require_token(profile)
    results = maven_reg.publish(
        upload_url=_ROUTER.maven_upload_url(api_url, customer_pid, repo_id),
        token=token,
        group_id=group,
        artifact_id=artifact,
        version=version,
        files=[artifact_file],
    )
    failed = False
    for result in results:
        if result.ok:
            output.success(f"Deployed {result.filename}")
        else:
            failed = True
            output.error(f"Failed {result.filename}: {result.detail}")
    if failed:
        raise typer.Exit(1)


@maven_app.command("configure")
def maven_configure(
    repo: str | None = typer.Option(None, "--repo", "-r", help="Repository public ID."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_pid: str | None = typer.Option(
        None, "--customer-pid", help="Customer public ID override."
    ),
) -> None:
    """Print Maven settings.xml configuration for the private Maven repository."""
    maven_settings(repo=repo, profile=profile, customer_pid=customer_pid)
