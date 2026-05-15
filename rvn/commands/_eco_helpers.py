"""Shared helpers for ecosystem command modules (pypi_eco, npm_eco, maven_eco).

These functions are trivially identical across all three files and are pulled
into one place to avoid copy-paste drift.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import auth as auth_mod
from .. import config as cfg_mod
from .. import output
from ..client import ApiClient


if TYPE_CHECKING:
    from ..config import RegistryKind


def resolve_registry(
    kind: RegistryKind,
    profile: str | None,
    repo: str | None,
) -> tuple[str, str, str | None]:
    """Return ``(api_url, slug, token_or_None)``.

    *token* may be ``None`` for read-only operations.  Calls ``output.fatal``
    (and exits) when no repository slug can be determined.
    """
    cfg = cfg_mod.load()
    p = cfg.active_profile(profile)
    reg = cfg.registry_defaults(kind)
    token = reg.token or auth_mod.get_token(profile or cfg.default_profile) or p.token
    slug = repo or reg.default_repo
    api_url = reg.api_url or p.api_url
    if not slug:
        output.fatal(
            f"No repository specified.  Pass --repo or set a default:\n"
            f"  rvn config set-default-repo {kind} <slug>"
        )
    return api_url, slug, token  # type: ignore[return-value]


def require_token(
    kind: RegistryKind,
    profile: str | None,
    repo: str | None,
) -> tuple[str, str, str]:
    """Like :func:`resolve_registry` but also fatals when the token is absent."""
    api_url, slug, token = resolve_registry(kind, profile, repo)
    if not token:
        output.fatal("Not authenticated. Run `rvn login` or `rvn auth add-registry`.")
    return api_url, slug, token  # type: ignore[return-value]


def api_client(api_url: str, token: str) -> ApiClient:
    """Return a configured :class:`~rvn.client.ApiClient`."""
    return ApiClient(api_url=api_url, token=token)
