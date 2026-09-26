from __future__ import annotations

from typing import Any, ClassVar

import httpx2 as httpx
import pytest
from rvs import auth as auth_mod
from rvs import config as cfg_mod
from rvs.client import ApiClient, ApiError, if_match, response_etag
from rvs.devapi import (
    api_path,
    api_url,
    artifacts_path,
    collection_all,
    is_mint_token_path,
    platform_path,
    read_collection,
    remote_cache_mint_token_path,
    repository_mint_token_path,
    retired_route_message,
    retry_after_seconds,
    segment,
)


class _FakeHttpClient:
    responses: ClassVar[list[httpx.Response | Exception]] = []
    requests: ClassVar[list[tuple[str, str, dict[str, str], dict[str, Any]]]] = []
    instances: ClassVar[list[_FakeHttpClient]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.instances.append(self)

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
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_api_client_refreshes_and_retries_once(monkeypatch) -> None:
    _FakeHttpClient.instances = []
    _FakeHttpClient.requests = []
    _FakeHttpClient.responses = [
        httpx.Response(401, json={"detail": "expired"}),
        httpx.Response(200, json={"ok": True}),
    ]

    monkeypatch.setattr(httpx, "Client", _FakeHttpClient)
    monkeypatch.setattr(
        auth_mod,
        "refresh_expiring_credential",
        lambda profile, **_kwargs: "new-access" if profile == "default" else None,
    )

    response = ApiClient(
        "https://api.ravenstash.com",
        "old-access",
        profile="default",
    ).get(artifacts_path("repositories"))

    assert response.json() == {"ok": True}
    assert [request[2]["Authorization"] for request in _FakeHttpClient.requests] == [
        "Bearer old-access",
        "Bearer new-access",
    ]
    assert len(_FakeHttpClient.instances) == 1


def test_api_client_preemptive_refresh_reuses_request_connection(monkeypatch) -> None:
    _FakeHttpClient.instances = []
    _FakeHttpClient.requests = []
    _FakeHttpClient.responses = [httpx.Response(200, json={"ok": True})]
    refresh_clients: list[object] = []

    monkeypatch.setattr(httpx, "Client", _FakeHttpClient)

    def refresh(profile: str, **kwargs: Any) -> str | None:
        assert profile == "default"
        refresh_clients.append(kwargs["http_client"])
        return "new-access"

    monkeypatch.setattr(auth_mod, "refresh_expiring_credential", refresh)

    response = ApiClient(
        "https://api.ravenstash.com",
        "old-access",
        profile="default",
        refresh_before_request=True,
    ).get(platform_path("accounts"))

    assert response.json() == {"ok": True}
    assert refresh_clients == _FakeHttpClient.instances
    assert _FakeHttpClient.requests[0][2]["Authorization"] == "Bearer new-access"


def test_api_client_retries_idempotent_get_transport_failures(monkeypatch) -> None:
    _FakeHttpClient.requests = []
    request = httpx.Request("GET", "https://api.ravenstash.com/v0/artifacts/repositories/resolve")
    _FakeHttpClient.responses = [
        httpx.ReadTimeout("timed out", request=request),
        httpx.Response(200, json={"ok": True}),
    ]

    monkeypatch.setattr(httpx, "Client", _FakeHttpClient)
    monkeypatch.setattr("rvs.client.time.sleep", lambda _seconds: None)

    response = ApiClient("https://api.ravenstash.com", "access").get(
        artifacts_path("repositories/resolve")
    )

    assert response.json() == {"ok": True}
    assert len(_FakeHttpClient.requests) == 2


def test_api_client_does_not_retry_post_transport_failures(monkeypatch) -> None:
    _FakeHttpClient.requests = []
    request = httpx.Request(
        "POST", "https://api.ravenstash.com/v0/artifacts/repositories/ar_xyzabcde/mint-token"
    )
    _FakeHttpClient.responses = [httpx.ReadTimeout("timed out", request=request)]

    monkeypatch.setattr(httpx, "Client", _FakeHttpClient)

    with pytest.raises(httpx.ReadTimeout):
        ApiClient("https://api.ravenstash.com", "access").post(
            repository_mint_token_path("ar_xyzabcde"),
            json={"formats": ["pypi"], "operations": ["read"]},
        )

    assert len(_FakeHttpClient.requests) == 1


def test_api_client_without_profile_does_not_refresh(monkeypatch) -> None:
    _FakeHttpClient.requests = []
    _FakeHttpClient.responses = [
        httpx.Response(401, json={"detail": "expired"}),
    ]
    refresh_calls: list[str] = []

    monkeypatch.setattr(httpx, "Client", _FakeHttpClient)
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
        ).get(artifacts_path("repositories"))

    assert exc_info.value.status_code == 401
    assert refresh_calls == []
    assert len(_FakeHttpClient.requests) == 1
    assert _FakeHttpClient.requests[0][2]["Authorization"] == "Bearer env-access"


