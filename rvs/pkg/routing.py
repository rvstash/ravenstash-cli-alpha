"""Package registry URL helpers for Ravenstash package repository names.

Ravenstash registry protocol routes are intentionally kind-specific:

    PyPI:  https://pypi.{download_host}/{customer_pid}/{repository_name}/simple/
    npm:   https://npm.{download_host}/{customer_pid}/{repository_name}/
    Maven: https://maven.{download_host}/{customer_pid}/{repository_name}/

Local HTTP profiles use the edge/publisher normalized ``/native/{kind}``
prefix because there is no public ingress rewrite in front of them.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def _native_base_url(service_url: str, kind: str) -> str:
    base = service_url.rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "https":
        return f"{base}/native/{kind}"

    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"Invalid registry service URL: {service_url}")

    host = f"{kind}.{hostname}"
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    if parsed.username is not None:
        credentials = parsed.username
        if parsed.password is not None:
            credentials = f"{credentials}:{parsed.password}"
        host = f"{credentials}@{host}"

    return urlunsplit((parsed.scheme, host, parsed.path.rstrip("/"), "", ""))


class CanonicalRouter:
    """Current production routing for package repositories."""

    @staticmethod
    def pypi_index_url(download_url: str, customer_pid: str, repository_name: str) -> str:
        return f"{_native_base_url(download_url, 'pypi')}/{customer_pid}/{repository_name}/simple/"

    @staticmethod
    def pypi_upload_url(upload_url: str, customer_pid: str, repository_name: str) -> str:
        return f"{_native_base_url(upload_url, 'pypi')}/{customer_pid}/{repository_name}/"

    @staticmethod
    def npm_registry_url(download_url: str, customer_pid: str, repository_name: str) -> str:
        return f"{_native_base_url(download_url, 'npm')}/{customer_pid}/{repository_name}/"

    @staticmethod
    def npm_upload_registry_url(upload_url: str, customer_pid: str, repository_name: str) -> str:
        return f"{_native_base_url(upload_url, 'npm')}/{customer_pid}/{repository_name}/"

    @staticmethod
    def maven_repo_url(download_url: str, customer_pid: str, repository_name: str) -> str:
        return f"{_native_base_url(download_url, 'maven')}/{customer_pid}/{repository_name}/"

    @staticmethod
    def maven_upload_url(upload_url: str, customer_pid: str, repository_name: str) -> str:
        return f"{_native_base_url(upload_url, 'maven')}/{customer_pid}/{repository_name}/"
