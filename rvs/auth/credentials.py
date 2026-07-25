"""Credential storage for rvs.

Device-login credentials are stored in the OS keyring. Automation credentials
must be supplied through ``RVS_TOKEN``.

Public API
----------
get_token(profile) -> str | None
set_token(profile, token) -> None
delete_token(profile) -> None
token_source(profile) -> str | None
"""

from __future__ import annotations

import importlib.metadata
import logging
import os
import platform as platform_mod
from datetime import UTC, datetime, timedelta

import httpx


logger = logging.getLogger(__name__)

_SERVICE = "rvs"
_REFRESH_SUFFIX = ":refresh"
_REFRESH_SKEW_SECONDS = 60
EXPIRING_CREDENTIAL_TYPE = "expiring"
_LEGACY_TEMPORARY_CREDENTIAL_TYPE = "temporary"
_REFRESHABLE_CREDENTIAL_TYPES = {
    EXPIRING_CREDENTIAL_TYPE,
    _LEGACY_TEMPORARY_CREDENTIAL_TYPE,
}


def is_refreshable_credential_type(credential_type: str | None) -> bool:
    """Return whether *credential_type* can use device refresh tokens."""
    return credential_type in _REFRESHABLE_CREDENTIAL_TYPES


def display_credential_type(credential_type: str | None) -> str | None:
    """Return the user-facing label for a stored credential type."""
    if credential_type == _LEGACY_TEMPORARY_CREDENTIAL_TYPE:
        return EXPIRING_CREDENTIAL_TYPE
    return credential_type


def _rvs_user_agent() -> str:
    try:
        return f"rvs/{importlib.metadata.version('ravenstash-cli')}"
    except importlib.metadata.PackageNotFoundError:
        return "rvs/dev"


def _device_platform() -> str:
    return platform_mod.system().strip().lower() or "unknown"


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
            "No usable OS keyring is available. Use RVS_TOKEN for CI/headless "
            "runs or configure a keyring before storing local credentials."
        )
        raise RuntimeError(msg) from exc


def _kr_delete(profile: str) -> None:
    try:
        import keyring

        keyring.delete_password(_SERVICE, profile)
    except Exception:
        pass


def _refresh_profile(profile: str) -> str:
    return f"{profile}{_REFRESH_SUFFIX}"


def _stored_profile_expired(profile: str) -> bool:
    from .. import config as cfg_mod

    p = cfg_mod.load().profiles.get(profile)
    if not p or not is_refreshable_credential_type(p.credential_type) or not p.expires_at:
        return False
    try:
        expires_at = datetime.fromisoformat(p.expires_at)
    except ValueError:
        return False
    now = datetime.now(expires_at.tzinfo or UTC)
    return expires_at <= now + timedelta(seconds=_REFRESH_SKEW_SECONDS)


def _stored_refresh_token_expired(profile: str) -> bool:
    from .. import config as cfg_mod

    p = cfg_mod.load().profiles.get(profile)
    if not p or not is_refreshable_credential_type(p.credential_type) or not p.refresh_expires_at:
        return False
    try:
        expires_at = datetime.fromisoformat(p.refresh_expires_at)
    except ValueError:
        return False
    now = datetime.now(expires_at.tzinfo or UTC)
    return expires_at <= now


def get_refresh_token(profile: str) -> str | None:
    """Return the stored device refresh token for *profile*, if present."""
    if not _keyring_available():
        return None
    return _kr_get(_refresh_profile(profile))


def has_active_expiring_session(profile: str) -> bool:
    """Return whether *profile* appears to have a reusable expiring login."""
    from .. import config as cfg_mod

    p = cfg_mod.load().profiles.get(profile)
    if not p or not is_refreshable_credential_type(p.credential_type):
        return False
    if _stored_refresh_token_expired(profile):
        return False
    return get_refresh_token(profile) is not None


