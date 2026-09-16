from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from rvs import config as cfg_mod
from rvs import output
from rvs.artifacts import commands as artifacts_cmd
from typer.testing import CliRunner


if TYPE_CHECKING:
    from pathlib import Path


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
        payload = {"json": json, **kwargs} if json is not None and kwargs else json or kwargs
        self.calls.append(("POST", path, payload))
        if path == "/package-credentials":
            assert isinstance(json, dict)
            return _JsonResponse(
                {
                    "access_token": "rvs_sltAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                    "native_realm": "in",
                    "native_paths": {kind: "/in/ar_xyzabcde" for kind in json["formats"]},
                }
            )
        return _JsonResponse(self.responses.pop(0) if self.responses else {})

    def patch(
        self,
        path: str,
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> _JsonResponse:
        payload = {"json": json, "params": params} if params is not None else json
        self.calls.append(("PATCH", path, payload))
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
            "account_handle": "test-account",
            "account_type": "organization",
            "organization_role": "owner",
        },
        "repository": {
            "repository_name": name,
            "namespace_name": "test-account",
            "namespace_realm": "internal",
            "namespace_unique_ref": "in_abcdefgh",
            "repository_unique_ref": "ar_xyzabcde",
            "formats": [
                {"format": kind, "upstream_config_revision": 7} for kind in ("pypi", "npm", "maven")
            ],
        },
    }


