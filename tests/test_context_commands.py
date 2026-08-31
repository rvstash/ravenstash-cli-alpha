from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rvs import config as cfg_mod
from rvs.account import commands as account_cmd
from rvs.cli import app
from rvs.context import commands as context_cmd
from typer.testing import CliRunner


if TYPE_CHECKING:
    from pathlib import Path


runner = CliRunner()


class _Response:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def json(self) -> Any:
        return self._payload


def _isolate_config(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / ".rvs"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text(
        """
default_profile = "work"

[profiles.work]
api_url = "https://api.work.example"
customer_id = "personal-user"
customer_unique_id = "personal-ref"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_file)
    monkeypatch.setattr(cfg_mod, "PROFILE_ENV_FILE", config_dir / "profiles.env")
    for key in ("RVS_PROFILE", "RVS_CUSTOMER_ID", "RVS_SESSION_ID"):
        monkeypatch.delenv(key, raising=False)


def test_context_current_shows_distinct_user_profile_account_and_target(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    calls: list[str] = []

    class _Client:
        @staticmethod
        def get(path: str) -> _Response:
            calls.append(path)
            return _Response({"email": "developer@example.test"})

    monkeypatch.setattr(
        context_cmd.ApiClient,
        "from_profile",
        staticmethod(lambda profile=None: _Client()),
    )

    result = runner.invoke(app, ["context", "current"])

    assert result.exit_code == 0, result.output
    assert calls == ["/v0/me"]
    assert "developer@example.test" in result.output
    assert "work" in result.output
    assert "persisted default" in result.output
    assert "personal" in result.output
    assert "personal account default" in result.output
    assert "not selected" in result.output
    assert "https://api.work.example" in result.output


def test_context_current_shows_account_scoped_selected_target(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    cfg_mod.set_active_account(
        profile="work",
        customer={
            "customer_id": "acme",
            "customer_unique_ref": "org-ref",
            "account_type": "organization",
            "account_label": "acme",
            "organization_role": "admin",
            "authority_revision": 2,
        },
    )
    cfg_mod.set_selected_package_target(
        cfg_mod.PackageTarget(
            target_type="official_cache",
            customer_id="acme",
            stable_selector="mirror:official-ref",
            display_selector="mirror:pypiorg",
            registry_kind="pypi",
        ),
        profile="work",
        customer_id="acme",
    )

    class _Client:
        @staticmethod
        def get(path: str) -> _Response:
            assert path == "/v0/me"
            return _Response({"email": "developer@example.test"})

    monkeypatch.setattr(
        context_cmd.ApiClient,
        "from_profile",
        staticmethod(lambda profile=None: _Client()),
    )

    result = runner.invoke(app, ["context", "current"])

    assert result.exit_code == 0, result.output
    assert "org:acme" in result.output
    assert "persisted profile" in result.output
    assert "mirror:pypiorg" in result.output


def test_profile_use_reports_persistence_scope(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)

    result = runner.invoke(app, ["profile", "use", "work"])

    assert result.exit_code == 0, result.output
    assert "Local profile 'work' selected for persisted default" in result.output
    assert cfg_mod.load().default_profile == "work"


def test_profile_current_owns_non_secret_endpoint_output(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)

    result = runner.invoke(app, ["profile", "current", "--verbose"])

    assert result.exit_code == 0, result.output
    assert "Current local Ravenstash profile" in result.output
    assert "https://api.work.example" in result.output
    assert "Repository domain" in result.output
    assert "https://pypi.rvsta.sh" in result.output
    assert "Owner ID" not in result.output
    assert "Authenticated" not in result.output


def test_account_use_warns_when_environment_still_overrides_selection(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    monkeypatch.setenv("RVS_CUSTOMER_ID", "forced-customer")

    class _Client:
        @staticmethod
        def get(path: str) -> _Response:
            assert path == "/v0/customers"
            return _Response(
                [
                    {
                        "customer_id": "acme",
                        "customer_unique_ref": "org-ref",
                        "account_type": "organization",
                        "account_label": "acme",
                        "organization_role": "admin",
                        "authority_revision": 2,
                    }
                ]
            )

    monkeypatch.setattr(
        account_cmd.ApiClient,
        "from_profile",
        staticmethod(lambda profile=None: _Client()),
    )

    result = runner.invoke(app, ["account", "use", "org:acme"])

    assert result.exit_code == 0, result.output
    assert "Acting account 'org:acme' selected for persisted profile" in result.output
    assert "RVS_CUSTOMER_ID is set and still overrides" in result.stderr
    assert cfg_mod.load().profiles["work"].active_customer_id == "acme"
    assert cfg_mod.current_customer_id("work") == "forced-customer"


def test_removed_profile_and_account_aliases_are_rejected(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)

    profile_result = runner.invoke(app, ["auth", "profile", "switch", "work"])
    account_result = runner.invoke(app, ["account", "switch", "personal"])
    top_level_profile_result = runner.invoke(app, ["profile", "switch", "work"])

    assert profile_result.exit_code == 2
    assert account_result.exit_code == 2
    assert top_level_profile_result.exit_code == 2
