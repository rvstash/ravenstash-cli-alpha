"""Secure credential-store adapters for Linux desktop and TTY environments."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


_COMMAND_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class StoreStatus:
    name: str
    available: bool
    backend: str
    detail: str
    guidance: str


class StoreError(RuntimeError):
    """A credential store could not complete a requested operation."""


def system_keyring_status() -> StoreStatus:
    try:
        import keyring

        backend = keyring.get_keyring()
        priority = backend.priority
        backend_name = f"{type(backend).__module__}.{type(backend).__name__}"
        if priority < 1:
            raise RuntimeError("no recommended keyring backend was detected")
    except Exception as exc:
        return StoreStatus(
            name="keyring",
            available=False,
            backend="none",
            detail=str(exc) or type(exc).__name__,
            guidance=(
                "Start or unlock your desktop credential service. Secret Service providers "
                "include GNOME Keyring, KWallet Secret Service, and KeePassXC integration."
            ),
        )
    return StoreStatus(
        name="keyring",
        available=True,
        backend=backend_name,
        detail="A recommended OS keyring backend is available.",
        guidance="",
    )


def system_get(service: str, account: str) -> str | None:
    try:
        import keyring

        return keyring.get_password(service, account)
    except Exception as exc:
        raise StoreError(f"OS keyring read failed: {exc}") from exc


def system_set(service: str, account: str, secret: str) -> None:
    try:
        import keyring

        keyring.set_password(service, account, secret)
    except Exception as exc:
        raise StoreError(f"OS keyring write failed: {exc}") from exc


def system_delete(service: str, account: str) -> None:
    try:
        import keyring

        if keyring.get_password(service, account) is None:
            return
        keyring.delete_password(service, account)
    except Exception as exc:
        raise StoreError(f"OS keyring delete failed: {exc}") from exc


def _password_store_dir() -> Path:
    configured = os.environ.get("PASSWORD_STORE_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".password-store"


def pass_status() -> StoreStatus:
    executable = shutil.which("pass")
    if executable is None:
        return StoreStatus(
            name="pass",
            available=False,
            backend="pass",
            detail="The pass executable is not installed or is not on PATH.",
            guidance="Install pass and initialize it with `pass init <gpg-id>`.",
        )
    store_dir = _password_store_dir()
    if not store_dir.is_dir() or not (store_dir / ".gpg-id").is_file():
        return StoreStatus(
            name="pass",
            available=False,
            backend=executable,
            detail=f"The password store at {store_dir} is not initialized.",
            guidance="Initialize it with `pass init <gpg-id>`.",
        )
    return StoreStatus(
        name="pass",
        available=True,
        backend=executable,
        detail=f"An initialized pass store is available at {store_dir}.",
        guidance="",
    )


def _pass_entry(account: str) -> str:
    encoded = base64.urlsafe_b64encode(account.encode("utf-8")).decode("ascii").rstrip("=")
    return f"ravenstash/rvs/{encoded}"


def _run_pass(
    arguments: list[str], *, secret: str | None = None
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["pass", *arguments],
            input=secret,
            text=True,
            capture_output=True,
            check=False,
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StoreError(f"pass could not be executed: {exc}") from exc


def pass_get(account: str) -> str | None:
    result = _run_pass(["show", _pass_entry(account)])
    if result.returncode != 0:
        if "not in the password store" in result.stderr.lower():
            return None
        raise StoreError(result.stderr.strip() or "pass could not read the credential")
    return result.stdout.rstrip("\n")


def pass_set(account: str, secret: str) -> None:
    result = _run_pass(["insert", "--multiline", "--force", _pass_entry(account)], secret=secret)
    if result.returncode != 0:
        raise StoreError(result.stderr.strip() or "pass could not store the credential")


def pass_delete(account: str) -> None:
    result = _run_pass(["rm", "--force", _pass_entry(account)])
    if result.returncode != 0 and "not in the password store" not in result.stderr.lower():
        raise StoreError(result.stderr.strip() or "pass could not delete the credential")
