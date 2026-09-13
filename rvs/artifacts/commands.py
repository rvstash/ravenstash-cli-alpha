"""`rvs art` command group."""

from __future__ import annotations

from typing import cast

import click
import typer

from .. import config as cfg_mod
from .. import output
from ..account.commands import display_name as account_display_name
from ..account.commands import ensure_active_account, resolve_account
from ..client import ApiClient, ApiError
from ..devapi import collection_items
from ..devapi import remote_cache as remote_cache_payload
from .auth_commands import app as native_auth_app
from .formats import FORMATS, flatten_formats
from .primitives import endpoint, native_app, reference
from .targets import (
    DEFAULT_OFFICIAL_SOURCES,
    PackageKind,
    parse_target,
    resolve_repository_entry,
    resolve_target,
)


app = typer.Typer(
    name="art",
    help="Manage repositories for packages, container images, and Helm charts.",
    no_args_is_help=True,
)

repo_app = typer.Typer(help="Manage Ravenstash repositories.", no_args_is_help=True)
upstream_app = typer.Typer(
    help="Manage the package sources used by a repository.", no_args_is_help=True
)
remote_app = typer.Typer(help="Manage private mirrors.", no_args_is_help=True)
package_app = typer.Typer(help="Manage packages hosted in a repository.", no_args_is_help=True)
app.add_typer(repo_app, name="repo")
repo_app.add_typer(upstream_app, name="upstream")
app.add_typer(remote_app, name="mirror")
app.add_typer(package_app, name="package")
app.add_typer(native_auth_app, name="token")
app.add_typer(native_app, name="native")
app.command("endpoint")(endpoint)
app.command("reference")(reference)

_PACKAGE_KINDS = ("pypi", "npm", "maven")
_MAX_UPSTREAM_POSITION = 4
_REPOSITORY_NAME_HELP = "Repository name or namespace/repository."


def _format_age_hours(value: float | int | str | None, *, missing: str) -> str:
    if value is None:
        return missing
    return f"{float(value):g} hours"


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
        return str(resolve_account(cast("str", options["account"]), profile)["account_ref"])
    profile_name, _ = _profile(profile)
    customer_id = cfg_mod.current_customer_id(profile_name)
    if not customer_id:
        output.fatal("No account is selected. Run `rvs account use USERNAME_OR_HANDLE`.")
    return customer_id


def _context_customer_id(profile: str | None, account: str | None) -> str | None:
    if account is None:
        return None
    return str(resolve_account(account, profile)["account_ref"])


@app.command("select")
def target_select(
    target: str = typer.Argument(
        ...,
        help="namespace/repository, mirror:<source>, or custom-mirror:<name>.",
    ),
    kind: str | None = typer.Option(None, "--format", help="Format if needed."),
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
            "Account ref": selected.customer_id if selected else "none",
            "Format": selected.registry_kind or "determined by command" if selected else "none",
        },
        title="Current artifact selection",
        json_keys=["profile", "account", "target", "type", "account_ref", "format"],
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
    output.success(
        f"Cleared the repository or mirror for {account_display_name(selected_account)}."
    )


def _require_kind(kind: str) -> cfg_mod.RegistryKind:
    if kind not in FORMATS:
        output.fatal(f"Unknown format '{kind}'. Use: pypi, npm, maven, container, helm")
    return cast("cfg_mod.RegistryKind", kind)


def _require_package_kind(kind: str) -> cfg_mod.RegistryKind:
    if kind not in _PACKAGE_KINDS:
        output.fatal(
            "Package/version commands and private mirrors support only pypi, npm, "
            "and maven. Use rvs docker, rvs helm, or rvs oras for OCI content."
        )
    return cast("cfg_mod.RegistryKind", kind)


def _require_lifecycle_kind(
    kind: str,
    *,
    expected: str,
    operation: str,
) -> cfg_mod.RegistryKind:
    registry_kind = _require_package_kind(kind)
    if registry_kind != expected:
        output.fatal(f"{operation} is supported only for {expected} packages.")
    return registry_kind


