"""`rvs pkg` command group."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import cast
from urllib.parse import urlparse, urlunparse

import click
import typer

from .. import auth as auth_mod
from .. import config as cfg_mod
from .. import output
from ..account.commands import display_name as account_display_name
from ..account.commands import ensure_active_account, resolve_account
from ..client import ApiClient, ApiError
from ..native import runner as native_runner
from ..runtime import tools
from .registries import maven as maven_reg
from .registries import npm as npm_reg
from .registries import pypi as pypi_reg
from .routing import CanonicalRouter
from .targets import RegistryContext, registry_context, resolve_target


app = typer.Typer(
    name="pkg",
    help="Manage Ravenstash package repositories and package-manager configuration.",
    no_args_is_help=True,
)

repo_app = typer.Typer(help="Manage Ravenstash package repositories.", no_args_is_help=True)
upstream_app = typer.Typer(help="Manage ordered repository-lane upstreams.", no_args_is_help=True)
remote_app = typer.Typer(
    help="Manage private mirrors backed by remote caches.", no_args_is_help=True
)
package_app = typer.Typer(help="Manage packages hosted in a repository.", no_args_is_help=True)
pypi_app = typer.Typer(help="PyPI package repository helpers.", no_args_is_help=True)
npm_app = typer.Typer(help="npm package repository helpers.", no_args_is_help=True)
maven_app = typer.Typer(help="Maven package repository helpers.", no_args_is_help=True)

app.add_typer(repo_app, name="repo")
repo_app.add_typer(upstream_app, name="upstream")
app.add_typer(remote_app, name="mirror")
app.add_typer(package_app, name="package")
app.add_typer(pypi_app, name="pypi")
app.add_typer(npm_app, name="npm")
app.add_typer(maven_app, name="maven")

_KINDS = ("pypi", "npm", "maven", "container", "helm")
_PACKAGE_KINDS = ("pypi", "npm", "maven")
_MAX_UPSTREAM_PRIORITY = 3
_ROUTER = CanonicalRouter()
_REPOSITORY_NAME_HELP = "Package repository name: lowercase letters, numbers, and hyphens."


def _format_age_hours(value: float | int | str | None, *, missing: str) -> str:
    if value is None:
        return missing
    return f"{float(value):g} hours"


@app.callback()
def package_context(
    ctx: typer.Context,
    target: str | None = typer.Option(
        None,
        "--target",
        help="One-shot package target: workspace/repository, mirror:<source>, or custom-mirror:<name>.",
    ),
    account: str | None = typer.Option(
        None,
        "--account",
        help="One-shot acting account selector.",
    ),
    kind: str | None = typer.Option(
        None, "--kind", help="Registry kind when inference is ambiguous."
    ),
    profile: str | None = typer.Option(None, "--profile", help="One-shot local CLI profile."),
) -> None:
    """Manage package targets and delegate package operations to native tools."""
    ctx.obj = {
        "target": target,
        "account": account,
        "kind": kind,
        "profile": profile,
    }


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
    profile_name, _ = _profile(profile)
    customer_id = cfg_mod.current_customer_id(profile_name)
    if not customer_id:
        output.fatal("No acting account is selected. Run `rvs account use` or pass --customer-id.")
    return customer_id


def _context_customer_id(profile: str | None, account: str | None) -> str | None:
    if account is None:
        return None
    return str(resolve_account(account, profile)["customer_id"])


@app.command("select")
def target_select(
    target: str = typer.Argument(
        ...,
        help="workspace/repository, mirror:<source>, or custom-mirror:<name>.",
    ),
    kind: str | None = typer.Option(None, "--kind", help="Registry kind if ambiguous."),
    account: str | None = typer.Option(None, "--account", help="Acting account selector."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Select the package target used when --target is omitted."""
    customer_id = _context_customer_id(profile, account)
    profile_name, selected_account, selected = resolve_target(
        target,
        profile=profile,
        customer_id=customer_id,
        kind=kind,
    )
    try:
        cfg_mod.set_selected_package_target(
            selected,
            profile=profile_name,
            customer_id=selected_account.customer_id,
        )
    except ValueError as exc:
        output.fatal(str(exc))
    kind_suffix = f" ({selected.registry_kind})" if selected.registry_kind else ""
    output.success(
        f"Selected '{selected.display_selector}'{kind_suffix} for "
        f"{account_display_name(selected_account)}."
    )


