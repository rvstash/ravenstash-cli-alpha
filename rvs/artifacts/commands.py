"""`rvs art` command group."""

from __future__ import annotations

from typing import cast

import click
import typer

from .. import config as cfg_mod
from .. import output
from ..account.commands import display_name as account_display_name
from ..account.commands import ensure_active_account, payload_display_name, resolve_account
from ..client import ApiClient, ApiError
from ..devapi import artifacts_path, collection_items, platform_path, segment
from .auth_commands import app as native_auth_app
from .evidence_commands import app as evidence_app
from .formats import FORMATS, flatten_formats
from .oci_commands import app as oci_app
from .primitives import endpoint, native_app, reference
from .targets import (
    DEFAULT_OFFICIAL_SOURCES,
    PackageKind,
    parse_target,
    remote_target_name,
    repository_display_name,
    repository_formats,
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
app.add_typer(evidence_app, name="evidence")
app.add_typer(oci_app, name="oci")
app.add_typer(native_auth_app, name="token")
app.add_typer(native_app, name="native")
app.command("endpoint")(endpoint)
app.command("reference")(reference)

_PACKAGE_KINDS = ("pypi", "npm", "maven")
_MAX_UPSTREAM_POSITION = 4
_REPOSITORY_NAME_HELP = "Name-based target (namespace/repository) or ID-based target (in/ar_...)."
_ACCOUNT_HELP = "Typed account handle (user:USERNAME or org:HANDLE). Bare handles remain supported."


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
        return str(resolve_account(cast("str", options["account"]), profile)["ref"])
    profile_name, _ = _profile(profile)
    customer_id = cfg_mod.current_customer_id(profile_name)
    if not customer_id:
        output.fatal("No account is selected. Run `rvs account switch`.")
    return customer_id


def _context_customer_id(profile: str | None, account: str | None) -> str | None:
    if account is None:
        return None
    return str(resolve_account(account, profile)["ref"])


@app.command("select")
def target_select(
    target: str = typer.Argument(
        ...,
        help=(
            "Name-based target (namespace/repository), ID-based target (in/ar_...), "
            "mirror:<source>, or custom-mirror:<name>."
        ),
    ),
    kind: str | None = typer.Option(None, "--format", help="Format if needed."),
    account: str | None = typer.Option(None, "--account", help=_ACCOUNT_HELP),
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
    account: str | None = typer.Option(None, "--account", help=_ACCOUNT_HELP),
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
    account: str | None = typer.Option(None, "--account", help=_ACCOUNT_HELP),
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
        output.fatal(f"Unknown format '{kind}'. Use: pypi, npm, maven, oci")
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


def _selected_account_handle(
    profile: str | None,
    account_ref: str,
    repositories: list[dict],
) -> str:
    for repository in repositories:
        if repository["account"]["ref"] == account_ref:
            return payload_display_name(repository["account"])

    profile_name, selected = ensure_active_account(profile, account_ref)
    if selected.customer_handle:
        return account_display_name(selected)
    return payload_display_name(resolve_account(account_ref, profile_name))


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
    return _resolve_repository_entry(repo, profile, kind=kind)["ref"]


def _repository_path(repository_ref: str, suffix: str = "") -> str:
    return artifacts_path(f"repositories/{segment(repository_ref)}{suffix}")


def _format_path(repository_ref: str, registry_kind: str, suffix: str) -> str:
    return _repository_path(repository_ref, f"/formats/{registry_kind}/{suffix}")


def _remote_cache_path(remote_cache_ref: str) -> str:
    return artifacts_path(f"remote-caches/{segment(remote_cache_ref)}")


# ── repo ─────────────────────────────────────────────────────────────────────


def _repository_access_label(repository: dict) -> str:
    actions = set(repository["allowed_actions"])
    if actions & {"repository.write", "repository.delete", "upstream.write", "content.delete"}:
        return "Admin"
    if "content.publish" in actions:
        return "Publish"
    if "content.read" in actions:
        return "Read"
    return "Unknown"


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
        help="Format: pypi | npm | maven | oci.",
    ),
) -> None:
    """List repositories in the selected account's namespaces."""
    if kind:
        _require_kind(kind)
    client = _client(profile)
    selected_account_ref = _customer_id(profile, customer_id)
    params = {
        key: value
        for key, value in {
            "account_ref": selected_account_ref,
            "format": kind,
        }.items()
        if value is not None
    }
    try:
        items = collection_items(client.get(artifacts_path("repositories"), params=params).json())
    except (ApiError, ValueError) as exc:
        output.fatal(str(exc))

    if output.is_json():
        account_handle = (
            _selected_account_handle(profile, selected_account_ref, items) if items else ""
        )
        output.table(
            ["Account", "Namespace", "Repository", "ID-based target", "Formats", "Access"],
            [
                [
                    account_handle,
                    item["namespace"]["name"],
                    item["name"],
                    f"in/{item['ref']}",
                    ", ".join(repository_formats(item)),
                    _repository_access_label(item),
                ]
                for item in items
            ],
            json_keys=[
                "account",
                "namespace",
                "repository",
                "id_based_target",
                "formats",
                "access",
            ],
        )
        return

    account_handle = _selected_account_handle(profile, selected_account_ref, items)
    output.kv({"Account": account_handle})
    if not items:
        output.info("No repositories found.")
        return

    output.table(
        ["Repository", "ID-based target", "Formats", "Access"],
        [
            [
                repository_display_name(item),
                f"in/{item['ref']}",
                ", ".join(repository_formats(item)),
                _repository_access_label(item),
            ]
            for item in items
        ],
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
        namespaces = collection_items(
            client.get(
                platform_path("namespaces"), params={"account_ref": selected_customer_id}
            ).json()
        )
        matches = [
            namespace
            for namespace in namespaces
            if namespace["account"]["ref"] == selected_customer_id
            and (
                (namespace["is_default"] and namespace["realm"] == "internal")
                if namespace_selector is None
                else (
                    namespace["ref"] == namespace_selector
                    or namespace["name"].casefold() == namespace_selector.casefold()
                )
            )
        ]
        if len(matches) != 1:
            output.fatal(
                "Select an accessible namespace with namespace/repository. "
                "If this account has no namespace, finish onboarding in the webapp."
            )
        payload = {
            "namespace_ref": matches[0]["ref"],
            "name": repository_name,
            "formats": kinds,
        }
        repo = client.post(artifacts_path("repositories"), json=payload).json()
    except (ApiError, ValueError) as exc:
        output.fatal(str(exc))

    output.success(f"Created repository '{repo['name']}' with formats: {', '.join(kinds)}.")


@repo_app.command("show")
def repo_show(
    account: str | None = typer.Option(None, "--account"),
    repo: str = typer.Argument(..., help=_REPOSITORY_NAME_HELP),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Show repository details."""
    try:
        item = _resolve_repository_entry(repo, profile)
    except ApiError as exc:
        output.fatal(str(exc))

    account_handle = payload_display_name(item["account"])
    repository_name = item["name"]
    namespace = item["namespace"]
    id_based_target = f"in/{item['ref']}"
    formats = ", ".join(repository_formats(item))
    totals = item["totals"]
    packages = str(totals["package_count"])
    versions = str(totals["version_count"])
    oci_paths = str(totals.get("oci_path_count", 0))
    manifests = str(totals.get("manifest_count", 0))
    storage_bytes = str(totals["storage_bytes"])
    created = str(item["created_at"])
    if output.is_json():
        output.kv(
            {
                "Name": repository_name,
                "Account": account_handle,
                "Namespace": namespace["name"],
                "Namespace permanent ID": namespace["ref"],
                "Repository permanent ID": item["ref"],
                "Formats": formats,
                "Packages": packages,
                "Versions": versions,
                "OCI paths": oci_paths,
                "Manifests": manifests,
                "Storage bytes": storage_bytes,
                "Created": created,
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
        return

    output.kv(
        {
            "Repository": repository_display_name(item),
            "Account": account_handle,
            "ID-based target": id_based_target,
            "Formats": formats,
            "Packages": packages,
            "Versions": versions,
            "OCI paths": oci_paths,
            "Manifests": manifests,
            "Storage bytes": storage_bytes,
            "Created": created,
        },
        title=f"Repository {repository_display_name(item)}",
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
        repository = _resolve_repository_entry(repo, profile)
        client.delete(_repository_path(repository["ref"]))
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
        repository = _resolve_repository_entry(repo, profile)
        updated = client.patch(_repository_path(repository["ref"]), json={"name": new_name}).json()
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Renamed repository '{repo}' to '{updated['name']}'.")


def _upstream_path(repository_ref: str, registry_kind: str, position: int | None = None) -> str:
    suffix = "upstreams" if position is None else f"upstreams/{position}"
    return _format_path(repository_ref, registry_kind, suffix)


def _upstream_revision(repository: dict, registry_kind: str) -> int:
    detail = next(item for item in repository["formats"] if item["format"] == registry_kind)
    return int(detail["upstream_config_revision"])


def _upstream_source_label(source: dict) -> str:
    if source.get("namespace_name"):
        return f"{source['namespace_name']}/{source['display_name']}"
    return str(source["display_name"])


def _print_upstreams(items: list[dict]) -> None:
    output.table(
        ["Position", "Type", "Source", "Source ref", "Minimum age", "Maximum age"],
        [
            [
                str(item["position"]),
                str(item["source"]["kind"]),
                _upstream_source_label(item["source"]),
                # A remote cache the caller cannot see has no public reference.
                str(item["source"]["ref"] or "-"),
                _format_age_hours(item.get("min_age_hours"), missing="No minimum"),
                _format_age_hours(item.get("max_age_hours"), missing="No maximum"),
            ]
            for item in sorted(items, key=lambda value: int(value["position"]))
        ],
        title="Repository upstreams",
        json_keys=["position", "type", "source", "source_ref", "min_age_hours", "max_age_hours"],
    )


@upstream_app.command("list")
def upstream_list(
    account: str | None = typer.Option(None, "--account"),
    repository: str = typer.Argument(...),
    format: str = typer.Argument(..., metavar="FORMAT"),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """List the package sources used by one repository format, by position."""
    registry_kind = _require_package_kind(format)
    client = _client(profile)
    try:
        destination = _resolve_repository_entry(repository, profile, kind=registry_kind)
        payload = client.get(_upstream_path(destination["ref"], registry_kind)).json()
        items = collection_items(payload)
    except (ApiError, KeyError, TypeError, ValueError) as exc:
        output.fatal(str(exc))
    _print_upstreams(items)


@upstream_app.command("add")
def upstream_add(
    account: str | None = typer.Option(None, "--account"),
    repository: str = typer.Argument(...),
    format: str = typer.Argument(..., metavar="FORMAT"),
    private_repository: str | None = typer.Option(None, "--private-repository"),
    remote_cache: str | None = typer.Option(
        None, "--remote-cache", help="Remote-cache permanent ID (rc_...)."
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
            source_repository = _resolve_repository_entry(
                private_repository, profile, kind=registry_kind
            )
            source = {"kind": "repository", "ref": source_repository["ref"]}
        else:
            remote = client.get(_remote_cache_path(cast("str", remote_cache))).json()
            if remote["format"] != registry_kind:
                output.fatal(f"Remote cache '{remote_cache}' is for {remote['format']}.")
            source = {"kind": "remote_cache", "ref": remote["ref"]}
        body: dict[str, object] = {
            "position": position,
            "source": source,
            "expected_revision": _upstream_revision(destination, registry_kind),
        }
        if max_age_hours is not None:
            body["max_age_hours"] = max_age_hours
        if min_age_hours is not None:
            body["min_age_hours"] = min_age_hours
        elif source["kind"] == "repository":
            body["min_age_hours"] = 0.0
        item = client.post(_upstream_path(destination["ref"], registry_kind), json=body).json()
    except (ApiError, KeyError, TypeError) as exc:
        output.fatal(str(exc))
    _print_upstreams([item])


@upstream_app.command("update")
def upstream_update(
    account: str | None = typer.Option(None, "--account"),
    repository: str = typer.Argument(...),
    format: str = typer.Argument(..., metavar="FORMAT"),
    current_position: int = typer.Argument(
        ...,
        metavar="POSITION",
        min=1,
        max=_MAX_UPSTREAM_POSITION,
        help="Current position of the source, as shown by `upstream list`.",
    ),
    position: int | None = typer.Option(
        None, "--position", min=1, max=_MAX_UPSTREAM_POSITION, help="Move to this position."
    ),
    min_age_hours: float | None = typer.Option(None, "--min-age-hours", min=0),
    max_age_hours: float | None = typer.Option(None, "--max-age-hours", min=0),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Change the fixed position or package-age settings for one source."""
    body: dict[str, object] = {
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
            _upstream_path(destination["ref"], registry_kind, current_position),
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
    position: int = typer.Argument(
        ...,
        metavar="POSITION",
        min=1,
        max=_MAX_UPSTREAM_POSITION,
        help="Position of the source, as shown by `upstream list`.",
    ),
    profile: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Remove the package source at one position."""
    registry_kind = _require_package_kind(format)
    client = _client(profile)
    try:
        destination = _resolve_repository_entry(repository, profile, kind=registry_kind)
        client.delete(
            _upstream_path(destination["ref"], registry_kind, position),
            params={"expected_revision": _upstream_revision(destination, registry_kind)},
        )
    except (ApiError, KeyError, TypeError) as exc:
        output.fatal(str(exc))
    output.success(
        f"Removed the upstream at position {position} from '{repository}' ({registry_kind})."
    )


# ── private mirrors and their remote caches ──────────────────────────────────


@remote_app.command("select")
def remote_select(
    mirror: str = typer.Argument(..., help="Official source slug or custom mirror name."),
    custom: bool = typer.Option(False, "--custom", help="Select a custom mirror."),
    kind: str | None = typer.Option(None, "--format", help="Package format if needed."),
    account: str | None = typer.Option(None, "--account", help=_ACCOUNT_HELP),
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
    params = {"account_ref": effective_customer_id}
    if kind:
        params["format"] = kind
    try:
        items = collection_items(client.get(artifacts_path("remote-caches"), params=params).json())
    except (ApiError, ValueError) as exc:
        output.fatal(str(exc))
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
                payload_display_name(item["account"]),
                str(item["ref"]),
                str(item["source_type"]),
                "externally_controlled" if item["source_type"] == "official" else "unknown",
                remote_target_name(item),
                str(item["format"]),
                _format_age_hours(item.get("min_age_hours"), missing="No minimum"),
            ]
            for item in items
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
        sources = collection_items(
            client.get(
                artifacts_path("official-sources"),
                params={"account_ref": customer_id},
            ).json()
        )
        matches = [
            item
            for item in sources
            if source == item["ref"] and (kind is None or item["format"] == kind)
        ]
        if not matches:
            output.fatal(f"Official mirror source '{source}' was not found.")
        if len(matches) > 1:
            output.fatal(f"Official mirror source '{source}' is ambiguous. Pass --format.")
        payload: dict[str, object] = {
            "account_ref": customer_id,
            "source_ref": matches[0]["ref"],
        }
        if min_age_hours is not None:
            payload["min_age_hours"] = min_age_hours
        if max_age_hours is not None:
            payload["max_age_hours"] = max_age_hours
        item = client.post(artifacts_path("remote-caches"), json=payload).json()
    except (ApiError, KeyError, TypeError, ValueError) as exc:
        output.fatal(str(exc))
    target_name = remote_target_name(item)
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
        ..., help="Remote-cache permanent ID (rc_...).", metavar="REMOTE_CACHE_ID"
    ),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    account: str | None = typer.Option(None, "--account", hidden=True),
    customer_id: str | None = typer.Option(None, "--account-ref", hidden=True),
    kind: str | None = typer.Option(None, "--format", "-f", help="Require this format."),
) -> None:
    """Show a private mirror."""
    # A remote-cache reference already identifies its owner; the hidden account
    # options remain accepted for existing scripts but are not sent.
    del account, customer_id
    if kind:
        _require_package_kind(kind)
    client = _client(profile)
    try:
        item = client.get(_remote_cache_path(remote)).json()
    except (ApiError, KeyError, TypeError) as exc:
        output.fatal(str(exc))
    if kind and item["format"] != kind:
        output.fatal(f"Private mirror '{remote}' is for {item['format']}, not {kind}.")
    output.kv(
        {
            "Remote-cache ref": item["ref"],
            "Type": item["source_type"],
            "Target": remote_target_name(item),
            "Format": item["format"],
            "Account ref": item["account"]["ref"],
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
        ..., help="Remote-cache permanent ID (rc_...).", metavar="REMOTE_CACHE_ID"
    ),
    min_age_hours: float = typer.Option(..., "--min-age-hours", min=0),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    account: str | None = typer.Option(None, "--account", hidden=True),
    customer_id: str | None = typer.Option(None, "--account-ref", hidden=True),
    kind: str | None = typer.Option(None, "--format", "-f", hidden=True),
) -> None:
    """Update the private mirror minimum package age."""
    # A remote-cache reference already identifies its owner; the hidden account
    # options remain accepted for existing scripts but are not sent.
    del account, customer_id
    if kind:
        _require_package_kind(kind)
    client = _client(profile)
    try:
        client.patch(_remote_cache_path(remote), json={"min_age_hours": min_age_hours})
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Updated private mirror minimum package age for '{remote}'.")


@remote_app.command("delete")
def remote_delete(
    remote: str = typer.Argument(
        ..., help="Remote-cache permanent ID (rc_...).", metavar="REMOTE_CACHE_ID"
    ),
    profile: str | None = typer.Option(None, "--profile", "-p"),
    customer_id: str | None = typer.Option(None, "--account-ref", hidden=True),
    account: str | None = typer.Option(None, "--account", hidden=True),
    kind: str | None = typer.Option(None, "--format", "-f", hidden=True),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Delete a private mirror."""
    # A remote-cache reference already identifies its owner; the hidden account
    # options remain accepted for existing scripts but are not sent.
    del account, customer_id
    if kind:
        _require_package_kind(kind)
    if not yes:
        typer.confirm(f"Delete private mirror '{remote}'?", abort=True)
    client = _client(profile)
    try:
        client.delete(_remote_cache_path(remote))
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
        items = collection_items(
            client.get(_format_path(repository_unique_ref, registry_kind, "packages")).json()
        )
    except (ApiError, ValueError) as exc:
        output.fatal(str(exc))

    if not items:
        output.info(f"No packages found in '{repo}'.")
        return

    output.table(
        ["Name", "Latest", "Versions", "Size", "Downloads", "Bandwidth"],
        [
            [
                item["name"],
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
            _format_path(repository_unique_ref, registry_kind, "package"),
            params={"package_name": name},
        ).json()
    except ApiError as exc:
        output.fatal(str(exc))

    output.kv(
        {
            "Repository": repository_unique_ref,
            "Name": item["name"],
            "Status": item.get("status") or "active",
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
            _format_path(repository_unique_ref, registry_kind, "package"),
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
            _format_path(repository_unique_ref, registry_kind, "package/version"),
            params={"package_name": name, "version": version},
        )
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Deleted {name}@{version} from '{repo}'.")


def _update_package_version(
    client: ApiClient,
    repository_ref: str,
    registry_kind: str,
    name: str,
    version: str,
    body: dict[str, object],
) -> None:
    client.patch(
        _format_path(repository_ref, registry_kind, "package/version"),
        params={"package_name": name, "version": version},
        json=body,
    )


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
    body: dict[str, object] = {"yanked": True}
    if reason is not None:
        body["yanked_reason"] = reason
    try:
        repository_unique_ref = _resolved_repository_unique_ref(repo, profile, kind=registry_kind)
        _update_package_version(client, repository_unique_ref, registry_kind, name, version, body)
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
        _update_package_version(
            client, repository_unique_ref, registry_kind, name, version, {"yanked": False}
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
        _update_package_version(
            client,
            repository_unique_ref,
            registry_kind,
            name,
            version,
            {"deprecated": True, "deprecated_reason": normalized_message},
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
        _update_package_version(
            client, repository_unique_ref, registry_kind, name, version, {"deprecated": False}
        )
    except ApiError as exc:
        output.fatal(str(exc))
    output.success(f"Undeprecated {name}@{version} in '{repo}'.")
