#!/usr/bin/env python3
"""Small command-line adapter for the source APT compatibility policy."""

from __future__ import annotations

import argparse
import sys

from rvs.apt_channels import channel_for_version, normalize_channel, version_matches_channel


def stanzas(text: str) -> list[str]:
    return [block for block in text.strip().split("\n\n") if block.strip()]


def stanza_version(stanza: str) -> str:
    for line in stanza.splitlines():
        if line.startswith("Version:"):
            return line.partition(":")[2].strip()
    raise SystemExit("error: APT package stanza has no Version")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    channel_parser = subparsers.add_parser("channel-for-version")
    channel_parser.add_argument("version")
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("version")
    validate_parser.add_argument("channel")
    filter_parser = subparsers.add_parser("filter")
    filter_parser.add_argument("channel")
    arguments = parser.parse_args()

    if arguments.command == "channel-for-version":
        print(channel_for_version(arguments.version))
        return
    channel = normalize_channel(arguments.channel)
    if arguments.command == "validate":
        if not version_matches_channel(arguments.version, channel):
            raise SystemExit(
                f"error: version {arguments.version} does not belong to channel {channel}"
            )
        return
    selected = [
        block for block in stanzas(sys.stdin.read()) if version_matches_channel(stanza_version(block), channel)
    ]
    if selected:
        sys.stdout.write("\n\n".join(selected) + "\n")


if __name__ == "__main__":
    main()
