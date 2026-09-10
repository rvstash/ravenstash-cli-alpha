"""Package registry URL helpers for stable Ravenstash repository references.

Ravenstash registry protocol routes are intentionally kind-specific:

    PyPI:  https://pypi.rvsta.sh/{namespace_ref}/{repository_ref}/simple/
    npm:   https://npm.rvsta.sh/{namespace_ref}/{repository_ref}/
    Maven: https://maven.rvsta.sh/{namespace_ref}/{repository_ref}/

Each service URL is an exact discovered endpoint. No hostname labels are derived.
"""

from __future__ import annotations

from enum import StrEnum
from urllib.parse import urlparse


class RepositoryRouteKind(StrEnum):
    """Package credential route families understood by DevAPI."""

    PRIVATE = "private"
    REMOTE_OFFICIAL = "remote_official"
    REMOTE_CUSTOM = "remote_custom"


def native_base_url(service_url: str) -> str:
    return service_url.rstrip("/")


def npm_auth_token_key(registry_url: str) -> str:
    """Return npm's environment/config key for one exact registry URL."""
    parsed = urlparse(registry_url)
    path = parsed.path or "/"
    if not path.endswith("/"):
        path += "/"
    return f"//{parsed.netloc}{path}:_authToken"


class CanonicalRouter:
    """Current production routing for package repositories."""

    @staticmethod
    def pypi_index_url(download_url: str, namespace_ref: str, repository_ref: str) -> str:
        return f"{native_base_url(download_url)}/{namespace_ref}/{repository_ref}/simple/"

    @staticmethod
    def pypi_upload_url(upload_url: str, namespace_ref: str, repository_ref: str) -> str:
        return f"{native_base_url(upload_url)}/{namespace_ref}/{repository_ref}/"

    @staticmethod
    def npm_registry_url(download_url: str, namespace_ref: str, repository_ref: str) -> str:
        return f"{native_base_url(download_url)}/{namespace_ref}/{repository_ref}/"

    @staticmethod
    def npm_upload_registry_url(upload_url: str, namespace_ref: str, repository_ref: str) -> str:
        return f"{native_base_url(upload_url)}/{namespace_ref}/{repository_ref}/"

    @staticmethod
    def maven_repo_url(download_url: str, namespace_ref: str, repository_ref: str) -> str:
        return f"{native_base_url(download_url)}/{namespace_ref}/{repository_ref}/"

    @staticmethod
    def maven_upload_url(upload_url: str, namespace_ref: str, repository_ref: str) -> str:
        return f"{native_base_url(upload_url)}/{namespace_ref}/{repository_ref}/"
