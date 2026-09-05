from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from rvs import config as cfg_mod
from rvs.artifacts import commands as artifacts_cmd
from rvs.artifacts.registries.base import PublishResult
from typer.testing import CliRunner


runner = CliRunner()
STAGING_API_URL = "https://control.example.test"
PYPI_READ_URL = "https://pypi.packages.example.test"
PYPI_READ_HOST = "pypi.packages.example.test"
PYPI_PUSH_URL = "https://push.pypi.packages.example.test"
NPM_READ_URL = "https://npm.packages.example.test"
NPM_READ_HOST = "npm.packages.example.test"
NPM_PUSH_URL = "https://push.npm.packages.example.test"
MAVEN_READ_URL = "https://maven.packages.example.test"
MAVEN_PUSH_URL = "https://push.maven.packages.example.test"


class _JsonResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class _FakeApiClient:
    def __init__(self, responses: list[Any] | None = None) -> None:
        self.responses = responses or []
        self.calls: list[tuple[str, str, Any]] = []

    def get(self, path: str, params: dict[str, Any] | None = None) -> _JsonResponse:
        self.calls.append(("GET", path, params))
        if path == "/v0/repositories/resolve" and not self.responses:
            return _JsonResponse(_repository_entry())
        return _JsonResponse(self.responses.pop(0))

    def post(self, path: str, json: Any = None, **kwargs: Any) -> _JsonResponse:
        self.calls.append(("POST", path, json if json is not None else kwargs))
        if path == "/v0/package-credentials":
            return _JsonResponse(
                {
                    "access_token": "secret-token",
                    "native_path": "/test-account/repo",
                }
            )
        return _JsonResponse(self.responses.pop(0) if self.responses else {})

    def patch(self, path: str, json: Any = None) -> _JsonResponse:
        self.calls.append(("PATCH", path, json))
        return _JsonResponse(self.responses.pop(0) if self.responses else {})

    def put(self, path: str, json: Any = None) -> _JsonResponse:
        self.calls.append(("PUT", path, json))
        return _JsonResponse(self.responses.pop(0) if self.responses else {})

    def delete(self, path: str, params: dict[str, Any] | None = None) -> _JsonResponse:
        self.calls.append(("DELETE", path, params))
        return _JsonResponse(self.responses.pop(0) if self.responses else {})


def _repository_entry(name: str = "repo") -> dict[str, Any]:
    return {
        "customer": {
            "customer_id": "cus_123",
            "customer_unique_ref": "_custpid1",
            "account_label": "Test account",
        },
        "repository": {
            "repository_name": name,
            "namespace_name": "test-account",
            "namespace_realm": "internal",
            "namespace_unique_ref": "in_abcdefgh",
            "repository_unique_ref": "r_xyzabcde",
            "registry_kinds": ["pypi", "npm", "maven"],
        },
    }


