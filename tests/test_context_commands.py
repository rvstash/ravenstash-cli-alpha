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


def _identity(email: str | None = "developer@example.test") -> dict[str, Any]:
    """Return a wire ``Identity`` for a signed-in user."""
    return {
        "principal_type": "user",
        "email": email,
        "personal_account": {"ref": "personal-user", "handle": "avery", "type": "personal"},
        "credential": None,
    }


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
        def get(path: str, params: dict | None = None) -> _Response:
            calls.append(path)
            if path == "/v0/platform/me":
                return _Response(_identity())
            assert path == "/v0/platform/accounts"
            return _Response(
                {
                    "items": [
                        {
                            "ref": "personal-user",
                            "handle": "avery",
                            "type": "personal",
                            "label": "Avery Example",
                            "is_admin": True,
                            "organization_role": None,
                            "authority_revision": 1,
                        }
                    ],
                    "next_cursor": None,
                }
            )

    monkeypatch.setattr(
        context_cmd.ApiClient,
        "from_profile",
        staticmethod(lambda profile=None: _Client()),
    )

    result = runner.invoke(app, ["context", "current"])

    assert result.exit_code == 0, result.output
    assert calls == ["/v0/platform/me", "/v0/platform/accounts"]
    assert "developer@example.test" in result.output
    assert "work" in result.output
    assert "persisted default" in result.output
    assert "user:avery" in result.output
    assert "personal account default" in result.output
    assert "not selected" in result.output
    assert "https://api.work.example" in result.output


def test_context_current_shows_account_scoped_selected_target(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    cfg_mod.set_active_account(
        profile="work",
        customer={
            "ref": "acme",
            "handle": "acme",
            "type": "organization",
            "label": "Acme Incorporated",
            "is_admin": True,
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
        def get(path: str, params: dict | None = None) -> _Response:
            assert path == "/v0/platform/me"
            return _Response(_identity())

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
        def get(path: str, params: dict | None = None) -> _Response:
            assert path == "/v0/platform/accounts"
            return _Response(
                {
                    "items": [
                        {
                            "ref": "acme",
                            "handle": "acme",
                            "type": "organization",
                            "label": "Acme Incorporated",
                            "is_admin": True,
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
    assert "Account 'org:acme' selected for persisted profile" in result.output
    assert "RVS_ACCOUNT_REF is set and still overrides" in result.stderr
    assert cfg_mod.load().profiles["work"].active_customer_id == "acme"
    assert cfg_mod.current_customer_id("work") == "forced-customer"


def test_account_list_displays_typed_user_and_organization_handles(
    monkeypatch, tmp_path: Path
) -> None:
    _isolate_config(monkeypatch, tmp_path)

    class _Client:
        @staticmethod
        def get(path: str, params: dict | None = None) -> _Response:
            assert path == "/v0/platform/accounts"
            return _Response(
                {
                    "items": [
                        {
                            "ref": "personal-user",
                            "handle": "avery",
                            "type": "personal",
                            "label": "Avery Example",
                            "is_admin": True,
                            "organization_role": None,
                            "authority_revision": 1,
                        },
                        {
                            "ref": "acme",
                            "handle": "acme",
                            "type": "organization",
                            "label": "Acme Incorporated",
                            "is_admin": True,
                            "organization_role": "admin",
                            "authority_revision": 2,
                        },
                    ],
                    "next_cursor": None,
                }
            )

    monkeypatch.setattr(
        account_cmd.ApiClient,
        "from_profile",
        staticmethod(lambda profile=None: _Client()),
    )

    result = runner.invoke(app, ["account", "list"])

    assert result.exit_code == 0, result.output
    assert "user:avery" in result.output
    assert "org:acme" in result.output


def test_account_list_follows_pages_and_shows_unknown_account_types(
    monkeypatch, tmp_path: Path
) -> None:
    _isolate_config(monkeypatch, tmp_path)
    calls: list[dict | None] = []
    pages = [
        {
            "items": [
                {
                    "ref": "personal-user",
                    "handle": "avery",
                    "type": "personal",
                    "label": "Avery Example",
                    "is_admin": True,
                    "organization_role": None,
                    "authority_revision": 1,
                }
            ],
            "next_cursor": "page-2",
        },
        {
            "items": [
                {
                    "ref": "ac_23456789",
                    "handle": "ops",
                    "type": "enterprise",
                    "label": "Ops",
                    "is_admin": False,
                    "organization_role": "auditor",
                    "authority_revision": 4,
                }
            ],
            "next_cursor": None,
        },
    ]

    class _Client:
        @staticmethod
        def get(path: str, params: dict | None = None) -> _Response:
            assert path == "/v0/platform/accounts"
            calls.append(params)
            return _Response(pages.pop(0))

    monkeypatch.setattr(
        account_cmd.ApiClient,
        "from_profile",
        staticmethod(lambda profile=None: _Client()),
    )

    result = runner.invoke(app, ["account", "list"])

    assert result.exit_code == 0, result.output
    assert calls == [{"limit": 100}, {"limit": 100, "cursor": "page-2"}]
    assert "user:avery" in result.output
    # Account types and roles are open value sets: unknown values display as-is.
    assert "enterprise:ops" in result.output
    assert "auditor" in result.output


def test_account_switch_without_selector_opens_account_picker(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    account_items = [
        {
            "ref": "acme",
            "handle": "acme",
            "type": "organization",
            "label": "Acme Incorporated",
            "is_admin": True,
            "organization_role": "admin",
            "authority_revision": 2,
        },
        {
            "ref": "personal-user",
            "handle": "avery",
            "type": "personal",
            "label": "Avery Example",
            "is_admin": True,
            "organization_role": None,
            "authority_revision": 1,
        },
    ]

    class _Client:
        @staticmethod
        def get(path: str, params: dict | None = None) -> _Response:
            assert path == "/v0/platform/accounts"
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
    assert "user:avery" in rendered
    assert "[dim]Personal[/]" in rendered
    assert "org:acme" in rendered
    assert "Organization · admin" in rendered
    assert "Avery Example" not in rendered
    assert "Acme Incorporated" not in rendered
    assert "(active)" in rendered
    assert "Account 'org:acme' selected for persisted profile" in result.output
    assert cfg_mod.load().profiles["work"].active_customer_id == "acme"


def test_removed_account_use_alias_is_rejected() -> None:
    result = runner.invoke(app, ["account", "use", "acme"])
    assert result.exit_code != 0
    assert "No such command" in result.output


def test_removed_profile_aliases_are_rejected(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _isolate_config(monkeypatch, tmp_path)

    profile_result = runner.invoke(app, ["auth", "profile", "switch", "work"])
    top_level_profile_result = runner.invoke(app, ["profile", "switch", "work"])

    assert profile_result.exit_code == 2
    assert top_level_profile_result.exit_code == 2


def test_an_unknown_account_type_is_selectable_by_its_shown_handle(monkeypatch) -> None:
    team = {"ref": "ac_teamteam", "type": "team", "handle": "Platform"}
    monkeypatch.setattr(
        account_cmd,
        "accounts",
        lambda profile=None: [{"ref": "ac_23456789", "type": "personal", "handle": "me"}, team],
    )
    monkeypatch.setattr(account_cmd.cfg_mod, "cache_account", lambda **kwargs: None)

    assert account_cmd.resolve_account("team:platform") == team
