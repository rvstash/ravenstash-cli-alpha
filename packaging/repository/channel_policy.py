#!/usr/bin/env python3
"""Compatibility-channel policy and signed manifest generation."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


CHANNEL_PATTERN = re.compile(r"^v([0-9]+)\.([0-9]+)$")
VERSION_PATTERN = re.compile(
    r"^([0-9]+)\.([0-9]+)\.([0-9]+)(?:rc[1-9][0-9]*|[~+.-][A-Za-z0-9.-]+)?$"
)


def channel_for_version(version: str) -> str:
    match = VERSION_PATTERN.fullmatch(version)
    if match is None:
        raise ValueError(f"unsupported rvs version: {version}")
    major, minor, _patch = (int(value) for value in match.groups()[:3])
    return f"v{major}.{minor}"


def normalize_channel(value: str) -> str:
    candidate = value if value.startswith("v") else f"v{value}"
    if CHANNEL_PATTERN.fullmatch(candidate) is None:
        raise ValueError("invalid compatibility channel")
    return candidate


def compatibility_channel(distribution: str) -> str:
    return normalize_channel(distribution)


def version_matches_channel(version: str, channel: str) -> bool:
    try:
        return channel_for_version(version) == normalize_channel(channel)
    except ValueError:
        return False


def stanzas(text: str) -> list[str]:
    return [block for block in text.strip().split("\n\n") if block.strip()]


def stanza_fields(stanza: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in stanza.splitlines():
        if line.startswith((" ", "\t")):
            continue
        key, separator, value = line.partition(":")
        if separator:
            result[key] = value.strip()
    return result


def filter_packages(text: str, channel: str, architecture: str | None = None) -> str:
    normalized = normalize_channel(channel)
    selected: list[str] = []
    for stanza in stanzas(text):
        fields = stanza_fields(stanza)
        version = fields.get("Version", "")
        if version_matches_channel(version, normalized) and (
            architecture is None or fields.get("Architecture") == architecture
        ):
            selected.append(stanza)
    return "\n\n".join(selected) + ("\n" if selected else "")


def newer(left: str, right: str) -> bool:
    result = subprocess.run(
        ["dpkg", "--compare-versions", left, "gt", right],
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def latest_version(packages_file: Path, channel: str) -> str:
    versions = [
        fields["Version"]
        for block in stanzas(packages_file.read_text(encoding="utf-8"))
        if (fields := stanza_fields(block)).get("Package") == "rvs"
        and version_matches_channel(fields.get("Version", ""), channel)
    ]
    if not versions:
        raise ValueError(f"channel {channel} has no rvs packages")
    latest = versions[0]
    for candidate in versions[1:]:
        if newer(candidate, latest):
            latest = candidate
    return latest


def manifest(repository: Path, recommended: str) -> dict[str, Any]:
    recommended = normalize_channel(recommended)
    channels: dict[str, dict[str, str]] = {}
    for distribution in sorted((repository / "dists").iterdir()):
        if not distribution.is_dir():
            continue
        channel = normalize_channel(distribution.name)
        packages = distribution / "main/binary-amd64/Packages"
        if not packages.is_file():
            continue
        channels[channel] = {
            "latest": latest_version(packages, channel),
            "migration_notes": (
                "https://docs.ravenstash.com/cli/releases/"
                f"{channel.removeprefix('v').replace('.', '-')}/"
            ),
            "status": "supported",
        }
    if recommended not in channels:
        raise ValueError(f"recommended channel {recommended} is not published")
    return {"channels": channels, "recommended": recommended, "schema": 1}


def existing_recommended(repository: Path, fallback: str) -> str:
    path = repository / "channels.json"
    if not path.is_file():
        return normalize_channel(fallback)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return normalize_channel(payload["recommended"])


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    channel_parser = subparsers.add_parser("channel-for-version")
    channel_parser.add_argument("version")
    compatibility_parser = subparsers.add_parser("compatibility-channel")
    compatibility_parser.add_argument("distribution")
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("version")
    validate_parser.add_argument("channel")
    filter_parser = subparsers.add_parser("filter")
    filter_parser.add_argument("channel")
    filter_parser.add_argument("--architecture", choices=("amd64", "arm64"))
    manifest_parser = subparsers.add_parser("manifest")
    manifest_parser.add_argument("repository", type=Path)
    manifest_parser.add_argument("recommended")
    recommended_parser = subparsers.add_parser("existing-recommended")
    recommended_parser.add_argument("repository", type=Path)
    recommended_parser.add_argument("fallback")
    arguments = parser.parse_args()

    try:
        if arguments.command == "channel-for-version":
            print(channel_for_version(arguments.version))
        elif arguments.command == "compatibility-channel":
            print(compatibility_channel(arguments.distribution))
        elif arguments.command == "validate":
            channel = normalize_channel(arguments.channel)
            if not version_matches_channel(arguments.version, channel):
                raise ValueError(
                    f"version {arguments.version} does not belong to channel {channel}"
                )
        elif arguments.command == "filter":
            sys.stdout.write(
                filter_packages(sys.stdin.read(), arguments.channel, arguments.architecture)
            )
        elif arguments.command == "manifest":
            print(
                json.dumps(
                    manifest(arguments.repository, arguments.recommended),
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(existing_recommended(arguments.repository, arguments.fallback))
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise SystemExit(f"error: {exc}") from exc


if __name__ == "__main__":
    main()