def test_repository_target_conflict_has_an_actionable_message() -> None:
    error = ApiError(
        409,
        {
            "code": "RepositoryTargetChanged",
            "expected": {
                "namespace_name": "old-namespace",
                "namespace_realm": "internal",
                "repository_name": "old-repository",
                "namespace_ref": "in_abcdefgh",
                "repository_ref": "ar_xyzabcde",
            },
            "current": {
                "namespace_name": "new-namespace",
                "namespace_realm": "internal",
                "repository_name": "new-repository",
                "namespace_ref": "in_abcdefgh",
                "repository_ref": "ar_xyzabcde",
            },
        },
    )

    assert "no package operation was attempted" in str(error)
    assert "old-namespace/old-repository" in str(error)
    assert "new-namespace/new-repository" in str(error)
    assert "in/ar_xyzabcde" in str(error)
    assert "rvs art select" in str(error)


def test_repository_target_ambiguity_uses_public_account_references() -> None:
    error = ApiError(
        409,
        {
            "code": "RepositoryTargetAmbiguous",
            "matches": [
                {"account_ref": "ac_abcdefgh"},
                {"account_ref": "ac_23456789"},
            ],
        },
    )

    assert str(error) == (
        "Repository target is ambiguous. Choose an account with --account: ac_abcdefgh, ac_23456789."
    )


def test_api_client_from_profile_honors_rvs_profile(monkeypatch, tmp_path) -> None:
    config_dir = tmp_path / ".rvs"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text(
        """
config_version = 6
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
    monkeypatch.setenv("RVS_PROFILE", "work")
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


def test_api_client_from_profile_never_refreshes_rvs_token_on_401(
    monkeypatch,
    tmp_path,
) -> None:
    config_dir = tmp_path / ".rvs"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text(
        """
config_version = 6
default_profile = "default"

[profiles.default]
pkg_api_url = "https://app.example/api"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_file)
    monkeypatch.setenv("RVS_TOKEN", "rvs_ust" + "A" * 43)
    _FakeHttpClient.requests = []
    _FakeHttpClient.responses = [httpx.Response(401, json={"detail": "rejected"})]
    refresh_calls: list[str] = []
    monkeypatch.setattr(httpx, "Client", _FakeHttpClient)
    monkeypatch.setattr(
        auth_mod,
        "refresh_expiring_credential",
        lambda profile: refresh_calls.append(profile) or "local-token",
    )

    with pytest.raises(ApiError):
        ApiClient.from_profile().get(platform_path("me"))

    assert refresh_calls == []
    assert len(_FakeHttpClient.requests) == 1
    assert _FakeHttpClient.requests[0][2]["Authorization"] == "Bearer rvs_ust" + "A" * 43


def test_api_client_request_methods_pass_paths_payloads_and_params(monkeypatch) -> None:
    _FakeHttpClient.requests = []
    _FakeHttpClient.responses = [
        httpx.Response(200, json={"items": []}),
        httpx.Response(201, json={"created": True}),
        httpx.Response(200, json={"updated": True}),
        httpx.Response(204),
    ]
    monkeypatch.setattr(httpx, "Client", _FakeHttpClient)
    client = ApiClient("https://api.example/", "token")

    client.get(platform_path("namespaces"), params={"account_ref": "ac_23456789"})
    client.post(artifacts_path("repositories"), json={"name": "repo"})
    client.patch(artifacts_path("repositories/ar_xyzabcde"), json={"name": "new"})
    client.delete(artifacts_path("repositories/ar_xyzabcde"))

    assert [(method, url) for method, url, _headers, _kwargs in _FakeHttpClient.requests] == [
        ("GET", "https://api.example/v0/platform/namespaces"),
        ("POST", "https://api.example/v0/artifacts/repositories"),
        ("PATCH", "https://api.example/v0/artifacts/repositories/ar_xyzabcde"),
        ("DELETE", "https://api.example/v0/artifacts/repositories/ar_xyzabcde"),
    ]
    assert _FakeHttpClient.requests[0][3]["params"] == {"account_ref": "ac_23456789"}
    assert _FakeHttpClient.requests[1][3]["json"] == {"name": "repo"}
    assert _FakeHttpClient.requests[2][3]["json"] == {"name": "new"}


