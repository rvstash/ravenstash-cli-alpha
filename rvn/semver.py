"""Shared semver utilities used across rvn ecosystem command modules."""

from __future__ import annotations

import re

from . import output


_VALID_PARTS = {"major", "minor", "patch"}


def bump_semver(version: str, part: str) -> str:
    """Increment *major*, *minor*, or *patch* in a semver string.

    Pre-release and build-metadata suffixes are stripped before parsing and
    the result is always a clean ``X.Y.Z`` string.

        >>> bump_semver("1.2.3", "patch")
        '1.2.4'
        >>> bump_semver("1.2.3-SNAPSHOT", "minor")
        '1.3.0'
        >>> bump_semver("v2.0.0+build.1", "major")
        '3.0.0'
    """
    v = version.strip().lstrip("v")
    base = re.split(r"[-+]", v)[0]
    segments = base.split(".")
    while len(segments) < 3:
        segments.append("0")
    major, minor, patch = int(segments[0]), int(segments[1]), int(segments[2])
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def validate_bump_part(part: str) -> None:
    """Call ``output.fatal`` and exit if *part* is not major/minor/patch."""
    if part not in _VALID_PARTS:
        output.fatal(
            f"Invalid bump value '{part}'. Must be one of: {', '.join(sorted(_VALID_PARTS))}"
        )
