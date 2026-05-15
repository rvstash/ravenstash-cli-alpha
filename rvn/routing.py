"""rvn.routing — registry URL routing modes.

Two routing modes are defined:

canonical (default)
    Uses the per-kind URL prefixes that exist in production today:
        PyPI:  {api_url}/pypi/r/{slug}/simple/
        npm:   {api_url}/npm/r/{slug}/
        Maven: {api_url}/maven/r/{slug}/

unified (not yet implemented)
    Will expose a single URL structure that is identical across all registry
    kinds, making cross-stack tooling trivially composable.  The server-side
    routes are still in development; selecting this mode currently raises
    NotImplementedError so callers can surface a clear "not yet available"
    message instead of a confusing HTTP 404.

Typical usage in a command
--------------------------
    from ..routing import get_router, RoutingMode

    def my_cmd(routing: RoutingMode = "canonical") -> None:
        try:
            router = get_router(routing)
            url = router.pypi_index_url(api_url, slug)
        except NotImplementedError as exc:
            output.fatal(str(exc))
"""

from __future__ import annotations

from typing import Literal


# The two routing modes exposed on the CLI.
RoutingMode = Literal["canonical", "unified"]
DEFAULT_ROUTING: RoutingMode = "canonical"

_UNIFIED_MSG = (
    "Unified routing is not yet implemented.\n"
    "\n"
    "The server-side unified registry routes (a single URL scheme shared\n"
    "across PyPI, npm, and Maven) are still in development.\n"
    "\n"
    "Use --routing canonical (the default) until unified routes are deployed."
)


# ── Canonical router ──────────────────────────────────────────────────────────


class CanonicalRouter:
    """Current production routing — per-kind URL prefixes."""

    @staticmethod
    def pypi_index_url(api_url: str, slug: str) -> str:
        return f"{api_url.rstrip('/')}/pypi/r/{slug}/simple/"

    @staticmethod
    def pypi_upload_url(api_url: str, slug: str) -> str:
        return f"{api_url.rstrip('/')}/pypi/r/{slug}/"

    @staticmethod
    def npm_registry_url(api_url: str, slug: str) -> str:
        return f"{api_url.rstrip('/')}/npm/r/{slug}/"

    @staticmethod
    def maven_repo_url(api_url: str, slug: str) -> str:
        return f"{api_url.rstrip('/')}/maven/r/{slug}/"


# ── Unified router (stub) ─────────────────────────────────────────────────────


class UnifiedRouter:
    """Future unified routing — identical URL structure for all registry kinds.

    Raises NotImplementedError for every method until the server-side
    unified routes are available and this class is implemented.
    """

    def pypi_index_url(self, api_url: str, slug: str) -> str:
        raise NotImplementedError(_UNIFIED_MSG)

    def pypi_upload_url(self, api_url: str, slug: str) -> str:
        raise NotImplementedError(_UNIFIED_MSG)

    def npm_registry_url(self, api_url: str, slug: str) -> str:
        raise NotImplementedError(_UNIFIED_MSG)

    def maven_repo_url(self, api_url: str, slug: str) -> str:
        raise NotImplementedError(_UNIFIED_MSG)


# ── Factory ───────────────────────────────────────────────────────────────────


def get_router(mode: RoutingMode = DEFAULT_ROUTING) -> CanonicalRouter | UnifiedRouter:
    """Return the router for *mode*.

    Args:
        mode: ``"canonical"`` (default) or ``"unified"``.

    Returns:
        A :class:`CanonicalRouter` or :class:`UnifiedRouter` instance.
        :class:`UnifiedRouter` raises :exc:`NotImplementedError` on every call.
    """
    if mode == "unified":
        return UnifiedRouter()
    return CanonicalRouter()
