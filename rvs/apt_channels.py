"""Compatibility-channel policy for signed Ravenstash APT releases."""

from __future__ import annotations

import re


_CHANNEL_PATTERN = re.compile(r"^v(?:(0)\.([0-9]+)|([1-9][0-9]*))$")
_VERSION_PATTERN = re.compile(r"^([0-9]+)\.([0-9]+)\.([0-9]+)(?:[~+.-][A-Za-z0-9.-]+)?$")


def channel_for_version(version: str) -> str:
    """Return the compatibility channel that owns a Debian package version."""
    match = _VERSION_PATTERN.fullmatch(version)
    if match is None:
        raise ValueError(f"unsupported rvs version: {version}")
    major, minor, _patch = (int(value) for value in match.groups()[:3])
    return f"v0.{minor}" if major == 0 else f"v{major}"


def normalize_channel(value: str) -> str:
    """Normalize a user-facing channel such as ``0.4`` or ``1``."""
    candidate = value if value.startswith("v") else f"v{value}"
    if _CHANNEL_PATTERN.fullmatch(candidate) is None:
        raise ValueError("channels must look like 0.4, v0.4, 1, or v1")
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
    if match.group(1) == "0":
        return (0, int(match.group(2)))
    return (int(match.group(3)), 0)
