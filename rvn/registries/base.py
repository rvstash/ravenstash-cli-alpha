"""Shared types and abstract base for registry adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class PublishResult:
    filename: str
    version: str
    ok: bool
    detail: str | None = None


@dataclass
class PackageSummary:
    name: str
    version: str
    filename: str
    size_bytes: int | None = None


class RegistryAdapter(Protocol):
    """Minimal protocol every registry adapter must satisfy."""

    kind: str

    def publish(self, repo_url: str, token: str, *args, **kwargs) -> list[PublishResult]: ...
    def install(self, repo_url: str, token: str, *args, **kwargs) -> None: ...
