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
        if path == "/repositories/resolve" and not self.responses:
            return _JsonResponse(_repository_entry())
        payload = self.responses.pop(0)
        if isinstance(payload, list):
            payload = {"items": payload, "next_cursor": None}
        return _JsonResponse(payload)

    def issue_native(self, path: str, payload: dict):
        assert payload["duration_seconds"] == 14400
        return self.post(path, json=payload)

    def post(self, path: str, json: Any = None, **kwargs: Any) -> _JsonResponse:
        self.calls.append(("POST", path, json if json is not None else kwargs))
        if path == "/package-credentials":
            return _JsonResponse(
                {
                    "access_token": "rvs_sltAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                    "native_paths": {kind: "/test-account/repo" for kind in json["formats"]},
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
        "account": {
            "account_ref": "ac_23456789",
            "account_label": "Test account",
            "account_type": "organization",
            "organization_role": "owner",
        },
        "repository": {
            "repository_name": name,
            "namespace_name": "test-account",
            "namespace_realm": "internal",
            "namespace_unique_ref": "in_abcdefgh",
            "repository_unique_ref": "r_xyzabcde",
            "formats": [
                {"format": kind, "upstream_config_revision": 7} for kind in ("pypi", "npm", "maven")
            ],
        },
    }


def _isolate_config(monkeypatch, tmp_path: Path, content: str | None = None) -> None:
    config_dir = tmp_path / ".rvs"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text(
        content
        or """
config_version = 4
default_profile = "default"

[profiles.default]
api_url = "https://api.ravenstash.com"
account_ref = "ac_23456789"

[profiles.staging]
account_ref = "ac_23456789"

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


def test_artifacts_repo_list_filters_by_kind_and_uses_profile_customer(
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
                        "formats": ["pypi", "npm"],
                    },
                },
            ]
        ]
    )
    _use_fake_client(monkeypatch, fake)

    result = runner.invoke(artifacts_cmd.app, ["repo", "list", "--format", "pypi"])

    assert result.exit_code == 0
    assert fake.calls == [
        (
            "GET",
            "/repositories",
            {"account_ref": "ac_23456789", "format": "pypi"},
        )
    ]
    assert "repo-pypi" in result.output


def test_artifacts_repo_list_omits_unset_query_filters(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient([[]])
    _use_fake_client(monkeypatch, fake)

    result = runner.invoke(artifacts_cmd.app, ["repo", "list"])

    assert result.exit_code == 0
    assert fake.calls == [("GET", "/repositories", {"account_ref": "ac_23456789"})]


def test_artifacts_repo_create_can_set_default_repo(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient(
        [
            [
                {
                    "account": _repository_entry()["account"],
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
        ["repo", "create", "new-node", "--format", "npm", "--default"],
    )

    assert result.exit_code == 0
    assert fake.calls == [
        ("GET", "/namespaces", {"account_ref": "ac_23456789"}),
        (
            "POST",
            "/repositories",
            {
                "account_ref": "ac_23456789",
                "namespace_unique_ref": "in_abcdefgh",
                "repository_name": "new-node",
                "formats": ["npm"],
            },
        ),
    ]
    assert cfg_mod.load().registry_defaults("npm").default_repo == "in_abcdefgh/r_xyzabcde"
    assert "with formats: npm" in result.output


@pytest.mark.parametrize(
    "flags",
    [
        ["-f", "pypi,npm,maven,container,helm"],
        ["-f", "pypi, npm", "--format", "maven", "-f", "container,helm,pypi"],
    ],
)
def test_repo_create_accepts_comma_separated_and_repeated_formats(monkeypatch, tmp_path, flags):
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient(
        [
            [
                {
                    "account": _repository_entry()["account"],
                    "namespace": {
                        "namespace_unique_ref": "in_abcdefgh",
                        "namespace_name": "test-account",
                        "namespace_realm": "internal",
                        "is_default": True,
                    },
                }
            ],
            _repository_entry("packages"),
        ]
    )
    _use_fake_client(monkeypatch, fake)
    result = runner.invoke(artifacts_cmd.app, ["repo", "create", "packages", *flags])
    assert result.exit_code == 0, result.output
    assert fake.calls[-1][2]["formats"] == ["pypi", "npm", "maven", "container", "helm"]


@pytest.mark.parametrize("value", ["pypi,", ",npm", "pypi,unknown", " "])
def test_repo_create_rejects_invalid_format_set_before_api(monkeypatch, value):
    monkeypatch.setattr(
        artifacts_cmd, "_client", lambda *_: pytest.fail("Invalid formats reached API")
    )
    result = runner.invoke(artifacts_cmd.app, ["repo", "create", "packages", "-f", value])
    assert result.exit_code != 0
    assert "Unknown or empty format" in result.output


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
                {"account": {"account_ref": "foreign"}, "namespace": namespace},
                {"account": _repository_entry()["account"], "namespace": namespace},
            ],
            _repository_entry(repo_name),
        ]
    )
    _use_fake_client(monkeypatch, fake)
    result = runner.invoke(
        artifacts_cmd.app, ["repo", "create", f"{selector}/{repo_name}", "-f", "npm"]
    )
    assert result.exit_code == 0, result.output
    assert fake.calls == [
        ("GET", "/namespaces", {"account_ref": "ac_23456789"}),
        (
            "POST",
            "/repositories",
            {
                "account_ref": "ac_23456789",
                "namespace_unique_ref": "in_abcdefgh",
                "repository_name": repo_name,
                "formats": ["npm"],
            },
        ),
    ]


def test_create_with_deferred_personal_namespace_requests_onboarding(monkeypatch, tmp_path):
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient([[]])
    _use_fake_client(monkeypatch, fake)
    result = runner.invoke(artifacts_cmd.app, ["repo", "create", "new-node", "-f", "npm"])
    assert result.exit_code != 0
    assert "finish onboarding" in result.output
    assert fake.calls == [("GET", "/namespaces", {"account_ref": "ac_23456789"})]


@pytest.mark.parametrize("flags", [["--public"], ["--scope", "public"]])
def test_public_scope_never_runs_private_mutation(monkeypatch, flags):
    def unexpected_client(*_args, **_kwargs):
        raise AssertionError("Unavailable public scope must not reach the API")

    monkeypatch.setattr(artifacts_cmd.ApiClient, "from_profile", unexpected_client)
    result = runner.invoke(artifacts_cmd.app, [*flags, "repo", "create", "demo", "-f", "npm"])
    assert result.exit_code != 0
    assert "No such option" in result.output


def test_artifacts_repo_create_rejects_unknown_kind(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)

    result = runner.invoke(artifacts_cmd.app, ["repo", "create", "bad", "--format", "gem"])

    assert result.exit_code == 1
    assert "Unknown or empty format 'gem'" in result.stderr


def test_artifacts_repo_show_renders_repository_details(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient(
        [
            {
                **_repository_entry("repo-pypi"),
                "repository": {
                    **_repository_entry("repo-pypi")["repository"],
                    "formats": ["pypi", "npm"],
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
            "/repositories/resolve",
            {"selector": "repo-pypi", "account_ref": "ac_23456789"},
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
def test_artifacts_repo_rename_updates_matching_profile_default(
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
            "/repositories/resolve",
            {"selector": "repo-pypi", "account_ref": "ac_23456789"},
        ),
        (
            "PATCH",
            "/repositories/r_xyzabcde",
            {"repository_name": new_name},
        ),
    ]
    saved = cfg_mod.load().registry_defaults("pypi", "default")
    assert saved.default_repo == "in_abcdefgh/r_xyzabcde"
    assert saved.namespace_name_cache == "test-account"
    assert saved.repository_name_cache == new_name
    assert saved.repository_unique_ref == "r_xyzabcde"


def test_artifacts_remote_management_and_upstream_configuration(
    monkeypatch, tmp_path: Path
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient(
        [
            [{"source_ref": "pypiorg", "format": "pypi"}],
            {
                "account": _repository_entry()["account"],
                "remote_cache": {
                    "id": "remote_1",
                    "public_id": "pypi",
                    "remote_cache_ref": "rc_abcdefgh",
                    "format": "pypi",
                },
            },
            _repository_entry("repo-pypi"),
            {
                "account": _repository_entry()["account"],
                "remote_cache": {
                    "id": "remote_1",
                    "public_id": "pypi",
                    "remote_cache_ref": "rc_abcdefgh",
                    "format": "pypi",
                },
            },
            {
                "id": "attachment-1",
                "position": 1,
                "source_type": "remote",
                "source_remote_name": "pypi",
                "format": "pypi",
                "min_age_hours": 5.0,
                "max_age_hours": None,
            },
        ]
    )
    _use_fake_client(monkeypatch, fake)

    create_result = runner.invoke(artifacts_cmd.app, ["mirror", "create", "--format", "pypi"])
    upstream_result = runner.invoke(
        artifacts_cmd.app,
        [
            "repo",
            "upstream",
            "add",
            "repo-pypi",
            "pypi",
            "--remote-cache",
            "rc_abcdefgh",
            "--position",
            "1",
            "--min-age-hours",
            "5",
        ],
    )

    assert create_result.exit_code == 0
    assert upstream_result.exit_code == 0
    assert fake.calls == [
        (
            "GET",
            "/remote-caches/official-sources",
            {"account_ref": "ac_23456789"},
        ),
        (
            "POST",
            "/remote-caches/official",
            {"account_ref": "ac_23456789", "source_ref": "pypiorg"},
        ),
        (
            "GET",
            "/repositories/resolve",
            {
                "selector": "repo-pypi",
                "account_ref": "ac_23456789",
                "format": "pypi",
            },
        ),
        (
            "GET",
            "/remote-caches/rc_abcdefgh",
            {"format": "pypi"},
        ),
        (
            "POST",
            "/repositories/r_xyzabcde/formats/pypi/upstreams",
            {
                "source_type": "remote",
                "remote_cache_ref": "rc_abcdefgh",
                "position": 1,
                "expected_revision": 7,
                "min_age_hours": 5.0,
                "max_age_hours": None,
            },
        ),
    ]


def test_artifacts_official_remote_add_uses_public_source_ref(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient(
        [
            {
                "items": [
                    {
                        "source_ref": "pypiorg",
                        "display_name": "Python Package Index",
                        "format": "pypi",
                    }
                ],
                "next_cursor": None,
            },
            {
                "account": _repository_entry()["account"],
                "remote_cache": {
                    "remote_cache_ref": "rc_23456789",
                    "source_type": "official",
                    "official_slug": "pypiorg",
                    "format": "pypi",
                },
            },
        ]
    )
    _use_fake_client(monkeypatch, fake)

    result = runner.invoke(artifacts_cmd.app, ["mirror", "create", "pypiorg"])

    assert result.exit_code == 0
    assert fake.calls == [
        (
            "GET",
            "/remote-caches/official-sources",
            {"account_ref": "ac_23456789"},
        ),
        (
            "POST",
            "/remote-caches/official",
            {"account_ref": "ac_23456789", "source_ref": "pypiorg"},
        ),
    ]


def test_artifacts_official_remote_list_reports_external_publication_control(
    monkeypatch, tmp_path: Path
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient(
        [
            [
                {
                    "account": _repository_entry()["account"],
                    "remote_cache": {
                        "id": "remote_official_1",
                        "public_id": "pypi",
                        "remote_cache_ref": "rc_23456789",
                        "official_slug": "pypi",
                        "source_type": "official",
                        "format": "pypi",
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
    assert tables[0][0][1] == "Remote-cache ref"
    assert tables[0][1][0][1] == "rc_23456789"
    assert tables[0][0][3] == "Publication"
    assert tables[0][1][0][3] == "externally_controlled"
    assert tables[0][1][0][-1] == "No minimum"


def test_artifacts_mirror_show_formats_absent_age_bounds(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient(
        [
            {
                "remote_cache": {
                    "id": "remote_official_1",
                    "public_id": "pypiorg",
                    "remote_cache_ref": "rc_abcdefgh",
                    "official_slug": "pypiorg",
                    "source_type": "official",
                    "account_ref": "ac_23456789",
                    "format": "pypi",
                    "min_age_hours": None,
                    "max_age_hours": None,
                }
            }
        ]
    )
    _use_fake_client(monkeypatch, fake)

    result = runner.invoke(artifacts_cmd.app, ["mirror", "show", "rc_abcdefgh"])

    assert result.exit_code == 0
    assert "No minimum" in result.output
    assert "No maximum" in result.output
    assert "None hours" not in result.output


def test_artifacts_repo_upstream_add_private_uses_source_lane_and_zero_age_default(
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
        "formats": [{"format": "pypi", "upstream_config_revision": 1}],
    }
    attachment = {
        "id": "attachment-a-b",
        "position": 1,
        "source_type": "private",
        "source_namespace_name": "libraries",
        "source_repository_name": "shared",
        "format": "pypi",
        "min_age_hours": None,
        "max_age_hours": None,
    }
    fake = _FakeApiClient([destination, source, attachment])
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
            "--position",
            "1",
        ],
    )

    assert result.exit_code == 0
    assert fake.calls[-1] == (
        "POST",
        "/repositories/r_xyzabcde/formats/pypi/upstreams",
        {
            "source_type": "private",
            "source_repository_unique_ref": "r_shared01",
            "position": 1,
            "expected_revision": 7,
            "min_age_hours": 0.0,
            "max_age_hours": None,
        },
    )


def test_artifacts_repo_upstream_add_uses_explicit_sparse_position(
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
        "formats": [{"format": "pypi", "upstream_config_revision": 1}],
    }
    attachment = {
        "id": "attachment-a-b",
        "position": 3,
        "source_type": "private",
        "source_namespace_name": "libraries",
        "source_repository_name": "shared",
        "format": "pypi",
        "min_age_hours": None,
        "max_age_hours": None,
    }
    fake = _FakeApiClient([destination, source, attachment])
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
            "--position",
            "3",
        ],
    )

    assert result.exit_code == 0
    assert fake.calls[-1][2]["position"] == 3


def test_artifacts_repo_upstream_reorder_is_removed_and_remove_uses_format_route(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient([_repository_entry("application")])
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

    assert reordered.exit_code == 2
    assert removed.exit_code == 0
    assert (
        "DELETE",
        "/repositories/r_xyzabcde/formats/npm/upstreams/attachment-b",
        {"expected_revision": 7},
    ) in fake.calls


def test_artifacts_repo_upstream_add_requires_exactly_one_source(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    _use_fake_client(monkeypatch, _FakeApiClient())

    neither = runner.invoke(
        artifacts_cmd.app,
        [
            "repo",
            "upstream",
            "add",
            "application",
            "pypi",
            "--position",
            "1",
        ],
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
            "--position",
            "1",
        ],
    )

    assert neither.exit_code == 1
    assert both.exit_code == 1
    assert "exactly one" in neither.output
    assert "exactly one" in both.output


def test_artifacts_repo_upstream_position_is_limited_to_four_slots() -> None:
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
            "--position",
            "5",
        ],
    )

    assert result.exit_code == 2
    assert "1<=x<=4" in result.output


def test_artifacts_package_list_and_show_use_repository_package_paths(
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
        artifacts_cmd.app, ["package", "list", "--target", "repo-pypi", "--format", "pypi"]
    )
    show_result = runner.invoke(
        artifacts_cmd.app,
        ["package", "show", "demo", "--target", "repo-pypi", "--format", "pypi"],
    )

    assert list_result.exit_code == 0
    assert show_result.exit_code == 0
    assert fake.calls == [
        (
            "GET",
            "/repositories/resolve",
            {
                "selector": "repo-pypi",
                "account_ref": "ac_23456789",
                "format": "pypi",
            },
        ),
        (
            "GET",
            "/repositories/r_xyzabcde/formats/pypi/packages",
            None,
        ),
        (
            "GET",
            "/repositories/resolve",
            {
                "selector": "repo-pypi",
                "account_ref": "ac_23456789",
                "format": "pypi",
            },
        ),
        (
            "GET",
            "/repositories/r_xyzabcde/formats/pypi/packages/detail",
            {"package_name": "demo"},
        ),
    ]
    assert "demo" in list_result.output
    assert "1.2.3" in show_result.output


def test_artifacts_package_mutations_call_expected_api_paths(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient()
    _use_fake_client(monkeypatch, fake)

    delete_result = runner.invoke(
        artifacts_cmd.app,
        [
            "package",
            "delete",
            "demo",
            "--target",
            "repo-pypi",
            "--format",
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
            "--target",
            "repo-pypi",
            "--format",
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
            "--target",
            "repo-pypi",
            "--format",
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
            "/repositories/resolve",
            {
                "selector": "repo-pypi",
                "account_ref": "ac_23456789",
                "format": "pypi",
            },
        ),
        (
            "DELETE",
            "/repositories/r_xyzabcde/formats/pypi/packages/detail",
            {"package_name": "demo"},
        ),
        (
            "GET",
            "/repositories/resolve",
            {
                "selector": "repo-pypi",
                "account_ref": "ac_23456789",
                "format": "pypi",
            },
        ),
        (
            "DELETE",
            "/repositories/r_xyzabcde/formats/pypi/packages/version",
            {"package_name": "demo", "version": "1.0.0"},
        ),
        (
            "GET",
            "/repositories/resolve",
            {
                "selector": "repo-pypi",
                "account_ref": "ac_23456789",
                "format": "pypi",
            },
        ),
        (
            "POST",
            "/repositories/r_xyzabcde/formats/pypi/packages/version/yank",
            {"reason": "bad build"},
        ),
    ]


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
    assert netrc_texts == [
        f"machine {PYPI_READ_HOST} login __token__ password rvs_sltAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n"
    ]
    assert not Path(calls[0][1]["NETRC"]).exists()


def test_pypi_install_refreshes_native_path_when_saved_target_name_changed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    cfg_mod.set_registry_default_target(
        "pypi",
        customer=_repository_entry("old-name")["account"],
        repository=_repository_entry("old-name")["repository"],
        profile="staging",
    )

    class ChangedTargetClient(_FakeApiClient):
        def post(self, path: str, json: Any = None, **kwargs: Any) -> _JsonResponse:
            self.calls.append(("POST", path, json if json is not None else kwargs))
            assert json["expected_target"]["repository_name"] == "old-name"
            return _JsonResponse(
                {
                    "access_token": "rvs_sltAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                    "native_paths": {"pypi": "/test-account/new-name"},
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
        calls[0][1][f"NPM_CONFIG_//{NPM_READ_HOST}/test-account/repo/:_authToken"]
        == "rvs_sltAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
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
        assert "rvs_sltAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" in settings.read_text(
            encoding="utf-8"
        )
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


@pytest.mark.parametrize(
    "answer,flags,published",
    [
        ("\n", [], False),
        ("n\n", [], False),
        ("", [], False),
        ("y\n", [], True),
        ("", ["--yes"], True),
    ],
)
def test_publish_confirmation_uses_resolved_org_and_blocks_upload(
    monkeypatch, tmp_path: Path, answer, flags, published
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    entry = _repository_entry("backend")
    entry["account"].update(account_type="organization", account_label="YYYY")
    entry["repository"]["namespace_name"] = "platform"
    client = _FakeApiClient([entry])
    monkeypatch.setattr(
        artifacts_cmd.ApiClient, "from_profile", staticmethod(lambda profile=None: client)
    )
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "demo.whl").write_bytes(b"wheel")
    calls = []
    monkeypatch.setattr(
        artifacts_cmd.pypi_reg, "publish", lambda **kwargs: calls.append(kwargs) or []
    )
    result = runner.invoke(
        artifacts_cmd.app,
        ["pypi", "publish", str(dist), "--profile", "staging", *flags],
        input=answer,
    )
    assert (result.exit_code == 0) == published, result.output
    assert bool(calls) == published
    if not flags:
        assert "Publish to platform/backend (org:YYYY)" in result.output
        assert "demo.whl" in result.output
        assert "Publish this 1 file? [y/N]" in result.output
    else:
        assert "Publish to" not in result.output


def test_pypi_publish_reports_failed_uploads(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    monkeypatch.setenv("RVS_TOKEN", "rvs_ustAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
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
        artifacts_cmd.app, ["pypi", "publish", str(dist_dir), "--profile", "staging"], input="y\n"
    )

    assert result.exit_code == 1
    assert "Published demo-1.0.0.whl" in result.output
    assert "Failed demo-1.0.0.tar.gz" in result.stderr


def test_npm_publish_calls_registry_adapter(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    monkeypatch.setenv("RVS_TOKEN", "rvs_ustAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    calls: list[dict[str, Any]] = []

    def fake_publish(**kwargs: Any) -> list[PublishResult]:
        calls.append(kwargs)
        return [PublishResult("demo-1.0.0.tgz", "1.0.0", True)]

    monkeypatch.setattr(artifacts_cmd.npm_reg, "publish", fake_publish)

    result = runner.invoke(
        artifacts_cmd.app, ["npm", "publish", str(package_dir), "--profile", "staging", "--yes"]
    )

    assert result.exit_code == 0
    assert calls == [
        {
            "registry_url": f"{NPM_PUSH_URL}/test-account/repo/",
            "token": "rvs_sltAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "package_dir": package_dir,
            "download_registry_url": f"{NPM_READ_URL}/test-account/repo/",
        }
    ]


def test_maven_publish_checks_file_and_calls_registry_adapter(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    monkeypatch.setenv("RVS_TOKEN", "rvs_ustAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
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
            "publish",
            str(artifact),
            "--yes",
            "--group-id",
            "com.example",
            "--artifact-id",
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
            "token": "rvs_sltAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "group_id": "com.example",
            "artifact_id": "demo",
            "version": "1.0.0",
            "files": [artifact],
        }
    ]
