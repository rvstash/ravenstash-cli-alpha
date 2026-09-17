"""Canonical public names for user and organization account resources."""

from __future__ import annotations


def typed_handle(account_type: object, handle: object) -> str:
    """Return the unambiguous public name for an account resource."""
    if account_type == "personal":
        prefix = "user"
    elif account_type == "organization":
        prefix = "org"
    else:
        raise ValueError("account type must be personal or organization")

    if not isinstance(handle, str) or not handle.strip():
        raise ValueError("account handle cannot be empty")
    return f"{prefix}:{handle.strip()}"
