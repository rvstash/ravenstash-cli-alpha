"""Compatibility-channel policy for signed Ravenstash APT releases."""

from __future__ import annotations

import re


_CHANNEL_PATTERN = re.compile(r"^v([0-9]+)\.([0-9]+)$")
_VERSION_PATTERN = re.compile(
    r"^([0-9]+)\.([0-9]+)\.([0-9]+)(?:rc[1-9][0-9]*|[~+.-][A-Za-z0-9.-]+)?$"
)


def channel_for_version(version: str) -> str:
    """Return the compatibility channel that owns a Debian package version."""
    match = _VERSION_PATTERN.fullmatch(version)
    if match is None:
        raise ValueError(f"unsupported rvs version: {version}")
    major, minor, _patch = (int(value) for value in match.groups()[:3])
    return f"v{major}.{minor}"


def normalize_channel(value: str) -> str:
    """Normalize a user-facing release series such as ``0.14`` or ``v1.1``."""
    candidate = value if value.startswith("v") else f"v{value}"
    if _CHANNEL_PATTERN.fullmatch(candidate) is None:
        raise ValueError("release series must look like 0.14 or v1.1")
    return candidate


def version_matches_channel(version: str, channel: str) -> bool:
    try:
        return channel_for_version(version) == normalize_channel(channel)
    except ValueError:
        return False


def channel_order(channel: str) -> tuple[int, int]:
    """Return a monotonic ordering key for explicit forward upgrades."""
    normalized = normalize_channel(channel)
    match = _CHANNEL_PATTERN.fullmatch(normalized)
    assert match is not None
    return (int(match.group(1)), int(match.group(2)))
