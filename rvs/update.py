"""Signed APT update and explicit compatibility-channel upgrades."""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import tempfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import httpx
import typer

from . import output
from .apt_channels import channel_order, normalize_channel, version_matches_channel


_APT_CACHE = Path("/usr/bin/apt-cache")
_APT_GET = Path("/usr/bin/apt-get")
_DPKG_QUERY = Path("/usr/bin/dpkg-query")
_GPGV = Path("/usr/bin/gpgv")
_INSTALL = Path("/usr/bin/install")
_SUDO = Path("/usr/bin/sudo")
_APT_SOURCE = Path("/etc/apt/sources.list.d/ravenstash-rvs.list")
_APT_KEYRING = Path("/etc/apt/keyrings/ravenstash-rvs.gpg")
_REPOSITORY_URL = "https://releases.ravenstash.com/rvs/apt"
_CHANNELS_URL = f"{_REPOSITORY_URL}/channels.json"
_CHANNELS_SIGNATURE_URL = f"{_CHANNELS_URL}.gpg"
_LEGACY_CHANNEL = "v0.3"
_SOURCE_PATTERN = re.compile(
    r"^deb \[arch=(?:amd64|arm64) signed-by=/etc/apt/keyrings/ravenstash-rvs\.gpg\] "
    r"https://releases\.ravenstash\.com/rvs/apt (?P<channel>stable|v[0-9.]+) main$"
)


def _cli_version() -> str:
    try:
        return version("ravenstash-cli")
    except PackageNotFoundError:
        return "dev"


def _safe_environment() -> dict[str, str]:
    return {
        "DEBIAN_FRONTEND": "noninteractive",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
    }


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=_safe_environment(),
    )


def _root_command(command: list[str]) -> list[str]:
    geteuid = getattr(os, "geteuid", None)
    if geteuid is not None and geteuid() == 0:
        return command
    if not _SUDO.is_file():
        output.fatal("Updating requires root privileges and /usr/bin/sudo is unavailable.")
    return [str(_SUDO), *command]


def _run_visible(command: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        _root_command(command),
        check=False,
        env=_safe_environment(),
    )


def _apt_versions() -> tuple[str | None, str | None]:
    if not _DPKG_QUERY.is_file() or not _APT_CACHE.is_file():
        return None, None
    installed_result = _run(
        [
            str(_DPKG_QUERY),
            "--show",
            "--showformat=${db:Status-Abbrev} ${Version}\\n",
            "rvs",
        ]
    )
    installed = None
    if installed_result.returncode == 0:
        status, separator, package_version = installed_result.stdout.strip().partition(" ")
        if separator and status == "ii":
            installed = package_version

    policy_result = _run([str(_APT_CACHE), "policy", "rvs"])
    candidate = None
    if policy_result.returncode == 0:
        for line in policy_result.stdout.splitlines():
            label, separator, value = line.strip().partition(":")
            if separator and label == "Candidate" and value.strip() != "(none)":
                candidate = value.strip()
                break
    return installed, candidate


def _upgrade_available(installed: str, candidate: str) -> bool:
    result = _run(["/usr/bin/dpkg", "--compare-versions", candidate, "gt", installed])
    return result.returncode == 0


def _current_channel() -> str | None:
    try:
        source = _APT_SOURCE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    match = _SOURCE_PATTERN.fullmatch(source)
    if match is None:
        return None
    channel = match.group("channel")
    return _LEGACY_CHANNEL if channel == "stable" else normalize_channel(channel)


def _source_for_channel(channel: str) -> str:
    normalized = normalize_channel(channel)
    machine = platform.machine().lower()
    architecture = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(machine)
    if architecture is None:
        output.fatal(f"APT updates are unsupported on CPU architecture {machine}.")
    return (
        f"deb [arch={architecture} signed-by=/etc/apt/keyrings/ravenstash-rvs.gpg] "
        f"{_REPOSITORY_URL} {normalized} main\n"
    )