@app.command("current")
def target_current(
    account: str | None = typer.Option(None, "--account", help="Acting account selector."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Show the current profile, account, and package target."""
    customer_id = _context_customer_id(profile, account)
    profile_name, selected_account = ensure_active_account(profile, customer_id)
    selected = cfg_mod.selected_package_target(profile_name, selected_account.customer_id)
    output.kv(
        {
            "Profile": profile_name,
            "Account": account_display_name(selected_account),
            "Target": selected.display_selector if selected else "none",
            "Target type": selected.target_type if selected else "none",
            "Registry kind": selected.registry_kind or "inferred by operation"
            if selected
            else "none",
        },
        title="Current package context",
    )


@app.command("clear")
def target_clear(
    account: str | None = typer.Option(None, "--account", help="Acting account selector."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Clear the explicit package target without changing login or account."""
    customer_id = _context_customer_id(profile, account)
    profile_name, selected_account = ensure_active_account(profile, customer_id)
    try:
        cfg_mod.set_selected_package_target(
            None,
            profile=profile_name,
            customer_id=selected_account.customer_id,
        )
    except ValueError as exc:
        output.fatal(str(exc))
    output.success(f"Cleared the package target for {account_display_name(selected_account)}.")


def _project_package_kind() -> str | None:
    candidates: list[str] = []
    if Path("pyproject.toml").exists() or Path("requirements.txt").exists():
        candidates.append("pypi")
    if Path("package.json").exists():
        candidates.append("npm")
    if Path("pom.xml").exists():
        candidates.append("maven")
    return candidates[0] if len(candidates) == 1 else None


@app.command("install")
def package_install(
    packages: list[str] = typer.Argument(..., help="Package specifications to install."),
) -> None:
    """Install from the one-shot, selected, or official-default package target."""
    options = _root_package_options()
    kind = options.get("kind")
    if kind is not None:
        _require_package_kind(kind)
    if kind is None and options.get("target"):
        customer_id = _context_customer_id(options.get("profile"), options.get("account"))
        _, _, target = resolve_target(
            cast("str", options["target"]),
            profile=options.get("profile"),
            customer_id=customer_id,
        )
        kind = target.registry_kind
    if kind is None:
        customer_id = _context_customer_id(options.get("profile"), options.get("account"))
        profile_name, account = ensure_active_account(options.get("profile"), customer_id)
        selected = cfg_mod.selected_package_target(profile_name, account.customer_id)
        kind = selected.registry_kind if selected is not None else None
    kind = kind or _project_package_kind()
    if kind not in _PACKAGE_KINDS:
        output.fatal("Cannot infer the package registry kind. Pass --kind pypi, npm, or maven.")
    if kind == "pypi":
        pypi_install(packages=packages, repo=None, profile=None, customer_id=None)
    elif kind == "npm":
        npm_install(packages=packages, repo=None, profile=None, customer_id=None)
    else:
        if len(packages) != 1:
            output.fatal("Maven install accepts one groupId:artifactId:version coordinate.")
        maven_install(coords=packages[0], repo=None, profile=None, customer_id=None)


def _require_kind(kind: str) -> cfg_mod.RegistryKind:
    if kind not in _KINDS:
        output.fatal(f"Unknown registry kind '{kind}'. Use: pypi, npm, maven, container, helm")
    return cast("cfg_mod.RegistryKind", kind)


def _require_package_kind(kind: str) -> cfg_mod.RegistryKind:
    if kind not in _PACKAGE_KINDS:
        output.fatal(
            "Package/version commands and private mirrors support only pypi, npm, "
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


def _root_package_options() -> dict[str, str | None]:
    context = click.get_current_context(silent=True)
    while context is not None:
        value = context.obj
        if isinstance(value, dict) and {"target", "account", "kind", "profile"} <= value.keys():
            return value
        context = context.parent
    return {}


def _registry_context(
    kind: str,
    repo: str | None,
    profile: str | None,
    customer_id: str | None = None,
    *,
    require_private: bool = False,
    allow_official_default: bool = False,
) -> RegistryContext:
    options = _root_package_options()
    effective_profile = profile or options.get("profile")
    effective_customer_id = customer_id
    if effective_customer_id is None and options.get("account"):
        effective_customer_id = _context_customer_id(effective_profile, options.get("account"))
    return registry_context(
        kind=kind,
        target=options.get("target"),
        repo=repo,
        profile=effective_profile,
        customer_id=effective_customer_id,
        allow_official_default=allow_official_default,
        require_private=require_private,
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


def _upstream_path(repository_id: str, registry_kind: str) -> str:
    return f"/v0/repositories/{repository_id}/lanes/{registry_kind}/upstreams"


def _repository_lane_id(entry: dict, registry_kind: str) -> str:
    lane = next(
        (
            lane
            for lane in entry["repository"].get("lanes", [])
            if lane.get("registry_kind") == registry_kind
        ),
        None,
    )
    if lane is None or not lane.get("id"):
        output.fatal(f"Repository has no {registry_kind} lane.")
    return str(lane["id"])


def _print_upstreams(items: list[dict]) -> None:
    output.table(
        ["ID", "Priority", "Type", "Source", "Minimum age", "Maximum age"],
        [
            [
                str(item.get("id", "")),
                str(item.get("priority", "")),
                str(item.get("source_type", "")),
                (
                    f"{item.get('source_workspace_name')}/{item.get('source_repository_name')}"
                    if item.get("source_workspace_name")
                    else str(item.get("source_repository_name", ""))
                ),
                _format_age_hours(item.get("min_age_hours"), missing="No minimum"),
                _format_age_hours(item.get("max_age_hours"), missing="No maximum"),
            ]
            for item in items
        ],
        title="Repository upstreams",
    )


@upstream_app.command("list")
def upstream_list(
    repository: str = typer.Argument(...),
    kind: str = typer.Argument(...),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """List the complete ordered upstream plan for one repository lane."""
    registry_kind = _require_package_kind(kind)
    client = _client(profile)
    try:
        entry = _resolve_repository_entry(repository, profile, kind=registry_kind)
        items = client.get(_upstream_path(entry["repository"]["id"], registry_kind)).json()
    except (ApiError, KeyError, TypeError) as exc:
        output.fatal(str(exc))
    _print_upstreams(items)


@upstream_app.command("add")
def upstream_add(
    repository: str = typer.Argument(...),
    kind: str = typer.Argument(...),
    private_repository: str | None = typer.Option(None, "--private-repository"),
    remote_cache: str | None = typer.Option(None, "--remote-cache"),
    priority: int | None = typer.Option(None, "--priority", min=0, max=_MAX_UPSTREAM_PRIORITY),
    min_age_hours: float | None = typer.Option(None, "--min-age-hours", min=0),
    max_age_hours: float | None = typer.Option(None, "--max-age-hours", min=0),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Attach one private repository lane or remote cache."""
    if (private_repository is None) == (remote_cache is None):
        output.fatal("Pass exactly one of --private-repository or --remote-cache.")
    registry_kind = _require_package_kind(kind)
    client = _client(profile)
    try:
        destination = _resolve_repository_entry(repository, profile, kind=registry_kind)
        if private_repository is not None:
            source = _resolve_repository_entry(private_repository, profile, kind=registry_kind)
            source_lane_id = _repository_lane_id(source, registry_kind)
            source_type = "private"
        else:
            remote_entry = client.get(
                f"/v0/remote-repositories/{remote_cache}",
                params={"registry_kind": registry_kind},
            ).json()
            source_lane_id = str(remote_entry["remote_repository"]["id"])
            source_type = "remote"
        if priority is None:
            current = client.get(
                _upstream_path(destination["repository"]["id"], registry_kind)
            ).json()
            effective_priority = len(current)
        else:
            effective_priority = priority
        body = {
            "source_type": source_type,
            "source_repository_lane_id": source_lane_id,
            "priority": effective_priority,
            "max_age_hours": max_age_hours,
        }
        if min_age_hours is not None:
            body["min_age_hours"] = min_age_hours
        elif source_type == "private":
            body["min_age_hours"] = 0.0
        item = client.post(
            _upstream_path(destination["repository"]["id"], registry_kind),
            json=body,
        ).json()
    except (ApiError, KeyError, TypeError) as exc:
        output.fatal(str(exc))
    _print_upstreams([item])


@upstream_app.command("update")
def upstream_update(
    repository: str = typer.Argument(...),
    kind: str = typer.Argument(...),
    attachment: str = typer.Argument(...),
    priority: int | None = typer.Option(None, "--priority", min=0, max=_MAX_UPSTREAM_PRIORITY),
    min_age_hours: float | None = typer.Option(None, "--min-age-hours", min=0),
    max_age_hours: float | None = typer.Option(None, "--max-age-hours", min=0),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Update priority or age bounds for one attachment."""
    body = {
        key: value
        for key, value in {
            "priority": priority,
            "min_age_hours": min_age_hours,
            "max_age_hours": max_age_hours,
        }.items()
        if value is not None
    }
    if not body:
        output.fatal("Pass at least one field to update.")
    registry_kind = _require_package_kind(kind)
    client = _client(profile)
    try:
        destination = _resolve_repository_entry(repository, profile, kind=registry_kind)
        item = client.patch(
            f"{_upstream_path(destination['repository']['id'], registry_kind)}/{attachment}",
            json=body,
        ).json()
    except (ApiError, KeyError, TypeError) as exc:
        output.fatal(str(exc))
    _print_upstreams([item])


@upstream_app.command("reorder")
def upstream_reorder(
    repository: str = typer.Argument(...),
    kind: str = typer.Argument(...),
    attachments: list[str] = typer.Argument(...),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Replace the complete attachment order atomically."""
    registry_kind = _require_package_kind(kind)
    client = _client(profile)
    try:
        destination = _resolve_repository_entry(repository, profile, kind=registry_kind)
        items = client.put(
            f"{_upstream_path(destination['repository']['id'], registry_kind)}/order",
            json={"attachment_ids": attachments},
        ).json()
    except (ApiError, KeyError, TypeError) as exc:
        output.fatal(str(exc))
    _print_upstreams(items)


@upstream_app.command("remove")
def upstream_remove(
    repository: str = typer.Argument(...),
    kind: str = typer.Argument(...),
    attachment: str = typer.Argument(...),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Remove one upstream attachment."""
    registry_kind = _require_package_kind(kind)
    client = _client(profile)
    try:
        destination = _resolve_repository_entry(repository, profile, kind=registry_kind)
        client.delete(
            f"{_upstream_path(destination['repository']['id'], registry_kind)}/{attachment}"
        )
    except (ApiError, KeyError, TypeError) as exc:
        output.fatal(str(exc))
    output.success(f"Removed upstream '{attachment}' from '{repository}' ({registry_kind}).")


# ── private mirrors and their remote caches ──────────────────────────────────


@remote_app.command("select")
def remote_select(
    mirror: str = typer.Argument(..., help="Official source slug or custom mirror name."),
    custom: bool = typer.Option(False, "--custom", help="Select a customer-defined mirror."),
    kind: str | None = typer.Option(None, "--kind", help="Registry kind if ambiguous."),
    account: str | None = typer.Option(None, "--account", help="Acting account selector."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Select an official or customer-defined private mirror."""
    prefix = "custom-mirror" if custom else "mirror"
    target_select(f"{prefix}:{mirror}", kind=kind, account=account, profile=profile)


@remote_app.command("current")
def remote_current(
    account: str | None = typer.Option(None, "--account", help="Acting account selector."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Show the current package context."""
    target_current(account=account, profile=profile)


@remote_app.command("clear")
def remote_clear(
    account: str | None = typer.Option(None, "--account", help="Acting account selector."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Clear the selected package target."""
    target_clear(account=account, profile=profile)


@remote_app.command("list")
def remote_list(
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(None, "--customer-id"),
    account: str | None = typer.Option(None, "--account"),
    kind: str | None = typer.Option(None, "--kind", "--registry-kind", "-k"),
) -> None:
    """List private mirrors for the selected customer."""
    if kind:
        _require_package_kind(kind)
    client = _client(profile)
    effective_customer_id = _context_customer_id(profile, account) or _customer_id(
        profile, customer_id
    )
    try:
        items = client.get(
            "/v0/remote-repositories",
            params={
                "customer_id": effective_customer_id,
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
        output.info("No private mirrors found.")
        return
    output.table(
        ["Account", "Mirror type", "Publication", "Mirror target", "Registry kind", "Minimum age"],
        [
            [
                str(entry.get("customer", {}).get("account_label", "")),
                str(item.get("source_family") or "unknown"),
                str(
                    item.get("publication_control")
                    or (
                        "externally_controlled"
                        if item.get("source_family") == "official"
                        else "unknown"
                    )
                ),
                (
                    f"mirror:{item.get('official_slug') or item['public_id']}"
                    if item.get("source_family") == "official"
                    else f"custom-mirror:{item.get('remote_name') or item['public_id']}"
                ),
                str(item.get("registry_kind", "")),
                _format_age_hours(item.get("min_age_hours"), missing="No minimum"),
            ]
            for entry in items
            for item in [entry["remote_repository"]]
        ],
    )


@remote_app.command("create")
def remote_create(
    kind: str = typer.Option(..., "--registry-kind", "-k"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(None, "--customer-id"),
    account: str | None = typer.Option(None, "--account"),
) -> None:
    """Initialize a remote cache and its private mirror for a registry kind."""
    _require_package_kind(kind)
    client = _client(profile)
    try:
        item = client.post(
            "/v0/remote-repositories",
            json={
                "customer_id": _context_customer_id(profile, account)
                or _customer_id(profile, customer_id),
                "registry_kind": kind,
            },
        ).json()["remote_repository"]
    except ApiError as exc:
        output.fatal(str(exc))
    remote_id = item["public_id"]
    output.success(f"Initialized {kind} remote cache and private mirror '{remote_id}'.")


@remote_app.command("add")
def remote_add_official(
    source: str = typer.Argument(..., help="Official source slug, such as pypiorg."),
    kind: str | None = typer.Option(None, "--kind", help="Registry kind if ambiguous."),
    min_age_hours: float | None = typer.Option(None, "--min-age-hours", min=0),
    max_age_hours: float | None = typer.Option(None, "--max-age-hours", min=0),
    select: bool = typer.Option(False, "--select", help="Select the mirror after creating it."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    account: str | None = typer.Option(None, "--account"),
) -> None:
    """Initialize a Ravenstash-curated remote cache and private mirror."""
    customer_id = _context_customer_id(profile, account) or _customer_id(profile)
    if kind:
        _require_package_kind(kind)
    client = _client(profile)
    try:
        sources = client.get(
            "/v0/remote-repositories/official-sources",
            params={"customer_id": customer_id},
        ).json()
        matches = [
            item
            for item in sources
            if source in {item.get("remote_repository_public_id"), item.get("official_source_id")}
            and (kind is None or item.get("registry_kind") == kind)
        ]
        if not matches:
            output.fatal(f"Official mirror source '{source}' was not found.")
        if len(matches) > 1:
            output.fatal(f"Official mirror source '{source}' is ambiguous. Pass --kind.")
        selected_source = matches[0]
        payload: dict[str, object] = {
            "customer_id": customer_id,
            "official_source_id": selected_source["official_source_id"],
        }
        if min_age_hours is not None:
            payload["min_age_hours"] = min_age_hours
        if max_age_hours is not None:
            payload["max_age_hours"] = max_age_hours
        entry = client.post(
            "/v0/remote-repositories/official",
            json=payload,
        ).json()
    except (ApiError, KeyError, TypeError) as exc:
        output.fatal(str(exc))
    item = entry["remote_repository"]
    target_name = f"mirror:{item.get('official_slug') or item['public_id']}"
    output.success(f"Added official remote cache with private mirror '{target_name}'.")
    if select:
        target_select(
            target_name,
            kind=str(item["registry_kind"]),
            account=account,
            profile=profile,
        )


@remote_app.command("create-custom")
def remote_create_custom(
    name: str = typer.Argument(..., help="Customer-scoped custom mirror name."),
    kind: str = typer.Option(..., "--kind", help="Registry kind: pypi, npm, or maven."),
    api_url: str = typer.Option(..., "--api-url", help="HTTPS metadata/API origin."),
    artifact_url: str | None = typer.Option(None, "--artifact-url"),
    publication_control: str = typer.Option(
        ...,
        "--publication-control",
        help="Who controls publishing: user-controlled or externally-controlled.",
    ),
    auth_scheme: str = typer.Option("none", "--auth-scheme", help="none, basic, or bearer."),
    username: str | None = typer.Option(None, "--username"),
    secret_env: str | None = typer.Option(
        None,
        "--secret-env",
        help="Environment variable containing the origin secret.",
    ),
    allowed_host: list[str] = typer.Option([], "--allowed-host"),
    min_age_hours: float | None = typer.Option(None, "--min-age-hours", min=0),
    max_age_hours: float | None = typer.Option(None, "--max-age-hours", min=0),
    managed_location: str | None = typer.Option(None, "--managed-location"),
    storage_target: str | None = typer.Option(None, "--storage-target"),
    select: bool = typer.Option(False, "--select", help="Select the mirror after creating it."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    account: str | None = typer.Option(None, "--account"),
) -> None:
    """Create a custom remote cache and private mirror backed by HTTPS."""
    registry_kind = _require_package_kind(kind)
    customer_id = _context_customer_id(profile, account) or _customer_id(profile)
    if auth_scheme not in {"none", "basic", "bearer"}:
        output.fatal("--auth-scheme must be none, basic, or bearer.")
    publication_control_value = publication_control.replace("-", "_")
    if publication_control_value not in {"user_controlled", "externally_controlled"}:
        output.fatal("--publication-control must be user-controlled or externally-controlled.")
    secret = os.environ.get(secret_env) if secret_env else None
    if secret_env and secret is None:
        output.fatal(f"Origin secret environment variable '{secret_env}' is not set.")
    if auth_scheme == "basic" and (not username or secret is None):
        output.fatal("Basic origin authentication requires --username and --secret-env.")
    if auth_scheme == "bearer" and secret is None:
        output.fatal("Bearer origin authentication requires --secret-env.")
    if auth_scheme == "none" and (username or secret_env):
        output.fatal("The none authentication scheme does not accept credentials.")
    if managed_location and storage_target:
        output.fatal("Pass either --managed-location or --storage-target, not both.")
    payload: dict[str, object] = {
        "customer_id": customer_id,
        "registry_kind": registry_kind,
        "remote_name": name,
        "publication_control": publication_control_value,
        "api_base_url": api_url,
        "credential": {
            "auth_scheme": auth_scheme,
            "allowed_hosts": allowed_host,
        },
    }
    credential = payload["credential"]
    assert isinstance(credential, dict)
    if artifact_url is not None:
        payload["artifact_base_url"] = artifact_url
    if username is not None:
        credential["username"] = username
    if secret is not None:
        credential["secret"] = secret
    if min_age_hours is not None:
        payload["min_age_hours"] = min_age_hours
    if max_age_hours is not None:
        payload["max_age_hours"] = max_age_hours
    if managed_location:
        payload.update(
            {
                "storage_mode": "ravenstash_managed",
                "managed_storage_location_key": managed_location,
            }
        )
    elif storage_target:
        payload.update(
            {
                "storage_mode": "customer_target",
                "object_storage_target_id": storage_target,
            }
        )
    try:
        entry = (
            _client(profile)
            .post(
                "/v0/remote-repositories/custom",
                json=payload,
            )
            .json()
        )
    except (ApiError, KeyError, TypeError) as exc:
        output.fatal(str(exc))
    item = entry["remote_repository"]
    target_name = f"custom-mirror:{item.get('remote_name') or item['public_id']}"
    output.success(f"Created custom remote cache with private mirror '{target_name}'.")
    if select:
        target_select(target_name, kind=kind, account=account, profile=profile)


@remote_app.command("show")
def remote_show(
    remote: str = typer.Argument(..., help="Remote cache ID."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    account: str | None = typer.Option(None, "--account"),
    customer_id: str | None = typer.Option(None, "--customer-id", hidden=True),
    kind: str | None = typer.Option(None, "--kind", "--registry-kind", "-k"),
) -> None:
    """Show a private mirror and its backing remote cache."""
    if kind:
        _require_package_kind(kind)
    selected_customer = _context_customer_id(profile, account) or _customer_id(profile, customer_id)
    client = _client(profile)
    try:
        item = client.get(
            f"/v0/remote-repositories/{remote}",
            params={"customer_id": selected_customer, "registry_kind": kind},
        ).json()["remote_repository"]
    except (ApiError, KeyError, TypeError) as exc:
        output.fatal(str(exc))
    output.kv(
        {
            "ID": item["public_id"],
            "Type": item.get("source_family"),
            "Target": (
                f"mirror:{item.get('official_slug') or item['public_id']}"
                if item.get("source_family") == "official"
                else f"custom-mirror:{item.get('remote_name') or item['public_id']}"
            ),
            "Registry kind": item.get("registry_kind"),
            "Owner ID": item.get("customer_id"),
            "Private mirror": "ready",
            "Mirror minimum package age": _format_age_hours(
                item.get("min_age_hours"), missing="No minimum"
            ),
            "Maximum package age": _format_age_hours(
                item.get("max_age_hours"), missing="No maximum"
            ),
        },
        title=f"Private mirror {remote}",
    )


@remote_app.command("set-age")
def remote_set_age(
    remote: str = typer.Argument(..., help="Remote cache ID."),
    min_age_hours: float = typer.Option(..., "--min-age-hours", min=0),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    account: str | None = typer.Option(None, "--account"),
    customer_id: str | None = typer.Option(None, "--customer-id", hidden=True),
    kind: str | None = typer.Option(None, "--kind", "--registry-kind", "-k"),
) -> None:
    """Update the private mirror minimum package age."""
    if kind:
        _require_package_kind(kind)
    selected_customer = _context_customer_id(profile, account) or _customer_id(profile, customer_id)
    client = _client(profile)
    payload = {"min_age_hours": min_age_hours}
    try:
        client.patch(
            f"/v0/remote-repositories/{remote}",
            params={"customer_id": selected_customer, "registry_kind": kind},
            json=payload,
        )
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Updated private mirror minimum package age for '{remote}'.")


@remote_app.command("delete")
def remote_delete(
    remote: str = typer.Argument(..., help="Remote cache ID."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(None, "--customer-id"),
    account: str | None = typer.Option(None, "--account"),
    kind: str | None = typer.Option(None, "--kind", "--registry-kind", "-k"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Delete a remote cache and its private mirror."""
    if kind:
        _require_package_kind(kind)
    if not yes:
        typer.confirm(f"Delete remote cache and private mirror '{remote}'?", abort=True)
    selected_customer = _context_customer_id(profile, account) or _customer_id(profile, customer_id)
    params = {"customer_id": selected_customer, "registry_kind": kind}
    client = _client(profile)
    try:
        client.delete(f"/v0/remote-repositories/{remote}", params=params)
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Deleted remote cache and private mirror '{remote}'.")


# ── package ──────────────────────────────────────────────────────────────────


@package_app.command("list")
def package_list(
    repo: str = typer.Option(..., "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    kind: str = typer.Option(
        ...,
        "--registry-kind",
        "-k",
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
    context = _registry_context("pypi", repo, profile, customer_id, allow_official_default=True)
    output.value(
        _ROUTER.pypi_index_url(
            context.read_base_url, context.workspace_reference, context.repository_reference
        ),
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
    context = _registry_context("pypi", repo, profile, customer_id, require_private=True)
    assert context.push_base_url is not None
    output.value(
        _ROUTER.pypi_upload_url(
            context.push_base_url, context.workspace_reference, context.repository_reference
        ),
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
    context = _registry_context("pypi", repo, profile, customer_id, allow_official_default=True)
    index_url = _ROUTER.pypi_index_url(
        context.read_base_url, context.workspace_reference, context.repository_reference
    )
    with tempfile.TemporaryDirectory(prefix="rvs-pip-") as temp_dir:
        env = {**os.environ, "PIP_INDEX_URL": index_url}
        if context.token:
            native_runner.inject_pip_auth(
                env,
                [index_url],
                context.token,
                Path(temp_dir),
                profile=context.profile_name,
                customer_id=context.customer_id,
            )
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
    context = _registry_context("pypi", repo, profile, customer_id, require_private=True)
    assert context.push_base_url is not None
    files = list(dist_dir.glob("*.whl")) + list(dist_dir.glob("*.tar.gz"))
    if not files:
        output.fatal(f"No .whl or .tar.gz files found in {dist_dir}")
    results = pypi_reg.publish(
        upload_url=_ROUTER.pypi_upload_url(
            context.push_base_url,
            context.workspace_reference,
            context.repository_reference,
        ),
        token=context.token,
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
    context = _registry_context("pypi", repo, profile, customer_id, allow_official_default=True)
    index_url = _ROUTER.pypi_index_url(
        context.read_base_url, context.workspace_reference, context.repository_reference
    )
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
    context = _registry_context("npm", repo, profile, customer_id, allow_official_default=True)
    output.value(
        _ROUTER.npm_registry_url(
            context.read_base_url, context.workspace_reference, context.repository_reference
        ),
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
    context = _registry_context("npm", repo, profile, customer_id, allow_official_default=True)
    registry_url = _ROUTER.npm_registry_url(
        context.read_base_url,
        context.workspace_reference,
        context.repository_reference,
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
    context = _registry_context("npm", repo, profile, customer_id, allow_official_default=True)
    registry_url = _ROUTER.npm_registry_url(
        context.read_base_url,
        context.workspace_reference,
        context.repository_reference,
    )
    env = {**os.environ}
    if context.token:
        env[f"NPM_CONFIG_{_npm_auth_token_key(registry_url)}"] = context.token
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
    context = _registry_context("npm", repo, profile, customer_id, require_private=True)
    assert context.push_base_url is not None
    results = npm_reg.publish(
        registry_url=_ROUTER.npm_upload_registry_url(
            context.push_base_url,
            context.workspace_reference,
            context.repository_reference,
        ),
        token=context.token,
        package_dir=package_dir,
        download_registry_url=_ROUTER.npm_registry_url(
            context.read_base_url,
            context.workspace_reference,
            context.repository_reference,
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
    context = _registry_context("maven", repo, profile, customer_id, allow_official_default=True)
    output.value(
        _ROUTER.maven_repo_url(
            context.read_base_url,
            context.workspace_reference,
            context.repository_reference,
        ),
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
    context = _registry_context("maven", repo, profile, customer_id, allow_official_default=True)
    output.value(
        _settings_xml(
            _ROUTER.maven_repo_url(
                context.read_base_url,
                context.workspace_reference,
                context.repository_reference,
            )
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
    context = _registry_context("maven", repo, profile, customer_id, allow_official_default=True)
    repo_url = _ROUTER.maven_repo_url(
        context.read_base_url, context.workspace_reference, context.repository_reference
    )
    settings_xml = maven_reg._build_settings_xml(repo_url, context.token)
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
    context = _registry_context("maven", repo, profile, customer_id, require_private=True)
    assert context.push_base_url is not None
    results = maven_reg.publish(
        upload_url=_ROUTER.maven_upload_url(
            context.push_base_url,
            context.workspace_reference,
            context.repository_reference,
        ),
        token=context.token,
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