def revoke_device_refresh_token(api_url: str, refresh_token: str) -> bool:
    """Best-effort server-side revocation for a stored device refresh token."""
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(
                f"{api_url.rstrip('/')}/v0/auth/device/revoke",
                headers={"User-Agent": _rvs_user_agent()},
                json={"refresh_token": refresh_token},
            )
    except httpx.HTTPError:
        logger.info("Device refresh token revocation request failed")
        return False
    return response.is_success


def refresh_expiring_credential(profile: str) -> str | None:
    """Refresh an expired expiring device credential for *profile*."""
    from .. import config as cfg_mod

    if not _keyring_available():
        return None

    cfg = cfg_mod.load()
    p = cfg.profiles.get(profile)
    if not p or not is_refreshable_credential_type(p.credential_type):
        return None

    refresh_token = _kr_get(_refresh_profile(profile))
    if not refresh_token:
        return None

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(
                f"{p.api_url.rstrip('/')}/v0/auth/device/refresh",
                headers={"User-Agent": _rvs_user_agent()},
                json={
                    "refresh_token": refresh_token,
                    "platform": _device_platform(),
                },
            )
    except httpx.HTTPError:
        logger.info("Device credential refresh failed for profile %s", profile)
        return None

    if not response.is_success:
        logger.info(
            "Device credential refresh rejected for profile %s: HTTP %s",
            profile,
            response.status_code,
        )
        delete_token(profile)
        return None

    payload = response.json()
    access_token = payload.get("access_token")
    new_refresh_token = payload.get("refresh_token")
    expires_in = int(payload.get("expires_in") or 0)
    refresh_expires_in = int(payload.get("refresh_expires_in") or 0)
    if not isinstance(access_token, str) or not isinstance(new_refresh_token, str):
        delete_token(profile)
        return None

    _kr_set(profile, access_token)
    _kr_set(_refresh_profile(profile), new_refresh_token)
    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
    refresh_expires_at = datetime.now(UTC) + timedelta(seconds=refresh_expires_in)
    cfg_mod.set_profile_metadata(
        profile,
        api_url=p.api_url,
        pkg_download_url=payload.get("pkg_download_url"),
        pkg_upload_url=payload.get("pkg_upload_url"),
        customer_id=payload.get("customer_id"),
        customer_unique_id=payload.get("customer_unique_id"),
        credential_type=EXPIRING_CREDENTIAL_TYPE,
        expires_at=expires_at.isoformat(),
        refresh_expires_at=refresh_expires_at.isoformat(),
    )
    return access_token


# ── Public API ────────────────────────────────────────────────────────────────


def get_token(profile: str) -> str | None:
    """Return the effective credential for *profile*.

    RVS_TOKEN always wins and is intended for PAT/M2M automation. Local stored
    credentials are short-lived CLI JWTs from the device login flow.
    """
    env_token = os.environ.get("RVS_TOKEN")
    if env_token:
        return env_token
    if _stored_profile_expired(profile):
        return refresh_expiring_credential(profile)
    if _keyring_available():
        token = _kr_get(profile)
        if token:
            return token
        return refresh_expiring_credential(profile)
    return None


def token_source(profile: str) -> str | None:
    """Return where the effective credential for *profile* comes from."""
    if os.environ.get("RVS_TOKEN"):
        return "RVS_TOKEN"
    if _stored_profile_expired(profile):
        return None
    if _keyring_available() and _kr_get(profile):
        return "keyring"
    return None


def set_token(profile: str, token: str) -> None:
    """Persist *token* for *profile* (keyring preferred)."""
    if not _keyring_available():
        raise RuntimeError("No usable OS keyring is available. Use RVS_TOKEN for CI/headless runs.")
    _kr_set(profile, token)


def set_refresh_token(profile: str, token: str) -> None:
    """Persist the device refresh token for *profile*."""
    if not _keyring_available():
        raise RuntimeError("No usable OS keyring is available. Use RVS_TOKEN for CI/headless runs.")
    _kr_set(_refresh_profile(profile), token)


def delete_token(profile: str) -> None:
    """Remove stored credentials for *profile*."""
    _kr_delete(profile)
    _kr_delete(_refresh_profile(profile))
    from .. import config as cfg_mod

    cfg_mod.clear_profile_credential_metadata(profile)