def _channel_manifest() -> dict[str, Any] | None:
    if not _APT_KEYRING.is_file() or not _GPGV.is_file():
        return None
    try:
        with httpx.Client(timeout=10.0, follow_redirects=False) as client:
            manifest_response = client.get(_CHANNELS_URL)
            signature_response = client.get(_CHANNELS_SIGNATURE_URL)
            manifest_response.raise_for_status()
            signature_response.raise_for_status()
        with tempfile.TemporaryDirectory(prefix="rvs-channels-") as directory:
            manifest_path = Path(directory) / "channels.json"
            signature_path = Path(directory) / "channels.json.gpg"
            manifest_path.write_bytes(manifest_response.content)
            signature_path.write_bytes(signature_response.content)
            verified = subprocess.run(
                [
                    str(_GPGV),
                    f"--keyring={_APT_KEYRING}",
                    str(signature_path),
                    str(manifest_path),
                ],
                check=False,
                capture_output=True,
                env=_safe_environment(),
            )
            if verified.returncode != 0:
                return None
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError, ValueError, httpx.HTTPError:
        return None

    if payload.get("schema") != 1 or not isinstance(payload.get("channels"), dict):
        return None
    try:
        recommended = normalize_channel(payload["recommended"])
        for name, channel_data in payload["channels"].items():
            normalized = normalize_channel(name)
            if normalized != name or not isinstance(channel_data, dict):
                return None
            if not version_matches_channel(channel_data.get("latest", ""), normalized):
                return None
        if recommended not in payload["channels"]:
            return None
    except KeyError, TypeError, ValueError:
        return None
    return payload


def _announce_new_channel(current_channel: str | None) -> None:
    if current_channel is None:
        return
    manifest = _channel_manifest()
    if manifest is None:
        return
    recommended = manifest["recommended"]
    if channel_order(recommended) <= channel_order(current_channel):
        return
    latest = manifest["channels"][recommended]["latest"]
    output.info(
        f"rvs {latest} is available in release series {recommended}. "
        f"Review the migration notes, then run: rvs update --to {recommended.removeprefix('v')}"
    )