def _package_lifecycle_columns(
    registry_kind: str,
    version: dict,
) -> tuple[list[str], list[str], list[str]]:
    if registry_kind == "pypi":
        return (
            ["Yanked", "Yank reason"],
            ["yanked", "yanked_reason"],
            [
                "yes" if version.get("yanked") else "no",
                str(version.get("yanked_reason") or ""),
            ],
        )
    if registry_kind == "npm":
        return (
            ["Deprecated", "Deprecation message"],
            ["deprecated", "deprecated_reason"],
            [
                "yes" if version.get("deprecated") else "no",
                str(version.get("deprecated_reason") or ""),
            ],
        )
    return [], [], []


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


def _root_package_options() -> dict[str, str | None]:
    context = click.get_current_context(silent=True)
    if context is None:
        return {}
    params = context.params
    return {
        "target": params.get("target") or params.get("repo"),
        "account": params.get("account"),
        "kind": params.get("kind") or params.get("registry_kind"),
        "profile": params.get("profile"),
    }


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
    account: str | None = typer.Option(None, "--account"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(
        None, "--account-ref", help="Typed account reference.", hidden=True
    ),
    kind: str | None = typer.Option(
        None,
        "--format",
        "-f",
        help="Format: pypi | npm | maven | container | helm.",
    ),
) -> None:
    """List repositories in the selected account's namespaces."""
    if kind:
        _require_kind(kind)
    client = _client(profile)
    params = {
        key: value
        for key, value in {
            "account_ref": _customer_id(profile, customer_id),
            "format": kind,
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
        output.info("No repositories found.")
        return

    output.table(
        ["Account", "Namespace", "Repository", "Repository ID", "Formats"],
        [
            [
                entry["account"]["account_label"],
                entry["repository"]["namespace_name"],
                _repository_name_from_response(item),
                (f"{item['namespace_unique_ref']}/{item['repository_unique_ref']}"),
                ", ".join(
                    detail["format"]
                    for detail in item.get("formats", [])
                    if isinstance(detail, dict) and isinstance(detail.get("format"), str)
                ),
            ]
            for entry, item in zip(entries, items, strict=True)
        ],
        json_keys=["account", "namespace", "repository", "repository_id", "formats"],
    )


@repo_app.command("create")
def repo_create(
    account: str | None = typer.Option(None, "--account"),
    name: str = typer.Argument(..., help="Repository name or namespace/repository."),
    kind: list[str] = typer.Option(
        ...,
        "--format",
        "-f",
        help="Formats to enable, comma-separated or with repeated --format flags.",
    ),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(
        None, "--account-ref", help="Typed owner account reference.", hidden=True
    ),
    set_default: bool = typer.Option(
        False, "--default", help="Set as default for each selected format."
    ),
) -> None:
    """Create a repository."""
    if name.startswith(("internal:", "global:", "@")):
        output.fatal("Use namespace/repository without a realm prefix or @ notation.")
    namespace_selector, repository_name = _split_repo_ref(name)
    try:
        kinds = cast("list[cfg_mod.RegistryKind]", flatten_formats(kind))
    except ValueError as exc:
        output.fatal(str(exc))
    client = _client(profile)
    try:
        selected_customer_id = _customer_id(profile, customer_id)
        namespaces_payload = client.get(
            "/namespaces", params={"account_ref": selected_customer_id}
        ).json()
        namespaces = collection_items(namespaces_payload)
        matches = [
            entry
            for entry in namespaces
            if entry["account"]["account_ref"] == selected_customer_id
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
            "account_ref": selected_namespace["account"]["account_ref"],
            "namespace_unique_ref": selected_namespace["namespace"]["namespace_unique_ref"],
            "repository_name": repository_name,
            "formats": kinds,
        }
        entry = client.post("/repositories", json=payload).json()
        repo = entry["repository"]
    except ApiError as exc:
        output.fatal(str(exc))

    repository_name = _repository_name_from_response(repo, name)
    output.success(f"Created repository '{repository_name}' with formats: {', '.join(kinds)}.")
    if set_default and repository_name:
        default_repo = _repo_ref_from_response(repo, repository_name)
        for registry_kind in kinds:
            cfg_mod.set_registry_default_target(
                registry_kind,
                customer=entry["account"],
                repository=repo,
                profile=profile,
            )
        output.info(f"Default repository for {', '.join(kinds)} set to {default_repo}.")


@repo_app.command("show")
def repo_show(
    account: str | None = typer.Option(None, "--account"),
    repo: str = typer.Argument(..., help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Show repository details."""
    try:
        entry = _resolve_repository_entry(repo, profile)
        item = entry["repository"]
    except ApiError as exc:
        output.fatal(str(exc))

    output.kv(
        {
            "Name": _repository_name_from_response(item, repo),
            "Account": entry["account"]["account_label"],
            "Namespace": item["namespace_name"],
            "Namespace ID": item["namespace_unique_ref"],
            "Repository ID": item["repository_unique_ref"],
            "Formats": ", ".join(
                detail["format"]
                for detail in item.get("formats", [])
                if isinstance(detail, dict) and isinstance(detail.get("format"), str)
            ),
            "Packages": str(item.get("aggregate_package_count", item.get("package_count", "0"))),
            "Versions": str(item.get("aggregate_version_count", item.get("version_count", "0"))),
            "OCI paths": str(item.get("aggregate_oci_repository_count", "0")),
            "Manifests": str(item.get("aggregate_manifest_count", "0")),
            "Storage bytes": str(
                item.get("aggregate_storage_bytes", item.get("storage_bytes", "0"))
            ),
            "Created": str(item.get("created_at", "")),
        },
        title=f"Repository {repo}",
        json_keys=[
            "name",
            "account",
            "namespace",
            "namespace_id",
            "repository_id",
            "formats",
            "packages",
            "versions",
            "oci_paths",
            "manifests",
            "storage_bytes",
            "created",
        ],
    )


@repo_app.command("delete")
def repo_delete(
    account: str | None = typer.Option(None, "--account"),
    repo: str = typer.Argument(..., help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """Delete a repository."""
    if not yes:
        typer.confirm(f"Delete repository '{repo}' and all its content?", abort=True)
    client = _client(profile)
    try:
        entry = _resolve_repository_entry(repo, profile)
        client.delete(f"/repositories/{entry['repository']['repository_unique_ref']}")
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Deleted repository '{repo}'.")


@repo_app.command("rename")
def repo_rename(
    account: str | None = typer.Option(None, "--account"),
    repo: str = typer.Argument(..., help="Current repository name."),
    new_name: str = typer.Argument(..., help="New repository name."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Rename a repository."""
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
        customer=entry["account"],
        repository=item,
        profile=profile,
    )
    renamed = _repository_name_from_response(item, new_name)
    output.success(f"Renamed repository '{repo}' to '{renamed}'.")


@repo_app.command("set-default")
def repo_set_default(
    account: str | None = typer.Option(None, "--account"),
    format: str = typer.Argument(
        ...,
        help="Format: pypi | npm | maven | container | helm",
        metavar="FORMAT",
    ),
    repo: str = typer.Argument(..., help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Set the default repository for a format."""
    registry_kind = _require_kind(format)
    profile_name = _profile_name(profile)
    entry = _resolve_repository_entry(repo, profile, kind=format)
    repository = entry["repository"]
    stable = f"{repository['namespace_unique_ref']}/{repository['repository_unique_ref']}"
    cfg_mod.set_registry_default_target(
        registry_kind,
        customer=entry["account"],
        repository=repository,
        profile=profile_name,
    )
    output.success(f"Default {format} repository for profile '{profile_name}' set to {stable}.")


@repo_app.command("defaults")
def repo_defaults(
    account: str | None = typer.Option(None, "--account"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Show default repositories by format."""
    cfg = cfg_mod.load()
    profile_name = profile or cfg_mod.current_profile_name(cfg)
    rows = [
        [kind, cfg.registry_defaults(kind, profile_name).default_repo or "not set"]  # type: ignore[arg-type]
        for kind in FORMATS
    ]
    output.table(
        ["Format", "Default repository"],
        rows,
        title=f"Repository defaults ({profile_name})",
        json_keys=["format", "default_repository"],
    )


def _upstream_path(repository_unique_ref: str, registry_kind: str) -> str:
    return f"/repositories/{repository_unique_ref}/formats/{registry_kind}/upstreams"


def _upstream_revision(entry: dict, registry_kind: str) -> int:
    formats = entry["repository"]["formats"]
    detail = next(item for item in formats if item["format"] == registry_kind)
    return int(detail["upstream_config_revision"])


def _print_upstreams(items: list[dict]) -> None:
    output.table(
        ["ID", "Position", "Type", "Source", "Minimum age", "Maximum age"],
        [
            [
                str(item.get("attachment_id") or item.get("id", "")),
                str(item.get("position", "")),
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
        json_keys=["id", "position", "type", "source", "min_age_hours", "max_age_hours"],
    )


@upstream_app.command("list")
def upstream_list(
    account: str | None = typer.Option(None, "--account"),
    repository: str = typer.Argument(...),
    format: str = typer.Argument(..., metavar="FORMAT"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """List the package sources used by one repository format."""
    registry_kind = _require_package_kind(format)
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
    account: str | None = typer.Option(None, "--account"),
    repository: str = typer.Argument(...),
    format: str = typer.Argument(..., metavar="FORMAT"),
    private_repository: str | None = typer.Option(None, "--private-repository"),
    remote_cache: str | None = typer.Option(
        None, "--remote-cache", help="Remote-cache reference (rc_...)."
    ),
    position: int = typer.Option(..., "--position", min=1, max=_MAX_UPSTREAM_POSITION),
    min_age_hours: float | None = typer.Option(None, "--min-age-hours", min=0),
    max_age_hours: float | None = typer.Option(None, "--max-age-hours", min=0),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Add a private repository or remote cache as a package source."""
    if (private_repository is None) == (remote_cache is None):
        output.fatal("Pass exactly one of --private-repository or --remote-cache.")
    registry_kind = _require_package_kind(format)
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
                f"/remote-caches/{remote_cache}",
                params={"format": registry_kind},
            ).json()
            source_type = "remote"
            remote_payload = remote_cache_payload(remote_entry)
            source_identity = {
                "remote_cache_ref": remote_payload.get("remote_cache_ref")
                or remote_payload.get("unique_ref")
                or remote_cache
            }
        body = {
            "source_type": source_type,
            **source_identity,
            "position": position,
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
    account: str | None = typer.Option(None, "--account"),
    repository: str = typer.Argument(...),
    format: str = typer.Argument(..., metavar="FORMAT"),
    attachment: str = typer.Argument(...),
    position: int | None = typer.Option(None, "--position", min=1, max=_MAX_UPSTREAM_POSITION),
    min_age_hours: float | None = typer.Option(None, "--min-age-hours", min=0),
    max_age_hours: float | None = typer.Option(None, "--max-age-hours", min=0),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Change the fixed position or package-age settings for one source."""
    body = {
        key: value
        for key, value in {
            "position": position,
            "min_age_hours": min_age_hours,
            "max_age_hours": max_age_hours,
        }.items()
        if value is not None
    }
    if not body:
        output.fatal("Pass at least one field to update.")
    registry_kind = _require_package_kind(format)
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


@upstream_app.command("remove")
def upstream_remove(
    account: str | None = typer.Option(None, "--account"),
    repository: str = typer.Argument(...),
    format: str = typer.Argument(..., metavar="FORMAT"),
    attachment: str = typer.Argument(...),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Remove one package source."""
    registry_kind = _require_package_kind(format)
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
    kind: str | None = typer.Option(None, "--format", help="Package format if needed."),
    account: str | None = typer.Option(None, "--account", help="Username or organization handle."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Select a Ravenstash-provided or custom private mirror."""
    prefix = "custom-mirror" if custom else "mirror"
    target_select(f"{prefix}:{mirror}", kind=kind, account=account, profile=profile)


@remote_app.command("list")
def remote_list(
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(None, "--account-ref", hidden=True),
    account: str | None = typer.Option(None, "--account"),
    kind: str | None = typer.Option(None, "--format", "-f"),
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
                "account_ref": effective_customer_id,
                "format": kind,
            },
        ).json()
        items = collection_items(payload)
    except ApiError as exc:
        output.fatal(str(exc))
    if kind:
        items = [entry for entry in items if remote_cache_payload(entry).get("format") == kind]
    if not items:
        output.info("No private mirrors found.")
        return
    output.table(
        [
            "Account",
            "Remote-cache ref",
            "Source",
            "Publication",
            "Mirror",
            "Format",
            "Minimum age",
        ],
        [
            [
                str(entry.get("account", {}).get("account_label", "")),
                str(item["remote_cache_ref"]),
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
                str(item.get("format", "")),
                _format_age_hours(item.get("min_age_hours"), missing="No minimum"),
            ]
            for entry in items
            for item in [remote_cache_payload(entry)]
        ],
        json_keys=[
            "account",
            "remote_cache_ref",
            "source",
            "publication",
            "mirror",
            "format",
            "min_age_hours",
        ],
    )


@remote_app.command("create")
def remote_create(
    source: str | None = typer.Argument(None, help="Official source slug; defaults by format."),
    kind: str | None = typer.Option(None, "--format", help="Package format if needed."),
    min_age_hours: float | None = typer.Option(None, "--min-age-hours", min=0),
    max_age_hours: float | None = typer.Option(None, "--max-age-hours", min=0),
    select: bool = typer.Option(False, "--select", help="Select the mirror after creating it."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    account: str | None = typer.Option(None, "--account"),
) -> None:
    """Create a Ravenstash-provided private mirror."""
    if source is None:
        if kind not in DEFAULT_OFFICIAL_SOURCES:
            output.fatal("Pass a SOURCE or --format pypi, npm, or maven.")
        source = DEFAULT_OFFICIAL_SOURCES[cast("PackageKind", kind)]
    customer_id = _context_customer_id(profile, account) or _customer_id(profile)
    if kind:
        _require_package_kind(kind)
    client = _client(profile)
    try:
        sources_payload = client.get(
            "/remote-caches/official-sources",
            params={"account_ref": customer_id},
        ).json()
        sources = collection_items(sources_payload)
        matches = [
            item
            for item in sources
            if source == item.get("source_ref") and (kind is None or item.get("format") == kind)
        ]
        if not matches:
            output.fatal(f"Official mirror source '{source}' was not found.")
        if len(matches) > 1:
            output.fatal(f"Official mirror source '{source}' is ambiguous. Pass --format.")
        selected_source = matches[0]
        payload: dict[str, object] = {
            "account_ref": customer_id,
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
            kind=str(item["format"]),
            account=account,
            profile=profile,
        )


@remote_app.command("show")
def remote_show(
    remote: str = typer.Argument(
        ..., help="Remote-cache reference (rc_...).", metavar="REMOTE_CACHE_REF"
    ),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    account: str | None = typer.Option(None, "--account"),
    customer_id: str | None = typer.Option(None, "--account-ref", hidden=True),
    kind: str | None = typer.Option(None, "--format", "-f"),
) -> None:
    """Show a private mirror."""
    if kind:
        _require_package_kind(kind)
    selected_customer = _context_customer_id(profile, account) or _customer_id(profile, customer_id)
    client = _client(profile)
    try:
        entry = client.get(
            f"/remote-caches/{remote}",
            params={"account_ref": selected_customer, "format": kind},
        ).json()
        item = remote_cache_payload(entry)
    except (ApiError, KeyError, TypeError) as exc:
        output.fatal(str(exc))
    output.kv(
        {
            "Remote-cache ref": item["remote_cache_ref"],
            "Type": item.get("source_type"),
            "Target": (
                f"mirror:{item.get('official_slug') or item['remote_cache_ref']}"
                if item.get("source_type") == "official"
                else f"custom-mirror:{item.get('remote_name') or item['remote_cache_ref']}"
            ),
            "Format": item.get("format"),
            "Account ref": entry.get("account", {}).get("account_ref"),
            "Private mirror": "ready",
            "Mirror minimum package age": _format_age_hours(
                item.get("min_age_hours"), missing="No minimum"
            ),
            "Maximum package age": _format_age_hours(
                item.get("max_age_hours"), missing="No maximum"
            ),
        },
        title=f"Private mirror {remote}",
        json_keys=[
            "remote_cache_ref",
            "type",
            "target",
            "format",
            "account_ref",
            "private_mirror",
            "min_age_hours",
            "max_age_hours",
        ],
    )


@remote_app.command("set-age")
def remote_set_age(
    remote: str = typer.Argument(
        ..., help="Remote-cache reference (rc_...).", metavar="REMOTE_CACHE_REF"
    ),
    min_age_hours: float = typer.Option(..., "--min-age-hours", min=0),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    account: str | None = typer.Option(None, "--account"),
    customer_id: str | None = typer.Option(None, "--account-ref", hidden=True),
    kind: str | None = typer.Option(None, "--format", "-f"),
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
            params={"account_ref": selected_customer, "format": kind},
            json=payload,
        )
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Updated private mirror minimum package age for '{remote}'.")


@remote_app.command("delete")
def remote_delete(
    remote: str = typer.Argument(
        ..., help="Remote-cache reference (rc_...).", metavar="REMOTE_CACHE_REF"
    ),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(None, "--account-ref", hidden=True),
    account: str | None = typer.Option(None, "--account"),
    kind: str | None = typer.Option(None, "--format", "-f"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Delete a private mirror."""
    if kind:
        _require_package_kind(kind)
    if not yes:
        typer.confirm(f"Delete private mirror '{remote}'?", abort=True)
    selected_customer = _context_customer_id(profile, account) or _customer_id(profile, customer_id)
    params = {"account_ref": selected_customer, "format": kind}
    client = _client(profile)
    try:
        client.delete(f"/remote-caches/{remote}", params=params)
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Deleted private mirror '{remote}'.")


# ── package ──────────────────────────────────────────────────────────────────


@package_app.command("list")
def package_list(
    account: str | None = typer.Option(None, "--account"),
    repo: str = typer.Option(..., "--target", "-t", help=_REPOSITORY_NAME_HELP),
    kind: str = typer.Option(
        ...,
        "--format",
        "-f",
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
            f"/repositories/{repository_unique_ref}/formats/{registry_kind}/packages"
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
        json_keys=["name", "latest", "versions", "size", "downloads", "bandwidth"],
    )


@package_app.command("show")
def package_show(
    account: str | None = typer.Option(None, "--account"),
    name: str = typer.Argument(..., help="Package name."),
    repo: str = typer.Option(..., "--target", "-t", help=_REPOSITORY_NAME_HELP),
    kind: str = typer.Option(
        ...,
        "--format",
        "-f",
        help="Package format: pypi | npm | maven.",
    ),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Show package metadata and versions."""
    registry_kind = _require_package_kind(kind)
    client = _client(profile)
    try:
        repository_unique_ref = _resolved_repository_unique_ref(repo, profile, kind=registry_kind)
        item = client.get(
            f"/repositories/{repository_unique_ref}/formats/{registry_kind}/packages/detail",
            params={"package_name": name},
        ).json()
    except ApiError as exc:
        output.fatal(str(exc))

    output.kv(
        {
            "Repository": item.get("repository_unique_ref", repo),
            "Name": item.get("package_name") or item.get("normalized_name", name),
            "Status": item.get("package_status") or "active",
            "Latest": item.get("latest_version") or "",
            "Versions": str(item.get("version_count", "")),
            "Size": str(item.get("total_size_bytes", "")),
        },
        title=name,
        json_keys=["repository", "name", "status", "latest", "versions", "size"],
    )

    versions = item.get("versions") or []
    if versions:
        lifecycle_headings, lifecycle_keys, _ = _package_lifecycle_columns(
            registry_kind, versions[0]
        )
        output.table(
            ["Version", *lifecycle_headings, "Files", "Size", "Downloads", "Bandwidth"],
            [
                [
                    version.get("version", ""),
                    *_package_lifecycle_columns(registry_kind, version)[2],
                    str(len(version.get("files") or [])),
                    str(version.get("total_size_bytes", "")),
                    str(version.get("downloads", "0")),
                    str(version.get("bandwidth_bytes", "0")),
                ]
                for version in versions
            ],
            json_keys=[
                "version",
                *lifecycle_keys,
                "files",
                "size",
                "downloads",
                "bandwidth",
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
                json_keys=["version", "artifact", "size", "sha256"],
            )


@package_app.command("delete")
def package_delete(
    account: str | None = typer.Option(None, "--account"),
    name: str = typer.Argument(..., help="Package name."),
    repo: str = typer.Option(..., "--target", "-t", help=_REPOSITORY_NAME_HELP),
    kind: str = typer.Option(
        ...,
        "--format",
        "-f",
        help="Package format: pypi | npm | maven.",
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
            f"/repositories/{repository_unique_ref}/formats/{registry_kind}/packages/detail",
            params={"package_name": name},
        )
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Deleted package '{name}' from '{repo}'.")


@package_app.command("delete-version")
def package_delete_version(
    account: str | None = typer.Option(None, "--account"),
    name: str = typer.Argument(..., help="Package name."),
    version: str = typer.Argument(..., help="Version to delete."),
    repo: str = typer.Option(..., "--target", "-t", help=_REPOSITORY_NAME_HELP),
    kind: str = typer.Option(
        ...,
        "--format",
        "-f",
        help="Package format: pypi | npm | maven.",
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
            f"/repositories/{repository_unique_ref}/formats/{registry_kind}/packages/version",
            params={"package_name": name, "version": version},
        )
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Deleted {name}@{version} from '{repo}'.")


@package_app.command("yank")
def package_yank(
    account: str | None = typer.Option(None, "--account"),
    name: str = typer.Argument(..., help="Package name."),
    version: str = typer.Argument(..., help="Version to yank."),
    repo: str = typer.Option(..., "--target", "-t", help=_REPOSITORY_NAME_HELP),
    kind: str = typer.Option(
        ...,
        "--format",
        "-f",
        help="Package format: pypi | npm | maven.",
    ),
    reason: str | None = typer.Option(None, "--reason", "-m", help="Yank reason."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Mark a package version as yanked."""
    registry_kind = _require_lifecycle_kind(
        kind,
        expected="pypi",
        operation="Yanking a package version",
    )
    client = _client(profile)
    body = {"yanked": True, "reason": reason}
    try:
        repository_unique_ref = _resolved_repository_unique_ref(repo, profile, kind=registry_kind)
        client.post(
            f"/repositories/{repository_unique_ref}/formats/{registry_kind}/packages/version/yank",
            params={"package_name": name, "version": version},
            json=body,
        )
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Yanked {name}@{version} in '{repo}'.")


@package_app.command("unyank")
def package_unyank(
    account: str | None = typer.Option(None, "--account"),
    name: str = typer.Argument(..., help="Package name."),
    version: str = typer.Argument(..., help="Version to unyank."),
    repo: str = typer.Option(..., "--target", "-t", help=_REPOSITORY_NAME_HELP),
    kind: str = typer.Option(..., "--format", "-f", help="Package format: pypi."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Make a yanked PyPI package version selectable again."""
    registry_kind = _require_lifecycle_kind(
        kind,
        expected="pypi",
        operation="Unyanking a package version",
    )
    client = _client(profile)
    try:
        repository_unique_ref = _resolved_repository_unique_ref(repo, profile, kind=registry_kind)
        client.post(
            f"/repositories/{repository_unique_ref}/formats/{registry_kind}/packages/version/yank",
            params={"package_name": name, "version": version},
            json={"yanked": False, "reason": None},
        )
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Unyanked {name}@{version} in '{repo}'.")


@package_app.command("deprecate")
def package_deprecate(
    account: str | None = typer.Option(None, "--account"),
    name: str = typer.Argument(..., help="Package name."),
    version: str = typer.Argument(..., help="Version to deprecate."),
    repo: str = typer.Option(..., "--target", "-t", help=_REPOSITORY_NAME_HELP),
    kind: str = typer.Option(..., "--format", "-f", help="Package format: npm."),
    message: str = typer.Option(
        ...,
        "--message",
        "-m",
        help="Deprecation message shown by npm clients.",
    ),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Attach a warning message to an npm package version."""
    registry_kind = _require_lifecycle_kind(
        kind,
        expected="npm",
        operation="Deprecating a package version",
    )
    normalized_message = message.strip()
    if not normalized_message:
        output.fatal("--message cannot be empty. Use undeprecate to clear the message.")
    client = _client(profile)
    try:
        repository_unique_ref = _resolved_repository_unique_ref(repo, profile, kind=registry_kind)
        client.patch(
            f"/repositories/{repository_unique_ref}/formats/{registry_kind}/packages/version/deprecation",
            params={"package_name": name, "version": version},
            json={"deprecated": True, "message": normalized_message},
        )
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Deprecated {name}@{version} in '{repo}'.")


@package_app.command("undeprecate")
def package_undeprecate(
    account: str | None = typer.Option(None, "--account"),
    name: str = typer.Argument(..., help="Package name."),
    version: str = typer.Argument(..., help="Version to undeprecate."),
    repo: str = typer.Option(..., "--target", "-t", help=_REPOSITORY_NAME_HELP),
    kind: str = typer.Option(..., "--format", "-f", help="Package format: npm."),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Clear the warning message from an npm package version."""
    registry_kind = _require_lifecycle_kind(
        kind,
        expected="npm",
        operation="Undeprecating a package version",
    )
    client = _client(profile)
    try:
        repository_unique_ref = _resolved_repository_unique_ref(repo, profile, kind=registry_kind)
        client.patch(
            f"/repositories/{repository_unique_ref}/formats/{registry_kind}/packages/version/deprecation",
            params={"package_name": name, "version": version},
            json={"deprecated": False, "message": None},
        )
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Undeprecated {name}@{version} in '{repo}'.")
