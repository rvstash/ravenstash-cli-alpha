"""APT-backed CLI update checks.

The signed APT repository is the update authority.  The CLI deliberately does
not download and replace its own executable.
"""

from __future__ import annotations

import os
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import typer

from . import output


_APT_CACHE = Path("/usr/bin/apt-cache")
_APT_GET = Path("/usr/bin/apt-get")
_DPKG_QUERY = Path("/usr/bin/dpkg-query")
_SUDO = Path("/usr/bin/sudo")


def _cli_version() -> str:
    try:
        return version("ravenstash-cli")
    except PackageNotFoundError:
        return "dev"


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env={
            "DEBIAN_FRONTEND": "noninteractive",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        },
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
    result = _run(
        [
            "/usr/bin/dpkg",
            "--compare-versions",
            candidate,
            "gt",
            installed,
        ]
    )
    return result.returncode == 0


def update(
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Refresh APT metadata and install the newest signed rvs package.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Do not ask for confirmation when used with --apply.",
    ),
) -> None:
    """Check for a signed APT update, or install it with --apply."""
    installed, candidate = _apt_versions()
    if installed is None:
        output.info(f"Ravenstash CLI {_cli_version()} is not managed by the rvs APT package.")
        output.info(
            "Install or migrate with: "
            "curl --proto '=https' --proto-redir '=https' --tlsv1.2 "
            "-fsSL https://ravenstash.com/install.sh | bash"
        )
        return
    if candidate is None:
        output.fatal(
            "APT has no rvs candidate. Check that the Ravenstash source is configured, "
            "then run `sudo apt-get update`."
        )

    if not _upgrade_available(installed, candidate):
        output.success(f"rvs {installed} is current.")
        return

    output.info(f"rvs {candidate} is available (installed: {installed}).")
    if not apply:
        output.info("Install it with: rvs update --apply")
        return
    if not _APT_GET.is_file():
        output.fatal("Cannot update because /usr/bin/apt-get is unavailable.")
    if not yes:
        typer.confirm(f"Install signed rvs package {candidate}?", abort=True)

    command = [
        str(_APT_GET),
        "update",
    ]
    if os.geteuid() != 0:
        if not _SUDO.is_file():
            output.fatal("Updating requires root privileges and /usr/bin/sudo is unavailable.")
        command.insert(0, str(_SUDO))
    refreshed = subprocess.run(command, check=False)
    if refreshed.returncode != 0:
        output.fatal("APT metadata refresh failed.")

    install_command = [
        str(_APT_GET),
        "install",
        "--only-upgrade",
        "--yes",
        "rvs",
    ]
    if os.geteuid() != 0:
        install_command.insert(0, str(_SUDO))
    installed_result = subprocess.run(install_command, check=False)
    if installed_result.returncode != 0:
        output.fatal("APT could not install the rvs update.")
    output.success(f"Updated rvs to {candidate}.")
