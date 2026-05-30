"""httpx-based Ravenstash Central API client.

All requests go through this module so that auth headers, base URL, and error
handling are consistent everywhere.

Usage
-----
    client = ApiClient.from_profile("default")
    repos = client.get("/webapp/repositories/").json()
"""

from __future__ import annotations

import importlib.metadata
from typing import TYPE_CHECKING, Any

import httpx

from . import auth as auth_mod
from . import config as cfg_mod


if TYPE_CHECKING:
    from .config import ProfileConfig


def _rvn_ua() -> str:
    try:
        return f"rvn/{importlib.metadata.version('rvn')}"
    except importlib.metadata.PackageNotFoundError:
        return "rvn/dev"


class ApiError(Exception):
    """Raised when the API returns a non-2xx response."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


class ApiClient:
    """Thin wrapper around httpx.Client for the Central REST API."""

    def __init__(self, api_url: str, token: str, timeout: float = 30.0) -> None:
        self._base = api_url.rstrip("/")
        self._token = token
        self._timeout = timeout

    @classmethod
    def from_profile(cls, profile: str | None = None) -> ApiClient:
        cfg = cfg_mod.load()
        profile_name = profile or cfg.default_profile
        p: ProfileConfig = cfg.active_profile(profile_name)
        token = auth_mod.get_token(profile_name) or p.token
        if not token:
            from . import output

            output.fatal(
                f"No token for profile '{profile_name}'. Run: rvn login --profile {profile_name}"
            )
        return cls(api_url=p.api_url, token=token)  # type: ignore[arg-type]

    # ── internal ──────────────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "User-Agent": _rvn_ua(),
        }

    def _url(self, path: str) -> str:
        return f"{self._base}/{path.lstrip('/')}"

    def _raise(self, resp: httpx.Response) -> None:
        if resp.is_success:
            return
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text or resp.reason_phrase
        raise ApiError(resp.status_code, str(detail))

    # ── request methods ───────────────────────────────────────────────────────

    def get(self, path: str, params: dict | None = None) -> httpx.Response:
        with httpx.Client(timeout=self._timeout) as hx:
            resp = hx.get(self._url(path), headers=self._headers(), params=params)
        self._raise(resp)
        return resp

    def post(self, path: str, json: Any = None, **kwargs: Any) -> httpx.Response:
        with httpx.Client(timeout=self._timeout) as hx:
            resp = hx.post(self._url(path), headers=self._headers(), json=json, **kwargs)
        self._raise(resp)
        return resp

    def patch(self, path: str, json: Any = None) -> httpx.Response:
        with httpx.Client(timeout=self._timeout) as hx:
            resp = hx.patch(self._url(path), headers=self._headers(), json=json)
        self._raise(resp)
        return resp

    def delete(self, path: str) -> httpx.Response:
        with httpx.Client(timeout=self._timeout) as hx:
            resp = hx.delete(self._url(path), headers=self._headers())
        self._raise(resp)
        return resp

    # ── auth helpers ──────────────────────────────────────────────────────────

    def login(self, email: str, password: str) -> str:
        """Exchange credentials for a JWT access token."""
        with httpx.Client(timeout=self._timeout) as hx:
            resp = hx.post(
                self._url("/webapp/auth/login"),
                json={"email": email, "password": password},
            )
        self._raise(resp)
        data = resp.json()
        return data["access_token"]

    def create_repo_token(self, repo_slug: str, write: bool = False) -> dict:
        """Create a repository-scoped API token.

        Returns the full token object including the plain-text ``token`` field
        (only returned on creation).
        """
        resp = self.post(
            "/webapp/tokens/",
            json={"repository_slug": repo_slug, "write": write},
        )
        return resp.json()
