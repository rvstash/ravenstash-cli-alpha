"""httpx-based Ravenstash DevAPI client.

All requests go through this module so that auth headers, base URL, and error
handling are consistent everywhere.

Usage
-----
    client = ApiClient.from_profile("default")
    repos = client.get("/repositories").json()
"""

from __future__ import annotations

import importlib.metadata
import random
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any

from . import auth as auth_mod
from . import config as cfg_mod
from .devapi import ApiVersionMismatchError, api_url, validate_api_version


if TYPE_CHECKING:
    import httpx

    from .config import ProfileConfig


def _rvs_ua() -> str:
    try:
        return f"rvs/{importlib.metadata.version('ravenstash-cli')}"
    except importlib.metadata.PackageNotFoundError:
        return "rvs/dev"


class ApiError(Exception):
    """Raised when the API returns a non-2xx response."""

    def __init__(self, status_code: int, detail: Any, *, retry_after: float | None = None) -> None:
        self.status_code = status_code
        self.detail = detail
        self.retry_after = retry_after
        super().__init__(self._message())

    def _message(self) -> str:
        if isinstance(self.detail, dict) and self.detail.get("code") == "RepositoryTargetAmbiguous":
            matches = self.detail.get("matches")
            if isinstance(matches, list):
                choices = ", ".join(
                    str(item.get("account_ref"))
                    for item in matches
                    if isinstance(item, dict) and item.get("account_ref")
                )
                suffix = f" Choose an account with --account: {choices}." if choices else ""
                return f"Repository target is ambiguous.{suffix}"
        if isinstance(self.detail, dict) and self.detail.get("code") == "RepositoryTargetChanged":
            expected = self.detail.get("expected")
            current = self.detail.get("current")
            if isinstance(expected, dict) and isinstance(current, dict):
                expected_name = "/".join(
                    str(expected.get(key) or "?") for key in ("namespace_name", "repository_name")
                )
                current_name = "/".join(
                    str(current.get(key) or "?") for key in ("namespace_name", "repository_name")
                )
                stable = "/".join(
                    str(current.get(key) or expected.get(key) or "?")
                    for key in ("namespace_unique_ref", "repository_unique_ref")
                )
                return (
                    "Repository target changed; no package operation was attempted. "
                    f"Expected {expected_name}, current {current_name}, identity {stable}. "
                    "Use `rvs art repo set-default` to explicitly re-select the stable "
                    "identity, or the repository currently using the former name."
                )
        return f"HTTP {self.status_code}: {self.detail}"


