#!/usr/bin/env python3
"""Create a verified-scope APT tree that retains only newer compatibility lines."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path, PurePosixPath
from typing import Any

from channel_policy import LEGACY_ALIASES, manifest, normalize_channel, stanza_fields, stanzas


def channel_key(channel: str) -> tuple[int, int]:
    normalized = normalize_channel(channel)
    match = re.fullmatch(r"v([0-9]+)\.([0-9]+)", normalized)
    if match is None:  # normalize_channel already enforces this grammar.
        raise ValueError(f"invalid compatibility channel: {channel}")
    return int(match[1]), int(match[2])


def package_paths(repository: Path, distributions: set[str]) -> set[PurePosixPath]:
    paths: set[PurePosixPath] = set()
    for distribution in sorted(distributions):
        for index in sorted(
            (repository / "dists" / distribution / "main").glob("binary-*/Packages")
        ):
            for stanza in stanzas(index.read_text(encoding="utf-8")):
                fields = stanza_fields(stanza)
                if fields.get("Package") != "rvs" or "Filename" not in fields:
                    raise ValueError(f"invalid package stanza in {index}")
                path = PurePosixPath(fields["Filename"])
                if path.is_absolute() or ".." in path.parts or path.suffix != ".deb":
                    raise ValueError(f"unsafe package path in {index}: {path}")
                paths.add(path)
    return paths


def prune(repository: Path, minimum: str) -> dict[str, Any]:
    minimum = normalize_channel(minimum)
    minimum_key = channel_key(minimum)
    distributions = {
        path.name
        for path in (repository / "dists").iterdir()
        if path.is_dir() and (path / "InRelease").is_file()
    }
    if minimum not in distributions:
        raise ValueError(f"minimum retained channel is not published: {minimum}")

    removed_distributions: set[str] = set()
    retained_distributions: set[str] = set()
    for distribution in distributions:
        normalized = LEGACY_ALIASES.get(distribution, distribution)
        if channel_key(normalized) < minimum_key:
            removed_distributions.add(distribution)
        else:
            retained_distributions.add(distribution)
    if not removed_distributions or not retained_distributions:
        raise ValueError("prune must remove and retain at least one signed distribution")

    retained_packages = package_paths(repository, retained_distributions)
    present_packages = {
        PurePosixPath(path.relative_to(repository).as_posix())
        for path in (repository / "pool").rglob("*.deb")
    }
    missing = retained_packages - present_packages
    if missing:
        raise ValueError(f"retained package is missing: {sorted(map(str, missing))}")
    removed_packages = present_packages - retained_packages

    for distribution in removed_distributions:
        shutil.rmtree(repository / "dists" / distribution)
    for package in removed_packages:
        repository.joinpath(*package.parts).unlink()

    prior_manifest = json.loads((repository / "channels.json").read_text(encoding="utf-8"))
    recommended = normalize_channel(prior_manifest["recommended"])
    if channel_key(recommended) < minimum_key:
        recommended = max(
            (
                distribution
                for distribution in retained_distributions
                if distribution not in LEGACY_ALIASES
            ),
            key=channel_key,
        )
    updated_manifest = manifest(repository, recommended)
    (repository / "channels.json").write_text(
        json.dumps(updated_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (repository / "channels.json.gpg").unlink(missing_ok=True)

    return {
        "minimum_retained_channel": minimum,
        "removed_distributions": sorted(removed_distributions),
        "removed_packages": sorted(map(str, removed_packages)),
        "retained_distributions": sorted(retained_distributions),
        "retained_packages": sorted(map(str, retained_packages)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repository", type=Path)
    parser.add_argument("--minimum", required=True)
    parser.add_argument("--plan", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        plan = prune(arguments.repository, arguments.minimum)
        arguments.plan.write_text(
            json.dumps(plan, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"error: {exc}") from exc
    print(
        f"Pruned {len(plan['removed_distributions'])} distributions and "
        f"{len(plan['removed_packages'])} packages below {plan['minimum_retained_channel']}."
    )


if __name__ == "__main__":
    main()