def test_devapi_version_and_groups_are_centralized_in_path_builders() -> None:
    assert api_path("meta") == "/v0/meta"
    assert platform_path("auth/device/code") == "/v0/platform/auth/device/code"
    assert platform_path("/me") == "/v0/platform/me"
    assert artifacts_path("repositories") == "/v0/artifacts/repositories"
    assert artifacts_path("repositories/ar_xyzabcde/formats/pypi/packages") == (
        "/v0/artifacts/repositories/ar_xyzabcde/formats/pypi/packages"
    )
    assert segment("sha256:abc/def") == "sha256%3Aabc%2Fdef"


@pytest.mark.parametrize("builder", [api_path, platform_path, artifacts_path])
@pytest.mark.parametrize(
    "path",
    [
        "/v0/repositories",
        "v0",
        "v1/platform/me",
        "v1beta1/meta",
        "/platform/me",
        "platform",
        "artifacts/repositories",
        "/artifacts",
    ],
)
def test_path_builders_reject_pre_versioned_or_pre_grouped_input(builder, path: str) -> None:
    with pytest.raises(ValueError, match="must not embed"):
        builder(path)


def test_grouped_path_builders_require_a_resource() -> None:
    with pytest.raises(ValueError, match="resource path is required"):
        platform_path("")
    with pytest.raises(ValueError, match="resource path is required"):
        artifacts_path("/")


@pytest.mark.parametrize(
    "path",
    ["repositories", "/repositories", "/v0/repositories", "/v0/me", "/v0/artifacts", "/v1/meta"],
)
def test_api_url_rejects_paths_not_built_by_a_group_builder(path: str) -> None:
    with pytest.raises(ValueError, match="Build DevAPI paths"):
        api_url("https://api.example", path)


def test_api_url_joins_built_paths() -> None:
    assert api_url("https://api.example/", api_path("meta")) == "https://api.example/v0/meta"
    assert (
        api_url("https://api.example", artifacts_path("meta"))
        == "https://api.example/v0/artifacts/meta"
    )


def test_mint_token_paths_are_the_only_native_issuance_routes() -> None:
    assert repository_mint_token_path("ar_xyzabcde") == (
        "/v0/artifacts/repositories/ar_xyzabcde/mint-token"
    )
    assert remote_cache_mint_token_path("rc_abcdefgh") == (
        "/v0/artifacts/remote-caches/rc_abcdefgh/mint-token"
    )
    assert is_mint_token_path(repository_mint_token_path("ar_xyzabcde"))
    assert is_mint_token_path(remote_cache_mint_token_path("rc_abcdefgh"))
    assert not is_mint_token_path("/package-credentials")
    assert not is_mint_token_path("/v0/package-credentials")
    assert not is_mint_token_path(artifacts_path("repositories/ar_xyzabcde"))
    assert not is_mint_token_path(artifacts_path("repositories/ar_xyzabcde/formats/oci/mint-token"))


def test_issue_native_rejects_non_mint_paths() -> None:
    with pytest.raises(ValueError, match="mint-token"):
        ApiClient("https://api.example", "token").issue_native(
            artifacts_path("repositories"), {"operations": ["read"]}
        )


_RETIRED = {
    "error": {
        "code": "ApiRouteRetired",
        "message": "This rvs release uses a retired API route. Upgrade rvs.",
        "details": None,
    },
    "request_id": "req_1",
}


def test_api_client_surfaces_retired_route_message(monkeypatch) -> None:
    _FakeHttpClient.requests = []
    _FakeHttpClient.responses = [httpx.Response(410, json=_RETIRED)]
    monkeypatch.setattr(httpx, "Client", _FakeHttpClient)

    with pytest.raises(ApiError) as exc_info:
        ApiClient("https://api.example", "token").get(artifacts_path("repositories"))

    assert exc_info.value.status_code == 410
    assert str(exc_info.value) == "This rvs release uses a retired API route. Upgrade rvs."


def test_retired_route_message_recognizes_only_the_retired_code() -> None:
    assert retired_route_message(httpx.Response(410, json=_RETIRED)) == (
        "This rvs release uses a retired API route. Upgrade rvs."
    )
    assert retired_route_message(httpx.Response(410, json={"error": {"code": "Gone"}})) is None
    assert retired_route_message(httpx.Response(404, json=_RETIRED)) is None
    assert retired_route_message(httpx.Response(410, text="gone")) is None


