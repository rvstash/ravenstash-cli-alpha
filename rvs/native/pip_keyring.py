"""Ephemeral pip keyring bridge for renewable Ravenstash capabilities."""

from __future__ import annotations

import json
import os
import sys
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Sequence


_PROFILE_ENV = "RVS_PIP_KEYRING_PROFILE"
_CUSTOMER_ENV = "RVS_PIP_KEYRING_CUSTOMER_ID"


def _credential(service: str) -> dict[str, str]:
    # Import lazily so the normal CLI does not load package-command dependencies
    # unless pip actually challenges an expired capability.
    from .runner import _package_token_for_url, _profile, _ravenstash_url_kind

    profile = os.environ.get(_PROFILE_ENV) or None
    customer_id = os.environ.get(_CUSTOMER_ENV) or None
    profile_config = _profile(profile)
    if (
        _ravenstash_url_kind(
            service,
            native_registries=profile_config.native_registries,
        )
        != "pypi"
    ):
        raise ValueError("Credential lookup is limited to configured Ravenstash PyPI routes")
    token = _package_token_for_url(service, "pypi", profile, customer_id)
    return {"username": "__token__", "password": token}


def main(argv: Sequence[str] | None = None) -> int:
    """Implement modern JSON and legacy password-only keyring lookups."""
    args = list(sys.argv[1:] if argv is None else argv)
    json_mode = len(args) in {4, 5} and args[:3] == [
        "--mode=creds",
        "--output=json",
        "get",
    ]
    legacy_mode = len(args) == 3 and args[0] == "get"
    if not json_mode and not legacy_mode:
        print("Unsupported keyring operation", file=sys.stderr)
        return 2
    try:
        payload = _credential(args[3] if json_mode else args[1])
    except (SystemExit, Exception) as exc:
        print(str(exc) or "Ravenstash credential exchange failed", file=sys.stderr)
        return 1
    if json_mode:
        print(json.dumps(payload, separators=(",", ":")))
    else:
        print(payload["password"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
