"""Package registry URL helpers for stable Ravenstash repository references.

Ravenstash registry protocol routes are intentionally kind-specific:

    PyPI:  https://pypi.rvsta.sh/{workspace_ref}/{repository_ref}/simple/
    npm:   https://npm.rvsta.sh/{workspace_ref}/{repository_ref}/
    Maven: https://maven.rvsta.sh/{workspace_ref}/{repository_ref}/

Each service URL is an exact discovered endpoint. No hostname labels are derived.
"""

from __future__ import annotations

from enum import StrEnum


class RepositoryRouteKind(StrEnum):
    """Package credential route families understood by DevAPI."""

    PRIVATE = "private"
    REMOTE_OFFICIAL = "remote_official"
    REMOTE_CUSTOM = "remote_custom"


def native_base_url(service_url: str, kind: str) -> str:
    del kind
    return service_url.rstrip("/")


class CanonicalRouter:
    """Current production routing for package repositories."""

    @staticmethod
    def pypi_index_url(download_url: str, workspace_ref: str, repository_ref: str) -> str:
        return f"{native_base_url(download_url, 'pypi')}/{workspace_ref}/{repository_ref}/simple/"

    @staticmethod
    def pypi_upload_url(upload_url: str, workspace_ref: str, repository_ref: str) -> str:
        return f"{native_base_url(upload_url, 'pypi')}/{workspace_ref}/{repository_ref}/"

    @staticmethod
    def npm_registry_url(download_url: str, workspace_ref: str, repository_ref: str) -> str:
        return f"{native_base_url(download_url, 'npm')}/{workspace_ref}/{repository_ref}/"

    @staticmethod
    def npm_upload_registry_url(upload_url: str, workspace_ref: str, repository_ref: str) -> str:
        return f"{native_base_url(upload_url, 'npm')}/{workspace_ref}/{repository_ref}/"

    @staticmethod
    def maven_repo_url(download_url: str, workspace_ref: str, repository_ref: str) -> str:
        return f"{native_base_url(download_url, 'maven')}/{workspace_ref}/{repository_ref}/"

    @staticmethod
    def maven_upload_url(upload_url: str, workspace_ref: str, repository_ref: str) -> str:
        return f"{native_base_url(upload_url, 'maven')}/{workspace_ref}/{repository_ref}/"
