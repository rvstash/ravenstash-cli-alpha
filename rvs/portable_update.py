"""Authenticated download and atomic activation for portable rvs installations."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

import httpx2 as httpx

from .apt_channels import minor_target_for_version, normalize_channel, normalize_minor_target
from .installations import RECEIPT_NAME, Installation, compatibility_channel, write_receipt
from .update_trust import VerificationError, verify_detached


if TYPE_CHECKING:
    from collections.abc import Iterator


REPOSITORY = "rvstash/ravenstash-cli-alpha"
RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}"
RELEASE_DOWNLOAD_ROOT = f"https://github.com/{REPOSITORY}/releases/download"
CHANNELS_URL = "https://releases.ravenstash.com/rvs/channels.json"
_VERSION = re.compile(
    r"^(?P<major>[0-9]+)\.(?P<minor>[0-9]+)\.(?P<patch>[0-9]+)(?:rc(?P<rc>[1-9][0-9]*))?$"
)


class UpdateError(RuntimeError):
    """A portable update could not be authenticated or activated safely."""


def version_key(value: str) -> tuple[int, int, int, int, int]:
    match = _VERSION.fullmatch(value)
    if match is None:
        raise UpdateError(f"unsupported rvs version: {value}")
    rc = match.group("rc")
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        1 if rc is None else 0,
        int(rc or 0),
    )


def newer(candidate: str, installed: str) -> bool:
    return version_key(candidate) > version_key(installed)


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("RVS_GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_channel_manifest() -> dict[str, Any]:
    try:
        with httpx.Client(timeout=15.0, follow_redirects=False) as client:
            manifest_response = client.get(CHANNELS_URL)
            signature_response = client.get(f"{CHANNELS_URL}.gpg")
            manifest_response.raise_for_status()
            signature_response.raise_for_status()
        verify_detached(manifest_response.content, signature_response.content)
        payload = json.loads(manifest_response.content)
        channels = payload.get("channels")
        if payload.get("schema") != 1 or not isinstance(channels, dict):
            raise UpdateError("the signed release-channel manifest has an unsupported schema")
        recommended = payload.get("recommended")
        if not isinstance(recommended, str) or recommended not in channels:
            raise UpdateError("the signed release-channel manifest has no valid recommendation")
        for channel, details in channels.items():
            if not re.fullmatch(r"v[0-9]+", channel) or not isinstance(details, dict):
                raise UpdateError("the signed release-channel manifest contains an invalid channel")
            latest = details.get("latest")
            if not isinstance(latest, str) or compatibility_channel(latest) != channel:
                raise UpdateError("the signed release-channel manifest contains an invalid version")
            targets = details.get("minor_targets")
            if not isinstance(targets, dict) or not targets:
                raise UpdateError("the signed release-channel manifest has no minor targets")
            for selector, target in targets.items():
                if (
                    not isinstance(selector, str)
                    or not isinstance(target, str)
                    or normalize_minor_target(selector) != selector
                    or minor_target_for_version(target) != selector
                    or compatibility_channel(target) != channel
                ):
                    raise UpdateError(
                        "the signed release-channel manifest contains an invalid minor target"
                    )
        return payload
    except (OSError, ValueError, VerificationError, httpx.HTTPError) as exc:
        if isinstance(exc, UpdateError):
            raise
        raise UpdateError("could not authenticate the Ravenstash release-channel manifest") from exc


def latest_for_channel(manifest: dict[str, Any], channel: str) -> str:
    details = manifest["channels"].get(channel)
    if not isinstance(details, dict) or details.get("status") != "supported":
        raise UpdateError(f"release channel {channel} is not available for upgrade")
    latest = details.get("latest")
    if not isinstance(latest, str):
        raise UpdateError(f"release channel {channel} has no valid latest version")
    return latest


def latest_for_minor(manifest: dict[str, Any], selector: str) -> str:
    normalized = normalize_minor_target(selector)
    channel = normalize_channel(normalized.partition(".")[0])
    details = manifest["channels"].get(channel)
    if not isinstance(details, dict) or details.get("status") != "supported":
        raise UpdateError(f"release channel {channel} is not available for upgrade")
    targets = details.get("minor_targets")
    target = targets.get(normalized) if isinstance(targets, dict) else None
    if not isinstance(target, str):
        raise UpdateError(f"minor release {normalized} is not available for upgrade")
    return target


def _archive_name(version: str, target: str) -> str:
    suffix = ".zip" if target.startswith("windows-") else ".tar.gz"
    return f"rvs-v{version}-{target}{suffix}"


def _download(client: httpx.Client, url: str, destination: Path) -> None:
    response = client.get(url, follow_redirects=True)
    response.raise_for_status()
    destination.write_bytes(response.content)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_verified_assets(
    version: str, asset_names: set[str], destination: Path, *, candidate: bool
) -> dict[str, Path]:
    """Download exact release assets and authenticate them against the signed inventory."""

    tag = f"v{version}"
    checksums_name = f"rvs-v{version}-checksums.txt"
    signature_name = f"{checksums_name}.asc"
    wanted = asset_names | {checksums_name, signature_name}
    try:
        with httpx.Client(timeout=90.0, headers=_headers(), follow_redirects=False) as client:
            response = client.get(f"{RELEASE_API}/releases/tags/{tag}")
            response.raise_for_status()
            release = response.json()
            if (
                release.get("tag_name") != tag
                or release.get("draft") is not False
                or release.get("prerelease") is not candidate
            ):
                kind = "release candidate" if candidate else "stable release"
                raise UpdateError(f"GitHub release {tag} is not a published {kind}")
            raw_assets = release.get("assets")
            if not isinstance(raw_assets, list):
                raise UpdateError(f"GitHub release {tag} has invalid asset metadata")
            assets = {
                asset.get("name"): asset.get("browser_download_url")
                for asset in raw_assets
                if isinstance(asset, dict)
                and isinstance(asset.get("name"), str)
                and isinstance(asset.get("browser_download_url"), str)
            }
            if not wanted.issubset(assets):
                missing = ", ".join(sorted(wanted - assets.keys()))
                raise UpdateError(f"GitHub release {tag} is missing signed assets: {missing}")
            for name in wanted:
                expected = f"{RELEASE_DOWNLOAD_ROOT}/{tag}/{name}"
                if assets[name] != expected:
                    raise UpdateError(f"GitHub release {tag} contains an unexpected asset URL")
                _download(client, expected, destination / name)
    except (OSError, ValueError, httpx.HTTPError) as exc:
        if isinstance(exc, UpdateError):
            raise
        raise UpdateError(f"could not download {tag} from GitHub") from exc

    checksums = (destination / checksums_name).read_bytes()
    try:
        verify_detached(checksums, (destination / signature_name).read_bytes())
    except (OSError, VerificationError) as exc:
        raise UpdateError("the release checksum signature is invalid") from exc
    expected_hashes: dict[str, str] = {}
    for line in checksums.decode("utf-8").splitlines():
        digest, separator, name = line.partition("  ")
        if name not in asset_names:
            continue
        if not separator or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise UpdateError(f"the signed checksum for {name} is invalid")
        if name in expected_hashes:
            raise UpdateError("the signed checksum inventory contains duplicate entries")
        expected_hashes[name] = digest
    missing_hashes = asset_names - expected_hashes.keys()
    if missing_hashes:
        missing = ", ".join(sorted(missing_hashes))
        raise UpdateError(f"the signed checksum inventory does not contain: {missing}")
    verified: dict[str, Path] = {}
    for name in sorted(asset_names):
        asset = destination / name
        if _sha256(asset) != expected_hashes[name]:
            raise UpdateError(f"the release asset checksum does not match: {name}")
        verified[name] = asset
    return verified


def download_release(version: str, target: str, destination: Path, *, candidate: bool) -> Path:
    archive_name = _archive_name(version, target)
    return download_verified_assets(version, {archive_name}, destination, candidate=candidate)[
        archive_name
    ]


def _safe_member(name: str, expected_root: str) -> bool:
    path = PurePosixPath(name.replace("\\", "/"))
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and "." not in path.parts
        and bool(path.parts)
        and path.parts[0] == expected_root
    )


def extract_release(archive: Path, destination: Path, version: str, target: str) -> Path:
    expected_root = f"rvs-v{version}-{target}"
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                mode = member.external_attr >> 16
                if not _safe_member(member.filename, expected_root) or stat.S_ISLNK(mode):
                    raise UpdateError("the portable release archive contains an unsafe path")
            bundle.extractall(destination)
    else:
        with tarfile.open(archive, "r:gz") as bundle:
            for member in bundle.getmembers():
                if (
                    not _safe_member(member.name, expected_root)
                    or member.issym()
                    or member.islnk()
                    or member.isdev()
                ):
                    raise UpdateError("the portable release archive contains an unsafe path")
            bundle.extractall(destination, filter="data")
    extracted = destination / expected_root
    executable = extracted / ("rvs.exe" if target.startswith("windows-") else "rvs")
    if not executable.is_file():
        raise UpdateError("the portable release archive is missing its rvs launcher")
    if os.name != "nt" and not os.access(executable, os.X_OK):
        raise UpdateError("the portable release archive contains a non-executable rvs launcher")
    return extracted


@contextmanager
def update_lock(root: Path) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".update.lock"
    stream = lock_path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            stream.seek(0)
            stream.write(b"0")
            stream.flush()
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise UpdateError("another rvs update is already running") from exc
        else:
            import fcntl

            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise UpdateError("another rvs update is already running") from exc
        if (root / ".update-pending").exists():
            raise UpdateError("a staged Windows rvs update is still pending")
        yield
    finally:
        if os.name == "nt":
            import msvcrt

            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def _smoke(executable: Path, version: str) -> None:
    result = subprocess.run(
        [str(executable), "--version"], check=False, capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0 or version not in result.stdout:
        raise UpdateError("the staged rvs executable failed its version health check")


def _replace_symlink(path: Path, target: Path) -> None:
    if path.exists() and not path.is_symlink():
        raise UpdateError(f"refusing to replace non-symlink command: {path}")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.symlink_to(target)
    os.replace(temporary, path)


def activate_posix(extracted: Path, installation: Installation, version: str) -> None:
    root = installation.root
    bin_directory = installation.bin
    destination = root / version
    if destination.exists():
        raise UpdateError(f"the target installation already exists: {destination}")
    bin_directory.mkdir(parents=True, exist_ok=True)
    staged_receipt = replace(installation, version=version, channel=compatibility_channel(version))
    write_receipt(extracted / RECEIPT_NAME, staged_receipt)
    shutil.move(str(extracted), destination)
    switched = False
    old_current: str | None = None
    current = root / "current"
    command_paths = [
        bin_directory / command for command in ("ravenstash", "docker-credential-rvs", "rvs")
    ]
    old_links: dict[Path, str | None] = {}
    try:
        _smoke(destination / "rvs", version)
        if current.is_symlink():
            old_current = os.readlink(current)
        elif current.exists():
            raise UpdateError(f"refusing to replace non-symlink activation path: {current}")
        for path in command_paths:
            if path.is_symlink():
                old_links[path] = os.readlink(path)
            elif path.exists():
                raise UpdateError(f"refusing to replace non-symlink command: {path}")
            else:
                old_links[path] = None
        temporary = root / f".current.{uuid.uuid4().hex}.tmp"
        temporary.symlink_to(version)
        os.replace(temporary, current)
        switched = True
        for path in command_paths:
            _replace_symlink(path, current / path.name)
        _smoke(bin_directory / "rvs", version)
    except Exception:
        if switched:
            if old_current is None:
                current.unlink(missing_ok=True)
            else:
                temporary = root / f".rollback.{uuid.uuid4().hex}.tmp"
                temporary.symlink_to(old_current)
                os.replace(temporary, current)
        for path, old_target in old_links.items():
            if old_target is None:
                path.unlink(missing_ok=True)
            else:
                _replace_symlink(path, Path(old_target))
        shutil.rmtree(destination, ignore_errors=True)
        raise


_WINDOWS_HELPER = r"""param(
  [Parameter(Mandatory=$true)][int]$ParentPid,
  [Parameter(Mandatory=$true)][string]$InstallRoot,
  [Parameter(Mandatory=$true)][string]$Staged,
  [Parameter(Mandatory=$true)][string]$Version
)
$ErrorActionPreference = "Stop"
$bin = Join-Path $InstallRoot "bin"
$backup = Join-Path $InstallRoot (".previous-" + $Version + "-" + [guid]::NewGuid())
try {
  $deadline = (Get-Date).AddSeconds(120)
  while ((Get-Process -Id $ParentPid -ErrorAction SilentlyContinue) -and
         ((Get-Date) -lt $deadline)) {
    Start-Sleep -Milliseconds 250
  }
  if (Get-Process -Id $ParentPid -ErrorAction SilentlyContinue) { throw "rvs did not exit" }
  if (Test-Path -LiteralPath $bin) { Move-Item -LiteralPath $bin -Destination $backup }
  Move-Item -LiteralPath $Staged -Destination $bin
  & (Join-Path $bin "rvs.exe") --version | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "updated rvs failed its health check" }
  Get-ChildItem -LiteralPath $InstallRoot -Directory -Filter ".previous-*" |
    Where-Object { $_.FullName -ne $backup } |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}