def _isolate_config(monkeypatch, tmp_path: Path, content: str | None = None) -> None:
    output.set_json(False)
    config_dir = tmp_path / ".rvs"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text(
        content
        or """
config_version = 6
default_profile = "default"

[profiles.default]
api_url = "https://api.ravenstash.com"
account_ref = "ac_23456789"

[profiles.staging]
account_ref = "ac_23456789"
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
    assert "Account" in result.output
    assert "test-account" in result.output
    assert "Test account" not in result.output
    assert "test-account/repo-pypi" in result.output
    assert "ID-based target" in result.output
    assert "in/ar_xyzabcde" in result.output
    assert "Namespace" not in result.output
    assert "Repository ID" not in result.output


def test_artifacts_repo_list_omits_unset_query_filters(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient([[], [_repository_entry()["account"]]])
    _use_fake_client(monkeypatch, fake)

    result = runner.invoke(artifacts_cmd.app, ["repo", "list"])

    assert result.exit_code == 0
    assert fake.calls == [
        ("GET", "/repositories", {"account_ref": "ac_23456789"}),
        ("GET", "/accounts", None),
    ]
    assert "Account" in result.output
    assert "test-account" in result.output
    assert "No repositories found" in result.output


def test_artifacts_repo_list_preserves_json_shape_and_uses_account_handle(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient([[_repository_entry("repo-pypi")]])
    _use_fake_client(monkeypatch, fake)

    output.set_json(True)
    try:
        result = runner.invoke(artifacts_cmd.app, ["repo", "list"])
    finally:
        output.set_json(False)

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["items"] == [
        {
            "account": "test-account",
            "namespace": "test-account",
            "repository": "repo-pypi",
            "id_based_target": "in/ar_xyzabcde",
            "formats": "pypi, npm, maven",
        }
    ]


def test_artifacts_repo_create_rejects_removed_default_option(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    result = runner.invoke(
        artifacts_cmd.app,
        ["repo", "create", "new-node", "--format", "npm", "--default"],
    )
    assert result.exit_code != 0
    assert "No such option" in result.output


@pytest.mark.parametrize(
    "flags",
    [
        ["-f", "pypi,npm,maven,oci"],
        ["-f", "pypi, npm", "--format", "maven", "-f", "oci,pypi"],
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
    assert fake.calls[-1][2]["formats"] == ["pypi", "npm", "maven", "oci"]


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
    assert "test-account/repo-pypi" in result.output
    assert "Test account" not in result.output
    assert "ID-based target" in result.output
    assert "in/ar_xyzabcde" in result.output
    assert "Repository ID" not in result.output
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
def test_artifacts_repo_rename(monkeypatch, tmp_path: Path, new_name) -> None:
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
            "/repositories/ar_xyzabcde",
            {"repository_name": new_name},
        ),
    ]


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
            "/repositories/ar_xyzabcde/formats/pypi/upstreams",
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
        "repository_unique_ref": "ar_shared23",
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
        "/repositories/ar_xyzabcde/formats/pypi/upstreams",
        {
            "source_type": "private",
            "source_repository_unique_ref": "ar_shared23",
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
        "repository_unique_ref": "ar_shared23",
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
        "/repositories/ar_xyzabcde/formats/npm/upstreams/attachment-b",
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
            "/repositories/ar_xyzabcde/formats/pypi/packages",
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
            "/repositories/ar_xyzabcde/formats/pypi/packages/detail",
            {"package_name": "demo"},
        ),
    ]
    assert "demo" in list_result.output
    assert "1.2.3" in show_result.output
    assert "Status" in show_result.output
    assert "Yank reason" in show_result.output


def test_package_lifecycle_columns_follow_format_semantics() -> None:
    assert artifacts_cmd._package_lifecycle_columns(
        "npm",
        {"deprecated": True, "deprecated_reason": "use version 3"},
    ) == (
        ["Deprecated", "Deprecation message"],
        ["deprecated", "deprecated_reason"],
        ["yes", "use version 3"],
    )
    assert artifacts_cmd._package_lifecycle_columns("maven", {}) == ([], [], [])


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
    unyank_result = runner.invoke(
        artifacts_cmd.app,
        [
            "package",
            "unyank",
            "demo",
            "1.0.1",
            "--target",
            "repo-pypi",
            "--format",
            "pypi",
        ],
    )
    deprecate_result = runner.invoke(
        artifacts_cmd.app,
        [
            "package",
            "deprecate",
            "demo",
            "2.0.0",
            "--target",
            "repo-npm",
            "--format",
            "npm",
            "--message",
            "use version 3",
        ],
    )
    undeprecate_result = runner.invoke(
        artifacts_cmd.app,
        [
            "package",
            "undeprecate",
            "demo",
            "2.0.0",
            "--target",
            "repo-npm",
            "--format",
            "npm",
        ],
    )

    assert delete_result.exit_code == 0
    assert delete_version_result.exit_code == 0
    assert yank_result.exit_code == 0
    assert unyank_result.exit_code == 0
    assert deprecate_result.exit_code == 0
    assert undeprecate_result.exit_code == 0
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
            "/repositories/ar_xyzabcde/formats/pypi/packages/detail",
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
            "/repositories/ar_xyzabcde/formats/pypi/packages/version",
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
            "/repositories/ar_xyzabcde/formats/pypi/packages/version/yank",
            {
                "json": {"yanked": True, "reason": "bad build"},
                "params": {"package_name": "demo", "version": "1.0.1"},
            },
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
            "/repositories/ar_xyzabcde/formats/pypi/packages/version/yank",
            {
                "json": {"yanked": False, "reason": None},
                "params": {"package_name": "demo", "version": "1.0.1"},
            },
        ),
        (
            "GET",
            "/repositories/resolve",
            {
                "selector": "repo-npm",
                "account_ref": "ac_23456789",
                "format": "npm",
            },
        ),
        (
            "PATCH",
            "/repositories/ar_xyzabcde/formats/npm/packages/version/deprecation",
            {
                "json": {"deprecated": True, "message": "use version 3"},
                "params": {"package_name": "demo", "version": "2.0.0"},
            },
        ),
        (
            "GET",
            "/repositories/resolve",
            {
                "selector": "repo-npm",
                "account_ref": "ac_23456789",
                "format": "npm",
            },
        ),
        (
            "PATCH",
            "/repositories/ar_xyzabcde/formats/npm/packages/version/deprecation",
            {
                "json": {"deprecated": False, "message": None},
                "params": {"package_name": "demo", "version": "2.0.0"},
            },
        ),
    ]


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (
            [
                "package",
                "yank",
                "demo",
                "1.0.0",
                "--target",
                "repo-npm",
                "--format",
                "npm",
            ],
            "only for pypi",
        ),
        (
            [
                "package",
                "deprecate",
                "demo",
                "1.0.0",
                "--target",
                "repo-pypi",
                "--format",
                "pypi",
                "--message",
                "obsolete",
            ],
            "only for npm",
        ),
        (
            [
                "package",
                "deprecate",
                "demo",
                "1.0.0",
                "--target",
                "repo-npm",
                "--format",
                "npm",
                "--message",
                "   ",
            ],
            "cannot be empty",
        ),
    ],
)
def test_artifacts_package_lifecycle_rejects_wrong_format_or_empty_message(
    monkeypatch,
    tmp_path: Path,
    args: list[str],
    message: str,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    fake = _FakeApiClient()
    _use_fake_client(monkeypatch, fake)

    result = runner.invoke(artifacts_cmd.app, args)

    assert result.exit_code != 0
    assert message in result.output
    assert fake.calls == []
