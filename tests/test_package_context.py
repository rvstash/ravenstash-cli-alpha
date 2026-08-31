from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from rvs import config as cfg_mod
from rvs.cli import app
from rvs.client import ApiClient
from rvs.native import runner as native_runner
from rvs.pkg import commands as pkg_commands
from rvs.pkg.targets import parse_target
from rvs.shell.commands import prompt_text
from typer.testing import CliRunner


if TYPE_CHECKING:
    from pathlib import Path


runner = CliRunner()


class Response:
    def __init__(self, value: Any) -> None:
        self.value = value

    def json(self) -> Any:
        return self.value


def customer(
    customer_id: str,
    label: str,
    account_type: str = "organization",
) -> dict[str, Any]:
    return {
        "customer_id": customer_id,
        "customer_unique_id": f"uid-{customer_id}",
        "customer_unique_ref": f"_{customer_id}",
        "account_type": account_type,
        "account_label": label,
        "organization_role": "member" if account_type == "organization" else "owner",
        "authority_revision": 4,
    }


def remote(
    *,
    owner: dict[str, Any],
    family: str,
    name: str,
    kind: str,
    suffix: str,
) -> dict[str, Any]:
    return {
        "customer": owner,
        "remote_repository": {
            "id": f"remote-{suffix}",
            "public_id": name,
            "unique_id": f"unique-{suffix}",
            "unique_ref": f"_{suffix}",
            "source_family": family,
            "source_id": f"source-{suffix}",
            "official_slug": name if family == "official" else None,
            "remote_name": name if family == "custom" else None,
            "customer_id": owner["customer_id"],
            "registry_kind": kind,
            "direct_access_enabled": True,
            "created_at": "2026-01-01T00:00:00Z",
        },
    }


class FakeApi:
    def __init__(self, customers: list[dict[str, Any]], remotes: list[dict[str, Any]]) -> None:
        self.customers = customers
        self.remotes = remotes
        self.calls: list[tuple[str, str, Any]] = []

    def get(self, path: str, params: dict[str, Any] | None = None) -> Response:
        self.calls.append(("GET", path, params))
        if path == "/v0/customers":
            return Response(self.customers)
        if path == "/v0/remote-repositories":
            selected = [
                item
                for item in self.remotes
                if params is None
                or (
                    (
                        not params.get("customer_id")
                        or item["customer"]["customer_id"] == params["customer_id"]
                    )
                    and (
                        not params.get("registry_kind")
                        or item["remote_repository"]["registry_kind"] == params["registry_kind"]
                    )
                )
            ]
            return Response(selected)
        raise AssertionError(path)

    def post(self, path: str, json: dict[str, Any] | None = None) -> Response:
        self.calls.append(("POST", path, json))
        if path == "/v0/remote-package-credentials":
            assert json is not None
            prefix = "o" if json["route_kind"] == "remote_official" else "c"
            name = "pypiorg" if prefix == "o" else "piwheels"
            return Response(
                {
                    "access_token": "cache-token",
                    "workspace_reference": prefix,
                    "repository_reference": name,
                }
            )
        raise AssertionError(path)


