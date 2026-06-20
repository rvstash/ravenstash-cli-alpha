from __future__ import annotations

from typing import Any, ClassVar

import httpx
import pytest
from rvn import auth as auth_mod
from rvn import config as cfg_mod
from rvn.client import ApiClient, ApiError


class _FakeHttpClient:
    responses: ClassVar[list[httpx.Response]] = []
    requests: ClassVar[list[tuple[str, str, dict[str, str], dict[str, Any]]]] = []

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
        self.requests.append((method, url, headers, kwargs))
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
    ).get("/webapp/repository")

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
        ).get("/webapp/repository")

    assert exc_info.value.status_code == 401
    assert refresh_calls == []
    assert len(_FakeHttpClient.requests) == 1
    assert _FakeHttpClient.requests[0][2]["Authorization"] == "Bearer env-access"


def test_api_client_from_profile_honors_rvn_profile(monkeypatch, tmp_path) -> None:
    config_dir = tmp_path / ".rvn"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text(
        """
default_profile = "default"

[profiles.default]
api_url = "https://api.default.example"

[profiles.work]
api_url = "https://api.work.example"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_file)
    monkeypatch.setenv("RVN_PROFILE", "work")
    seen_profiles: list[str] = []
    monkeypatch.setattr(
        auth_mod,
        "get_token",
        lambda profile: seen_profiles.append(profile) or "work-token",
    )

    client = ApiClient.from_profile()

    assert client._base == "https://api.work.example"
    assert client._profile == "work"
    assert seen_profiles == ["work"]


def test_api_client_request_methods_pass_paths_payloads_and_params(monkeypatch) -> None:
    _FakeHttpClient.requests = []
    _FakeHttpClient.responses = [
        httpx.Response(200, json={"items": []}),
        httpx.Response(201, json={"created": True}),
        httpx.Response(200, json={"updated": True}),
        httpx.Response(204),
    ]
    monkeypatch.setattr("rvn.client.httpx.Client", _FakeHttpClient)
    client = ApiClient("https://api.example/", "token")

    client.get("/items", params={"customer_id": "cus_123"})
    client.post("items", json={"name": "repo"})
    client.patch("/items/repo", json={"name": "new"})
    client.delete("/items/repo")

    assert [(method, url) for method, url, _headers, _kwargs in _FakeHttpClient.requests] == [
        ("GET", "https://api.example/items"),
        ("POST", "https://api.example/items"),
        ("PATCH", "https://api.example/items/repo"),
        ("DELETE", "https://api.example/items/repo"),
    ]
    assert _FakeHttpClient.requests[0][3]["params"] == {"customer_id": "cus_123"}
    assert _FakeHttpClient.requests[1][3]["json"] == {"name": "repo"}
    assert _FakeHttpClient.requests[2][3]["json"] == {"name": "new"}


def test_api_client_error_uses_json_detail(monkeypatch) -> None:
    _FakeHttpClient.requests = []
    _FakeHttpClient.responses = [httpx.Response(403, json={"detail": "forbidden"})]
    monkeypatch.setattr("rvn.client.httpx.Client", _FakeHttpClient)

    with pytest.raises(ApiError) as exc_info:
        ApiClient("https://api.example", "token").get("/private")

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "forbidden"
