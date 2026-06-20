from __future__ import annotations

from typing import Any, ClassVar

import httpx
import pytest
from rvn import auth as auth_mod
from rvn.client import ApiClient, ApiError


class _FakeHttpClient:
    responses: ClassVar[list[httpx.Response]] = []
    requests: ClassVar[list[tuple[str, str, dict[str, str]]]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> _FakeHttpClient:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        **kwargs: Any,
    ) -> httpx.Response:
        del kwargs
        self.requests.append((method, url, headers))
        return self.responses.pop(0)


def test_api_client_refreshes_and_retries_once(monkeypatch) -> None:
    _FakeHttpClient.requests = []
    _FakeHttpClient.responses = [
        httpx.Response(401, json={"detail": "expired"}),
        httpx.Response(200, json={"ok": True}),
    ]

    monkeypatch.setattr("rvn.client.httpx.Client", _FakeHttpClient)
    monkeypatch.setattr(
        auth_mod,
        "refresh_expiring_credential",
        lambda profile: "new-access" if profile == "default" else None,
    )

    response = ApiClient(
        "https://api.ravenstash.com",
        "old-access",
        profile="default",
    ).get("/webapp/repositories")

    assert response.json() == {"ok": True}
    assert [request[2]["Authorization"] for request in _FakeHttpClient.requests] == [
        "Bearer old-access",
        "Bearer new-access",
    ]


def test_api_client_without_profile_does_not_refresh(monkeypatch) -> None:
    _FakeHttpClient.requests = []
    _FakeHttpClient.responses = [
        httpx.Response(401, json={"detail": "expired"}),
    ]
    refresh_calls: list[str] = []

    monkeypatch.setattr("rvn.client.httpx.Client", _FakeHttpClient)
    monkeypatch.setattr(
        auth_mod,
        "refresh_expiring_credential",
        lambda profile: refresh_calls.append(profile) or "new-access",
    )

    with pytest.raises(ApiError) as exc_info:
        ApiClient(
            "https://api.ravenstash.com",
            "env-access",
            profile=None,
        ).get("/webapp/repositories")

    assert exc_info.value.status_code == 401
    assert refresh_calls == []
    assert len(_FakeHttpClient.requests) == 1
    assert _FakeHttpClient.requests[0][2]["Authorization"] == "Bearer env-access"