def test_api_client_rejects_a_different_reported_contract(monkeypatch) -> None:
    _FakeHttpClient.requests = []
    _FakeHttpClient.responses = [
        httpx.Response(
            200,
            headers={"Ravenstash-API-Version": "v1beta1"},
            json={"items": []},
        )
    ]
    monkeypatch.setattr(httpx, "Client", _FakeHttpClient)

    with pytest.raises(ApiError, match="expects 'v0'") as exc_info:
        ApiClient("https://api.example", "token").get(artifacts_path("repositories"))

    assert exc_info.value.status_code == 502


def test_api_client_error_uses_json_detail(monkeypatch) -> None:
    _FakeHttpClient.requests = []
    _FakeHttpClient.responses = [httpx.Response(403, json={"detail": "forbidden"})]
    monkeypatch.setattr(httpx, "Client", _FakeHttpClient)

    with pytest.raises(ApiError) as exc_info:
        ApiClient("https://api.example", "token").get(platform_path("me"))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "forbidden"


@pytest.mark.parametrize("status", [429, 503])
def test_api_client_retries_reads_after_the_servers_retry_after(monkeypatch, status) -> None:
    _FakeHttpClient.requests = []
    _FakeHttpClient.responses = [
        httpx.Response(status, headers={"Retry-After": "3"}, json={"error": {"code": "x"}}),
        httpx.Response(status, headers={"Retry-After": "1"}, json={"error": {"code": "x"}}),
        httpx.Response(200, json={"ok": True}),
    ]
    sleeps: list[float] = []
    monkeypatch.setattr(httpx, "Client", _FakeHttpClient)
    monkeypatch.setattr("rvs.client.time.sleep", sleeps.append)

    response = ApiClient("https://api.example", "token").get(platform_path("me"))

    assert response.json() == {"ok": True}
    assert sleeps == [3.0, 1.0]
    assert len(_FakeHttpClient.requests) == 3


def test_api_client_reports_a_retry_after_longer_than_it_waits(monkeypatch) -> None:
    _FakeHttpClient.requests = []
    _FakeHttpClient.responses = [
        httpx.Response(
            429,
            headers={"Retry-After": "120"},
            json={"error": {"code": "RateLimited", "message": "Too many requests"}},
        )
    ]
    sleeps: list[float] = []
    monkeypatch.setattr(httpx, "Client", _FakeHttpClient)
    monkeypatch.setattr("rvs.client.time.sleep", sleeps.append)

    with pytest.raises(ApiError) as exc_info:
        ApiClient("https://api.example", "token").get(platform_path("me"))

    assert sleeps == []
    assert exc_info.value.retry_after == 120.0
    assert "retry after 120s" in str(exc_info.value)


def test_api_client_gives_up_after_bounded_read_retries(monkeypatch) -> None:
    _FakeHttpClient.requests = []
    _FakeHttpClient.responses = [
        httpx.Response(503, json={"error": {"code": "ServiceUnavailable", "message": "down"}})
        for _ in range(3)
    ]
    monkeypatch.setattr(httpx, "Client", _FakeHttpClient)
    monkeypatch.setattr("rvs.client.time.sleep", lambda _seconds: None)

    with pytest.raises(ApiError) as exc_info:
        ApiClient("https://api.example", "token").get(platform_path("me"))

    assert exc_info.value.status_code == 503
    assert len(_FakeHttpClient.requests) == 3


def test_api_client_does_not_retry_rate_limited_writes(monkeypatch) -> None:
    _FakeHttpClient.requests = []
    _FakeHttpClient.responses = [
        httpx.Response(429, headers={"Retry-After": "1"}, json={"error": {"code": "RateLimited"}})
    ]
    monkeypatch.setattr(httpx, "Client", _FakeHttpClient)
    monkeypatch.setattr("rvs.client.time.sleep", lambda _seconds: None)

    with pytest.raises(ApiError) as exc_info:
        ApiClient("https://api.example", "token").patch(
            artifacts_path("repositories/ar_xyzabcde"), json={"name": "new"}
        )

    assert exc_info.value.retry_after == 1.0
    assert len(_FakeHttpClient.requests) == 1


