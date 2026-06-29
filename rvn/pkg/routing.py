"""Package registry URL helpers for Ravenstash package repository names.

Ravenstash registry protocol routes are intentionally kind-specific:

    PyPI:  {api_url}/n/pypi/x/{customer_pid}/{repository_name}/simple/
    npm:   {api_url}/n/npm/x/{customer_pid}/{repository_name}/
    Maven: {api_url}/n/maven/x/{customer_pid}/{repository_name}/
"""

from __future__ import annotations


class CanonicalRouter:
    """Current production routing for package repositories."""

    @staticmethod
    def pypi_index_url(api_url: str, customer_pid: str, repository_name: str) -> str:
        return f"{api_url.rstrip('/')}/n/pypi/x/{customer_pid}/{repository_name}/simple/"

    @staticmethod
    def pypi_upload_url(api_url: str, customer_pid: str, repository_name: str) -> str:
        return f"{api_url.rstrip('/')}/n/pypi/x/{customer_pid}/{repository_name}/"

    @staticmethod
    def npm_registry_url(api_url: str, customer_pid: str, repository_name: str) -> str:
        return f"{api_url.rstrip('/')}/n/npm/x/{customer_pid}/{repository_name}/"

    @staticmethod
    def npm_upload_registry_url(api_url: str, customer_pid: str, repository_name: str) -> str:
        return f"{api_url.rstrip('/')}/n/npm/x/{customer_pid}/{repository_name}/"

    @staticmethod
    def maven_repo_url(api_url: str, customer_pid: str, repository_name: str) -> str:
        return f"{api_url.rstrip('/')}/n/maven/x/{customer_pid}/{repository_name}/"

    @staticmethod
    def maven_upload_url(api_url: str, customer_pid: str, repository_name: str) -> str:
        return f"{api_url.rstrip('/')}/n/maven/x/{customer_pid}/{repository_name}/"
