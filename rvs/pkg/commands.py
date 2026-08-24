"""`rvs pkg` command group.

`rvs packages` is registered as an alias for the same app at the root.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import cast
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

repo_app = typer.Typer(help="Manage Ravenstash package repositories.", no_args_is_help=True)
remote_app = typer.Typer(help="Manage remote caches & proxies.", no_args_is_help=True)
package_app = typer.Typer(help="Manage packages hosted in a repository.", no_args_is_help=True)
pypi_app = typer.Typer(help="PyPI package repository helpers.", no_args_is_help=True)
npm_app = typer.Typer(help="npm package repository helpers.", no_args_is_help=True)
maven_app = typer.Typer(help="Maven package repository helpers.", no_args_is_help=True)

app.add_typer(repo_app, name="repo")
app.add_typer(remote_app, name="remote-cache")
app.add_typer(package_app, name="package")
app.add_typer(pypi_app, name="pypi")
app.add_typer(npm_app, name="npm")
app.add_typer(maven_app, name="maven")

_KINDS = ("pypi", "npm", "maven", "container", "helm")
_PACKAGE_KINDS = ("pypi", "npm", "maven")
_ROUTER = CanonicalRouter()
_REPOSITORY_NAME_HELP = "Package repository name: lowercase letters, numbers, and hyphens."


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
            "No customer ID is stored for this profile. "
            "Run `rvs auth login` again or pass --customer-id."
        )
    return p.customer_id


def _require_kind(kind: str) -> cfg_mod.RegistryKind:
    if kind not in _KINDS:
        output.fatal(f"Unknown registry kind '{kind}'. Use: pypi, npm, maven, container, helm")
    return cast("cfg_mod.RegistryKind", kind)


def _require_package_kind(kind: str) -> cfg_mod.RegistryKind:
    if kind not in _PACKAGE_KINDS:
        output.fatal(
            "Package/version commands and remote caches support only pypi, npm, "
            "and maven. Use rvs docker, rvs helm, or rvs oras for OCI content."
        )
    return cast("cfg_mod.RegistryKind", kind)


def _split_repo_ref(repo_ref: str) -> tuple[str | None, str]:
    value = repo_ref.strip().strip("/")
    if not value:
        output.fatal("Repository name cannot be empty.")
    if "/" not in value:
        return None, value
    workspace_selector, repository_name = value.split("/", 1)
    workspace_selector = workspace_selector.strip()
    repository_name = repository_name.strip().strip("/")
    if not workspace_selector or not repository_name or "/" in repository_name:
        output.fatal("Repository must be <repository-name> or <workspace>/<repository-name>.")
    return workspace_selector, repository_name


def _repository_name_from_response(repo: dict, fallback_repository_name: str = "") -> str:
    return (
        repo.get("repo_name")
        or repo.get("name")
        or repo.get("repository_name")
        or repo.get("id")
        or fallback_repository_name
    )


def _repo_ref_from_response(repo: dict, fallback_repository_name: str) -> str:
    workspace_ref = repo.get("workspace_unique_ref")
    repository_ref = repo.get("repository_unique_ref")
    if workspace_ref and repository_ref:
        return f"{workspace_ref}/{repository_ref}"
    return _repository_name_from_response(repo, fallback_repository_name)


def _repo_for_kind(
    kind: str,
    repo: str | None,
    profile: str | None = None,
) -> tuple[str | None, str]:
    registry_kind = _require_kind(kind)
    cfg = cfg_mod.load()
    profile_name = profile or cfg_mod.current_profile_name(cfg)
    resolved = (
        repo
        or cfg.registry_defaults(
            registry_kind,
            profile_name,
        ).default_repo
    )
    if not resolved:
        output.fatal(
            f"No {kind} package repository selected. "
            f"Pass --repo or run `rvs pkg repo set-default {kind} <repository-name>`."
        )
    return _split_repo_ref(resolved)


def _token(profile: str | None) -> str | None:
    return auth_mod.get_token(_profile_name(profile))


def _registry_profile(profile: str | None) -> cfg_mod.ProfileConfig:
    _, p = _profile(profile)
    return p


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
    customer_id: str | None = None,
) -> tuple[cfg_mod.ProfileConfig, str, str, str]:
    workspace_selector, repository_selector = _repo_for_kind(kind, repo, profile)
    selector = (
        f"{workspace_selector}/{repository_selector}" if workspace_selector else repository_selector
    )
    profile_name = _profile_name(profile)
    expected_target = cfg_mod.registry_target_expectation(
        _require_kind(kind), selector, profile_name
    )
    client = _client(profile)
    try:
        entry = client.get(
            "/v0/repositories/resolve",
            params={
                "selector": selector,
                "customer_id": customer_id,
                "registry_kind": kind,
            },
        ).json()
        repository = entry["repository"]
        credential_body: dict[str, object] = {
            "repository_id": repository["id"],
            "registry_kind": kind,
            "expected_target": expected_target or cfg_mod.repository_target_snapshot(repository),
        }
        credential = client.post(
            "/v0/package-credentials",
            json=credential_body,
        ).json()
    except (ApiError, KeyError, TypeError, ValueError) as exc:
        output.fatal(str(exc))
    if repo is None:
        cfg_mod.set_registry_default_target(
            _require_kind(kind),
            customer=entry["customer"],
            repository=repository,
            profile=profile,
        )
    return (
        _registry_profile(profile),
        repository["workspace_unique_ref"],
        repository["repository_unique_ref"],
        credential["access_token"],
    )


def _resolve_repository_entry(
    repo: str,
    profile: str | None,
    *,
    kind: str | None = None,
    customer_id: str | None = None,
) -> dict:
    try:
        return (
            _client(profile)
            .get(
                "/v0/repositories/resolve",
                params={
                    "selector": repo,
                    "customer_id": customer_id,
                    "registry_kind": kind,
                },
            )
            .json()
        )
    except ApiError as exc:
        output.fatal(str(exc))


def _resolved_repository_id(
    repo: str,
    profile: str | None,
    *,
    kind: str,
) -> str:
    return _resolve_repository_entry(
        repo,
        profile,
        kind=kind,
    )["repository"]["id"]


# ── repo ─────────────────────────────────────────────────────────────────────


@repo_app.command("list")
def repo_list(
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(None, "--customer-id", help="Customer filter."),
    kind: str | None = typer.Option(
        None,
        "--registry-kind",
        "-k",
        "--ecosystem",
        "-e",
        help="Registry-kind filter: pypi | npm | maven | container | helm.",
    ),
) -> None:
    """List repositories across every authorized customer and workspace."""
    if kind:
        _require_kind(kind)
    client = _client(profile)
    try:
        data = client.get(
            "/v0/repositories",
            params={"customer_id": customer_id, "registry_kind": kind},
        ).json()
    except ApiError as exc:
        output.fatal(str(exc))

    entries = data if isinstance(data, list) else data.get("items", [])
    items = [entry["repository"] for entry in entries]
    if not items:
        output.info("No package repositories found.")
        return

    output.table(
        ["Account", "Workspace", "Repository", "Stable reference", "Registry kinds"],
        [
            [
                entry["customer"]["account_label"],
                entry["repository"]["workspace_name"],
                _repository_name_from_response(item),
                (f"{item['workspace_unique_ref']}/{item['repository_unique_ref']}"),
                ", ".join(item.get("registry_kinds", [])),
            ]
            for entry, item in zip(entries, items, strict=True)
        ],
    )


@repo_app.command("create")
def repo_create(
    name: str = typer.Argument(..., help=_REPOSITORY_NAME_HELP),
    kind: list[str] = typer.Option(
        ...,
        "--registry-kind",
        "-k",
        "--ecosystem",
        "-e",
        help="Registry kind to enable; repeat to enable more than one.",
    ),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(None, "--customer-id", help="Owning customer ID."),
    set_default: bool = typer.Option(
        False, "--default", help="Set as default for each selected registry kind."
    ),
) -> None:
    """Create a package repository."""
    kinds: list[cfg_mod.RegistryKind] = list(dict.fromkeys(_require_kind(value) for value in kind))
    client = _client(profile)
    payload = {
        "customer_id": _customer_id(profile, customer_id),
        "repository_name": name,
        "registry_kinds": kinds,
    }
    try:
        entry = client.post("/v0/repositories", json=payload).json()
        repo = entry["repository"]
    except ApiError as exc:
        output.fatal(str(exc))

    repository_name = _repository_name_from_response(repo, name)
    output.success(
        f"Created package repository '{repository_name}' with registry kinds: {', '.join(kinds)}."
    )
    if set_default and repository_name:
        default_repo = _repo_ref_from_response(repo, repository_name)
        for registry_kind in kinds:
            cfg_mod.set_registry_default_target(
                registry_kind,
                customer=entry["customer"],
                repository=repo,
                profile=profile,
            )
        output.info(f"Default repository for {', '.join(kinds)} set to {default_repo}.")


@repo_app.command("show")
def repo_show(
    repo: str = typer.Argument(..., help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Show package repository details."""
    try:
        entry = _resolve_repository_entry(repo, profile)
        item = entry["repository"]
    except ApiError as exc:
        output.fatal(str(exc))

    output.kv(
        {
            "Name": _repository_name_from_response(item, repo),
            "Account": entry["customer"]["account_label"],
            "Workspace": item["workspace_name"],
            "Workspace reference": item["workspace_unique_ref"],
            "Repository reference": item["repository_unique_ref"],
            "Registry kinds": ", ".join(item.get("registry_kinds", [])),
            "Packages": str(item.get("aggregate_package_count", item.get("package_count", "0"))),
            "Versions": str(item.get("aggregate_version_count", item.get("version_count", "0"))),
            "OCI paths": str(item.get("aggregate_oci_repository_count", "0")),
            "Manifests": str(item.get("aggregate_manifest_count", "0")),
            "Storage bytes": str(
                item.get("aggregate_storage_bytes", item.get("storage_bytes", "0"))
            ),
            "Created": str(item.get("created_at", "")),
        },
        title=f"Package repository {repo}",
    )