def _install_source(source: str) -> bool:
    if not _INSTALL.is_file():
        return False
    with tempfile.NamedTemporaryFile(prefix="rvs-source-", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(source.encode("utf-8"))
    temporary.chmod(0o600)
    try:
        installed = _run_visible([str(_INSTALL), "-m", "0644", str(temporary), str(_APT_SOURCE)])
        return installed.returncode == 0
    finally:
        temporary.unlink(missing_ok=True)


def _restore_source(source: str) -> None:
    if _install_source(source):
        _run_visible([str(_APT_GET), "update"])


def update(
    to: str | None = typer.Option(
        None, "--to", help="Preview a newer release series; install with --apply."
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Download and install the newest update in this release series.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Do not ask for confirmation when used with --apply.",
    ),
) -> None:
    """Check for a Ravenstash CLI update, or install it with --apply."""
    if yes and not apply:
        output.fatal("--yes requires --apply.")
    if to is not None:
        _update_series(to, apply=apply, yes=yes)
        return
    installed, candidate = _apt_versions()
    if installed is None:
        output.info(f"Ravenstash CLI {_cli_version()} is not managed by the rvs APT package.")
        output.info("Install or migrate with: curl -fsSL https://ravenstash.com/install.sh | bash")
        return
    if candidate is None:
        output.fatal(
            "APT has no rvs candidate. Check that the Ravenstash source is configured, "
            "then run `sudo apt-get update`."
        )

    current_channel = _current_channel()
    if not _upgrade_available(installed, candidate):
        suffix = f" on release series {current_channel}" if current_channel else ""
        output.success(f"rvs {installed} is current{suffix}.")
        _announce_new_channel(current_channel)
        return

    if current_channel and not version_matches_channel(candidate, current_channel):
        output.fatal(
            f"APT candidate {candidate} does not belong to configured release series {current_channel}."
        )
    output.info(f"rvs {candidate} is available (installed: {installed}).")
    if not apply:
        output.info("Install it with: rvs update --apply")
        _announce_new_channel(current_channel)
        return
    if not _APT_GET.is_file():
        output.fatal("Cannot update because /usr/bin/apt-get is unavailable.")
    if not yes:
        typer.confirm(f"Install signed rvs package {candidate}?", abort=True)

    if _run_visible([str(_APT_GET), "update"]).returncode != 0:
        output.fatal("APT metadata refresh failed.")
    refreshed_installed, refreshed_candidate = _apt_versions()
    if refreshed_candidate != candidate or refreshed_installed != installed:
        output.fatal("APT candidate changed during refresh; run rvs update again to review it.")
    if (
        _run_visible(
            [str(_APT_GET), "install", "--only-upgrade", "--yes", f"rvs={candidate}"]
        ).returncode
        != 0
    ):
        output.fatal("APT could not install the rvs update.")
    output.success(f"Updated rvs to {candidate}.")


def _update_series(to: str, *, apply: bool, yes: bool) -> None:
    """Move the Ravenstash CLI to a newer release series."""
    try:
        target = normalize_channel(to)
    except ValueError as exc:
        output.fatal(str(exc))
    installed, _candidate = _apt_versions()
    current = _current_channel()
    if installed is None or current is None:
        output.fatal("rvs is not managed by a recognized Ravenstash APT source.")
    if target == current:
        update(to=None, apply=apply, yes=yes)
        return
    if channel_order(target) <= channel_order(current):
        output.fatal("Release-series downgrades are not supported automatically.")

    manifest = _channel_manifest()
    if manifest is None:
        output.fatal("Cannot authenticate the Ravenstash release-series manifest.")
    channel_data = manifest["channels"].get(target)
    if not isinstance(channel_data, dict) or channel_data.get("status") != "supported":
        output.fatal(f"Release series {target} is not available for upgrade.")
    target_version = channel_data["latest"]
    if not _upgrade_available(installed, target_version):
        output.fatal("The target release is not newer than the installed package.")
    notes = channel_data.get(
        "migration_notes",
        f"https://docs.ravenstash.com/cli/releases/{target.removeprefix('v').replace('.', '-')}/",
    )
    output.warn(
        f"This changes release series {current} to {target} and may include breaking changes."
    )
    output.info(f"Target release: {target_version}")
    output.info(f"Migration notes: {notes}")
    if not apply:
        output.info(f"Install it with: rvs update --to {to} --apply")
        return
    if not yes:
        typer.confirm(f"Upgrade rvs from {current} to {target}?", abort=True)

    try:
        previous_source = _APT_SOURCE.read_text(encoding="utf-8")
    except OSError:
        output.fatal("Cannot read the existing Ravenstash APT source.")
    if not _install_source(_source_for_channel(target)):
        output.fatal("Could not change the Ravenstash APT release series.")
    if _run_visible([str(_APT_GET), "update"]).returncode != 0:
        _restore_source(previous_source)
        output.fatal(
            "The target release series could not be authenticated; the prior release series was restored."
        )

    installed_after_refresh, candidate = _apt_versions()
    if (
        installed_after_refresh != installed
        or candidate is None
        or candidate != target_version
        or not version_matches_channel(candidate, target)
    ):
        _restore_source(previous_source)
        output.fatal(
            "The target release series returned an incompatible candidate; the prior release series was restored."
        )
    if (
        _run_visible(
            [str(_APT_GET), "install", "--only-upgrade", "--yes", f"rvs={candidate}"]
        ).returncode
        != 0
    ):
        _restore_source(previous_source)
        output.fatal(
            "APT could not install the compatibility upgrade; the prior release series was restored."
        )
    output.success(f"Updated rvs to {candidate} on release series {target}.")
