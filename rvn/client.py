"""httpx-based Ravenstash Central API client.

All requests go through this module so that auth headers, base URL, and error
handling are consistent everywhere.

Usage
-----
    client = ApiClient.from_profile("default")
    repos = client.get("/webapp/repository/").json()
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

    def __init__(
        self,
        api_url: str,
        token: str,
        timeout: float = 30.0,
        profile: str | None = None,
    ) -> None:
        self._base = api_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._profile = profile

    @classmethod
    def from_profile(cls, profile: str | None = None) -> ApiClient:
        cfg = cfg_mod.load()
        profile_name = profile or cfg_mod.current_profile_name(cfg)
        p: ProfileConfig = cfg.active_profile(profile_name)
        token = auth_mod.get_token(profile_name)
        if not token:
            from . import output

            output.fatal(
                f"No token for profile '{profile_name}'. Run: rvn auth login --profile {profile_name}"
            )
        return cls(api_url=p.pkg_api_url, token=token, profile=profile_name)  # type: ignore[arg-type]

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

    def _refresh(self) -> bool:
        if not self._profile:
            return False
        token = auth_mod.refresh_expiring_credential(self._profile)
        if not token:
            return False
        self._token = token
        return True

    def _request(
        self, method: str, path: str, *, retry: bool = True, **kwargs: Any
    ) -> httpx.Response:
        with httpx.Client(timeout=self._timeout) as hx:
            resp = hx.request(method, self._url(path), headers=self._headers(), **kwargs)
        if resp.status_code == 401 and retry and self._refresh():
            return self._request(method, path, retry=False, **kwargs)
        self._raise(resp)
        return resp

    # ── request methods ───────────────────────────────────────────────────────

    def get(self, path: str, params: dict | None = None) -> httpx.Response:
        return self._request("GET", path, params=params)

    def post(self, path: str, json: Any = None, **kwargs: Any) -> httpx.Response:
        return self._request("POST", path, json=json, **kwargs)

    def patch(self, path: str, json: Any = None) -> httpx.Response:
        return self._request("PATCH", path, json=json)

    def delete(self, path: str) -> httpx.Response:
        return self._request("DELETE", path)
