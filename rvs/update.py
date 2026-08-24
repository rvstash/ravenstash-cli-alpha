"""Signed APT update and explicit compatibility-channel upgrades."""

from __future__ import annotations

import json
import os
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
    r"^deb \[arch=amd64 signed-by=/etc/apt/keyrings/ravenstash-rvs\.gpg\] "
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
    if os.geteuid() == 0:
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
    return (
        "deb [arch=amd64 signed-by=/etc/apt/keyrings/ravenstash-rvs.gpg] "
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
        f"rvs {latest} is available on compatibility channel {recommended}. "
        f"Review the migration notes, then run: rvs upgrade --to {recommended.removeprefix('v')}"
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
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Refresh APT metadata and install the newest update in this channel.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Do not ask for confirmation when used with --apply.",
    ),
) -> None:
    """Check for a compatible signed APT update, or install it with --apply."""
    installed, candidate = _apt_versions()
    if installed is None:
        output.info(f"Ravenstash CLI {_cli_version()} is not managed by the rvs APT package.")
        output.info(
            "Install or migrate with: "
            "curl -fsSL https://ravenstash.com/install.sh | bash"
        )
        return
    if candidate is None:
        output.fatal(
            "APT has no rvs candidate. Check that the Ravenstash source is configured, "
            "then run `sudo apt-get update`."
        )

    current_channel = _current_channel()
    if not _upgrade_available(installed, candidate):
        suffix = f" on channel {current_channel}" if current_channel else ""
        output.success(f"rvs {installed} is current{suffix}.")
        _announce_new_channel(current_channel)
        return

    if current_channel and not version_matches_channel(candidate, current_channel):
        output.fatal(
            f"APT candidate {candidate} does not belong to configured channel {current_channel}."
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
    if _run_visible([str(_APT_GET), "install", "--only-upgrade", "--yes", "rvs"]).returncode != 0:
        output.fatal("APT could not install the rvs update.")
    output.success(f"Updated rvs to {candidate}.")


def upgrade(
    to: str = typer.Option(..., "--to", help="Target compatibility channel, such as 0.4 or 1."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation."),
) -> None:
    """Explicitly move to a newer compatibility channel."""
    try:
        target = normalize_channel(to)
    except ValueError as exc:
        output.fatal(str(exc))
    installed, _candidate = _apt_versions()
    current = _current_channel()
    if installed is None or current is None:
        output.fatal("rvs is not managed by a recognized Ravenstash APT source.")
    if target == current:
        output.success(f"rvs already tracks compatibility channel {target}.")
        return
    if channel_order(target) <= channel_order(current):
        output.fatal("Channel downgrades are not supported automatically.")

    manifest = _channel_manifest()
    if manifest is None:
        output.fatal("Cannot authenticate the Ravenstash compatibility-channel manifest.")
    channel_data = manifest["channels"].get(target)
    if not isinstance(channel_data, dict) or channel_data.get("status") != "supported":
        output.fatal(f"Compatibility channel {target} is not available for upgrade.")
    target_version = channel_data["latest"]
    notes = channel_data.get(
        "migration_notes",
        f"https://docs.ravenstash.com/cli/releases/{target.removeprefix('v').replace('.', '-')}/",
    )
    output.warn(
        f"This changes compatibility channel {current} to {target} and may include breaking changes."
    )
    output.info(f"Target release: {target_version}")
    output.info(f"Migration notes: {notes}")
    if not yes:
        typer.confirm(f"Upgrade rvs from {current} to {target}?", abort=True)

    try:
        previous_source = _APT_SOURCE.read_text(encoding="utf-8")
    except OSError:
        output.fatal("Cannot read the existing Ravenstash APT source.")
    if not _install_source(_source_for_channel(target)):
        output.fatal("Could not change the Ravenstash APT compatibility channel.")
    if _run_visible([str(_APT_GET), "update"]).returncode != 0:
        _restore_source(previous_source)
        output.fatal(
            "The target channel could not be authenticated; the prior channel was restored."
        )

    _installed_after_refresh, candidate = _apt_versions()
    if candidate is None or not version_matches_channel(candidate, target):
        _restore_source(previous_source)
        output.fatal(
            "The target channel returned an incompatible candidate; the prior channel was restored."
        )
    if _run_visible([str(_APT_GET), "install", "--only-upgrade", "--yes", "rvs"]).returncode != 0:
        _restore_source(previous_source)
        output.fatal(
            "APT could not install the compatibility upgrade; the prior channel was restored."
        )
    output.success(f"Updated rvs to {candidate} on compatibility channel {target}.")
