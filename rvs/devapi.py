"""Ravenstash DevAPI version selection and wire-shape helpers."""

from __future__ import annotations

from typing import Any


API_VERSION = "v0"
API_STABILITY = "unstable"


class ApiVersionMismatchError(RuntimeError):
    """The server identified a different wire-contract generation."""


def api_path(path: str) -> str:
    candidate = path.strip("/")
    if candidate == API_VERSION or candidate.startswith(f"{API_VERSION}/"):
        raise ValueError("DevAPI resource paths must not embed an API version")
    return f"/{API_VERSION}/{candidate}" if candidate else f"/{API_VERSION}"


def api_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{api_path(path)}"


def validate_api_version(response: Any) -> None:
    reported = getattr(response, "headers", {}).get("Ravenstash-API-Version")
    if reported is not None and reported != API_VERSION:
        raise ApiVersionMismatchError(
            f"DevAPI returned version {reported!r}; rvs expects {API_VERSION!r}"
        )


def collection_items(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("DevAPI collection response is invalid")
    return payload["items"]


def remote_cache(entry: dict[str, Any]) -> dict[str, Any]:
    value = entry.get("remote_cache")
    if not isinstance(value, dict):
        raise ValueError("DevAPI remote-cache response is invalid")
    return value