@repo_app.command("delete")
def repo_delete(
    repo: str = typer.Argument(..., help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """Delete a package repository."""
    if not yes:
        typer.confirm(f"Delete package repository '{repo}' and its packages?", abort=True)
    client = _client(profile)
    try:
        entry = _resolve_repository_entry(repo, profile)
        client.delete(f"/v0/repositories/{entry['repository']['id']}")
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Deleted package repository '{repo}'.")


@repo_app.command("rename")
def repo_rename(
    repo: str = typer.Argument(..., help="Current package repository name."),
    new_name: str = typer.Argument(..., help="New package repository name."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Rename a package repository."""
    client = _client(profile)
    try:
        entry = _resolve_repository_entry(repo, profile)
        updated = client.patch(
            f"/v0/repositories/{entry['repository']['id']}",
            json={"repository_name": new_name},
        ).json()
        item = updated["repository"]
    except ApiError as exc:
        output.fatal(str(exc))
    cfg_mod.refresh_matching_registry_targets(
        customer=entry["customer"],
        repository=item,
        profile=profile,
    )
    renamed = _repository_name_from_response(item, new_name)
    output.success(f"Renamed package repository '{repo}' to '{renamed}'.")


@repo_app.command("set-default")
def repo_set_default(
    kind: str = typer.Argument(
        ...,
        help="Registry kind: pypi | npm | maven | container | helm",
        metavar="REGISTRY_KIND",
    ),
    repo: str = typer.Argument(..., help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Set the default package repository for a registry kind."""
    registry_kind = _require_kind(kind)
    profile_name = _profile_name(profile)
    entry = _resolve_repository_entry(repo, profile, kind=kind)
    repository = entry["repository"]
    stable = f"{repository['workspace_unique_ref']}/{repository['repository_unique_ref']}"
    cfg_mod.set_registry_default_target(
        registry_kind,
        customer=entry["customer"],
        repository=repository,
        profile=profile_name,
    )
    output.success(
        f"Default {kind} package repository for profile '{profile_name}' set to {stable}."
    )


@repo_app.command("defaults")
def repo_defaults(
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Show default package repositories."""
    cfg = cfg_mod.load()
    profile_name = profile or cfg_mod.current_profile_name(cfg)
    rows = [
        [kind, cfg.registry_defaults(kind, profile_name).default_repo or "not set"]  # type: ignore[arg-type]
        for kind in _KINDS
    ]
    output.table(
        ["Registry kind", "Default repository"],
        rows,
        title=f"Package repository defaults ({profile_name})",
    )


@repo_app.command("set-upstream")
def repo_set_upstream(
    repo: str = typer.Argument(..., help="Private package repository name."),
    remote: str = typer.Argument(..., help="Remote cache & proxy ID."),
    min_age_days: float = typer.Option(3, "--min-age-days", min=0),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Connect a remote cache & proxy to a private repository."""
    client = _client(profile)
    try:
        remote_entry = client.get(f"/v0/remote-repositories/{remote}").json()
        remote_repository = remote_entry["remote_repository"]
        registry_kind = remote_repository["registry_kind"]
        repository_id = _resolved_repository_id(repo, profile, kind=registry_kind)
        client.post(
            f"/v0/repositories/{repository_id}/lanes/{registry_kind}/remote-upstreams",
            json={
                "remote_repository_lane_id": remote_repository["id"],
                "min_age_days": min_age_days,
            },
        )
    except (ApiError, KeyError, TypeError) as exc:
        output.fatal(str(exc))
    output.success(f"Connected remote cache & proxy '{remote}' to '{repo}'.")


@repo_app.command("clear-upstream")
def repo_clear_upstream(
    repo: str = typer.Argument(..., help="Private package repository name."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Remove the upstream configuration from a private repository."""
    client = _client(profile)
    try:
        entry = _resolve_repository_entry(repo, profile)
        repository = entry["repository"]
        for registry_kind in repository["registry_kinds"]:
            if registry_kind not in _PACKAGE_KINDS:
                continue
            path = f"/v0/repositories/{repository['id']}/lanes/{registry_kind}/remote-upstreams"
            attachments = client.get(path).json()
            for attachment in attachments:
                client.delete(f"{path}/{attachment['id']}")
    except (ApiError, KeyError, TypeError) as exc:
        output.fatal(str(exc))
    output.success(f"Removed the upstream connection from '{repo}'.")


# ── remote caches & proxies ───────────────────────────────────────────────────


@remote_app.command("list")
def remote_list(
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(None, "--customer-id"),
    kind: str | None = typer.Option(None, "--registry-kind", "-k", "--ecosystem", "-e"),
) -> None:
    """List remote caches & proxies for the selected customer."""
    if kind:
        _require_package_kind(kind)
    client = _client(profile)
    try:
        items = client.get(
            "/v0/remote-repositories",
            params={
                "customer_id": customer_id,
                "registry_kind": kind,
            },
        ).json()
    except ApiError as exc:
        output.fatal(str(exc))
    if kind:
        items = [
            entry for entry in items if entry["remote_repository"].get("registry_kind") == kind
        ]
    if not items:
        output.info("No remote caches & proxies found.")
        return
    output.table(
        ["ID", "Registry kind", "Minimum package age", "Maximum age"],
        [
            [
                str(item["public_id"]),
                str(item.get("registry_kind", "")),
                str(item.get("min_age_days", "")),
                str(item.get("max_age_days", "")),
            ]
            for entry in items
            for item in [entry["remote_repository"]]
        ],
    )


@remote_app.command("create")
def remote_create(
    kind: str = typer.Option(..., "--registry-kind", "-k", "--ecosystem", "-e"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(None, "--customer-id"),
) -> None:
    """Create a remote cache & proxy for a registry kind."""
    _require_package_kind(kind)
    client = _client(profile)
    try:
        item = client.post(
            "/v0/remote-repositories",
            json={
                "customer_id": _customer_id(profile, customer_id),
                "registry_kind": kind,
            },
        ).json()["remote_repository"]
    except ApiError as exc:
        output.fatal(str(exc))
    remote_id = item["public_id"]
    output.success(f"Created {kind} remote cache & proxy '{remote_id}'.")


@remote_app.command("show")
def remote_show(
    remote: str = typer.Argument(..., help="Remote cache & proxy ID."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Show a remote cache & proxy."""
    client = _client(profile)
    try:
        item = client.get(f"/v0/remote-repositories/{remote}").json()["remote_repository"]
    except (ApiError, KeyError, TypeError) as exc:
        output.fatal(str(exc))
    output.kv(
        {
            "ID": item["public_id"],
            "Registry kind": item.get("registry_kind"),
            "Owner ID": item.get("customer_id"),
            "Minimum package age (days)": str(item.get("min_age_days", "")),
            "Maximum age days": str(item.get("max_age_days", "")),
        },
        title=f"Remote cache & proxy {remote}",
    )


@remote_app.command("set-age")
def remote_set_age(
    remote: str = typer.Argument(..., help="Remote cache & proxy ID."),
    min_age_days: float = typer.Option(..., "--min-age-days", min=0),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Update the minimum package age for direct access."""
    client = _client(profile)
    payload = {"min_age_days": min_age_days}
    try:
        client.patch(f"/v0/remote-repositories/{remote}", json=payload)
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Updated minimum package age for remote cache & proxy '{remote}'.")


@remote_app.command("delete")
def remote_delete(
    remote: str = typer.Argument(..., help="Remote cache & proxy ID."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(None, "--customer-id"),
    kind: str | None = typer.Option(None, "--registry-kind", "-k", "--ecosystem", "-e"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Delete a remote cache & proxy."""
    if (customer_id is None) != (kind is None):
        output.fatal("Pass both --customer-id and --registry-kind, or neither.")
    if kind:
        _require_package_kind(kind)
    if not yes:
        typer.confirm(f"Delete remote cache & proxy '{remote}'?", abort=True)
    params = None
    if customer_id and kind:
        params = {"customer_id": customer_id, "registry_kind": kind}
    client = _client(profile)
    try:
        client.delete(f"/v0/remote-repositories/{remote}", params=params)
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Deleted remote cache & proxy '{remote}'.")


# ── package ──────────────────────────────────────────────────────────────────


@package_app.command("list")
def package_list(
    repo: str = typer.Option(..., "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    kind: str = typer.Option(
        ...,
        "--registry-kind",
        "-k",
        "--ecosystem",
        "-e",
        help="Registry kind: pypi | npm | maven.",
    ),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """List packages hosted in a package repository."""
    registry_kind = _require_package_kind(kind)
    client = _client(profile)
    try:
        repository_id = _resolved_repository_id(repo, profile, kind=registry_kind)
        data = client.get(f"/v0/repositories/{repository_id}/lanes/{registry_kind}/packages").json()
    except ApiError as exc:
        output.fatal(str(exc))

    items = data if isinstance(data, list) else data.get("items", [])
    if not items:
        output.info(f"No packages found in '{repo}'.")
        return

    output.table(
        ["Name", "Latest", "Versions", "Size", "Downloads", "Bandwidth"],
        [
            [
                item.get("package_name") or item.get("normalized_name", ""),
                item.get("latest_version") or "",
                str(item.get("version_count", "")),
                str(item.get("total_size_bytes", "")),
                str(item.get("downloads", "0")),
                str(item.get("bandwidth_bytes", "0")),
            ]
            for item in items
        ],
        title=f"Packages in {repo}",
    )


@package_app.command("show")
def package_show(
    name: str = typer.Argument(..., help="Package name."),
    repo: str = typer.Option(..., "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    kind: str = typer.Option(
        ...,
        "--registry-kind",
        "-k",
        "--ecosystem",
        "-e",
        help="Registry kind: pypi | npm | maven.",
    ),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Show package metadata and versions."""
    registry_kind = _require_package_kind(kind)
    client = _client(profile)
    try:
        repository_id = _resolved_repository_id(repo, profile, kind=registry_kind)
        item = client.get(
            f"/v0/repositories/{repository_id}/lanes/{registry_kind}/package",
            params={"package_name": name},
        ).json()
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
            ["Version", "Yanked", "Files", "Size", "Downloads", "Bandwidth"],
            [
                [
                    version.get("version", ""),
                    "yes" if version.get("yanked") else "no",
                    str(len(version.get("files") or [])),
                    str(version.get("total_size_bytes", "")),
                    str(version.get("downloads", "0")),
                    str(version.get("bandwidth_bytes", "0")),
                ]
                for version in versions
            ],
        )
        artifacts = [
            [
                str(version.get("version", "")),
                str(artifact.get("filename", "")),
                str(artifact.get("size", "")),
                str(artifact.get("sha256_digest") or ""),
            ]
            for version in versions
            for artifact in version.get("files") or []
        ]
        if artifacts:
            output.table(
                ["Version", "Artifact", "Size", "SHA256"],
                artifacts,
                title="Artifacts",
            )


@package_app.command("delete")
def package_delete(
    name: str = typer.Argument(..., help="Package name."),
    repo: str = typer.Option(..., "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    kind: str = typer.Option(
        ...,
        "--registry-kind",
        "-k",
        "--ecosystem",
        "-e",
        help="Registry kind: pypi | npm | maven.",
    ),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """Delete a package and all of its versions."""
    if not yes:
        typer.confirm(f"Delete package '{name}' from '{repo}'?", abort=True)
    registry_kind = _require_package_kind(kind)
    client = _client(profile)
    try:
        repository_id = _resolved_repository_id(repo, profile, kind=registry_kind)
        client.delete(
            f"/v0/repositories/{repository_id}/lanes/{registry_kind}/package",
            params={"package_name": name},
        )
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Deleted package '{name}' from '{repo}'.")


@package_app.command("delete-version")
def package_delete_version(
    name: str = typer.Argument(..., help="Package name."),
    version: str = typer.Argument(..., help="Version to delete."),
    repo: str = typer.Option(..., "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    kind: str = typer.Option(
        ...,
        "--registry-kind",
        "-k",
        "--ecosystem",
        "-e",
        help="Registry kind: pypi | npm | maven.",
    ),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """Delete one package version."""
    if not yes:
        typer.confirm(f"Delete {name}@{version} from '{repo}'?", abort=True)
    registry_kind = _require_package_kind(kind)
    client = _client(profile)
    try:
        repository_id = _resolved_repository_id(repo, profile, kind=registry_kind)
        client.delete(
            f"/v0/repositories/{repository_id}/lanes/{registry_kind}/package-version",
            params={"package_name": name, "version": version},
        )
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Deleted {name}@{version} from '{repo}'.")


@package_app.command("yank")
def package_yank(
    name: str = typer.Argument(..., help="Package name."),
    version: str = typer.Argument(..., help="Version to yank."),
    repo: str = typer.Option(..., "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    kind: str = typer.Option(
        ...,
        "--registry-kind",
        "-k",
        "--ecosystem",
        "-e",
        help="Registry kind: pypi | npm | maven.",
    ),
    reason: str | None = typer.Option(None, "--reason", "-m", help="Yank reason."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Mark a package version as yanked."""
    registry_kind = _require_package_kind(kind)
    client = _client(profile)
    body = {"reason": reason} if reason else None
    try:
        repository_id = _resolved_repository_id(repo, profile, kind=registry_kind)
        client.post(
            f"/v0/repositories/{repository_id}/lanes/{registry_kind}/package-version/yank",
            params={"package_name": name, "version": version},
            json=body,
        )
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Yanked {name}@{version} in '{repo}'.")


# ── PyPI ─────────────────────────────────────────────────────────────────────


@pypi_app.command("index-url")
def pypi_index_url(
    repo: str | None = typer.Option(None, "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(
        None, "--customer-id", help="Customer disambiguation override."
    ),
) -> None:
    """Print the private PyPI simple-index URL."""
    profile_cfg, customer_id, repository_name, _ = _registry_context(
        "pypi", repo, profile, customer_id
    )
    output.value(
        _ROUTER.pypi_index_url(profile_cfg.pkg_download_url, customer_id, repository_name),
        key="index_url",
    )


@pypi_app.command("upload-url")
def pypi_upload_url(
    repo: str | None = typer.Option(None, "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(
        None, "--customer-id", help="Customer disambiguation override."
    ),
) -> None:
    """Print the private PyPI upload URL."""
    profile_cfg, customer_id, repository_name, _ = _registry_context(
        "pypi", repo, profile, customer_id
    )
    output.value(
        _ROUTER.pypi_upload_url(profile_cfg.pkg_upload_url, customer_id, repository_name),
        key="upload_url",
    )


@pypi_app.command("install")
def pypi_install(
    packages: list[str] = typer.Argument(..., help="Package specs to install."),
    repo: str | None = typer.Option(None, "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(
        None, "--customer-id", help="Customer disambiguation override."
    ),
) -> None:
    """Install Python packages using pip with Ravenstash credentials injected."""
    profile_cfg, customer_id, repository_name, token = _registry_context(
        "pypi", repo, profile, customer_id
    )
    index_url = _ROUTER.pypi_index_url(profile_cfg.pkg_download_url, customer_id, repository_name)
    env = {**os.environ}
    if token:
        env["PIP_INDEX_URL"] = _authed_url(index_url, token)
    else:
        output.warn("No credentials found; running pip without private repository auth.")

    cmd = [*tools.pip_cmd(), "install", *packages]
    subprocess.run(cmd, env=env, check=True)


@pypi_app.command("publish")
def pypi_publish(
    dist_dir: Path = typer.Argument(Path("dist"), help="Directory with wheels/sdists."),
    repo: str | None = typer.Option(None, "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(
        None, "--customer-id", help="Customer disambiguation override."
    ),
) -> None:
    """Upload wheel and sdist files to a PyPI package repository."""
    profile_cfg, customer_id, repository_name, token = _registry_context(
        "pypi", repo, profile, customer_id
    )
    files = list(dist_dir.glob("*.whl")) + list(dist_dir.glob("*.tar.gz"))
    if not files:
        output.fatal(f"No .whl or .tar.gz files found in {dist_dir}")
    results = pypi_reg.publish(
        upload_url=_ROUTER.pypi_upload_url(
            profile_cfg.pkg_upload_url, customer_id, repository_name
        ),
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
    repo: str | None = typer.Option(None, "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(
        None, "--customer-id", help="Customer disambiguation override."
    ),
) -> None:
    """Print pip configuration for the private PyPI repository."""
    profile_cfg, customer_id, repository_name, _ = _registry_context(
        "pypi", repo, profile, customer_id
    )
    index_url = _ROUTER.pypi_index_url(profile_cfg.pkg_download_url, customer_id, repository_name)
    output.value(f"[global]\nindex-url = {index_url}", key="configuration")


# ── npm ──────────────────────────────────────────────────────────────────────


@npm_app.command("registry-url")
def npm_registry_url(
    repo: str | None = typer.Option(None, "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(
        None, "--customer-id", help="Customer disambiguation override."
    ),
) -> None:
    """Print the private npm registry URL."""
    profile_cfg, customer_id, repository_name, _ = _registry_context(
        "npm", repo, profile, customer_id
    )
    output.value(
        _ROUTER.npm_registry_url(profile_cfg.pkg_download_url, customer_id, repository_name),
        key="registry_url",
    )


@npm_app.command("npmrc")
def npmrc(
    repo: str | None = typer.Option(None, "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(
        None, "--customer-id", help="Customer disambiguation override."
    ),
) -> None:
    """Print an .npmrc snippet for the private npm repository."""
    profile_cfg, customer_id, repository_name, _ = _registry_context(
        "npm", repo, profile, customer_id
    )
    registry_url = _ROUTER.npm_registry_url(
        profile_cfg.pkg_download_url, customer_id, repository_name
    )
    auth_key = _npm_auth_token_key(registry_url)
    output.value(
        f"registry={registry_url}\n{auth_key}=${{RVS_TOKEN}}",
        key="configuration",
    )


@npm_app.command("install")
def npm_install(
    packages: list[str] = typer.Argument(..., help="Package specs to install."),
    repo: str | None = typer.Option(None, "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(
        None, "--customer-id", help="Customer disambiguation override."
    ),
) -> None:
    """Install npm packages with Ravenstash credentials injected."""
    profile_cfg, customer_id, repository_name, token = _registry_context(
        "npm", repo, profile, customer_id
    )
    registry_url = _ROUTER.npm_registry_url(
        profile_cfg.pkg_download_url, customer_id, repository_name
    )
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
    repo: str | None = typer.Option(None, "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(
        None, "--customer-id", help="Customer disambiguation override."
    ),
) -> None:
    """Publish an npm package to a Ravenstash npm repository."""
    profile_cfg, customer_id, repository_name, token = _registry_context(
        "npm", repo, profile, customer_id
    )
    results = npm_reg.publish(
        registry_url=_ROUTER.npm_upload_registry_url(
            profile_cfg.pkg_upload_url, customer_id, repository_name
        ),
        token=token,
        package_dir=package_dir,
        download_registry_url=_ROUTER.npm_registry_url(
            profile_cfg.pkg_download_url, customer_id, repository_name
        ),
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
    repo: str | None = typer.Option(None, "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(
        None, "--customer-id", help="Customer disambiguation override."
    ),
) -> None:
    """Print .npmrc configuration for the private npm repository."""
    npmrc(repo=repo, profile=profile, customer_id=customer_id)


# ── Maven ────────────────────────────────────────────────────────────────────


@maven_app.command("repo-url")
def maven_repo_url(
    repo: str | None = typer.Option(None, "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(
        None, "--customer-id", help="Customer disambiguation override."
    ),
) -> None:
    """Print the private Maven repository URL."""
    profile_cfg, customer_id, repository_name, _ = _registry_context(
        "maven", repo, profile, customer_id
    )
    output.value(
        _ROUTER.maven_repo_url(profile_cfg.pkg_download_url, customer_id, repository_name),
        key="repository_url",
    )


def _settings_xml(repo_url: str, password_expr: str = "${env.RVS_TOKEN}") -> str:
    return f"""<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0">
  <servers>
    <server>
      <id>rvs-private</id>
      <username>__token__</username>
      <password>{password_expr}</password>
    </server>
  </servers>
  <profiles>
    <profile>
      <id>rvs</id>
      <repositories>
        <repository>
          <id>rvs-private</id>
          <url>{repo_url}</url>
          <releases><enabled>true</enabled></releases>
          <snapshots><enabled>true</enabled></snapshots>
        </repository>
      </repositories>
    </profile>
  </profiles>
  <activeProfiles>
    <activeProfile>rvs</activeProfile>
  </activeProfiles>
</settings>"""


@maven_app.command("settings")
def maven_settings(
    repo: str | None = typer.Option(None, "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(
        None, "--customer-id", help="Customer disambiguation override."
    ),
) -> None:
    """Print a Maven settings.xml snippet for the private Maven repository."""
    profile_cfg, customer_id, repository_name, _ = _registry_context(
        "maven", repo, profile, customer_id
    )
    output.value(
        _settings_xml(
            _ROUTER.maven_repo_url(profile_cfg.pkg_download_url, customer_id, repository_name)
        ),
        key="configuration",
    )


@maven_app.command("install")
def maven_install(
    coords: str = typer.Argument(..., help="Maven coordinates: groupId:artifactId:version."),
    repo: str | None = typer.Option(None, "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(
        None, "--customer-id", help="Customer disambiguation override."
    ),
) -> None:
    """Fetch a Maven artifact into the local Maven cache."""
    profile_cfg, customer_id, repository_name, token = _registry_context(
        "maven", repo, profile, customer_id
    )
    repo_url = _ROUTER.maven_repo_url(profile_cfg.pkg_download_url, customer_id, repository_name)
    settings_xml = maven_reg._build_settings_xml(repo_url, token)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".xml", prefix="rvs-settings-", delete=False
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
    repo: str | None = typer.Option(None, "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(
        None, "--customer-id", help="Customer disambiguation override."
    ),
) -> None:
    """Deploy an artifact file to a Ravenstash Maven repository."""
    if not artifact_file.exists():
        output.fatal(f"Artifact file not found: {artifact_file}")
    try:
        maven_reg.validate_artifact_filename(artifact_file.name, artifact, version)
    except ValueError as exc:
        output.fatal(str(exc))
    profile_cfg, customer_id, repository_name, token = _registry_context(
        "maven", repo, profile, customer_id
    )
    results = maven_reg.publish(
        upload_url=_ROUTER.maven_upload_url(
            profile_cfg.pkg_upload_url, customer_id, repository_name
        ),
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
    repo: str | None = typer.Option(None, "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(
        None, "--customer-id", help="Customer disambiguation override."
    ),
) -> None:
    """Print Maven settings.xml configuration for the private Maven repository."""
    maven_settings(repo=repo, profile=profile, customer_id=customer_id)
