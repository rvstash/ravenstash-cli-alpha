"""Ravenstash DevAPI version selection, path builders, and wire-shape helpers.

Every DevAPI resource lives below one API generation and one owning group:
``/v0/platform/...`` for platform identity and sign-in, and ``/v0/{product}/...``
for product resources such as ``/v0/artifacts/...``. Command modules pass
group-relative paths to :func:`platform_path` or :func:`artifacts_path`; they
never spell the version or group segments themselves.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote


API_VERSION = "v0"
API_STABILITY = "unstable"
PLATFORM_GROUP = "platform"
ARTIFACTS_PRODUCT = "artifacts"
API_ROUTE_RETIRED = "ApiRouteRetired"

_GROUPS = frozenset({PLATFORM_GROUP, ARTIFACTS_PRODUCT})
_ROOT_RESOURCES = frozenset({"meta"})
_VERSION_SEGMENT = re.compile(r"v[0-9]+(?:(?:alpha|beta)[0-9]*)?")
_MINT_TOKEN_PATH = re.compile(
    rf"/{API_VERSION}/{ARTIFACTS_PRODUCT}/(?:repositories|remote-caches)/[^/]+/mint-token"
)


class ApiVersionMismatchError(RuntimeError):
    """The server identified a different wire-contract generation."""


def _relative(path: str) -> str:
    candidate = path.strip("/")
    first = candidate.split("/", 1)[0]
    if _VERSION_SEGMENT.fullmatch(first):
        raise ValueError("DevAPI resource paths must not embed an API version")
    if first in _GROUPS:
        raise ValueError(
            "DevAPI resource paths must not embed a platform or product segment; "
            "use platform_path or artifacts_path"
        )
    return candidate


def _grouped(group: str, path: str) -> str:
    candidate = _relative(path)
    if not candidate:
        raise ValueError(f"A {group} resource path is required")
    return f"/{API_VERSION}/{group}/{candidate}"


def api_path(path: str) -> str:
    """Return an ungrouped generation resource path such as ``/v0/meta``."""
    candidate = _relative(path)
    if candidate not in _ROOT_RESOURCES:
        raise ValueError("Only generation metadata is outside a platform or product group")
    return f"/{API_VERSION}/{candidate}"


def platform_path(path: str) -> str:
    """Return a platform (identity, accounts, sign-in) resource path."""
    return _grouped(PLATFORM_GROUP, path)


def artifacts_path(path: str) -> str:
    """Return an Artifacts product resource path."""
    return _grouped(ARTIFACTS_PRODUCT, path)


def segment(value: str) -> str:
    """Encode one caller-supplied path segment, such as a reference or digest."""
    if not value:
        raise ValueError("DevAPI path segments cannot be empty")
    return quote(value, safe="")


def is_mint_token_path(path: str) -> bool:
    return _MINT_TOKEN_PATH.fullmatch(path) is not None


def repository_mint_token_path(repository_ref: str) -> str:
    return artifacts_path(f"repositories/{segment(repository_ref)}/mint-token")


def remote_cache_mint_token_path(remote_cache_ref: str) -> str:
    return artifacts_path(f"remote-caches/{segment(remote_cache_ref)}/mint-token")


def api_url(base_url: str, path: str) -> str:
    """Join a control-plane base URL with a path built by a builder above."""
    parts = path.split("/")
    grouped = len(parts) > 3 and parts[2] in _GROUPS and all(parts[3:])
    root_resource = len(parts) == 3 and parts[2] in _ROOT_RESOURCES
    if parts[:2] != ["", API_VERSION] or not (grouped or root_resource):
        raise ValueError("Build DevAPI paths with api_path, platform_path, or artifacts_path")
    return f"{base_url.rstrip('/')}{path}"


def validate_api_version(response: Any) -> None:
    reported = getattr(response, "headers", {}).get("Ravenstash-API-Version")
    if reported is not None and reported != API_VERSION:
        raise ApiVersionMismatchError(
            f"DevAPI returned version {reported!r}; rvs expects {API_VERSION!r}"
        )


def retired_route_message(response: Any) -> str | None:
    """Return the server's upgrade message for a retired DevAPI route."""
    if getattr(response, "status_code", None) != 410:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict) or error.get("code") != API_ROUTE_RETIRED:
        return None
    message = error.get("message")
    return message if isinstance(message, str) and message else API_ROUTE_RETIRED


def collection_items(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("DevAPI collection response is invalid")
    return payload["items"]
