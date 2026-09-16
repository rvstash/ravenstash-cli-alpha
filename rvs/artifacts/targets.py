"""Artifact-target parsing, resolution, and credential exchange."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal, cast

from .. import config as cfg_mod
from .. import output
from ..account.commands import ensure_active_account
from ..auth.token_format import STATIC_NATIVE_DURATION_SECONDS, validate_public_token
from ..client import ApiClient, ApiError
from ..devapi import collection_items, remote_cache


PackageKind = Literal["pypi", "npm", "maven"]
PackageOperation = Literal["download", "upload"]
DEFAULT_OFFICIAL_SOURCES: dict[PackageKind, str] = {
    "pypi": "pypiorg",
    "npm": "npmjs",
    "maven": "maven-central",
}


@dataclass(frozen=True)
class TargetSpec:
    target_type: cfg_mod.ArtifactTargetType
    selector: str
    namespace_realm: cfg_mod.NamespaceRealm | None = None


@dataclass(frozen=True)
class RegistryContext:
    profile_name: str
    customer_id: str
    kind: cfg_mod.RegistryKind
    target: cfg_mod.ArtifactTarget
    read_base_url: str
    push_base_url: str | None
    route_coordinate: str
    repository_reference: str
    route_realm: Literal["in"] | None
    token: str = field(repr=False)


def parse_target(value: str) -> TargetSpec:
    candidate = value.strip().strip("/")
    if not candidate:
        output.fatal("Artifact target cannot be empty.")
    if candidate.startswith("mirror:"):
        selector = candidate.removeprefix("mirror:").strip().strip("/")
        target_type: cfg_mod.ArtifactTargetType = "official_cache"
        namespace_realm = None
    elif candidate.startswith("custom-mirror:"):
        selector = candidate.removeprefix("custom-mirror:").strip().strip("/")
        target_type = "custom_cache"
        namespace_realm = None
    elif candidate.startswith(("internal:", "global:", "@")):
        output.fatal("Use namespace/repository without a realm prefix or @ notation.")
    elif ":" in candidate:
        output.fatal(
            "Unknown repository or mirror. Use namespace/repository, mirror:<source>, "
            "or custom-mirror:<name>."
        )
    else:
        selector = candidate
        target_type = "repository"
        namespace_realm = None
    if not selector or (target_type != "repository" and "/" in selector):
        output.fatal("The repository or mirror name is invalid.")
    if target_type == "repository":
        parts = selector.split("/")
        if len(parts) != 2 or not all(parts):
            output.fatal("Repository targets must use namespace/repository.")
        namespace_part, repository_part = parts
        typed = namespace_part.startswith(("in_", "gn_", "ar_")) or repository_part.startswith(
            ("in_", "gn_", "ar_")
        )
        if repository_part.startswith("ar_"):
            if namespace_part != "in":
                output.fatal("Stable internal repository targets require in/ar_....")
            namespace_realm = "internal"
        elif typed:
            output.fatal("Typed IDs cannot be used as a name-based repository target.")
    return TargetSpec(
        target_type=target_type,
        selector=selector,
        namespace_realm=namespace_realm,
    )


def _package_kind(kind: str | None) -> PackageKind | None:
    if kind is None:
        return None
    if kind not in DEFAULT_OFFICIAL_SOURCES:
        output.fatal("Remote caches support only pypi, npm, and maven.")
    return cast("PackageKind", kind)


def _repository_target(entry: dict) -> cfg_mod.ArtifactTarget:
    account = entry["account"]
    repository = entry["repository"]
    repository_kinds = [
        item["format"]
        for item in repository.get("formats", [])
        if isinstance(item, dict) and item.get("format") in {"pypi", "npm", "maven", "oci"}
    ]
    inferred_kind = repository_kinds[0] if len(repository_kinds) == 1 else None
    return cfg_mod.ArtifactTarget(
        target_type="repository",
        customer_id=account["account_ref"],
        stable_selector=(f"in/{repository['repository_unique_ref']}"),
        display_selector=f"{repository['namespace_name']}/{repository['repository_name']}",
        registry_kind=cast("cfg_mod.RegistryKind | None", inferred_kind),
        namespace_realm=repository["namespace_realm"],
        namespace_unique_ref=repository["namespace_unique_ref"],
        namespace_name_cache=repository["namespace_name"],
        repository_unique_ref=repository["repository_unique_ref"],
        repository_name_cache=repository["repository_name"],
        is_available=True,
    )


def _remote_target(entry: dict, target_type: cfg_mod.ArtifactTargetType) -> cfg_mod.ArtifactTarget:
    account = entry["account"]
    remote = remote_cache(entry)
    family = remote.get("source_type")
    expected_family = "official" if target_type == "official_cache" else "custom"
    if family != expected_family:
        raise ValueError(f"Remote cache is {family or 'of an unknown type'}, not {expected_family}")
    public_name = (
        remote.get("official_slug") or remote.get("remote_name") or remote["remote_cache_ref"]
    )
    prefix = "mirror" if target_type == "official_cache" else "custom-mirror"
    unique_ref = remote["remote_cache_ref"]
    return cfg_mod.ArtifactTarget(
        target_type=target_type,
        customer_id=account["account_ref"],
        stable_selector=f"{prefix}:{unique_ref}",
        display_selector=f"{prefix}:{public_name}",
        registry_kind=cast("cfg_mod.RegistryKind", remote["format"]),
        remote_id=unique_ref,
        remote_unique_ref=unique_ref,
        remote_name_cache=public_name,
        is_available=True,
    )


def is_stable_repository_selector(selector: str) -> bool:
    """Typed references identify resources; readable names stay account-scoped.

    The API validates reference syntax and authorization. Bare repository refs
    are accepted only by repository-management commands, as before.
    """
    parts = selector.split("/")
    return (len(parts) == 1 and parts[0].startswith("ar_")) or (
        len(parts) == 2 and parts[0] == "in" and parts[1].startswith("ar_")
    )


def resolve_repository_entry(
    client: ApiClient, selector: str, customer_id: str, kind: str | None = None
) -> dict:
    stable = is_stable_repository_selector(selector)
    params = {"selector": selector}
    if not stable:
        params["account_ref"] = customer_id
    if kind is not None:
        params["format"] = kind
    entry = client.get("/repositories/resolve", params=params).json()
    owner = entry["account"]
    if owner["account_ref"] != customer_id:
        if not stable:
            output.fatal("The repository belongs to a different account.")
        output.resource_account_hint(selector, customer_id, owner)
    return entry


def resolve_target(
    value: str,
    *,
    profile: str | None = None,
    customer_id: str | None = None,
    kind: str | None = None,
) -> tuple[str, cfg_mod.AccountContext, cfg_mod.ArtifactTarget]:
    spec = parse_target(value)
    profile_name = profile or cfg_mod.current_profile_name()
    if kind is not None and kind not in {"pypi", "npm", "maven", "oci"}:
        output.fatal(f"Unknown format '{kind}'.")
    if spec.target_type != "repository":
        registry_kind: str | None = _package_kind(kind)
    else:
        registry_kind = kind
    client = ApiClient.from_profile(profile_name)
    try:
        if spec.target_type == "repository":
            effective_customer_id = customer_id or cfg_mod.current_customer_id(profile_name)
            if effective_customer_id is None:
                output.fatal("No account is selected. Run `rvs account switch`.")
            entry = resolve_repository_entry(
                client, spec.selector, effective_customer_id, registry_kind
            )
            raw_customer = entry["account"]
            account = cfg_mod.cache_account(
                profile=profile_name,
                customer=raw_customer,
                activate=False,
            )
            target = _repository_target(entry)
        else:
            profile_name, account = ensure_active_account(profile_name, customer_id)
            entries = collection_items(
                client.get(
                    "/remote-caches",
                    params={
                        key: value
                        for key, value in {
                            "account_ref": account.customer_id,
                            "format": registry_kind,
                        }.items()
                        if value is not None
                    },
                ).json()
            )
            expected_family = "official" if spec.target_type == "official_cache" else "custom"
            matches = []
            for entry in entries:
                remote = remote_cache(entry)
                if remote.get("source_type") == expected_family and spec.selector in {
                    remote.get("remote_cache_ref"),
                    remote.get("official_slug"),
                    remote.get("remote_name"),
                }:
                    matches.append(entry)
            if not matches:
                raise ValueError(f"Package target '{value}' was not found in this account")
            if len(matches) > 1:
                kinds = ", ".join(
                    sorted({str(remote_cache(item).get("format")) for item in matches})
                )
                raise ValueError(
                    f"Package target '{value}' is ambiguous across {kinds}. Pass --format."
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
) -> tuple[str, cfg_mod.AccountContext, cfg_mod.ArtifactTarget]:
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
    saved = cfg_mod.selected_artifact_target(profile_name, account.customer_id)
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
                legacy.namespace_realm,
                legacy.namespace_unique_ref,
                legacy.namespace_name_cache,
                legacy.repository_unique_ref,
                legacy.repository_name_cache,
            )
        ):
            resolved_target = replace(
                resolved_target,
                namespace_realm=legacy.namespace_realm,
                namespace_unique_ref=legacy.namespace_unique_ref,
                namespace_name_cache=legacy.namespace_name_cache,
                repository_unique_ref=legacy.repository_unique_ref,
                repository_name_cache=legacy.repository_name_cache,
            )
        return resolved_profile, resolved_account, resolved_target
    output.fatal(
        f"No {kind} repository or mirror is selected. Pass --target or run `rvs art select`."
    )


def registry_context(
    *,
    kind: str,
    target: str | None = None,
    repo: str | None = None,
    profile: str | None = None,
    customer_id: str | None = None,
    require_private: bool = False,
    operations: tuple[PackageOperation, ...] = ("download",),
) -> RegistryContext:
    profile_name, account, selected = effective_target(
        kind=kind,
        target=target,
        repo=repo,
        profile=profile,
        customer_id=customer_id,
    )
    if require_private and selected.target_type != "repository":
        output.fatal(f"'{selected.display_selector}' is read-only; select a private repository.")
    client = ApiClient.from_profile(profile_name)
    profile_config = cfg_mod.load().active_profile(profile_name)
    registry_kind = cast("PackageKind", kind)
    endpoints = profile_config.native_registries.package(registry_kind)
    try:
        if selected.target_type == "repository":
            if not selected.repository_unique_ref:
                raise ValueError("Selected private repository has no stable identity")
            credential = client.issue_native(
                "/package-credentials",
                {
                    "repository_unique_ref": selected.repository_unique_ref,
                    "formats": [kind],
                    "operations": list(operations),
                    "duration_seconds": STATIC_NATIVE_DURATION_SECONDS,
                    "expected_target": {
                        "namespace_unique_ref": selected.namespace_unique_ref,
                        "namespace_name": selected.namespace_name_cache,
                        "namespace_realm": selected.namespace_realm,
                        "repository_unique_ref": selected.repository_unique_ref,
                        "repository_name": selected.repository_name_cache,
                    },
                },
            ).json()
            native_path = credential.get("native_paths", {}).get(kind)
            if not isinstance(native_path, str):
                raise ValueError("Private repository resolution omitted its native path")
            native_parts = native_path.strip("/").split("/")
            if (
                credential.get("native_realm") != "in"
                or len(native_parts) != 2
                or native_parts != ["in", selected.repository_unique_ref]
            ):
                raise ValueError("Private repository resolution returned an invalid native path")
            route_coordinate, repository_reference = native_parts
            route_realm: Literal["in"] | None = "in"
            read_base_url = endpoints.read_base_url
            push_base_url: str | None = endpoints.push_base_url
        else:
            credential = client.issue_native(
                "/remote-package-credentials",
                {
                    "account_ref": account.customer_id,
                    "remote_cache_ref": selected.remote_unique_ref,
                    "duration_seconds": STATIC_NATIVE_DURATION_SECONDS,
                    "format": kind,
                },
            ).json()
            native_parts = credential["native_path"].strip("/").split("/")
            if len(native_parts) != 2 or not all(native_parts):
                raise ValueError("Remote cache resolution returned an invalid native path")
            route_coordinate, repository_reference = native_parts
            route_realm = None
            read_base_url = endpoints.mirror_base_url
            push_base_url = None
        native_token = validate_public_token(credential["access_token"], native=True)
    except (ApiError, KeyError, TypeError, ValueError) as exc:
        output.fatal(str(exc))
    return RegistryContext(
        profile_name=profile_name,
        customer_id=account.customer_id,
        kind=cast("cfg_mod.RegistryKind", kind),
        target=selected,
        read_base_url=read_base_url,
        push_base_url=push_base_url,
        route_coordinate=route_coordinate,
        repository_reference=repository_reference,
        route_realm=route_realm,
        token=native_token,
    )