class ApiClient:
    """Thin wrapper around the versioned Ravenstash DevAPI."""

    def __init__(
        self,
        api_url: str,
        token: str,
        timeout: float = 30.0,
        profile: str | None = None,
        allow_refresh: bool = True,
        refresh_before_request: bool = False,
    ) -> None:
        self._base = api_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._profile = profile
        self._allow_refresh = allow_refresh
        self._refresh_before_request = refresh_before_request

    @classmethod
    def from_profile(cls, profile: str | None = None) -> ApiClient:
        cfg = cfg_mod.load()
        profile_name = profile or cfg_mod.current_profile_name(cfg)
        p: ProfileConfig = cfg.active_profile(profile_name)
        refresh_before_request = auth_mod.credential_needs_refresh(profile_name)
        token = (
            auth_mod.get_token(profile_name, refresh=False)
            if refresh_before_request
            else auth_mod.get_token(profile_name)
        )
        if not token and refresh_before_request:
            token = auth_mod.get_token(profile_name)
            refresh_before_request = False
        if not token:
            from . import output

            output.fatal(
                f"No token for profile '{profile_name}'. Run: rvs auth login --profile {profile_name}"
            )
        return cls(
            api_url=p.api_url,
            token=token,  # type: ignore[arg-type]
            profile=profile_name,
            allow_refresh=auth_mod.token_source(profile_name) != "RVS_TOKEN",
            refresh_before_request=refresh_before_request,
        )

    # ── internal ──────────────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "User-Agent": _rvs_ua(),
        }

    def _url(self, path: str) -> str:
        return api_url(self._base, path)

    def _raise(self, resp: httpx.Response) -> None:
        if resp.is_success:
            return
        try:
            payload = resp.json()
            error = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(error, dict):
                detail = {"code": error.get("code"), "message": error.get("message")}
                if isinstance(error.get("details"), dict):
                    detail.update(error["details"])
            else:
                detail = payload.get("detail", resp.text)
        except Exception:
            detail = resp.text or resp.reason_phrase
        retry_after = None
        raw_retry_after = resp.headers.get("Retry-After")
        if raw_retry_after:
            try:
                retry_after = max(0.0, float(raw_retry_after))
            except ValueError:
                try:
                    retry_after = max(
                        0.0,
                        (
                            parsedate_to_datetime(raw_retry_after) - datetime.now(UTC)
                        ).total_seconds(),
                    )
                except TypeError, ValueError, OverflowError:
                    pass
        raise ApiError(resp.status_code, detail, retry_after=retry_after)

    def _validate_contract(self, resp: httpx.Response) -> None:
        try:
            validate_api_version(resp)
        except ApiVersionMismatchError as exc:
            raise ApiError(502, str(exc)) from exc

    def _refresh(self, http_client: httpx.Client) -> bool:
        if not self._profile or not self._allow_refresh:
            return False
        token = auth_mod.refresh_expiring_credential(
            self._profile,
            stale_access_token=self._token,
            http_client=http_client,
        )
        if not token:
            return False
        self._token = token
        return True

    def _request(
        self, method: str, path: str, *, retry: bool = True, **kwargs: Any
    ) -> httpx.Response:
        import httpx

        transport_attempts = 3 if method.upper() == "GET" else 1
        with httpx.Client(timeout=self._timeout) as hx:

            def send() -> httpx.Response:
                for attempt in range(transport_attempts):
                    try:
                        return hx.request(
                            method,
                            self._url(path),
                            headers=self._headers(),
                            **kwargs,
                        )
                    except httpx.TransportError:
                        if attempt + 1 == transport_attempts:
                            raise
                        time.sleep((0.25, 1.0)[attempt])
                raise RuntimeError("HTTP transport attempt limit exceeded")

            if self._refresh_before_request:
                if not self._refresh(hx):
                    raise ApiError(401, "Could not refresh the expired CLI session")
                self._refresh_before_request = False
            resp = send()
            if resp.status_code == 401 and retry and self._refresh(hx):
                resp = send()
        self._raise(resp)
        self._validate_contract(resp)
        return resp

    # ── request methods ───────────────────────────────────────────────────────

    def get(self, path: str, params: dict | None = None) -> httpx.Response:
        return self._request("GET", path, params=params)

    def post(self, path: str, json: Any = None, **kwargs: Any) -> httpx.Response:
        return self._request("POST", path, json=json, **kwargs)

    def issue_native(self, path: str, payload: dict) -> httpx.Response:
        """Bounded retries only for temporary issuance, never arbitrary mutations."""
        import httpx

        if path not in {"/package-credentials", "/remote-package-credentials"}:
            raise ValueError("Native issuance requires a known credential endpoint")
        deadline = time.monotonic() + 30
        for attempt in range(3):
            retry_after = None
            try:
                return self.post(
                    path,
                    json=payload,
                    retry=False,
                    timeout=min(5.0, max(0.01, (deadline - time.monotonic()) / 4)),
                )
            except ApiError as exc:
                if exc.status_code not in {429, 502, 503, 504} or attempt == 2:
                    raise
                failure: Exception = exc
                retry_after = exc.retry_after
            except httpx.TransportError as exc:
                if attempt == 2:
                    raise
                failure = exc
            delay = (0.25, 1.0)[attempt] + random.uniform(0, 0.1)
            if retry_after is not None:
                delay = max(delay, retry_after)
            if time.monotonic() + delay >= deadline:
                raise failure
            time.sleep(delay)
        raise RuntimeError("Native issuance retry limit exceeded")

    def patch(
        self,
        path: str,
        json: Any = None,
        params: dict | None = None,
    ) -> httpx.Response:
        return self._request("PATCH", path, json=json, params=params)

    def put(
        self,
        path: str,
        json: Any = None,
        params: dict | None = None,
    ) -> httpx.Response:
        return self._request("PUT", path, json=json, params=params)

    def delete(self, path: str, params: dict | None = None) -> httpx.Response:
        return self._request("DELETE", path, params=params)