catch {
  if (Test-Path -LiteralPath $backup) {
    if (Test-Path -LiteralPath $bin) { Remove-Item -Recurse -Force -LiteralPath $bin }
    Move-Item -LiteralPath $backup -Destination $bin
  }
  if (Test-Path -LiteralPath $Staged) { Remove-Item -Recurse -Force -LiteralPath $Staged }
  throw
}
finally {
  Remove-Item -LiteralPath (Join-Path $InstallRoot ".update-pending") -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
}
"""


def stage_windows(extracted: Path, installation: Installation, version: str) -> None:
    root = installation.root
    staged = root / f".staged-{version}-{uuid.uuid4().hex}"
    pending = root / ".update-pending"
    if staged.exists():
        raise UpdateError(f"the update staging path already exists: {staged}")
    staged_receipt = replace(
        installation,
        version=version,
        channel=compatibility_channel(version),
        bin_directory=str(root / "bin"),
    )
    write_receipt(extracted / RECEIPT_NAME, staged_receipt)
    shutil.move(str(extracted), staged)
    try:
        _smoke(staged / "rvs.exe", version)
        with pending.open("x", encoding="ascii") as stream:
            stream.write(f"{version}\n")
        helper = Path(tempfile.gettempdir()) / f"rvs-update-{uuid.uuid4().hex}.ps1"
        helper.write_text(_WINDOWS_HELPER, encoding="utf-8")
        creation_flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(helper),
                "-ParentPid",
                str(os.getpid()),
                "-InstallRoot",
                str(root),
                "-Staged",
                str(staged),
                "-Version",
                version,
            ],
            close_fds=True,
            creationflags=creation_flags,
        )
    except Exception:
        pending.unlink(missing_ok=True)
        shutil.rmtree(staged, ignore_errors=True)
        raise


def apply_portable_update(installation: Installation, version: str, *, candidate: bool) -> bool:
    """Install a verified update; return ``True`` when Windows finishes asynchronously."""

    with update_lock(installation.root), tempfile.TemporaryDirectory(prefix="rvs-update-") as raw:
        work = Path(raw)
        archive = download_release(version, installation.target, work, candidate=candidate)
        extracted = extract_release(archive, work / "extracted", version, installation.target)
        if installation.target.startswith("windows-"):
            stage_windows(extracted, installation, version)
            return True
        activate_posix(extracted, installation, version)
        return False
