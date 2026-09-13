"""Read-only discovery shared by endpoint, reference, token and setup commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from .. import config as cfg
from ..account.commands import resolve_account
from ..client import ApiClient
from ..devapi import collection_items, remote_cache
from ..oci.registry import normalized_registry_host
from ..oci.runner import _friendly_oci_root
from .formats import FORMATS
from .routing import CanonicalRouter
from .targets import (
    PackageKind,
    _remote_target,
    _repository_target,
    parse_target,
    resolve_repository_entry,
)


@dataclass(frozen=True)
class Discovery:
    profile: str
    target: cfg.ArtifactTarget
    formats: tuple[str, ...]
    native_path: tuple[str, str]

    @property
    def oci_plain_http(self) -> bool:
        from urllib.parse import urlsplit

        registries = cfg.load().active_profile(self.profile).native_registries
        return urlsplit(registries.oci_registry_base_url).scheme == "http"

    def select_format(self, value: str | None, applicable: tuple[str, ...] = FORMATS) -> str:
        choices = tuple(item for item in self.formats if item in applicable)
        if value is not None:
            if value not in choices:
                raise ValueError(f"Format '{value}' is not enabled or applicable to this target.")
            return value
        if len(choices) != 1:
            raise ValueError("Select one enabled format with --format.")
        return choices[0]

    def endpoint(self, kind: str, access: str = "read") -> str:
        self.select_format(kind)
        if access not in {"read", "publish"}:
            raise ValueError("Endpoint access must be read or publish.")
        if access == "publish" and self.target.target_type != "repository":
            raise ValueError("Private mirrors are read-only.")
        registries = cfg.load().active_profile(self.profile).native_registries
        if kind in {"container", "helm"}:
            return normalized_registry_host(registries.oci_registry_base_url)
        endpoints = registries.package(cast("PackageKind", kind))
        base = (
            endpoints.push_base_url
            if access == "publish"
            else (
                endpoints.read_base_url
                if self.target.target_type == "repository"
                else endpoints.mirror_base_url
            )
        )
        router = CanonicalRouter()
        if kind == "pypi":
            route = router.pypi_index_url if access == "read" else router.pypi_upload_url
        elif kind == "maven":
            route = router.maven_repo_url if access == "read" else router.maven_upload_url
        else:
            route = router.npm_registry_url if access == "read" else router.npm_upload_registry_url
        return route(base, *self.native_path)

    def reference(self, kind: str, operand: str | None = None) -> str:
        from ..oci.reference import qualify_reference

        self.select_format(kind, ("container", "helm"))
        root = _friendly_oci_root(
            self.target.namespace_name_cache, self.target.repository_name_cache
        )
        return qualify_reference(f"{self.endpoint(kind)}/{root}", operand)


def discover(
    target: str | None, profile: str | None, account: str | None, kind: str | None = None
) -> Discovery:
    profile_name = profile or cfg.current_profile_name()
    customer_id = (
        str(resolve_account(account, profile_name)["customer_id"])
        if account
        else cfg.current_customer_id(profile_name)
    )
    if not customer_id:
        raise ValueError("No account is selected. Run rvs account use USERNAME_OR_HANDLE.")
    if target is None:
        saved = cfg.selected_artifact_target(profile_name, customer_id)
        if saved is None:
            raise ValueError("No target is selected. Pass --target or run rvs art select.")
        target = saved.stable_selector
    spec = parse_target(target)
    client = ApiClient.from_profile(profile_name)
    if spec.target_type == "repository":
        entry = resolve_repository_entry(client, spec.selector, customer_id)
        selected = _repository_target(entry)
        formats = tuple(item for item in entry["repository"]["registry_kinds"] if item in FORMATS)
        path = (str(selected.namespace_unique_ref), str(selected.repository_unique_ref))
    else:
        params = {"customer_id": customer_id}
        if kind is not None:
            params["registry_kind"] = kind
        entries = collection_items(client.get("/remote-caches", params=params).json())
        family = "official" if spec.target_type == "official_cache" else "custom"
        matches = [
            item
            for item in entries
            if (remote := remote_cache(item)).get("source_type") == family
            and spec.selector
            in {
                remote.get("remote_cache_ref"),
                remote.get("official_slug"),
                remote.get("remote_name"),
            }
        ]
        if len(matches) != 1:
            raise ValueError(
                "Mirror was not found or is ambiguous; specify --account and --format."
            )
        selected = _remote_target(matches[0], spec.target_type)
        remote = remote_cache(matches[0])
        formats = (str(remote["registry_kind"]),)
        path = (
            "o" if family == "official" else "c",
            str(remote["official_slug"] if family == "official" else remote["remote_name"]),
        )
    if not formats:
        raise ValueError("The target has no enabled formats.")
    return Discovery(profile_name, selected, formats, path)
