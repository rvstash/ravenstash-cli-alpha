"""Shared types and abstract base for registry adapters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PublishResult:
    filename: str
    version: str
    ok: bool
    detail: str | None = None
