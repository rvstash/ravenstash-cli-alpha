"""Authentication and credential storage for the Ravenstash CLI."""

from __future__ import annotations

from .credentials import (
    EXPIRING_CREDENTIAL_TYPE,
    NoCredentialStoreError,
    credential_store_preference,
    credential_store_statuses,
    delete_token,
    delete_token_from_all_stores,
    delete_token_from_store,
    display_credential_type,
    get_refresh_token,
    get_token,
    has_active_expiring_session,
    is_refreshable_credential_type,
    preflight_credential_store,
    refresh_expiring_credential,
    revoke_device_refresh_token,
    selected_credential_store,
    set_refresh_token,
    set_token,
    token_source,
)


__all__ = [
    "EXPIRING_CREDENTIAL_TYPE",
    "NoCredentialStoreError",
    "credential_store_preference",
    "credential_store_statuses",
    "delete_token",
    "delete_token_from_all_stores",
    "delete_token_from_store",
    "display_credential_type",
    "get_refresh_token",
    "get_token",
    "has_active_expiring_session",
    "is_refreshable_credential_type",
    "preflight_credential_store",
    "refresh_expiring_credential",
    "revoke_device_refresh_token",
    "selected_credential_store",
    "set_refresh_token",
    "set_token",
    "token_source",
]
