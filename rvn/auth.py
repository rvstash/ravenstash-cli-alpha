"""Credential storage for rvn.

Prefers keyring (OS keychain / secret service) and falls back to plain-text
in the config file.  The keyring service name is ``rvn`` and the username is
the profile name.

Public API
----------
get_token(profile) -> str | None
set_token(profile, token) -> None
delete_token(profile) -> None
"""

from __future__ import annotations

import logging


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
        logger.warning("keyring unavailable, storing token in config file: %s", exc)
        _fallback_set(profile, token)


def _kr_delete(profile: str) -> None:
    try:
        import keyring

        keyring.delete_password(_SERVICE, profile)
    except Exception:
        pass


# ── config-file fallback ──────────────────────────────────────────────────────


def _fallback_get(profile: str) -> str | None:
    from . import config as cfg_mod

    cfg = cfg_mod.load()
    p = cfg.profiles.get(profile)
    return p.token if p else None


def _fallback_set(profile: str, token: str) -> None:
    from . import config as cfg_mod

    cfg_mod.set_profile_value(profile, token=token)


# ── Public API ────────────────────────────────────────────────────────────────


def get_token(profile: str) -> str | None:
    """Return the stored token for *profile*, trying keyring first."""
    if _keyring_available():
        token = _kr_get(profile)
        if token:
            return token
    return _fallback_get(profile)


def set_token(profile: str, token: str) -> None:
    """Persist *token* for *profile* (keyring preferred)."""
    if _keyring_available():
        _kr_set(profile, token)
    else:
        _fallback_set(profile, token)


def delete_token(profile: str) -> None:
    """Remove stored credentials for *profile*."""
    _kr_delete(profile)
    from . import config as cfg_mod

    cfg_mod.set_profile_value(profile, token=None)