def _isolate_config(monkeypatch, tmp_path: Path, content: str | None = None) -> None:
    config_dir = tmp_path / ".rvs"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text(
        content
        or """
default_profile = "default"

[profiles.default]
api_url = "https://api.ravenstash.com"
customer_id = "cus_123"
customer_unique_id = "custpid1"

[profiles.staging]
customer_id = "cus_123"
customer_unique_id = "custpid1"

[profiles.default.registries.pypi]
default_repo = "in_abcdefgh/r_xyzabcde"

[profiles.default.registries.npm]
default_repo = "in_abcdefgh/r_xyzabcde"

[profiles.default.registries.maven]
default_repo = "in_abcdefgh/r_xyzabcde"

[profiles.staging.registries.pypi]
default_repo = "in_abcdefgh/r_xyzabcde"

[profiles.staging.registries.npm]
default_repo = "in_abcdefgh/r_xyzabcde"

[profiles.staging.registries.maven]
default_repo = "in_abcdefgh/r_xyzabcde"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_file)
    monkeypatch.setattr(cfg_mod, "PROFILE_ENV_FILE", config_dir / "profiles.env")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RVS_ENV_FILE", raising=False)
    monkeypatch.setenv("RVS_PROFILE_STAGING_API_URL", STAGING_API_URL)
    monkeypatch.setenv("RVS_PROFILE_STAGING_PKG_API_URL", "https://app-staging.example.test/api")
    monkeypatch.setenv("RVS_PROFILE_STAGING_REPOSITORY_DOMAIN", "packages.example.test")
    _use_fake_client(monkeypatch, _FakeApiClient())


def _use_fake_client(monkeypatch, fake: _FakeApiClient) -> None:
    monkeypatch.setattr(
        artifacts_cmd.ApiClient, "from_profile", staticmethod(lambda profile=None: fake)
    )


def test_pkg_repo_list_filters_by_kind_and_uses_profile_customer(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient(
        [
            [
                {
                    **_repository_entry("repo-pypi"),
                    "repository": {
                        **_repository_entry("repo-pypi")["repository"],
                        "registry_kinds": ["pypi", "npm"],
                    },
                },
            ]
        ]
    )
    _use_fake_client(monkeypatch, fake)

    result = runner.invoke(artifacts_cmd.app, ["repo", "list", "--registry-kind", "pypi"])

    assert result.exit_code == 0
    assert fake.calls == [
        (
            "GET",
            "/v0/repositories",
            {"customer_id": "cus_123", "registry_kind": "pypi"},
        )
    ]
    assert "repo-pypi" in result.output


def test_pkg_repo_list_omits_unset_query_filters(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient([[]])
    _use_fake_client(monkeypatch, fake)

    result = runner.invoke(artifacts_cmd.app, ["repo", "list"])

    assert result.exit_code == 0
    assert fake.calls == [("GET", "/v0/repositories", {"customer_id": "cus_123"})]


def test_pkg_repo_create_can_set_default_repo(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient(
        [
            [
                {
                    "customer": _repository_entry()["customer"],
                    "namespace": {
                        "namespace_unique_ref": "in_abcdefgh",
                        "namespace_name": "test-account",
                        "namespace_realm": "internal",
                        "is_default": True,
                    },
                }
            ],
            _repository_entry("new-node"),
        ]
    )
    _use_fake_client(monkeypatch, fake)

    result = runner.invoke(
        artifacts_cmd.app,
        ["repo", "create", "new-node", "--registry-kind", "npm", "--default"],
    )

    assert result.exit_code == 0
    assert fake.calls == [
        ("GET", "/v0/namespaces", {"customer_id": "cus_123"}),
        (
            "POST",
            "/v0/repositories",
            {
                "customer_unique_ref": "_custpid1",
                "namespace_unique_ref": "in_abcdefgh",
                "repository_name": "new-node",
                "registry_kinds": ["npm"],
            },
        ),
    ]
    assert cfg_mod.load().registry_defaults("npm").default_repo == "in_abcdefgh/r_xyzabcde"
    assert "with registry kinds: npm" in result.output


@pytest.mark.parametrize("selector", ["Engineering", "in_abcdefgh"])
@pytest.mark.parametrize("repo_name", ["new-node", "New-Node"])
def test_create_resolves_namespace_inside_selected_customer(
    monkeypatch, tmp_path, selector, repo_name
):
    _isolate_config(monkeypatch, tmp_path)
    namespace = {
        "namespace_unique_ref": "in_abcdefgh",
        "namespace_name": "engineering",
        "namespace_realm": "internal",
        "is_default": False,
    }
    fake = _FakeApiClient(
        [
            [
                {"customer": {"customer_id": "foreign"}, "namespace": namespace},
                {"customer": _repository_entry()["customer"], "namespace": namespace},
            ],
            _repository_entry(repo_name),
        ]
    )
    _use_fake_client(monkeypatch, fake)
    result = runner.invoke(
        artifacts_cmd.app, ["repo", "create", f"{selector}/{repo_name}", "-k", "npm"]
    )
    assert result.exit_code == 0, result.output
    assert fake.calls == [
        ("GET", "/v0/namespaces", {"customer_id": "cus_123"}),
        (
            "POST",
            "/v0/repositories",
            {
                "customer_unique_ref": "_custpid1",
                "namespace_unique_ref": "in_abcdefgh",
                "repository_name": repo_name,
                "registry_kinds": ["npm"],
            },
        ),
    ]


def test_create_with_deferred_personal_namespace_requests_onboarding(monkeypatch, tmp_path):
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient([[]])
    _use_fake_client(monkeypatch, fake)
    result = runner.invoke(artifacts_cmd.app, ["repo", "create", "new-node", "-k", "npm"])
    assert result.exit_code != 0
    assert "finish onboarding" in result.output
    assert fake.calls == [("GET", "/v0/namespaces", {"customer_id": "cus_123"})]


@pytest.mark.parametrize("flags", [["--public"], ["--scope", "public"]])
def test_public_scope_never_runs_private_mutation(monkeypatch, flags):
    def unexpected_client(*_args, **_kwargs):
        raise AssertionError("Unavailable public scope must not reach the API")

    monkeypatch.setattr(artifacts_cmd.ApiClient, "from_profile", unexpected_client)
    result = runner.invoke(artifacts_cmd.app, [*flags, "repo", "create", "demo", "-k", "npm"])
    assert result.exit_code != 0
    assert "PublicCatalogUnavailable" in result.output


def test_pkg_repo_create_rejects_unknown_kind(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)

    result = runner.invoke(artifacts_cmd.app, ["repo", "create", "bad", "--registry-kind", "gem"])

    assert result.exit_code == 1
    assert "Unknown registry kind 'gem'" in result.stderr


def test_pkg_repo_show_renders_repository_details(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient(
        [
            {
                **_repository_entry("repo-pypi"),
                "repository": {
                    **_repository_entry("repo-pypi")["repository"],
                    "registry_kinds": ["pypi", "npm"],
                    "lanes": [{}, {}],
                    "aggregate_package_count": 7,
                    "aggregate_version_count": 13,
                    "aggregate_oci_repository_count": 2,
                    "aggregate_manifest_count": 5,
                    "aggregate_storage_bytes": 4096,
                    "created_at": "2026-06-20T00:00:00Z",
                },
            }
        ]
    )
    _use_fake_client(monkeypatch, fake)

    result = runner.invoke(artifacts_cmd.app, ["repo", "show", "repo-pypi"])

    assert result.exit_code == 0
    assert fake.calls == [
        (
            "GET",
            "/v0/repositories/resolve",
            {"selector": "repo-pypi", "customer_id": "cus_123"},
        )
    ]
    assert "repo-pypi" in result.output
    assert "Packages" in result.output
    assert "7" in result.output
    assert "Versions" in result.output
    assert "13" in result.output
    assert "OCI paths" in result.output
    assert "2" in result.output
    assert "Manifests" in result.output
    assert "5" in result.output
    assert "4096" in result.output


@pytest.mark.parametrize("new_name", ["renamed", "Repo-PyPI"])
def test_pkg_repo_rename_updates_matching_profile_default(
    monkeypatch, tmp_path: Path, new_name
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient([_repository_entry("repo-pypi"), _repository_entry(new_name)])
    _use_fake_client(monkeypatch, fake)

    result = runner.invoke(artifacts_cmd.app, ["repo", "rename", "repo-pypi", new_name])

    assert result.exit_code == 0
    assert fake.calls == [
        (
            "GET",
            "/v0/repositories/resolve",
            {"selector": "repo-pypi", "customer_id": "cus_123"},
        ),
        (
            "PATCH",
            "/v0/repositories/r_xyzabcde",
            {"repository_name": new_name},
        ),
    ]
    saved = cfg_mod.load().registry_defaults("pypi", "default")
    assert saved.default_repo == "in_abcdefgh/r_xyzabcde"
    assert saved.namespace_name_cache == "test-account"
    assert saved.repository_name_cache == new_name
    assert saved.repository_unique_ref == "r_xyzabcde"


def test_pkg_remote_management_and_upstream_configuration(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient(
        [
            {
                "customer": _repository_entry()["customer"],
                "remote_repository": {
                    "id": "remote_1",
                    "public_id": "pypi",
                    "registry_kind": "pypi",
                },
            },
            _repository_entry("repo-pypi"),
            {
                "customer": _repository_entry()["customer"],
                "remote_repository": {
                    "id": "remote_1",
                    "public_id": "pypi",
                    "registry_kind": "pypi",
                },
            },
            [],
            {
                "id": "attachment-1",
                "priority": 0,
                "source_type": "remote",
                "source_remote_name": "pypi",
                "registry_kind": "pypi",
                "min_age_hours": 5.0,
                "max_age_hours": None,
            },
        ]
    )
    _use_fake_client(monkeypatch, fake)

    create_result = runner.invoke(
        artifacts_cmd.app, ["mirror", "create", "--registry-kind", "pypi"]
    )
    upstream_result = runner.invoke(
        artifacts_cmd.app,
        [
            "repo",
            "upstream",
            "add",
            "repo-pypi",
            "pypi",
            "--remote-cache",
            "pypi",
            "--min-age-hours",
            "5",
        ],
    )

    assert create_result.exit_code == 0
    assert upstream_result.exit_code == 0
    assert fake.calls == [
        (
            "POST",
            "/v0/remote-repositories",
            {"customer_id": "cus_123", "registry_kind": "pypi"},
        ),
        (
            "GET",
            "/v0/repositories/resolve",
            {
                "selector": "repo-pypi",
                "customer_id": "cus_123",
                "registry_kind": "pypi",
            },
        ),
        (
            "GET",
            "/v0/remote-repositories/pypi",
            {"registry_kind": "pypi"},
        ),
        (
            "GET",
            "/v0/repositories/r_xyzabcde/lanes/pypi/upstreams",
            None,
        ),
        (
            "POST",
            "/v0/repositories/r_xyzabcde/lanes/pypi/upstreams",
            {
                "source_type": "remote",
                "source_repository_lane_id": "remote_1",
                "priority": 0,
                "min_age_hours": 5.0,
                "max_age_hours": None,
            },
        ),
    ]


def test_pkg_custom_remote_requires_and_submits_publication_control(
    monkeypatch, tmp_path: Path
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient(
        [
            {
                "customer": _repository_entry()["customer"],
                "remote_repository": {
                    "id": "remote_custom_1",
                    "public_id": "company-packages",
                    "remote_name": "company-packages",
                    "registry_kind": "pypi",
                },
            }
        ]
    )
    _use_fake_client(monkeypatch, fake)

    result = runner.invoke(
        artifacts_cmd.app,
        [
            "mirror",
            "create-custom",
            "company-packages",
            "--kind",
            "pypi",
            "--api-url",
            "https://packages.example.test/simple/",
            "--publication-control",
            "user-controlled",
        ],
    )

    assert result.exit_code == 0
    assert fake.calls == [
        (
            "POST",
            "/v0/remote-repositories/custom",
            {
                "customer_id": "cus_123",
                "registry_kind": "pypi",
                "remote_name": "company-packages",
                "publication_control": "user_controlled",
                "api_base_url": "https://packages.example.test/simple/",
                "credential": {"auth_scheme": "none", "allowed_hosts": []},
            },
        )
    ]


def test_pkg_official_remote_list_reports_external_publication_control(
    monkeypatch, tmp_path: Path
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient(
        [
            [
                {
                    "customer": _repository_entry()["customer"],
                    "remote_repository": {
                        "id": "remote_official_1",
                        "public_id": "pypi",
                        "official_slug": "pypi",
                        "source_family": "official",
                        "registry_kind": "pypi",
                        "min_age_hours": None,
                    },
                }
            ]
        ]
    )
    _use_fake_client(monkeypatch, fake)
    tables: list[tuple[list[str], list[list[str]]]] = []
    monkeypatch.setattr(
        artifacts_cmd.output,
        "table",
        lambda headers, rows, **_kwargs: tables.append((headers, rows)),
    )

    result = runner.invoke(artifacts_cmd.app, ["mirror", "list"])

    assert result.exit_code == 0
    assert tables[0][0][2] == "Publication"
    assert tables[0][1][0][2] == "externally_controlled"
    assert tables[0][1][0][-1] == "No minimum"


def test_pkg_mirror_show_formats_absent_age_bounds(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient(
        [
            {
                "remote_repository": {
                    "id": "remote_official_1",
                    "public_id": "pypiorg",
                    "official_slug": "pypiorg",
                    "source_family": "official",
                    "customer_id": "cus_123",
                    "registry_kind": "pypi",
                    "min_age_hours": None,
                    "max_age_hours": None,
                }
            }
        ]
    )
    _use_fake_client(monkeypatch, fake)

    result = runner.invoke(artifacts_cmd.app, ["mirror", "show", "pypiorg"])

    assert result.exit_code == 0
    assert "No minimum" in result.output
    assert "No maximum" in result.output
    assert "None hours" not in result.output


def test_pkg_repo_upstream_add_private_uses_source_lane_and_zero_age_default(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    destination = _repository_entry("application")
    source = _repository_entry("shared")
    source["repository"] = {
        **source["repository"],
        "repository_unique_ref": "r_shared01",
        "namespace_name": "libraries",
        "namespace_realm": "internal",
        "lanes": [{"id": "lane-b-pypi", "registry_kind": "pypi"}],
    }
    attachment = {
        "id": "attachment-a-b",
        "priority": 0,
        "source_type": "private",
        "source_namespace_name": "libraries",
        "source_repository_name": "shared",
        "registry_kind": "pypi",
        "min_age_hours": None,
        "max_age_hours": None,
    }
    fake = _FakeApiClient([destination, source, [], attachment])
    _use_fake_client(monkeypatch, fake)

    result = runner.invoke(
        artifacts_cmd.app,
        [
            "repo",
            "upstream",
            "add",
            "application",
            "pypi",
            "--private-repository",
            "libraries/shared",
        ],
    )

    assert result.exit_code == 0
    assert fake.calls[-1] == (
        "POST",
        "/v0/repositories/r_xyzabcde/lanes/pypi/upstreams",
        {
            "source_type": "private",
            "source_repository_lane_id": "lane-b-pypi",
            "priority": 0,
            "min_age_hours": 0.0,
            "max_age_hours": None,
        },
    )


def test_pkg_repo_upstream_add_appends_after_existing_plan(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    destination = _repository_entry("application")
    source = _repository_entry("shared")
    source["repository"] = {
        **source["repository"],
        "repository_unique_ref": "r_shared01",
        "namespace_name": "libraries",
        "namespace_realm": "internal",
        "lanes": [{"id": "lane-b-pypi", "registry_kind": "pypi"}],
    }
    attachment = {
        "id": "attachment-a-b",
        "priority": 2,
        "source_type": "private",
        "source_namespace_name": "libraries",
        "source_repository_name": "shared",
        "registry_kind": "pypi",
        "min_age_hours": None,
        "max_age_hours": None,
    }
    fake = _FakeApiClient([destination, source, [{"id": "one"}, {"id": "two"}], attachment])
    _use_fake_client(monkeypatch, fake)

    result = runner.invoke(
        artifacts_cmd.app,
        [
            "repo",
            "upstream",
            "add",
            "application",
            "pypi",
            "--private-repository",
            "libraries/shared",
        ],
    )

    assert result.exit_code == 0
    assert fake.calls[-1][2]["priority"] == 2


def test_pkg_repo_upstream_reorder_and_remove_use_generic_routes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient([_repository_entry("application"), [], _repository_entry("application")])
    _use_fake_client(monkeypatch, fake)

    reordered = runner.invoke(
        artifacts_cmd.app,
        [
            "repo",
            "upstream",
            "reorder",
            "application",
            "npm",
            "attachment-b",
            "attachment-r",
        ],
    )
    removed = runner.invoke(
        artifacts_cmd.app,
        [
            "repo",
            "upstream",
            "remove",
            "application",
            "npm",
            "attachment-b",
        ],
    )

    assert reordered.exit_code == 0
    assert removed.exit_code == 0
    assert (
        "PUT",
        "/v0/repositories/r_xyzabcde/lanes/npm/upstreams/order",
        {"attachment_ids": ["attachment-b", "attachment-r"]},
    ) in fake.calls
    assert (
        "DELETE",
        "/v0/repositories/r_xyzabcde/lanes/npm/upstreams/attachment-b",
        None,
    ) in fake.calls


def test_pkg_repo_upstream_add_requires_exactly_one_source(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _use_fake_client(monkeypatch, _FakeApiClient())

    neither = runner.invoke(
        artifacts_cmd.app,
        ["repo", "upstream", "add", "application", "pypi"],
    )
    both = runner.invoke(
        artifacts_cmd.app,
        [
            "repo",
            "upstream",
            "add",
            "application",
            "pypi",
            "--private-repository",
            "shared",
            "--remote-cache",
            "pypi",
        ],
    )

    assert neither.exit_code == 1
    assert both.exit_code == 1
    assert "exactly one" in neither.output
    assert "exactly one" in both.output


def test_pkg_repo_upstream_priority_is_limited_to_four_slots() -> None:
    result = runner.invoke(
        artifacts_cmd.app,
        [
            "repo",
            "upstream",
            "add",
            "application",
            "pypi",
            "--private-repository",
            "shared",
            "--priority",
            "4",
        ],
    )

    assert result.exit_code == 2
    assert "0<=x<=3" in result.output


def test_pkg_package_list_and_show_use_repository_package_paths(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient(
        [
            _repository_entry("repo-pypi"),
            {
                "items": [
                    {
                        "package_name": "demo",
                        "latest_version": "1.2.3",
                        "version_count": 2,
                        "total_size_bytes": 1234,
                    }
                ]
            },
            _repository_entry("repo-pypi"),
            {
                "repository_unique_ref": "repo-pypi",
                "package_name": "demo",
                "latest_version": "1.2.3",
                "version_count": 2,
                "total_size_bytes": 1234,
                "versions": [
                    {
                        "version": "1.2.3",
                        "yanked": False,
                        "files": [{"filename": "demo.whl"}],
                        "total_size_bytes": 1000,
                    }
                ],
            },
        ]
    )
    _use_fake_client(monkeypatch, fake)

    list_result = runner.invoke(
        artifacts_cmd.app, ["package", "list", "--repo", "repo-pypi", "--registry-kind", "pypi"]
    )
    show_result = runner.invoke(
        artifacts_cmd.app,
        ["package", "show", "demo", "--repo", "repo-pypi", "--registry-kind", "pypi"],
    )

    assert list_result.exit_code == 0
    assert show_result.exit_code == 0
    assert fake.calls == [
        (
            "GET",
            "/v0/repositories/resolve",
            {
                "selector": "repo-pypi",
                "customer_id": "cus_123",
                "registry_kind": "pypi",
            },
        ),
        (
            "GET",
            "/v0/repositories/r_xyzabcde/lanes/pypi/packages",
            None,
        ),
        (
            "GET",
            "/v0/repositories/resolve",
            {
                "selector": "repo-pypi",
                "customer_id": "cus_123",
                "registry_kind": "pypi",
            },
        ),
        (
            "GET",
            "/v0/repositories/r_xyzabcde/lanes/pypi/package",
            {"package_name": "demo"},
        ),
    ]
    assert "demo" in list_result.output
    assert "1.2.3" in show_result.output


def test_pkg_package_mutations_call_expected_api_paths(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient()
    _use_fake_client(monkeypatch, fake)

    delete_result = runner.invoke(
        artifacts_cmd.app,
        [
            "package",
            "delete",
            "demo",
            "--repo",
            "repo-pypi",
            "--registry-kind",
            "pypi",
            "--yes",
        ],
    )
    delete_version_result = runner.invoke(
        artifacts_cmd.app,
        [
            "package",
            "delete-version",
            "demo",
            "1.0.0",
            "--repo",
            "repo-pypi",
            "--registry-kind",
            "pypi",
            "--yes",
        ],
    )
    yank_result = runner.invoke(
        artifacts_cmd.app,
        [
            "package",
            "yank",
            "demo",
            "1.0.1",
            "--repo",
            "repo-pypi",
            "--registry-kind",
            "pypi",
            "--reason",
            "bad build",
        ],
    )

    assert delete_result.exit_code == 0
    assert delete_version_result.exit_code == 0
    assert yank_result.exit_code == 0
    assert fake.calls == [
        (
            "GET",
            "/v0/repositories/resolve",
            {
                "selector": "repo-pypi",
                "customer_id": "cus_123",
                "registry_kind": "pypi",
            },
        ),
        (
            "DELETE",
            "/v0/repositories/r_xyzabcde/lanes/pypi/package",
            {"package_name": "demo"},
        ),
        (
            "GET",
            "/v0/repositories/resolve",
            {
                "selector": "repo-pypi",
                "customer_id": "cus_123",
                "registry_kind": "pypi",
            },
        ),
        (
            "DELETE",
            "/v0/repositories/r_xyzabcde/lanes/pypi/package-version",
            {"package_name": "demo", "version": "1.0.0"},
        ),
        (
            "GET",
            "/v0/repositories/resolve",
            {
                "selector": "repo-pypi",
                "customer_id": "cus_123",
                "registry_kind": "pypi",
            },
        ),
        (
            "POST",
            "/v0/repositories/r_xyzabcde/lanes/pypi/package-version/yank",
            {"reason": "bad build"},
        ),
    ]


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (
            ["pypi", "index-url", "--profile", "staging"],
            f"{PYPI_READ_URL}/test-account/repo/simple/",
        ),
        (
            ["pypi", "upload-url", "--profile", "staging"],
            f"{PYPI_PUSH_URL}/test-account/repo/",
        ),
        (
            ["npm", "registry-url", "--profile", "staging"],
            f"{NPM_READ_URL}/test-account/repo/",
        ),
        (
            ["maven", "repo-url", "--profile", "staging"],
            f"{MAVEN_READ_URL}/test-account/repo/",
        ),
    ],
)
def test_pkg_registry_url_helpers_use_profile_and_default_repo(
    monkeypatch,
    tmp_path: Path,
    args: list[str],
    expected: str,
) -> None:
    _isolate_config(monkeypatch, tmp_path)

    result = runner.invoke(artifacts_cmd.app, args)

    assert result.exit_code == 0
    assert result.output.strip() == expected


def test_pkg_configure_snippets_are_printed_for_native_toolchains(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)

    pypi_result = runner.invoke(artifacts_cmd.app, ["pypi", "configure", "--profile", "staging"])
    npm_result = runner.invoke(artifacts_cmd.app, ["npm", "configure", "--profile", "staging"])
    maven_result = runner.invoke(artifacts_cmd.app, ["maven", "configure", "--profile", "staging"])

    assert pypi_result.exit_code == 0
    assert "index-url" in pypi_result.output
    assert "extra-index-url" not in pypi_result.output
    assert "/test-account/repo/" in pypi_result.output
    assert npm_result.exit_code == 0
    assert "_authToken=${RVS_TOKEN}" in npm_result.output
    assert "/test-account/repo/" in npm_result.output
    assert maven_result.exit_code == 0
    assert "<settings" in maven_result.output
    assert "/test-account/repo/" in maven_result.output


def test_pypi_install_uses_ephemeral_netrc_auth(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    monkeypatch.delenv("PIP_KEYRING_PROVIDER", raising=False)
    monkeypatch.setenv("RVS_TOKEN", "raw-control-token")
    monkeypatch.setattr(artifacts_cmd.tools, "pip_cmd", lambda: ["/bin/pip"])
    calls: list[tuple[list[str], dict[str, str]]] = []
    netrc_texts: list[str] = []

    def capture(cmd, *, env, check) -> None:
        del check
        netrc_texts.append(Path(env["NETRC"]).read_text(encoding="utf-8"))
        calls.append((cmd, env.copy()))

    monkeypatch.setattr(artifacts_cmd.subprocess, "run", capture)

    result = runner.invoke(artifacts_cmd.app, ["pypi", "install", "demo", "--profile", "staging"])

    assert result.exit_code == 0
    assert calls[0][0] == ["/bin/pip", "install", "demo"]
    assert calls[0][1]["PIP_INDEX_URL"] == (f"https://{PYPI_READ_HOST}/test-account/repo/simple/")
    assert "RVS_TOKEN" not in calls[0][1]
    assert "PIP_KEYRING_PROVIDER" not in calls[0][1]
    assert netrc_texts == [f"machine {PYPI_READ_HOST} login __token__ password secret-token\n"]
    assert not Path(calls[0][1]["NETRC"]).exists()


def test_pypi_install_refreshes_native_path_when_saved_target_name_changed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    cfg_mod.set_registry_default_target(
        "pypi",
        customer=_repository_entry("old-name")["customer"],
        repository=_repository_entry("old-name")["repository"],
        profile="staging",
    )

    class ChangedTargetClient(_FakeApiClient):
        def post(self, path: str, json: Any = None, **kwargs: Any) -> _JsonResponse:
            self.calls.append(("POST", path, json if json is not None else kwargs))
            assert json["expected_target"]["repository_name"] == "old-name"
            return _JsonResponse(
                {
                    "access_token": "secret-token",
                    "native_path": "/test-account/new-name",
                }
            )

    fake = ChangedTargetClient([_repository_entry("new-name")])
    _use_fake_client(monkeypatch, fake)
    monkeypatch.setattr(artifacts_cmd.tools, "pip_cmd", lambda: ["/bin/pip"])
    native_calls: list[list[str]] = []
    monkeypatch.setattr(
        artifacts_cmd.subprocess,
        "run",
        lambda cmd, **kwargs: native_calls.append(cmd),
    )

    result = runner.invoke(artifacts_cmd.app, ["pypi", "install", "demo", "--profile", "staging"])

    assert result.exit_code == 0
    assert native_calls == [["/bin/pip", "install", "demo"]]
    assert cfg_mod.load().registry_defaults("pypi", "staging").repository_name_cache == "old-name"


def test_npm_install_injects_token_for_registry_host(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    monkeypatch.setenv("RVS_TOKEN", "raw-control-token")
    monkeypatch.setattr(artifacts_cmd.tools, "npm", lambda: "/bin/npm")
    calls: list[tuple[list[str], dict[str, str]]] = []
    monkeypatch.setattr(
        artifacts_cmd.subprocess,
        "run",
        lambda cmd, *, env, check: calls.append((cmd, env)),
    )

    result = runner.invoke(
        artifacts_cmd.app, ["npm", "install", "@scope/demo", "--profile", "staging"]
    )

    assert result.exit_code == 0
    assert calls[0][0] == [
        "/bin/npm",
        "install",
        "--registry",
        f"{NPM_READ_URL}/test-account/repo/",
        "@scope/demo",
    ]
    assert (
        calls[0][1][f"NPM_CONFIG_//{NPM_READ_HOST}/test-account/repo/:_authToken"] == "secret-token"
    )
    assert "RVS_TOKEN" not in calls[0][1]


def test_maven_install_does_not_forward_control_token(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    monkeypatch.setenv("RVS_TOKEN", "raw-control-token")
    monkeypatch.setattr(
        artifacts_cmd.tools, "require", lambda name, *, install_kind: f"/bin/{name}"
    )
    calls: list[tuple[list[str], dict[str, str]]] = []

    def capture(cmd, *, env, check) -> None:
        del check
        settings_arg = next(arg for arg in cmd if arg.startswith("--settings="))
        settings = Path(settings_arg.removeprefix("--settings="))
        assert "secret-token" in settings.read_text(encoding="utf-8")
        calls.append((cmd, env.copy()))

    monkeypatch.setattr(artifacts_cmd.subprocess, "run", capture)

    result = runner.invoke(
        artifacts_cmd.app,
        ["maven", "install", "com.example:demo:1.0.0", "--profile", "staging"],
    )

    assert result.exit_code == 0
    assert calls[0][0][0] == "/bin/mvn"
    assert "RVS_TOKEN" not in calls[0][1]
    settings_arg = next(arg for arg in calls[0][0] if arg.startswith("--settings="))
    assert not Path(settings_arg.removeprefix("--settings=")).exists()


def test_pypi_publish_reports_failed_uploads(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    monkeypatch.setenv("RVS_TOKEN", "secret-token")
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "demo-1.0.0.whl").write_bytes(b"wheel")
    monkeypatch.setattr(
        artifacts_cmd.pypi_reg,
        "publish",
        lambda **kwargs: [
            PublishResult("demo-1.0.0.whl", "1.0.0", True),
            PublishResult("demo-1.0.0.tar.gz", "1.0.0", False, "HTTP 500"),
        ],
    )

    result = runner.invoke(
        artifacts_cmd.app, ["pypi", "publish", str(dist_dir), "--profile", "staging"]
    )

    assert result.exit_code == 1
    assert "Published demo-1.0.0.whl" in result.output
    assert "Failed demo-1.0.0.tar.gz" in result.stderr


def test_npm_publish_calls_registry_adapter(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    monkeypatch.setenv("RVS_TOKEN", "secret-token")
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    calls: list[dict[str, Any]] = []

    def fake_publish(**kwargs: Any) -> list[PublishResult]:
        calls.append(kwargs)
        return [PublishResult("demo-1.0.0.tgz", "1.0.0", True)]

    monkeypatch.setattr(artifacts_cmd.npm_reg, "publish", fake_publish)

    result = runner.invoke(
        artifacts_cmd.app, ["npm", "publish", str(package_dir), "--profile", "staging"]
    )

    assert result.exit_code == 0
    assert calls == [
        {
            "registry_url": f"{NPM_PUSH_URL}/test-account/repo/",
            "token": "secret-token",
            "package_dir": package_dir,
            "download_registry_url": f"{NPM_READ_URL}/test-account/repo/",
        }
    ]


def test_maven_deploy_checks_file_and_calls_registry_adapter(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    monkeypatch.setenv("RVS_TOKEN", "secret-token")
    artifact = tmp_path / "demo-1.0.0.jar"
    artifact.write_bytes(b"jar")
    calls: list[dict[str, Any]] = []

    def fake_publish(**kwargs: Any) -> list[PublishResult]:
        calls.append(kwargs)
        return [PublishResult("demo.jar", "1.0.0", True)]

    monkeypatch.setattr(artifacts_cmd.maven_reg, "publish", fake_publish)

    result = runner.invoke(
        artifacts_cmd.app,
        [
            "maven",
            "deploy",
            str(artifact),
            "--group",
            "com.example",
            "--artifact",
            "demo",
            "--version",
            "1.0.0",
            "--profile",
            "staging",
        ],
    )

    assert result.exit_code == 0
    assert calls == [
        {
            "upload_url": f"{MAVEN_PUSH_URL}/test-account/repo/",
            "token": "secret-token",
            "group_id": "com.example",
            "artifact_id": "demo",
            "version": "1.0.0",
            "files": [artifact],
        }
    ]