def test_api_client_sends_if_match_and_explains_a_failed_precondition(monkeypatch) -> None:
    _FakeHttpClient.requests = []
    _FakeHttpClient.responses = [
        httpx.Response(200, headers={"ETag": '"rev-1"'}, json={"ref": "rc_abcdefgh"}),
        httpx.Response(
            412,
            json={
                "error": {
                    "code": "PreconditionFailed",
                    "message": "If-Match does not match",
                    "details": None,
                }
            },
        ),
        httpx.Response(201, json={"tag": "v1", "digest": "sha256:" + "a" * 64}),
    ]
    monkeypatch.setattr(httpx, "Client", _FakeHttpClient)
    client = ApiClient("https://api.example", "token")

    etag = response_etag(client.get(artifacts_path("remote-caches/rc_abcdefgh")))
    with pytest.raises(ApiError) as exc_info:
        client.delete(artifacts_path("remote-caches/rc_abcdefgh"), headers=if_match(etag))
    put = client.put(
        artifacts_path("repositories/ar_xyzabcde/formats/oci/tags/v1"),
        json={"digest": "sha256:" + "a" * 64},
        params={"path": "images/api"},
    )

    assert etag == '"rev-1"'
    assert _FakeHttpClient.requests[1][2]["If-Match"] == '"rev-1"'
    assert "If-Match" not in _FakeHttpClient.requests[0][2]
    assert exc_info.value.precondition_failed
    assert "changed since it was read" in str(exc_info.value)
    assert _FakeHttpClient.requests[2][0] == "PUT"
    assert _FakeHttpClient.requests[2][3]["params"] == {"path": "images/api"}
    assert put.status_code == 201
    assert if_match(None) is None


def test_retry_after_accepts_seconds_and_http_dates() -> None:
    assert retry_after_seconds({"Retry-After": "7"}) == 7.0
    assert retry_after_seconds({"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}) == 0.0
    assert retry_after_seconds({"Retry-After": "soon"}) is None
    assert retry_after_seconds({}) is None


class _PagedClient:
    def __init__(self, pages: list[Any]) -> None:
        self.pages = pages
        self.calls: list[tuple[str, dict | None]] = []

    def get(self, path: str, params: dict | None = None) -> Any:
        self.calls.append((path, params))
        payload = self.pages.pop(0)
        if isinstance(payload, Exception):
            raise payload

        class _Response:
            @staticmethod
            def json() -> Any:
                return payload

        return _Response()


def test_collections_follow_next_cursor_until_null() -> None:
    client = _PagedClient(
        [
            {"items": [{"n": 1}, {"n": 2}], "next_cursor": "c1"},
            {"items": [], "next_cursor": "c2"},
            {"items": [{"n": 3}], "next_cursor": None},
        ]
    )

    items = collection_all(client, "/v0/platform/accounts", {"account_ref": None, "x": "y"})

    assert items == [{"n": 1}, {"n": 2}, {"n": 3}]
    assert client.calls == [
        ("/v0/platform/accounts", {"x": "y", "limit": 100}),
        ("/v0/platform/accounts", {"x": "y", "limit": 100, "cursor": "c1"}),
        ("/v0/platform/accounts", {"x": "y", "limit": 100, "cursor": "c2"}),
    ]


def test_bounded_collection_reads_stop_early_and_keep_the_resume_cursor() -> None:
    client = _PagedClient(
        [
            {"items": [{"n": 1}], "next_cursor": "c1"},
            {"items": [{"n": 2}, {"n": 3}], "next_cursor": "c3"},
        ]
    )

    page = read_collection(client, "/v0/x", max_items=3, cursor="c0")

    assert page.items == [{"n": 1}, {"n": 2}, {"n": 3}]
    assert page.next_cursor == "c3"
    assert page.envelope() == {"items": page.items, "next_cursor": "c3"}
    assert client.calls == [
        ("/v0/x", {"limit": 3, "cursor": "c0"}),
        ("/v0/x", {"limit": 2, "cursor": "c1"}),
    ]


@pytest.mark.parametrize(
    "pages",
    [
        [{"items": [], "next_cursor": 5}],
        [{"items": [], "next_cursor": ""}],
        [{"items": [{}, {}], "next_cursor": None}],
        [{"items": [], "next_cursor": "same"}, {"items": [], "next_cursor": "same"}],
        [[{"n": 1}]],
    ],
)
def test_collections_reject_invalid_pages(pages) -> None:
    with pytest.raises(ValueError):
        read_collection(_PagedClient(pages), "/v0/x", page_size=1)


def test_a_rejected_cursor_is_surfaced() -> None:
    client = _PagedClient(
        [
            {"items": [{"n": 1}], "next_cursor": "bad"},
            ApiError(422, {"code": "ValidationFailed", "message": "Invalid cursor"}),
        ]
    )

    with pytest.raises(ApiError) as exc_info:
        collection_all(client, "/v0/x")

    assert exc_info.value.status_code == 422
