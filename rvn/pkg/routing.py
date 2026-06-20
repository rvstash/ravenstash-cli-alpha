"""Package registry URL helpers for Ravenstash repository public IDs.

Ravenstash registry protocol routes are intentionally kind-specific:

    PyPI:  {api_url}/pypi/r/{repo_id}/simple/
    npm:   {api_url}/npm/r/{repo_id}/
    Maven: {api_url}/maven/r/{repo_id}/
"""

from __future__ import annotations


class CanonicalRouter:
    """Current production routing for package repositories."""

    @staticmethod
    def pypi_index_url(api_url: str, repo_id: str) -> str:
        return f"{api_url.rstrip('/')}/pypi/r/{repo_id}/simple/"

    @staticmethod
    def pypi_upload_url(api_url: str, repo_id: str) -> str:
        return f"{api_url.rstrip('/')}/pypi/r/{repo_id}/"

    @staticmethod
    def npm_registry_url(api_url: str, repo_id: str) -> str:
        return f"{api_url.rstrip('/')}/npm/r/{repo_id}/"

    @staticmethod
    def maven_repo_url(api_url: str, repo_id: str) -> str:
        return f"{api_url.rstrip('/')}/maven/r/{repo_id}/"
