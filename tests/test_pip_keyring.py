from __future__ import annotations

import json
from types import SimpleNamespace

from rvs.native import pip_keyring
from rvs.native import runner as native_runner


def test_keyring_protocol_returns_fresh_credential(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        pip_keyring,
        "_credential",
        lambda service: {"username": "__token__", "password": f"fresh:{service}"},
    )

    result = pip_keyring.main(
        ["--mode=creds", "--output=json", "get", "https://pypi.example/simple/"]
    )

    assert result == 0
    assert json.loads(capsys.readouterr().out) == {
        "username": "__token__",
        "password": "fresh:https://pypi.example/simple/",
    }


def test_legacy_keyring_protocol_returns_password(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        pip_keyring,
        "_credential",
        lambda service: {"username": "__token__", "password": f"fresh:{service}"},
    )

    result = pip_keyring.main(["get", "https://pypi.example/simple/", "__token__"])

    assert result == 0
    assert capsys.readouterr().out == "fresh:https://pypi.example/simple/\n"


def test_credential_exchange_is_limited_to_configured_pypi_routes(monkeypatch) -> None:
    registries = SimpleNamespace()
    monkeypatch.setattr(
        native_runner,
        "_profile",
        lambda _profile: SimpleNamespace(native_registries=registries),
    )
    monkeypatch.setattr(native_runner, "_ravenstash_url_kind", lambda *_args, **_kwargs: None)

    try:
        pip_keyring._credential("https://attacker.example/simple/")
    except ValueError as exc:
        assert "configured Ravenstash PyPI routes" in str(exc)
    else:
        raise AssertionError("foreign credential lookup must fail closed")


def test_credential_exchange_mints_a_new_capability(monkeypatch) -> None:
    registries = SimpleNamespace()
    calls: list[tuple[str, str, str | None, str | None]] = []
    monkeypatch.setenv("RVS_PIP_KEYRING_PROFILE", "development")
    monkeypatch.setenv("RVS_PIP_KEYRING_CUSTOMER_ID", "customer-1")
    monkeypatch.setattr(
        native_runner,
        "_profile",
        lambda _profile: SimpleNamespace(native_registries=registries),
    )
    monkeypatch.setattr(native_runner, "_ravenstash_url_kind", lambda *_args, **_kwargs: "pypi")

    def exchange(url, kind, profile, customer_id):
        calls.append((url, kind, profile, customer_id))
        return "rvs_pkg_v1_fresh"

    monkeypatch.setattr(native_runner, "_package_token_for_url", exchange)

    assert pip_keyring._credential("https://pypi.example/simple/demo/") == {
        "username": "__token__",
        "password": "rvs_pkg_v1_fresh",
    }
    assert calls == [
        (
            "https://pypi.example/simple/demo/",
            "pypi",
            "development",
            "customer-1",
        )
    ]