def isolate(monkeypatch, tmp_path: Path, *, profiles: tuple[str, ...] = ("alice",)) -> None:
    config_dir = tmp_path / ".rvs"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    profile_tables = "\n".join(
        f"""
[profiles.{profile}]
api_url = "https://api.example.test"
customer_id = "personal-{profile}"
customer_unique_id = "personal-{profile}-uid"
""".strip()
        for profile in profiles
    )
    config_file.write_text(
        f'default_profile = "{profiles[0]}"\n\n{profile_tables}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_file)
    monkeypatch.setattr(cfg_mod, "PROFILE_ENV_FILE", config_dir / "profiles.env")
    monkeypatch.delenv("RVS_PROFILE", raising=False)
    monkeypatch.delenv("RVS_CUSTOMER_ID", raising=False)
    monkeypatch.delenv("RVS_SESSION_ID", raising=False)


def test_target_parser_keeps_private_and_mirror_namespaces_disjoint() -> None:
    assert parse_target("acme/backend").target_type == "private"
    assert parse_target("mirror:pypiorg").target_type == "official_cache"
    assert parse_target("custom-mirror:piwheels").target_type == "custom_cache"


@pytest.mark.parametrize("selector", ["cache:pypiorg", "custom-cache:piwheels"])
def test_target_parser_rejects_removed_cache_aliases(selector: str) -> None:
    with pytest.raises(SystemExit):
        parse_target(selector)


def test_account_and_official_cache_selection_are_visible_and_clearable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    isolate(monkeypatch, tmp_path)
    personal = customer("personal-alice", "Alice", "personal")
    acme = customer("acme", "acme")
    fake = FakeApi(
        [personal, acme],
        [remote(owner=acme, family="official", name="pypiorg", kind="pypi", suffix="pypi")],
    )
    monkeypatch.setattr(ApiClient, "from_profile", staticmethod(lambda profile=None: fake))

    switched = runner.invoke(app, ["account", "switch", "org:acme"])
    selected = runner.invoke(app, ["pkg", "select", "mirror:pypiorg"])

    assert switched.exit_code == 0, switched.output
    assert selected.exit_code == 0, selected.output
    saved = cfg_mod.selected_package_target("alice", "acme")
    assert saved is not None
    assert saved.target_type == "official_cache"
    assert saved.stable_selector == "mirror:_pypi"
    assert prompt_text() == "(alice · org:acme · mirror:pypiorg) "

    cleared = runner.invoke(app, ["pkg", "clear"])
    assert cleared.exit_code == 0, cleared.output
    assert cfg_mod.selected_package_target("alice", "acme") is None


def test_custom_cache_kind_collision_requires_disambiguation(monkeypatch, tmp_path: Path) -> None:
    isolate(monkeypatch, tmp_path)
    personal = customer("personal-alice", "Alice", "personal")
    remotes = [
        remote(owner=personal, family="custom", name="piwheels", kind="pypi", suffix="py"),
        remote(owner=personal, family="custom", name="piwheels", kind="maven", suffix="mv"),
    ]
    fake = FakeApi([personal], remotes)
    monkeypatch.setattr(ApiClient, "from_profile", staticmethod(lambda profile=None: fake))

    ambiguous = runner.invoke(app, ["pkg", "select", "custom-mirror:piwheels"])
    selected = runner.invoke(
        app,
        ["pkg", "select", "custom-mirror:piwheels", "--kind", "pypi"],
    )

    assert ambiguous.exit_code == 1
    assert "ambiguous" in ambiguous.output
    assert selected.exit_code == 0, selected.output
    assert cfg_mod.selected_package_target("alice", "personal-alice").registry_kind == "pypi"


def test_two_login_profiles_keep_separate_actor_state_for_the_same_org(
    monkeypatch,
    tmp_path: Path,
) -> None:
    isolate(monkeypatch, tmp_path, profiles=("alice", "bob"))
    acme = customer("acme", "acme")
    fake = FakeApi(
        [acme], [remote(owner=acme, family="official", name="pypiorg", kind="pypi", suffix="pypi")]
    )
    monkeypatch.setattr(ApiClient, "from_profile", staticmethod(lambda profile=None: fake))

    assert (
        runner.invoke(app, ["account", "switch", "org:acme", "--profile", "alice"]).exit_code == 0
    )
    assert (
        runner.invoke(app, ["pkg", "select", "mirror:pypiorg", "--profile", "alice"]).exit_code == 0
    )
    assert runner.invoke(app, ["account", "switch", "org:acme", "--profile", "bob"]).exit_code == 0

    assert cfg_mod.selected_package_target("alice", "acme") is not None
    assert cfg_mod.selected_package_target("bob", "acme") is None


def test_one_shot_account_does_not_switch_the_active_account(monkeypatch, tmp_path: Path) -> None:
    isolate(monkeypatch, tmp_path)
    personal = customer("personal-alice", "Alice", "personal")
    acme = customer("acme", "acme")
    fake = FakeApi([personal, acme], [])
    monkeypatch.setattr(ApiClient, "from_profile", staticmethod(lambda profile=None: fake))

    result = runner.invoke(app, ["pkg", "current", "--account", "org:acme"])

    assert result.exit_code == 0, result.output
    assert "org:acme" in result.output
    assert cfg_mod.current_customer_id("alice") == "personal-alice"


def test_account_switch_is_local_to_an_integrated_shell(monkeypatch, tmp_path: Path) -> None:
    isolate(monkeypatch, tmp_path)
    personal = customer("personal-alice", "Alice", "personal")
    acme = customer("acme", "acme")
    fake = FakeApi([personal, acme], [])
    monkeypatch.setattr(ApiClient, "from_profile", staticmethod(lambda profile=None: fake))
    monkeypatch.setenv("RVS_SESSION_ID", "terminal-a")

    switched = runner.invoke(app, ["account", "switch", "org:acme"])

    assert switched.exit_code == 0, switched.output
    assert cfg_mod.current_customer_id("alice") == "acme"
    monkeypatch.setenv("RVS_SESSION_ID", "terminal-b")
    assert cfg_mod.current_customer_id("alice") == "personal-alice"


def test_native_wrapper_uses_selected_cache_and_one_shot_does_not_mutate_it(
    monkeypatch,
    tmp_path: Path,
) -> None:
    isolate(monkeypatch, tmp_path)
    personal = customer("personal-alice", "Alice", "personal")
    remotes = [
        remote(owner=personal, family="official", name="pypiorg", kind="pypi", suffix="py"),
        remote(owner=personal, family="custom", name="piwheels", kind="pypi", suffix="custom"),
    ]
    fake = FakeApi([personal], remotes)
    monkeypatch.setattr(ApiClient, "from_profile", staticmethod(lambda profile=None: fake))
    assert runner.invoke(app, ["pkg", "select", "mirror:pypiorg"]).exit_code == 0

    calls: list[tuple[list[str], dict[str, str]]] = []

    class Completed:
        returncode = 0

    monkeypatch.setattr(native_runner.tools, "pip_cmd", lambda: ["/bin/pip"])
    monkeypatch.setattr(
        native_runner.subprocess,
        "run",
        lambda cmd, *, env, check: calls.append((cmd, env.copy())) or Completed(),
    )

    result = runner.invoke(
        app,
        ["pip", "--rvs-target", "custom-mirror:piwheels", "install", "numpy"],
    )

    assert result.exit_code == 0, result.output
    assert calls[0][0] == [
        "/bin/pip",
        "install",
        "--index-url",
        "https://cache.pypi.rvsta.sh/c/piwheels/simple/",
        "numpy",
    ]
    assert cfg_mod.selected_package_target("alice", "personal-alice").display_selector == (
        "mirror:pypiorg"
    )


def test_pkg_install_uses_account_scoped_official_default_without_selection(
    monkeypatch,
    tmp_path: Path,
) -> None:
    isolate(monkeypatch, tmp_path)
    personal = customer("personal-alice", "Alice", "personal")
    fake = FakeApi(
        [personal],
        [remote(owner=personal, family="official", name="pypiorg", kind="pypi", suffix="py")],
    )
    monkeypatch.setattr(ApiClient, "from_profile", staticmethod(lambda profile=None: fake))
    calls: list[tuple[list[str], dict[str, str]]] = []
    monkeypatch.setattr(pkg_commands.tools, "pip_cmd", lambda: ["/bin/pip"])
    monkeypatch.setattr(
        pkg_commands.subprocess,
        "run",
        lambda cmd, *, env, check: calls.append((cmd, env.copy())),
    )

    result = runner.invoke(app, ["pkg", "--kind", "pypi", "install", "requests"])

    assert result.exit_code == 0, result.output
    assert calls[0][0] == ["/bin/pip", "install", "requests"]
    assert calls[0][1]["PIP_INDEX_URL"].startswith(
        "https://__token__:cache-token@cache.pypi.rvsta.sh/o/pypiorg/simple/"
    )
    assert cfg_mod.selected_package_target("alice", "personal-alice") is None


def test_pkg_repo_one_liner_is_a_target_alias(monkeypatch, tmp_path: Path) -> None:
    isolate(monkeypatch, tmp_path)
    calls: list[tuple[list[str], str | None]] = []
    monkeypatch.setattr(
        pkg_commands,
        "pypi_install",
        lambda packages, repo, profile, customer_id: calls.append((packages, repo)),
    )

    result = runner.invoke(
        app,
        [
            "pkg",
            "--repo",
            "acme/backend",
            "--kind",
            "pypi",
            "install",
            "internal-lib",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [(["internal-lib"], None)]
