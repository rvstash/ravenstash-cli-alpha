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
config_version = 6
default_profile = "work"

[profiles.work]
api_url = "https://api.work.example"
account_ref = "personal-user"
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
    assert calls == ["/me"]
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
            "account_ref": "acme",
            "account_type": "organization",
            "account_label": "acme",
            "organization_role": "admin",
            "authority_revision": 2,
        },
    )
    cfg_mod.set_selected_artifact_target(
        cfg_mod.ArtifactTarget(
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
            assert path == "/me"
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


def test_account_switch_warns_when_environment_still_overrides_selection(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    monkeypatch.setenv("RVS_ACCOUNT_REF", "forced-customer")

    class _Client:
        @staticmethod
        def get(path: str) -> _Response:
            assert path == "/accounts"
            return _Response(
                {
                    "items": [
                        {
                            "account_ref": "acme",
                            "account_handle": "acme",
                            "account_type": "organization",
                            "account_label": "Acme Incorporated",
                            "organization_role": "admin",
                            "authority_revision": 2,
                        }
                    ],
                    "next_cursor": None,
                }
            )

    monkeypatch.setattr(
        account_cmd.ApiClient,
        "from_profile",
        staticmethod(lambda profile=None: _Client()),
    )

    result = runner.invoke(app, ["account", "switch", "acme"])

    assert result.exit_code == 0, result.output
    assert "Account 'acme' selected for persisted profile" in result.output
    assert "RVS_ACCOUNT_REF is set and still overrides" in result.stderr
    assert cfg_mod.load().profiles["work"].active_customer_id == "acme"
    assert cfg_mod.current_customer_id("work") == "forced-customer"


def test_account_switch_without_selector_opens_account_picker(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    account_items = [
        {
            "account_ref": "acme",
            "account_handle": "acme",
            "account_type": "organization",
            "account_label": "Acme Incorporated",
            "organization_role": "admin",
            "authority_revision": 2,
        },
        {
            "account_ref": "personal-user",
            "account_handle": "avery",
            "account_type": "personal",
            "account_label": "Avery Example",
            "organization_role": "owner",
            "authority_revision": 1,
        },
    ]

    class _Client:
        @staticmethod
        def get(path: str) -> _Response:
            assert path == "/accounts"
            return _Response({"items": account_items, "next_cursor": None})

    selector: dict[str, Any] = {}

    def select_index(**kwargs: Any) -> int:
        selector.update(kwargs)
        return 1

    monkeypatch.setattr(
        account_cmd.ApiClient,
        "from_profile",
        staticmethod(lambda profile=None: _Client()),
    )
    monkeypatch.setattr(account_cmd, "select_index", select_index)

    result = runner.invoke(app, ["account", "switch"])

    assert result.exit_code == 0, result.output
    assert selector["initial_index"] == 0
    rendered = selector["render"](1)
    assert "avery" in rendered
    assert "Personal · owner" in rendered
    assert "acme" in rendered
    assert "Organization · admin" in rendered
    assert "Avery Example" not in rendered
    assert "Acme Incorporated" not in rendered
    assert "(active)" in rendered
    assert "Account 'acme' selected for persisted profile" in result.output
    assert cfg_mod.load().profiles["work"].active_customer_id == "acme"


def test_account_use_remains_a_hidden_deprecated_alias(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)

    class _Client:
        @staticmethod
        def get(path: str) -> _Response:
            assert path == "/accounts"
            return _Response(
                {
                    "items": [
                        {
                            "account_ref": "acme",
                            "account_handle": "acme",
                            "account_type": "organization",
                            "account_label": "Acme Incorporated",
                            "organization_role": "admin",
                            "authority_revision": 2,
                        }
                    ]
                }
            )

    monkeypatch.setattr(
        account_cmd.ApiClient,
        "from_profile",
        staticmethod(lambda profile=None: _Client()),
    )

    result = runner.invoke(app, ["account", "use", "acme"])

    assert result.exit_code == 0, result.output
    assert "deprecated" in result.stderr
    assert cfg_mod.load().profiles["work"].active_customer_id == "acme"

    help_result = runner.invoke(app, ["account", "--help"])
    assert help_result.exit_code == 0
    assert "switch" in help_result.output
    assert not any(line.strip().startswith("│ use ") for line in help_result.output.splitlines())


def test_removed_profile_aliases_are_rejected(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)

    profile_result = runner.invoke(app, ["auth", "profile", "switch", "work"])
    top_level_profile_result = runner.invoke(app, ["profile", "switch", "work"])

    assert profile_result.exit_code == 2
    assert top_level_profile_result.exit_code == 2
