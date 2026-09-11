"""`rvs art` command group."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Literal, cast

import click
import typer

from .. import auth as auth_mod
from .. import config as cfg_mod
from .. import output
from ..account.commands import display_name as account_display_name
from ..account.commands import ensure_active_account, resolve_account
from ..client import ApiClient, ApiError
from ..devapi import collection_items
from ..devapi import remote_cache as remote_cache_payload
from ..native import runner as native_runner
from ..publishing import confirm_context, maven_artifact, npm_artifact, pypi_artifacts
from ..runtime import tools
from ..subprocesses import child_environment
from .auth_commands import app as native_auth_app
from .registries import maven as maven_reg
from .registries import npm as npm_reg
from .registries import pypi as pypi_reg
from .routing import CanonicalRouter, npm_auth_token_key
from .targets import (
    RegistryContext,
    parse_target,
    registry_context,
    resolve_repository_entry,
    resolve_target,
)


app = typer.Typer(
    name="artifacts",
    help="Manage repositories for packages, container images, and Helm charts.",
    no_args_is_help=True,
)

repo_app = typer.Typer(help="Manage Ravenstash repositories.", no_args_is_help=True)
upstream_app = typer.Typer(help="Manage the package sources used by a repository.", no_args_is_help=True)
remote_app = typer.Typer(
    help="Manage private mirrors.", no_args_is_help=True
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
app.add_typer(native_auth_app, name="auth")

_KINDS = ("pypi", "npm", "maven", "container", "helm")
_PACKAGE_KINDS = ("pypi", "npm", "maven")
_MAX_UPSTREAM_PRIORITY = 3
_ROUTER = CanonicalRouter()
_REPOSITORY_NAME_HELP = "Repository name or namespace/repository."


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
        help="Repository or mirror for this command: namespace/repository, mirror:<source>, or custom-mirror:<name>.",
    ),
    account: str | None = typer.Option(
        None,
        "--account",
        help="Username or organization handle for this command.",
    ),
    kind: str | None = typer.Option(
        None, "--kind", help="Package format when it cannot be determined automatically."
    ),
    profile: str | None = typer.Option(None, "--profile", help="Local profile for this command."),
    scope: Literal["self", "public"] = typer.Option(
        "self", "--scope", hidden=True
    ),
    public: bool = typer.Option(False, "--public", hidden=True),
) -> None:
    """Choose repositories or mirrors and run package commands."""
    if public or scope == "public":
        output.fatal("PublicCatalogUnavailable: the public package catalog is not available yet.")
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
    return ApiClient.from_profile(profile or _root_package_options().get("profile"))


def _customer_id(profile: str | None, explicit_customer_id: str | None = None) -> str:
    if explicit_customer_id:
        return explicit_customer_id
    options = _root_package_options()
    profile = profile or options.get("profile")
    if options.get("account"):
        return str(resolve_account(cast("str", options["account"]), profile)["customer_id"])
    profile_name, _ = _profile(profile)
    customer_id = cfg_mod.current_customer_id(profile_name)
    if not customer_id:
        output.fatal("No account is selected. Run `rvs account use USERNAME_OR_HANDLE`.")
    return customer_id


def _context_customer_id(profile: str | None, account: str | None) -> str | None:
    if account is None:
        return None
    return str(resolve_account(account, profile)["customer_id"])


@app.command("select")
def target_select(
    target: str = typer.Argument(
        ...,
        help="namespace/repository, mirror:<source>, or custom-mirror:<name>.",
    ),
    kind: str | None = typer.Option(None, "--kind", help="Package format if needed."),
    account: str | None = typer.Option(None, "--account", help="Username or organization handle."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Choose the repository or mirror used when --target is omitted."""
    customer_id = _context_customer_id(profile, account)
    profile_name, selected_account = ensure_active_account(profile, customer_id)
    _, _, selected = resolve_target(
        target,
        profile=profile_name,
        customer_id=selected_account.customer_id,
        kind=kind,
    )
    try:
        cfg_mod.set_selected_artifact_target(
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
    account: str | None = typer.Option(None, "--account", help="Username or organization handle."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Show the current profile, account, and repository or mirror."""
    customer_id = _context_customer_id(profile, account)
    profile_name, selected_account = ensure_active_account(profile, customer_id)
    selected = cfg_mod.selected_artifact_target(profile_name, selected_account.customer_id)
    output.kv(
        {
            "Profile": profile_name,
            "Account": account_display_name(selected_account),
            "Repository or mirror": selected.display_selector if selected else "none",
            "Type": selected.target_type if selected else "none",
            "Owner ID": selected.customer_id if selected else "none",
            "Package format": selected.registry_kind or "determined by command"
            if selected
            else "none",
        },
        title="Current package selection",
    )


@app.command("clear")
def target_clear(
    account: str | None = typer.Option(None, "--account", help="Username or organization handle."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Clear the selected repository or mirror without signing out."""
    customer_id = _context_customer_id(profile, account)
    profile_name, selected_account = ensure_active_account(profile, customer_id)
    try:
        cfg_mod.set_selected_artifact_target(
            None,
            profile=profile_name,
            customer_id=selected_account.customer_id,
        )
    except ValueError as exc:
        output.fatal(str(exc))
    output.success(f"Cleared the repository or mirror for {account_display_name(selected_account)}.")


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
    """Install from the named, selected, or default repository or mirror."""
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
        selected = cfg_mod.selected_artifact_target(profile_name, account.customer_id)
        kind = selected.registry_kind if selected is not None else None
    kind = kind or _project_package_kind()
    if kind not in _PACKAGE_KINDS:
        output.fatal("Cannot determine the package format. Pass --kind pypi, npm, or maven.")
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
        output.fatal(f"Unknown package format '{kind}'. Use: pypi, npm, maven, container, helm")
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
    namespace_selector, repository_name = value.split("/", 1)
    namespace_selector = namespace_selector.strip()
    repository_name = repository_name.strip().strip("/")
    if not namespace_selector or not repository_name or "/" in repository_name:
        output.fatal("Repository must be <repository-name> or <namespace>/<repository-name>.")
    return namespace_selector, repository_name


def _repository_name_from_response(repo: dict, fallback_repository_name: str = "") -> str:
    return (
        repo.get("repo_name")
        or repo.get("name")
        or repo.get("repository_name")
        or repo.get("id")
        or fallback_repository_name
    )


def _repo_ref_from_response(repo: dict, fallback_repository_name: str) -> str:
    namespace_ref = repo.get("namespace_unique_ref")
    repository_ref = repo.get("repository_unique_ref")
    if namespace_ref and repository_ref:
        return f"{namespace_ref}/{repository_ref}"
    return _repository_name_from_response(repo, fallback_repository_name)


def _token(profile: str | None) -> str | None:
    return auth_mod.get_token(_profile_name(profile))


def _registry_profile(profile: str | None) -> cfg_mod.ProfileConfig:
    _, p = _profile(profile)
    return p


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
    operations: tuple[Literal["download", "upload"], ...] = ("download",),
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
        operations=operations,
    )


def _resolve_repository_entry(
    repo: str,
    profile: str | None,
    *,
    kind: str | None = None,
    customer_id: str | None = None,
) -> dict:
    candidate = repo.strip().strip("/")
    if not candidate:
        output.fatal("Repository selector cannot be empty.")
    if "/" in candidate or ":" in candidate:
        spec = parse_target(candidate)
        if spec.target_type != "repository":
            output.fatal("Repository commands require a repository target.")
        selector = spec.selector
    else:
        # Repository-management commands retain the convenient unique-name/ref
        # lookup. Saved artifact targets still require the complete namespace pair.
        selector = candidate
    options = _root_package_options()
    profile = profile or options.get("profile")
    try:
        return resolve_repository_entry(
            _client(profile), selector, _customer_id(profile, customer_id), kind
        )
    except ApiError as exc:
        output.fatal(str(exc))


def _resolved_repository_unique_ref(
    repo: str,
    profile: str | None,
    *,
    kind: str,
) -> str:
    return _resolve_repository_entry(
        repo,
        profile,
        kind=kind,
    )["repository"]["repository_unique_ref"]


# ── repo ─────────────────────────────────────────────────────────────────────


@repo_app.command("list")
def repo_list(
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(None, "--customer-id", help="Account ID.", hidden=True),
    kind: str | None = typer.Option(
        None,
        "--registry-kind",
        "-k",
        help="Package format: pypi | npm | maven | container | helm.",
    ),
) -> None:
    """List repositories in the selected account's namespaces."""
    if kind:
        _require_kind(kind)
    client = _client(profile)
    params = {
        key: value
        for key, value in {
            "customer_id": _customer_id(profile, customer_id),
            "registry_kind": kind,
        }.items()
        if value is not None
    }
    try:
        data = client.get(
            "/repositories",
            params=params,
        ).json()
    except ApiError as exc:
        output.fatal(str(exc))

    entries = data if isinstance(data, list) else data.get("items", [])
    items = [entry["repository"] for entry in entries]
    if not items:
        output.info("No package repositories found.")
        return

    output.table(
        ["Account", "Namespace", "Repository", "Repository ID", "Package formats"],
        [
            [
                entry["customer"]["account_label"],
                entry["repository"]["namespace_name"],
                _repository_name_from_response(item),
                (f"{item['namespace_unique_ref']}/{item['repository_unique_ref']}"),
                ", ".join(item.get("registry_kinds", [])),
            ]
            for entry, item in zip(entries, items, strict=True)
        ],
    )


@repo_app.command("create")
def repo_create(
    name: str = typer.Argument(..., help="Repository name or namespace/repository."),
    kind: list[str] = typer.Option(
        ...,
        "--registry-kind",
        "-k",
        help="Package format to enable; repeat to enable more than one.",
    ),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(
        None, "--customer-id", help="Owner account ID.", hidden=True
    ),
    set_default: bool = typer.Option(
        False, "--default", help="Set as default for each selected package format."
    ),
) -> None:
    """Create a package repository."""
    if name.startswith(("internal:", "global:", "@")):
        output.fatal("Use namespace/repository without a realm prefix or @ notation.")
    namespace_selector, repository_name = _split_repo_ref(name)
    kinds: list[cfg_mod.RegistryKind] = list(dict.fromkeys(_require_kind(value) for value in kind))
    client = _client(profile)
    try:
        selected_customer_id = _customer_id(profile, customer_id)
        namespaces_payload = client.get(
            "/namespaces", params={"customer_id": selected_customer_id}
        ).json()
        namespaces = collection_items(namespaces_payload)
        matches = [
            entry
            for entry in namespaces
            if entry["customer"]["customer_id"] == selected_customer_id
            and (
                (
                    entry["namespace"]["is_default"]
                    and entry["namespace"]["namespace_realm"] == "internal"
                )
                if namespace_selector is None
                else (
                    entry["namespace"]["namespace_unique_ref"] == namespace_selector
                    or entry["namespace"]["namespace_name"].casefold()
                    == namespace_selector.casefold()
                )
            )
        ]
        if len(matches) != 1:
            output.fatal(
                "Select an accessible namespace with namespace/repository. "
                "If this account has no namespace, finish onboarding in the webapp."
            )
        selected_namespace = matches[0]
        payload = {
            "customer_id": selected_namespace["customer"]["customer_id"],
            "namespace_unique_ref": selected_namespace["namespace"]["namespace_unique_ref"],
            "repository_name": repository_name,
            "registry_kinds": kinds,
        }
        entry = client.post("/repositories", json=payload).json()
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
            "Namespace": item["namespace_name"],
            "Namespace ID": item["namespace_unique_ref"],
            "Repository ID": item["repository_unique_ref"],
            "Package formats": ", ".join(item.get("registry_kinds", [])),
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
        client.delete(f"/repositories/{entry['repository']['repository_unique_ref']}")
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
            f"/repositories/{entry['repository']['repository_unique_ref']}",
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
        help="Package format: pypi | npm | maven | container | helm",
        metavar="FORMAT",
    ),
    repo: str = typer.Argument(..., help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Set the default repository for a package format."""
    registry_kind = _require_kind(kind)
    profile_name = _profile_name(profile)
    entry = _resolve_repository_entry(repo, profile, kind=kind)
    repository = entry["repository"]
    stable = f"{repository['namespace_unique_ref']}/{repository['repository_unique_ref']}"
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


def _upstream_path(repository_unique_ref: str, registry_kind: str) -> str:
    return f"/repositories/{repository_unique_ref}/lanes/{registry_kind}/upstreams"


def _upstream_revision(entry: dict, registry_kind: str) -> int:
    lanes = entry["repository"]["lanes"]
    lane = next(item for item in lanes if item["registry_kind"] == registry_kind)
    return int(lane["upstream_config_revision"])


def _print_upstreams(items: list[dict]) -> None:
    output.table(
        ["ID", "Priority", "Type", "Source", "Minimum age", "Maximum age"],
        [
            [
                str(item.get("attachment_id") or item.get("id", "")),
                str(item.get("priority", "")),
                str(item.get("source_type", "")),
                (
                    f"{item.get('source_namespace_name')}/{item.get('display_name') or item.get('source_repository_name')}"
                    if item.get("source_namespace_name")
                    else str(item.get("display_name") or item.get("source_repository_name", ""))
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
    """List the package sources used by one repository format."""
    registry_kind = _require_package_kind(kind)
    client = _client(profile)
    try:
        entry = _resolve_repository_entry(repository, profile, kind=registry_kind)
        payload = client.get(
            _upstream_path(entry["repository"]["repository_unique_ref"], registry_kind)
        ).json()
        items = collection_items(payload)
    except (ApiError, KeyError, TypeError) as exc:
        output.fatal(str(exc))
    _print_upstreams(items)


@upstream_app.command("add")
def upstream_add(
    repository: str = typer.Argument(...),
    kind: str = typer.Argument(...),
    private_repository: str | None = typer.Option(None, "--private-repository"),
    mirror: str | None = typer.Option(None, "--mirror", help="Private mirror ID."),
    remote_cache: str | None = typer.Option(None, "--remote-cache", hidden=True),
    priority: int | None = typer.Option(None, "--priority", min=0, max=_MAX_UPSTREAM_PRIORITY),
    min_age_hours: float | None = typer.Option(None, "--min-age-hours", min=0),
    max_age_hours: float | None = typer.Option(None, "--max-age-hours", min=0),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Add a private repository or mirror as a package source."""
    if mirror is not None and remote_cache is not None:
        output.fatal("Pass --mirror only once.")
    selected_mirror = mirror or remote_cache
    if (private_repository is None) == (selected_mirror is None):
        output.fatal("Pass exactly one of --private-repository or --mirror.")
    registry_kind = _require_package_kind(kind)
    client = _client(profile)
    try:
        destination = _resolve_repository_entry(repository, profile, kind=registry_kind)
        if private_repository is not None:
            source = _resolve_repository_entry(private_repository, profile, kind=registry_kind)
            source_type = "private"
            source_identity = {
                "source_repository_unique_ref": source["repository"]["repository_unique_ref"]
            }
        else:
            remote_entry = client.get(
                f"/remote-caches/{selected_mirror}",
                params={"registry_kind": registry_kind},
            ).json()
            source_type = "remote"
            remote_payload = remote_cache_payload(remote_entry)
            source_identity = {
                "remote_cache_ref": remote_payload.get("remote_cache_ref")
                or remote_payload.get("unique_ref")
                or selected_mirror
            }
        if priority is None:
            current_payload = client.get(
                _upstream_path(destination["repository"]["repository_unique_ref"], registry_kind)
            ).json()
            effective_priority = len(collection_items(current_payload))
        else:
            effective_priority = priority
        body = {
            "source_type": source_type,
            **source_identity,
            "priority": effective_priority,
            "expected_revision": _upstream_revision(destination, registry_kind),
            "max_age_hours": max_age_hours,
        }
        if min_age_hours is not None:
            body["min_age_hours"] = min_age_hours
        elif source_type == "private":
            body["min_age_hours"] = 0.0
        item = client.post(
            _upstream_path(destination["repository"]["repository_unique_ref"], registry_kind),
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
    """Change the order or package-age settings for one source."""
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
        body["expected_revision"] = _upstream_revision(destination, registry_kind)
        item = client.patch(
            f"{_upstream_path(destination['repository']['repository_unique_ref'], registry_kind)}/{attachment}",
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
    """Set the complete package-source order."""
    registry_kind = _require_package_kind(kind)
    client = _client(profile)
    try:
        destination = _resolve_repository_entry(repository, profile, kind=registry_kind)
        payload = client.put(
            f"{_upstream_path(destination['repository']['repository_unique_ref'], registry_kind)}/order",
            json={
                "attachment_ids": attachments,
                "expected_revision": _upstream_revision(destination, registry_kind),
            },
        ).json()
        items = collection_items(payload)
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
    """Remove one package source."""
    registry_kind = _require_package_kind(kind)
    client = _client(profile)
    try:
        destination = _resolve_repository_entry(repository, profile, kind=registry_kind)
        client.delete(
            f"{_upstream_path(destination['repository']['repository_unique_ref'], registry_kind)}/{attachment}",
            params={"expected_revision": _upstream_revision(destination, registry_kind)},
        )
    except (ApiError, KeyError, TypeError) as exc:
        output.fatal(str(exc))
    output.success(f"Removed upstream '{attachment}' from '{repository}' ({registry_kind}).")


# ── private mirrors and their remote caches ──────────────────────────────────


@remote_app.command("select")
def remote_select(
    mirror: str = typer.Argument(..., help="Official source slug or custom mirror name."),
    custom: bool = typer.Option(False, "--custom", help="Select a custom mirror."),
    kind: str | None = typer.Option(None, "--kind", help="Package format if needed."),
    account: str | None = typer.Option(None, "--account", help="Username or organization handle."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Select a Ravenstash-provided or custom private mirror."""
    prefix = "custom-mirror" if custom else "mirror"
    target_select(f"{prefix}:{mirror}", kind=kind, account=account, profile=profile)


@remote_app.command("current")
def remote_current(
    account: str | None = typer.Option(
        None, "--account", help="Username or organization handle."
    ),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Show the selected repository or mirror."""
    target_current(account=account, profile=profile)


@remote_app.command("clear")
def remote_clear(
    account: str | None = typer.Option(
        None, "--account", help="Username or organization handle."
    ),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Clear the selected repository or mirror."""
    target_clear(account=account, profile=profile)


@remote_app.command("list")
def remote_list(
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(None, "--customer-id", hidden=True),
    account: str | None = typer.Option(None, "--account"),
    kind: str | None = typer.Option(None, "--kind", "--registry-kind", "-k"),
) -> None:
    """List private mirrors for the selected account."""
    if kind:
        _require_package_kind(kind)
    client = _client(profile)
    effective_customer_id = _context_customer_id(profile, account) or _customer_id(
        profile, customer_id
    )
    try:
        payload = client.get(
            "/remote-caches",
            params={
                "customer_id": effective_customer_id,
                "registry_kind": kind,
            },
        ).json()
        items = collection_items(payload)
    except ApiError as exc:
        output.fatal(str(exc))
    if kind:
        items = [
            entry for entry in items if remote_cache_payload(entry).get("registry_kind") == kind
        ]
    if not items:
        output.info("No private mirrors found.")
        return
    output.table(
        ["Account", "Source", "Publication", "Mirror", "Package format", "Minimum age"],
        [
            [
                str(entry.get("customer", {}).get("account_label", "")),
                str(item.get("source_type") or "unknown"),
                str(
                    item.get("publication_control")
                    or (
                        "externally_controlled"
                        if item.get("source_type") == "official"
                        else "unknown"
                    )
                ),
                (
                    f"mirror:{item.get('official_slug') or item['remote_cache_ref']}"
                    if item.get("source_type") == "official"
                    else f"custom-mirror:{item.get('remote_name') or item['remote_cache_ref']}"
                ),
                str(item.get("registry_kind", "")),
                _format_age_hours(item.get("min_age_hours"), missing="No minimum"),
            ]
            for entry in items
            for item in [remote_cache_payload(entry)]
        ],
    )


@remote_app.command("create")
def remote_create(
    kind: str = typer.Option(..., "--registry-kind", "-k"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(None, "--customer-id", hidden=True),
    account: str | None = typer.Option(None, "--account"),
) -> None:
    """Create the default private mirror for a package format."""
    _require_package_kind(kind)
    client = _client(profile)
    try:
        entry = client.post(
            "/remote-caches",
            json={
                "customer_id": _context_customer_id(profile, account)
                or _customer_id(profile, customer_id),
                "registry_kind": kind,
            },
        ).json()
        item = remote_cache_payload(entry)
    except ApiError as exc:
        output.fatal(str(exc))
    remote_id = item["remote_cache_ref"]
    output.success(f"Created {kind} private mirror '{remote_id}'.")


@remote_app.command("add")
def remote_add_official(
    source: str = typer.Argument(..., help="Official source slug, such as pypiorg."),
    kind: str | None = typer.Option(None, "--kind", help="Package format if needed."),
    min_age_hours: float | None = typer.Option(None, "--min-age-hours", min=0),
    max_age_hours: float | None = typer.Option(None, "--max-age-hours", min=0),
    select: bool = typer.Option(False, "--select", help="Select the mirror after creating it."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    account: str | None = typer.Option(None, "--account"),
) -> None:
    """Add a Ravenstash-provided private mirror."""
    customer_id = _context_customer_id(profile, account) or _customer_id(profile)
    if kind:
        _require_package_kind(kind)
    client = _client(profile)
    try:
        sources_payload = client.get(
            "/remote-caches/official-sources",
            params={"customer_id": customer_id},
        ).json()
        sources = collection_items(sources_payload)
        matches = [
            item
            for item in sources
            if source == item.get("source_ref")
            and (kind is None or item.get("registry_kind") == kind)
        ]
        if not matches:
            output.fatal(f"Official mirror source '{source}' was not found.")
        if len(matches) > 1:
            output.fatal(f"Official mirror source '{source}' is ambiguous. Pass --kind.")
        selected_source = matches[0]
        payload: dict[str, object] = {
            "customer_id": customer_id,
            "source_ref": selected_source["source_ref"],
        }
        if min_age_hours is not None:
            payload["min_age_hours"] = min_age_hours
        if max_age_hours is not None:
            payload["max_age_hours"] = max_age_hours
        entry = client.post(
            "/remote-caches/official",
            json=payload,
        ).json()
    except (ApiError, KeyError, TypeError) as exc:
        output.fatal(str(exc))
    item = remote_cache_payload(entry)
    target_name = f"mirror:{item.get('official_slug') or item['remote_cache_ref']}"
    output.success(f"Added private mirror '{target_name}'.")
    if select:
        target_select(
            target_name,
            kind=str(item["registry_kind"]),
            account=account,
            profile=profile,
        )


@remote_app.command("create-custom")
def remote_create_custom(
    name: str = typer.Argument(..., help="Name for the custom mirror."),
    kind: str = typer.Option(..., "--kind", help="Package format: pypi, npm, or maven."),
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
    """Create a private mirror for a custom HTTPS package source."""
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
                "/remote-caches/custom",
                json=payload,
            )
            .json()
        )
    except (ApiError, KeyError, TypeError) as exc:
        output.fatal(str(exc))
    item = remote_cache_payload(entry)
    target_name = f"custom-mirror:{item.get('remote_name') or item['remote_cache_ref']}"
    output.success(f"Created private mirror '{target_name}'.")
    if select:
        target_select(target_name, kind=kind, account=account, profile=profile)


@remote_app.command("show")
def remote_show(
    remote: str = typer.Argument(..., help="Mirror ID."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    account: str | None = typer.Option(None, "--account"),
    customer_id: str | None = typer.Option(None, "--customer-id", hidden=True),
    kind: str | None = typer.Option(None, "--kind", "--registry-kind", "-k"),
) -> None:
    """Show a private mirror."""
    if kind:
        _require_package_kind(kind)
    selected_customer = _context_customer_id(profile, account) or _customer_id(profile, customer_id)
    client = _client(profile)
    try:
        entry = client.get(
            f"/remote-caches/{remote}",
            params={"customer_id": selected_customer, "registry_kind": kind},
        ).json()
        item = remote_cache_payload(entry)
    except (ApiError, KeyError, TypeError) as exc:
        output.fatal(str(exc))
    output.kv(
        {
            "ID": item["remote_cache_ref"],
            "Type": item.get("source_type"),
            "Target": (
                f"mirror:{item.get('official_slug') or item['remote_cache_ref']}"
                if item.get("source_type") == "official"
                else f"custom-mirror:{item.get('remote_name') or item['remote_cache_ref']}"
            ),
            "Package format": item.get("registry_kind"),
            "Account ID": item.get("customer_id"),
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
    remote: str = typer.Argument(..., help="Mirror ID."),
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
            f"/remote-caches/{remote}",
            params={"customer_id": selected_customer, "registry_kind": kind},
            json=payload,
        )
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Updated private mirror minimum package age for '{remote}'.")


@remote_app.command("delete")
def remote_delete(
    remote: str = typer.Argument(..., help="Mirror ID."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(None, "--customer-id", hidden=True),
    account: str | None = typer.Option(None, "--account"),
    kind: str | None = typer.Option(None, "--kind", "--registry-kind", "-k"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Delete a private mirror."""
    if kind:
        _require_package_kind(kind)
    if not yes:
        typer.confirm(f"Delete private mirror '{remote}'?", abort=True)
    selected_customer = _context_customer_id(profile, account) or _customer_id(profile, customer_id)
    params = {"customer_id": selected_customer, "registry_kind": kind}
    client = _client(profile)
    try:
        client.delete(f"/remote-caches/{remote}", params=params)
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Deleted private mirror '{remote}'.")


# ── package ──────────────────────────────────────────────────────────────────


@package_app.command("list")
def package_list(
    repo: str = typer.Option(..., "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    kind: str = typer.Option(
        ...,
        "--registry-kind",
        "-k",
        help="Package format: pypi | npm | maven.",
    ),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """List packages hosted in a package repository."""
    registry_kind = _require_package_kind(kind)
    client = _client(profile)
    try:
        repository_unique_ref = _resolved_repository_unique_ref(repo, profile, kind=registry_kind)
        data = client.get(
            f"/repositories/{repository_unique_ref}/lanes/{registry_kind}/packages"
        ).json()
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
        repository_unique_ref = _resolved_repository_unique_ref(repo, profile, kind=registry_kind)
        item = client.get(
            f"/repositories/{repository_unique_ref}/lanes/{registry_kind}/packages/detail",
            params={"package_name": name},
        ).json()
    except ApiError as exc:
        output.fatal(str(exc))

    output.kv(
        {
            "Repository": item.get("repository_unique_ref", repo),
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
        repository_unique_ref = _resolved_repository_unique_ref(repo, profile, kind=registry_kind)
        client.delete(
            f"/repositories/{repository_unique_ref}/lanes/{registry_kind}/packages/detail",
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
        repository_unique_ref = _resolved_repository_unique_ref(repo, profile, kind=registry_kind)
        client.delete(
            f"/repositories/{repository_unique_ref}/lanes/{registry_kind}/packages/version",
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
        repository_unique_ref = _resolved_repository_unique_ref(repo, profile, kind=registry_kind)
        client.post(
            f"/repositories/{repository_unique_ref}/lanes/{registry_kind}/packages/version/yank",
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
        None, "--customer-id", help="Account ID for advanced use.", hidden=True
    ),
) -> None:
    """Print the private PyPI simple-index URL."""
    context = _registry_context("pypi", repo, profile, customer_id, allow_official_default=True)
    output.value(
        _ROUTER.pypi_index_url(
            context.read_base_url, context.namespace_reference, context.repository_reference
        ),
        key="index_url",
    )


@pypi_app.command("upload-url")
def pypi_upload_url(
    repo: str | None = typer.Option(None, "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(
        None, "--customer-id", help="Account ID for advanced use.", hidden=True
    ),
) -> None:
    """Print the private PyPI upload URL."""
    context = _registry_context(
        "pypi",
        repo,
        profile,
        customer_id,
        require_private=True,
        operations=("upload",),
    )
    assert context.push_base_url is not None
    output.value(
        _ROUTER.pypi_upload_url(
            context.push_base_url, context.namespace_reference, context.repository_reference
        ),
        key="upload_url",
    )


@pypi_app.command("install")
def pypi_install(
    packages: list[str] = typer.Argument(..., help="Package specs to install."),
    repo: str | None = typer.Option(None, "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(
        None, "--customer-id", help="Account ID for advanced use.", hidden=True
    ),
) -> None:
    """Install Python packages using pip with Ravenstash credentials injected."""
    context = _registry_context("pypi", repo, profile, customer_id, allow_official_default=True)
    index_url = _ROUTER.pypi_index_url(
        context.read_base_url, context.namespace_reference, context.repository_reference
    )
    with tempfile.TemporaryDirectory(prefix="rvs-pip-") as temp_dir:
        env = child_environment({"PIP_INDEX_URL": index_url})
        if context.token:
            native_runner.inject_pip_auth(
                env,
                [index_url],
                context.token,
                Path(temp_dir),
            )
        else:
            output.warn("No credentials found; running pip without private repository auth.")

        cmd = [*tools.pip_cmd(), "install", *packages]
        subprocess.run(cmd, env=env, check=True)


@pypi_app.command("publish")
def pypi_publish(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip publishing confirmation."),
    dist_dir: Path = typer.Argument(Path("dist"), help="Directory with wheels/sdists."),
    repo: str | None = typer.Option(None, "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(
        None, "--customer-id", help="Account ID for advanced use.", hidden=True
    ),
) -> None:
    """Upload wheel and sdist files to a PyPI package repository."""
    context = _registry_context(
        "pypi",
        repo,
        profile,
        customer_id,
        require_private=True,
        operations=("upload",),
    )
    assert context.push_base_url is not None
    files = list(dist_dir.glob("*.whl")) + list(dist_dir.glob("*.tar.gz"))
    if not files:
        output.fatal(f"No .whl or .tar.gz files found in {dist_dir}")
    confirm_context(context, pypi_artifacts(files), yes=yes)
    results = pypi_reg.publish(
        upload_url=_ROUTER.pypi_upload_url(
            context.push_base_url,
            context.namespace_reference,
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
        None, "--customer-id", help="Account ID for advanced use.", hidden=True
    ),
) -> None:
    """Print pip configuration for the private PyPI repository."""
    context = _registry_context("pypi", repo, profile, customer_id, allow_official_default=True)
    index_url = _ROUTER.pypi_index_url(
        context.read_base_url, context.namespace_reference, context.repository_reference
    )
    output.value(f"[global]\nindex-url = {index_url}", key="configuration")


# ── npm ──────────────────────────────────────────────────────────────────────


@npm_app.command("registry-url")
def npm_registry_url(
    repo: str | None = typer.Option(None, "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(
        None, "--customer-id", help="Account ID for advanced use.", hidden=True
    ),
) -> None:
    """Print the private npm registry URL."""
    context = _registry_context("npm", repo, profile, customer_id, allow_official_default=True)
    output.value(
        _ROUTER.npm_registry_url(
            context.read_base_url, context.namespace_reference, context.repository_reference
        ),
        key="registry_url",
    )


@npm_app.command("npmrc")
def npmrc(
    repo: str | None = typer.Option(None, "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(
        None, "--customer-id", help="Account ID for advanced use.", hidden=True
    ),
) -> None:
    """Print an .npmrc snippet for the private npm repository."""
    context = _registry_context("npm", repo, profile, customer_id, allow_official_default=True)
    registry_url = _ROUTER.npm_registry_url(
        context.read_base_url,
        context.namespace_reference,
        context.repository_reference,
    )
    auth_key = npm_auth_token_key(registry_url)
    output.value(
        "# Generate a short-lived token with rvs artifacts auth print-token.\n"
        f"registry={registry_url}\n{auth_key}=${{RVS_ARTIFACTS_TOKEN}}",
        key="configuration",
    )


@npm_app.command("install")
def npm_install(
    packages: list[str] = typer.Argument(..., help="Package specs to install."),
    repo: str | None = typer.Option(None, "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(
        None, "--customer-id", help="Account ID for advanced use.", hidden=True
    ),
) -> None:
    """Install npm packages with Ravenstash credentials injected."""
    context = _registry_context("npm", repo, profile, customer_id, allow_official_default=True)
    registry_url = _ROUTER.npm_registry_url(
        context.read_base_url,
        context.namespace_reference,
        context.repository_reference,
    )
    env = child_environment()
    if context.token:
        env[f"NPM_CONFIG_{npm_auth_token_key(registry_url)}"] = context.token
    else:
        output.warn("No credentials found; running npm without private repository auth.")
    subprocess.run(
        [tools.npm(), "install", "--registry", registry_url, *packages], env=env, check=True
    )


@npm_app.command("publish")
def npm_publish(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip publishing confirmation."),
    package_dir: Path = typer.Argument(Path("."), help="Directory containing package.json."),
    repo: str | None = typer.Option(None, "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(
        None, "--customer-id", help="Account ID for advanced use.", hidden=True
    ),
) -> None:
    """Publish an npm package to a Ravenstash npm repository."""
    context = _registry_context(
        "npm",
        repo,
        profile,
        customer_id,
        require_private=True,
        operations=("upload",),
    )
    assert context.push_base_url is not None
    confirm_context(context, [npm_artifact(package_dir)], yes=yes)
    results = npm_reg.publish(
        registry_url=_ROUTER.npm_upload_registry_url(
            context.push_base_url,
            context.namespace_reference,
            context.repository_reference,
        ),
        token=context.token,
        package_dir=package_dir,
        download_registry_url=_ROUTER.npm_registry_url(
            context.read_base_url,
            context.namespace_reference,
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
        None, "--customer-id", help="Account ID for advanced use.", hidden=True
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
        None, "--customer-id", help="Account ID for advanced use.", hidden=True
    ),
) -> None:
    """Print the private Maven repository URL."""
    context = _registry_context("maven", repo, profile, customer_id, allow_official_default=True)
    output.value(
        _ROUTER.maven_repo_url(
            context.read_base_url,
            context.namespace_reference,
            context.repository_reference,
        ),
        key="repository_url",
    )


def _settings_xml(repo_url: str, password_expr: str = "${env.RVS_ARTIFACTS_TOKEN}") -> str:
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
        None, "--customer-id", help="Account ID for advanced use.", hidden=True
    ),
) -> None:
    """Print a Maven settings.xml snippet for the private Maven repository."""
    context = _registry_context("maven", repo, profile, customer_id, allow_official_default=True)
    output.value(
        _settings_xml(
            _ROUTER.maven_repo_url(
                context.read_base_url,
                context.namespace_reference,
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
        None, "--customer-id", help="Account ID for advanced use.", hidden=True
    ),
) -> None:
    """Fetch a Maven artifact into the local Maven cache."""
    context = _registry_context("maven", repo, profile, customer_id, allow_official_default=True)
    repo_url = _ROUTER.maven_repo_url(
        context.read_base_url, context.namespace_reference, context.repository_reference
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
            env=child_environment(),
            check=True,
        )
    finally:
        Path(settings_path).unlink(missing_ok=True)


@maven_app.command("deploy")
def maven_deploy(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip publishing confirmation."),
    artifact_file: Path = typer.Argument(..., help="Artifact file to deploy."),
    group: str = typer.Option(..., "--group", "-g", help="Maven groupId."),
    artifact: str = typer.Option(..., "--artifact", "-a", help="Maven artifactId."),
    version: str = typer.Option(..., "--version", "-v", help="Maven version."),
    repo: str | None = typer.Option(None, "--repo", "-r", help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(
        None, "--customer-id", help="Account ID for advanced use.", hidden=True
    ),
) -> None:
    """Deploy an artifact file to a Ravenstash Maven repository."""
    if not artifact_file.exists():
        output.fatal(f"Artifact file not found: {artifact_file}")
    try:
        maven_reg.validate_artifact_filename(artifact_file.name, artifact, version)
    except ValueError as exc:
        output.fatal(str(exc))
    context = _registry_context(
        "maven",
        repo,
        profile,
        customer_id,
        require_private=True,
        operations=("upload",),
    )
    assert context.push_base_url is not None
    confirm_context(
        context,
        [
            maven_artifact(
                group,
                artifact,
                version,
                [str(artifact_file), str(artifact_file) + ".md5", str(artifact_file) + ".sha1"],
            )
        ],
        yes=yes,
    )
    results = maven_reg.publish(
        upload_url=_ROUTER.maven_upload_url(
            context.push_base_url,
            context.namespace_reference,
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
        None, "--customer-id", help="Account ID for advanced use.", hidden=True
    ),
) -> None:
    """Print Maven settings.xml configuration for the private Maven repository."""
    maven_settings(repo=repo, profile=profile, customer_id=customer_id)
