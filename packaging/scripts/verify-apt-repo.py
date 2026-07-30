#!/usr/bin/env python3
"""Verify a complete Ravenstash APT repository against a trusted keyring."""

from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import gzip
import hashlib
import subprocess
import tempfile
from pathlib import Path, PurePosixPath


def fail(message: str) -> None:
    raise SystemExit(f"error: {message}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        fail(f"unsafe repository path: {value}")
    return path


def release_hashes(text: str) -> dict[PurePosixPath, tuple[str, int]]:
    in_sha256 = False
    entries: dict[PurePosixPath, tuple[str, int]] = {}
    for line in text.splitlines():
        if line == "SHA256:":
            in_sha256 = True
            continue
        if in_sha256 and line and not line.startswith(" "):
            break
        if not in_sha256 or not line.strip():
            continue
        fields = line.split()
        if len(fields) != 3:
            fail("malformed SHA256 entry in Release")
        digest, size_text, name = fields
        if len(digest) != 64:
            fail("malformed SHA256 digest in Release")
        path = safe_relative(name)
        if path in entries:
            fail(f"duplicate Release entry: {name}")
        entries[path] = (digest.lower(), int(size_text))
    return entries


def release_field(text: str, name: str) -> str:
    prefix = f"{name}:"
    for line in text.splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip()
    fail(f"Release is missing {name}")


def verify_expiry(release: str) -> None:
    valid_until = email.utils.parsedate_to_datetime(release_field(release, "Valid-Until"))
    if valid_until.tzinfo is None:
        fail("Valid-Until has no timezone")
    now = dt.datetime.now(dt.UTC)
    if valid_until <= now:
        fail("APT repository metadata has expired")
    if valid_until > now + dt.timedelta(days=8):
        fail("APT repository validity exceeds the eight-day policy limit")
    if release_field(release, "Acquire-By-Hash").lower() != "yes":
        fail("Release does not require Acquire-By-Hash")


def package_stanzas(text: str) -> list[dict[str, str]]:
    stanzas: list[dict[str, str]] = []
    for raw_stanza in text.strip().split("\n\n"):
        if not raw_stanza.strip():
            continue
        stanza: dict[str, str] = {}
        for line in raw_stanza.splitlines():
            if line.startswith((" ", "\t")):
                continue
            key, separator, value = line.partition(":")
            if separator:
                stanza[key] = value.strip()
        stanzas.append(stanza)
    return stanzas


def verify_packages(repo: Path, packages_file: Path) -> None:
    listed: set[PurePosixPath] = set()
    for stanza in package_stanzas(packages_file.read_text(encoding="utf-8")):
        required = {"Package", "Version", "Architecture", "Filename", "Size", "SHA256"}
        if missing := required - stanza.keys():
            fail(f"Packages stanza is missing: {', '.join(sorted(missing))}")
        if stanza["Package"] != "rvs":
            fail(f"unexpected package in repository: {stanza['Package']}")
        relative = safe_relative(stanza["Filename"])
        if relative in listed or relative.suffix != ".deb":
            fail(f"invalid or duplicate package path: {relative}")
        package = repo.joinpath(*relative.parts)
        if not package.is_file():
            fail(f"listed package is missing: {relative}")
        expected = stanza["SHA256"].lower()
        if sha256(package) != expected or package.stat().st_size != int(stanza["Size"]):
            fail(f"listed package digest or size mismatch: {relative}")
        if f"_{expected[:16]}.deb" not in package.name:
            fail(f"package path is not content-addressed: {relative}")
        fields = subprocess.run(
            [
                "dpkg-deb",
                "--field",
                str(package),
                "Package",
                "Version",
                "Architecture",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        expected_fields = [
            stanza["Package"],
            stanza["Version"],
            stanza["Architecture"],
        ]
        if fields.returncode != 0 or fields.stdout.splitlines() != expected_fields:
            fail(f"Debian control metadata mismatch: {relative}")
        listed.add(relative)

    present = {
        PurePosixPath(path.relative_to(repo).as_posix()) for path in (repo / "pool").rglob("*.deb")
    }
    if present != listed:
        extras = sorted(str(path) for path in present - listed)
        missing = sorted(str(path) for path in listed - present)
        fail(f"pool inventory mismatch; unlisted={extras}, missing={missing}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repository", type=Path)
    parser.add_argument("trusted_keyring", type=Path)
    args = parser.parse_args()
    repo = args.repository.resolve()
    keyring = args.trusted_keyring.resolve()
    in_release = repo / "dists/stable/InRelease"
    if not keyring.is_file() or not in_release.is_file():
        fail("trusted keyring or InRelease is missing")

    with tempfile.TemporaryDirectory(prefix="rvs-apt-verify-") as temp_dir:
        release_path = Path(temp_dir) / "Release"
        verified = subprocess.run(
            [
                "gpgv",
                f"--keyring={keyring}",
                f"--output={release_path}",
                str(in_release),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if verified.returncode != 0:
            fail("InRelease signature verification failed")
        release = release_path.read_text(encoding="utf-8")

    verify_expiry(release)
    entries = release_hashes(release)
    required_metadata = {
        PurePosixPath("main/binary-amd64/Packages"),
        PurePosixPath("main/binary-amd64/Packages.gz"),
    }
    if not required_metadata.issubset(entries):
        fail("Release does not cover the required package indexes")
    dist_root = repo / "dists/stable"
    for relative, (digest, size) in entries.items():
        target = dist_root.joinpath(*relative.parts)
        if not target.is_file():
            fail(f"Release metadata target is missing: {relative}")
        if target.stat().st_size != size or sha256(target) != digest:
            fail(f"Release metadata target mismatch: {relative}")

    packages = dist_root / "main/binary-amd64/Packages"
    compressed = dist_root / "main/binary-amd64/Packages.gz"
    with gzip.open(compressed, "rt", encoding="utf-8") as stream:
        if stream.read() != packages.read_text(encoding="utf-8"):
            fail("Packages.gz does not expand to Packages")
    verify_packages(repo, packages)
    print("APT repository verification passed.")


if __name__ == "__main__":
    main()
