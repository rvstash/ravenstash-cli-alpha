"""Typed package-target parsing, resolution, and credential exchange."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, cast

from .. import config as cfg_mod
from .. import output
from ..account.commands import ensure_active_account
from ..client import ApiClient, ApiError
from .routing import RepositoryRouteKind


PackageKind = Literal["pypi", "npm", "maven"]
PackageOperation = Literal["download", "upload"]
DEFAULT_OFFICIAL_SOURCES: dict[PackageKind, str] = {
    "pypi": "pypiorg",
    "npm": "npmjs",
    "maven": "maven-central",
}


@dataclass(frozen=True)
class TargetSpec:
    target_type: cfg_mod.PackageTargetType
    selector: str


@dataclass(frozen=True)
class RegistryContext:
    profile_name: str
    customer_id: str
    kind: cfg_mod.RegistryKind
    target: cfg_mod.PackageTarget
    read_base_url: str
    push_base_url: str | None
    workspace_reference: str
    repository_reference: str
    token: str


def parse_target(value: str) -> TargetSpec:
    candidate = value.strip().strip("/")
    if not candidate:
        output.fatal("Package target cannot be empty.")
    if candidate.startswith("mirror:"):
        selector = candidate.removeprefix("mirror:").strip().strip("/")
        target_type: cfg_mod.PackageTargetType = "official_cache"
    elif candidate.startswith("custom-mirror:"):
        selector = candidate.removeprefix("custom-mirror:").strip().strip("/")
        target_type = "custom_cache"
    elif candidate.startswith("public:"):
        output.fatal("Public package targets are reserved for a future Ravenstash release.")
    elif ":" in candidate:
        output.fatal(
            "Unknown package target type. Use workspace/repository, mirror:<source>, "
            "or custom-mirror:<name>."
        )
    else:
        selector = candidate
        target_type = "private"
    if not selector or (target_type != "private" and "/" in selector):
        output.fatal("The package target selector is invalid.")
    return TargetSpec(target_type=target_type, selector=selector)


def _package_kind(kind: str | None) -> PackageKind | None:
    if kind is None:
        return None
    if kind not in DEFAULT_OFFICIAL_SOURCES:
        output.fatal("Remote caches support only pypi, npm, and maven.")
    return cast("PackageKind", kind)


def _private_target(entry: dict) -> cfg_mod.PackageTarget:
    customer = entry["customer"]
    repository = entry["repository"]
    package_kinds = [
        kind for kind in repository.get("registry_kinds", []) if kind in {"pypi", "npm", "maven"}
    ]
    inferred_kind = package_kinds[0] if len(package_kinds) == 1 else None
    return cfg_mod.PackageTarget(
        target_type="private",
        customer_id=customer["customer_id"],
        stable_selector=(
            f"{repository['workspace_unique_ref']}/{repository['repository_unique_ref']}"
        ),
        display_selector=f"{repository['workspace_name']}/{repository['repository_name']}",
        registry_kind=cast("cfg_mod.RegistryKind | None", inferred_kind),
        workspace_id=repository["workspace_id"],
        workspace_unique_ref=repository["workspace_unique_ref"],
        workspace_name_cache=repository["workspace_name"],
        repository_id=repository["id"],
        repository_unique_ref=repository["repository_unique_ref"],
        repository_name_cache=repository["repository_name"],
        is_available=True,
    )


def _remote_target(entry: dict, target_type: cfg_mod.PackageTargetType) -> cfg_mod.PackageTarget:
    customer = entry["customer"]
    remote = entry["remote_repository"]
    family = remote.get("source_family")
    expected_family = "official" if target_type == "official_cache" else "custom"
    if family != expected_family:
        raise ValueError(f"Remote cache is {family or 'of an unknown type'}, not {expected_family}")
    public_name = remote.get("official_slug") or remote.get("remote_name") or remote["public_id"]
    prefix = "mirror" if target_type == "official_cache" else "custom-mirror"
    unique_ref = remote.get("unique_ref") or remote.get("public_id")
    return cfg_mod.PackageTarget(
        target_type=target_type,
        customer_id=customer["customer_id"],
        stable_selector=f"{prefix}:{unique_ref}",
        display_selector=f"{prefix}:{public_name}",
        registry_kind=cast("cfg_mod.RegistryKind", remote["registry_kind"]),
        remote_id=remote.get("id"),
        remote_unique_ref=unique_ref,
        remote_name_cache=public_name,
        source_id=remote.get("source_id"),
        is_available=True,
    )


def resolve_target(
    value: str,
    *,
    profile: str | None = None,
    customer_id: str | None = None,
    kind: str | None = None,
) -> tuple[str, cfg_mod.AccountContext, cfg_mod.PackageTarget]:
    spec = parse_target(value)
    profile_name = profile or cfg_mod.current_profile_name()
    if kind is not None and kind not in {"pypi", "npm", "maven", "container", "helm"}:
        output.fatal(f"Unknown registry kind '{kind}'.")
    if spec.target_type != "private":
        registry_kind: str | None = _package_kind(kind)
    else:
        registry_kind = kind
    client = ApiClient.from_profile(profile_name)
    try:
        if spec.target_type == "private":
            effective_customer_id = customer_id or cfg_mod.current_customer_id(profile_name)
            params = {
                "selector": spec.selector,
                "registry_kind": registry_kind,
            }
            if effective_customer_id is not None:
                params["customer_id"] = effective_customer_id
            entry = client.get(
                "/v0/repositories/resolve",
                params=params,
            ).json()
            raw_customer = entry["customer"]
            raw_customer.setdefault("customer_unique_ref", raw_customer["customer_id"])
            raw_customer.setdefault("account_type", "personal")
            raw_customer.setdefault("account_label", raw_customer["customer_unique_ref"])
            raw_customer.setdefault("organization_role", "owner")
            account = cfg_mod.cache_account(
                profile=profile_name,
                customer=raw_customer,
                activate=customer_id is None,
            )
            target = _private_target(entry)
        else:
            profile_name, account = ensure_active_account(profile_name, customer_id)
            entries = client.get(
                "/v0/remote-repositories",
                params={
                    "customer_id": account.customer_id,
                    "registry_kind": registry_kind,
                },
            ).json()
            expected_family = "official" if spec.target_type == "official_cache" else "custom"
            matches = [
                entry
                for entry in entries
                if entry.get("remote_repository", {}).get("source_family") == expected_family
                and spec.selector
                in {
                    entry["remote_repository"].get("id"),
                    entry["remote_repository"].get("public_id"),
                    entry["remote_repository"].get("unique_ref"),
                    entry["remote_repository"].get("official_slug"),
                    entry["remote_repository"].get("remote_name"),
                }
            ]
            if not matches:
                raise ValueError(f"Package target '{value}' was not found in this account")
            if len(matches) > 1:
                kinds = ", ".join(
                    sorted(
                        {str(item["remote_repository"].get("registry_kind")) for item in matches}
                    )
                )
                raise ValueError(
                    f"Package target '{value}' is ambiguous across {kinds}. Pass --kind."
                )
            target = _remote_target(matches[0], spec.target_type)
    except (ApiError, KeyError, TypeError, ValueError) as exc:
        output.fatal(str(exc))
    return profile_name, account, target


def effective_target(
    *,
    kind: str,
    target: str | None = None,
    repo: str | None = None,
    profile: str | None = None,
    customer_id: str | None = None,
    allow_official_default: bool = False,
) -> tuple[str, cfg_mod.AccountContext, cfg_mod.PackageTarget]:
    registry_kind = _package_kind(kind)
    assert registry_kind is not None
    profile_name, account = ensure_active_account(profile, customer_id)
    explicit = target or repo
    if explicit:
        value = explicit if target else cast("str", repo)
        return resolve_target(
            value,
            profile=profile_name,
            customer_id=account.customer_id,
            kind=kind,
        )
    saved = cfg_mod.selected_package_target(profile_name, account.customer_id)
    if saved is not None:
        if saved.registry_kind is not None and saved.registry_kind != kind:
            output.fatal(
                f"Selected target '{saved.display_selector}' is for {saved.registry_kind}, not {kind}."
            )
        return resolve_target(
            saved.stable_selector,
            profile=profile_name,
            customer_id=account.customer_id,
            kind=kind,
        )
    legacy = cfg_mod.load().registry_defaults(cast("cfg_mod.RegistryKind", kind), profile_name)
    if legacy.default_repo:
        resolved_profile, resolved_account, resolved_target = resolve_target(
            legacy.default_repo,
            profile=profile_name,
            customer_id=account.customer_id,
            kind=kind,
        )
        if all(
            (
                legacy.workspace_id,
                legacy.workspace_unique_ref,
                legacy.workspace_name_cache,
                legacy.repository_id,
                legacy.repository_unique_ref,
                legacy.repository_name_cache,
            )
        ):
            resolved_target = replace(
                resolved_target,
                workspace_id=legacy.workspace_id,
                workspace_unique_ref=legacy.workspace_unique_ref,
                workspace_name_cache=legacy.workspace_name_cache,
                repository_id=legacy.repository_id,
                repository_unique_ref=legacy.repository_unique_ref,
                repository_name_cache=legacy.repository_name_cache,
            )
        return resolved_profile, resolved_account, resolved_target
    if allow_official_default:
        return resolve_target(
            f"mirror:{DEFAULT_OFFICIAL_SOURCES[registry_kind]}",
            profile=profile_name,
            customer_id=account.customer_id,
            kind=kind,
        )
    output.fatal(f"No {kind} package target is selected. Pass --target or run `rvs pkg select`.")


def registry_context(
    *,
    kind: str,
    target: str | None = None,
    repo: str | None = None,
    profile: str | None = None,
    customer_id: str | None = None,
    allow_official_default: bool = False,
    require_private: bool = False,
    operations: tuple[PackageOperation, ...] = ("download",),
) -> RegistryContext:
    profile_name, account, selected = effective_target(
        kind=kind,
        target=target,
        repo=repo,
        profile=profile,
        customer_id=customer_id,
        allow_official_default=allow_official_default,
    )
    if require_private and selected.target_type != "private":
        output.fatal(f"'{selected.display_selector}' is read-only; select a private repository.")
    client = ApiClient.from_profile(profile_name)
    profile_config = cfg_mod.load().active_profile(profile_name)
    registry_kind = cast("PackageKind", kind)
    endpoints = profile_config.native_registries.package(registry_kind)
    try:
        if selected.target_type == "private":
            if not selected.repository_id:
                raise ValueError("Selected private repository has no stable identity")
            credential = client.post(
                "/v0/package-credentials",
                json={
                    "repository_id": selected.repository_id,
                    "registry_kind": kind,
                    "operations": list(operations),
                    "expected_target": {
                        "workspace_id": selected.workspace_id,
                        "workspace_unique_ref": selected.workspace_unique_ref,
                        "workspace_name": selected.workspace_name_cache,
                        "repository_id": selected.repository_id,
                        "repository_unique_ref": selected.repository_unique_ref,
                        "repository_name": selected.repository_name_cache,
                    },
                },
            ).json()
            native_path = credential.get("native_path")
            if not isinstance(native_path, str):
                workspace_name = credential.get("workspace_name") or selected.workspace_name_cache
                repository_name = (
                    credential.get("repository_name") or selected.repository_name_cache
                )
                if not isinstance(workspace_name, str) or not isinstance(repository_name, str):
                    raise ValueError("Private repository resolution omitted its native path")
                native_path = f"/{workspace_name}/{repository_name}"
            native_parts = native_path.strip("/").split("/")
            if len(native_parts) != 2 or not all(native_parts):
                raise ValueError("Private repository resolution returned an invalid native path")
            workspace_reference, repository_reference = native_parts
            read_base_url = endpoints.read_base_url
            push_base_url: str | None = endpoints.push_base_url
        else:
            route_kind = (
                RepositoryRouteKind.REMOTE_OFFICIAL
                if selected.target_type == "official_cache"
                else RepositoryRouteKind.REMOTE_CUSTOM
            )
            workspace_reference = "o" if selected.target_type == "official_cache" else "c"
            credential = client.post(
                "/v0/remote-package-credentials",
                json={
                    "customer_id": account.customer_id,
                    "route_kind": route_kind,
                    "workspace_reference": workspace_reference,
                    "repository_reference": selected.remote_unique_ref,
                    "registry_kind": kind,
                },
            ).json()
            workspace_reference = credential["workspace_reference"]
            repository_reference = credential["repository_reference"]
            read_base_url = endpoints.mirror_base_url
            push_base_url = None
    except (ApiError, KeyError, TypeError, ValueError) as exc:
        output.fatal(str(exc))
    return RegistryContext(
        profile_name=profile_name,
        customer_id=account.customer_id,
        kind=cast("cfg_mod.RegistryKind", kind),
        target=selected,
        read_base_url=read_base_url,
        push_base_url=push_base_url,
        workspace_reference=workspace_reference,
        repository_reference=repository_reference,
        token=credential["access_token"],
    )
