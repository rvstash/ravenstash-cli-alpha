"""Credential storage for rvn.

Device-login credentials are stored in the OS keyring. Automation credentials
must be supplied through ``RVN_TOKEN``.

Public API
----------
get_token(profile) -> str | None
set_token(profile, token) -> None
delete_token(profile) -> None
token_source(profile) -> str | None
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime


logger = logging.getLogger(__name__)

_SERVICE = "rvn"


# ── keyring helpers ───────────────────────────────────────────────────────────


def _keyring_available() -> bool:
    try:
        import keyring  # noqa: F401

        return True
    except ImportError:
        return False


def _kr_get(profile: str) -> str | None:
    try:
        import keyring

        return keyring.get_password(_SERVICE, profile)
    except Exception:
        return None


def _kr_set(profile: str, token: str) -> None:
    try:
        import keyring

        keyring.set_password(_SERVICE, profile, token)
    except Exception as exc:
        msg = (
            "No usable OS keyring is available. Use RVN_TOKEN for CI/headless "
            "runs or configure a keyring before storing local credentials."
        )
        raise RuntimeError(msg) from exc


def _kr_delete(profile: str) -> None:
    try:
        import keyring

        keyring.delete_password(_SERVICE, profile)
    except Exception:
        pass


def _stored_profile_expired(profile: str) -> bool:
    from . import config as cfg_mod

    p = cfg_mod.load().profiles.get(profile)
    if not p or p.credential_type != "temporary" or not p.expires_at:
        return False
    try:
        expires_at = datetime.fromisoformat(p.expires_at)
    except ValueError:
        return False
    now = datetime.now(expires_at.tzinfo or UTC)
    return expires_at <= now


# ── Public API ────────────────────────────────────────────────────────────────


def get_token(profile: str) -> str | None:
    """Return the effective credential for *profile*.

    RVN_TOKEN always wins and is intended for PAT/M2M automation. Local stored
    credentials are short-lived CLI JWTs from the device login flow.
    """
    env_token = os.environ.get("RVN_TOKEN")
    if env_token:
        return env_token
    if _stored_profile_expired(profile):
        return None
    if _keyring_available():
        token = _kr_get(profile)
        if token:
            return token
    return None


def token_source(profile: str) -> str | None:
    """Return where the effective credential for *profile* comes from."""
    if os.environ.get("RVN_TOKEN"):
        return "RVN_TOKEN"
    if _stored_profile_expired(profile):
        return None
    if _keyring_available() and _kr_get(profile):
        return "keyring"
    return None


def set_token(profile: str, token: str) -> None:
    """Persist *token* for *profile* (keyring preferred)."""
    if not _keyring_available():
        raise RuntimeError("No usable OS keyring is available. Use RVN_TOKEN for CI/headless runs.")
    _kr_set(profile, token)


def delete_token(profile: str) -> None:
    """Remove stored credentials for *profile*."""
    _kr_delete(profile)
    from . import config as cfg_mod

    cfg_mod.clear_profile_credential_metadata(profile)
