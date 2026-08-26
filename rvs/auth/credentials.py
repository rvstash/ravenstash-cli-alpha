"""Credential storage for rvs.

Device-login credentials are stored in a selected secure provider (an OS
keyring or ``pass``). Automation credentials must be supplied through
``RVS_TOKEN``.

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
import secrets
from datetime import UTC, datetime, timedelta

import httpx

from . import stores


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
_CREDENTIAL_STORES = {"auto", "keyring", "pass"}


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
    return stores.system_keyring_status().available


def _kr_get(profile: str) -> str | None:
    try:
        return stores.system_get(_SERVICE, profile)
    except stores.StoreError:
        return None


def _kr_set(profile: str, token: str) -> None:
    try:
        stores.system_set(_SERVICE, profile, token)
    except stores.StoreError as exc:
        msg = (
            "No usable OS keyring is available. Use RVS_TOKEN for CI/headless "
            "runs or configure a keyring before storing local credentials."
        )
        raise RuntimeError(msg) from exc


def _kr_delete(profile: str) -> None:
    stores.system_delete(_SERVICE, profile)


def credential_store_statuses() -> list[stores.StoreStatus]:
    """Return non-secret diagnostics for supported local credential stores."""
    return [stores.system_keyring_status(), stores.pass_status()]


def _credential_store_preference(profile: str, requested: str | None = None) -> str:
    from .. import config as cfg_mod

    value = requested or os.environ.get("RVS_CREDENTIAL_STORE")
    if value is None:
        cfg = cfg_mod.load()
        profile_config = cfg.profiles.get(profile)
        value = (
            profile_config.credential_store
            if profile_config is not None and profile_config.credential_store
            else cfg.credential_store
        )
    if not isinstance(value, str):
        raise RuntimeError("Credential store must be auto, keyring, or pass.")
    normalized = value.strip().lower()
    if normalized not in _CREDENTIAL_STORES:
        raise RuntimeError("Credential store must be auto, keyring, or pass.")
    return normalized


def _store_available(name: str) -> bool:
    if name == "keyring":
        return _keyring_available()
    if name == "pass":
        return stores.pass_status().available
    return False


def selected_credential_store(
    profile: str,
    requested: str | None = None,
    *,
    required: bool = False,
) -> str | None:
    """Resolve the configured or automatically detected secure store."""
    preference = _credential_store_preference(profile, requested)
    candidates = ("keyring", "pass") if preference == "auto" else (preference,)
    for candidate in candidates:
        if _store_available(candidate):
            return candidate
    if not required:
        return None

    statuses = {status.name: status for status in credential_store_statuses()}
    details = "; ".join(
        f"{candidate}: {statuses[candidate].detail.rstrip('.')}" for candidate in candidates
    )
    raise RuntimeError(
        "No usable secure credential store is available. "
        f"{details}. Configure an existing store, choose one with "
        "`rvs auth keyring set keyring|pass`, or use RVS_TOKEN for CI/headless runs."
    )


def _store_get(name: str, account: str, *, strict: bool = False) -> str | None:
    if name == "keyring":
        if strict:
            try:
                return stores.system_get(_SERVICE, account)
            except stores.StoreError as exc:
                raise RuntimeError(str(exc)) from exc
        return _kr_get(account)
    try:
        return stores.pass_get(account)
    except stores.StoreError as exc:
        if strict:
            raise RuntimeError(str(exc)) from exc
        return None


def _store_set(name: str, account: str, token: str) -> None:
    if name == "keyring":
        _kr_set(account, token)
        return
    try:
        stores.pass_set(account, token)
    except stores.StoreError as exc:
        raise RuntimeError(f"Could not store credentials with pass: {exc}") from exc


def _store_delete(name: str, account: str, *, strict: bool = False) -> None:
    try:
        if name == "keyring":
            _kr_delete(account)
        else:
            stores.pass_delete(account)
    except stores.StoreError as exc:
        if strict:
            raise RuntimeError(str(exc)) from exc
        return


def preflight_credential_store(profile: str, requested: str | None = None) -> str:
    """Verify a secure store with a disposable round trip before device auth."""
    store = selected_credential_store(profile, requested, required=True)
    assert store is not None
    account = f"__probe__:{secrets.token_urlsafe(12)}"
    probe = secrets.token_urlsafe(24)
    failure: RuntimeError | None = None
    try:
        _store_set(store, account, probe)
        if _store_get(store, account, strict=True) != probe:
            raise RuntimeError("the credential store did not return the probe value")
    except RuntimeError as exc:
        failure = exc
    try:
        _store_delete(store, account, strict=True)
    except RuntimeError as cleanup_error:
        if failure is not None:
            raise RuntimeError(
                f"Credential-store preflight failed for {store}: {failure}; "
                f"probe cleanup also failed: {cleanup_error}"
            ) from failure
        raise RuntimeError(
            f"Credential-store preflight failed for {store}: probe cleanup failed: {cleanup_error}"
        ) from cleanup_error
    if failure is not None:
        raise RuntimeError(f"Credential-store preflight failed for {store}: {failure}") from failure
    return store


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
    store = selected_credential_store(profile)
    if store is None:
        return None
    return _store_get(store, _refresh_profile(profile))


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

    store = selected_credential_store(profile)
    if store is None:
        return None

    cfg = cfg_mod.load()
    p = cfg.profiles.get(profile)
    if not p or not is_refreshable_credential_type(p.credential_type):
        return None

    refresh_token = _store_get(store, _refresh_profile(profile))
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

    try:
        _store_set(store, profile, access_token)
        _store_set(store, _refresh_profile(profile), new_refresh_token)
        expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
        refresh_expires_at = datetime.now(UTC) + timedelta(seconds=refresh_expires_in)
        cfg_mod.set_profile_metadata(
            profile,
            api_url=p.api_url,
            native_registries=payload.get("native_registries"),
            customer_id=payload.get("customer_id"),
            customer_unique_id=payload.get("customer_unique_id"),
            credential_store=store,
            credential_type=EXPIRING_CREDENTIAL_TYPE,
            expires_at=expires_at.isoformat(),
            refresh_expires_at=refresh_expires_at.isoformat(),
        )
    except OSError, RuntimeError:
        # A rotated pair is useful only when both secrets and its metadata are
        # durable. Revoke and remove a partial pair rather than leaving an
        # access token whose refresh state is ambiguous.
        revoke_device_refresh_token(p.api_url, new_refresh_token)
        delete_token_from_store(profile, store)
        cfg_mod.clear_profile_credential_metadata(profile)
        return None
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
    store = selected_credential_store(profile)
    if store is not None:
        token = _store_get(store, profile)
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
    store = selected_credential_store(profile)
    if store is not None and _store_get(store, profile):
        return store
    return None


def set_token(profile: str, token: str, credential_store: str | None = None) -> None:
    """Persist *token* for *profile* in the selected secure store."""
    store = selected_credential_store(profile, credential_store, required=True)
    assert store is not None
    _store_set(store, profile, token)


def set_refresh_token(profile: str, token: str, credential_store: str | None = None) -> None:
    """Persist the device refresh token for *profile*."""
    store = selected_credential_store(profile, credential_store, required=True)
    assert store is not None
    _store_set(store, _refresh_profile(profile), token)


def delete_token_from_store(profile: str, credential_store: str) -> None:
    """Remove both device credentials from one explicitly selected store."""
    if credential_store not in {"keyring", "pass"}:
        raise ValueError("Credential store must be keyring or pass")
    _store_delete(credential_store, profile)
    _store_delete(credential_store, _refresh_profile(profile))


def delete_token(profile: str) -> None:
    """Remove stored credentials for *profile*."""
    preference = _credential_store_preference(profile)
    candidates = ("keyring", "pass") if preference == "auto" else (preference,)
    for store in candidates:
        delete_token_from_store(profile, store)
    from .. import config as cfg_mod

    cfg_mod.clear_profile_credential_metadata(profile)
