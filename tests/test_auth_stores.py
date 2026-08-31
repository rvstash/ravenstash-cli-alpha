from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any

import pytest
from rvs.auth import plaintext_store, stores, vault


if TYPE_CHECKING:
    from pathlib import Path


def test_pass_status_requires_initialized_store(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(stores.shutil, "which", lambda command: "/usr/bin/pass")
    monkeypatch.setattr(stores, "_password_store_dir", lambda: tmp_path)

    status = stores.pass_status()

    assert status.available is False
    assert "not initialized" in status.detail


def test_pass_status_accepts_initialized_store(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".gpg-id").write_text("developer@example.test\n", encoding="utf-8")
    monkeypatch.setattr(stores.shutil, "which", lambda command: "/usr/bin/pass")
    monkeypatch.setattr(stores, "_password_store_dir", lambda: tmp_path)

    status = stores.pass_status()

    assert status.available is True
    assert status.backend == "/usr/bin/pass"


def test_pass_set_sends_secret_only_over_stdin(monkeypatch) -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(stores.subprocess, "run", fake_run)

    stores.pass_set("profile/with/slashes", "secret-token")

    command, kwargs = calls[0]
    assert command[:4] == ["pass", "insert", "--multiline", "--force"]
    assert "profile/with/slashes" not in command[-1]
    assert "secret-token" not in command
    assert kwargs["input"] == "secret-token"


def test_plaintext_store_requires_private_file_and_round_trips(monkeypatch, tmp_path: Path) -> None:
    from rvs import config as cfg_mod

    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", tmp_path / ".rvs")
    plaintext_store.initialize()
    plaintext_store.set("default", "plain-secret")

    assert plaintext_store.get("default") == "plain-secret"
    assert plaintext_store.path().stat().st_mode & 0o777 == 0o600
    assert "plain-secret" in plaintext_store.path().read_text(encoding="utf-8")

    plaintext_store.path().chmod(0o644)
    with pytest.raises(plaintext_store.PlaintextStoreError, match="unsafe permissions"):
        plaintext_store.get("default")


def test_encrypted_vault_round_trip_and_lock(monkeypatch, tmp_path: Path) -> None:
    from rvs import config as cfg_mod

    config_dir = tmp_path / ".rvs"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(mode=0o700)
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setattr(vault, "_ARGON2_MEMORY_KIB", 8 * 1024)

    vault.initialize("correct horse battery staple")
    try:
        vault.set("default", "encrypted-secret")
        assert vault.get("default") == "encrypted-secret"
        assert "encrypted-secret" not in vault.path().read_text(encoding="utf-8")
        assert vault.path().stat().st_mode & 0o777 == 0o600
        assert vault.lock() is True
        monkeypatch.setattr(vault, "_interactive_terminal_available", lambda: False)
        with pytest.raises(vault.VaultLockedError, match="unlock"):
            vault.get("default")
        with pytest.raises(vault.VaultError, match="Incorrect vault passphrase"):
            vault.unlock("incorrect passphrase here")
        vault.unlock("correct horse battery staple")
        assert vault.get("default") == "encrypted-secret"
    finally:
        vault.lock()


def test_vault_accepts_eight_characters_and_rejects_shorter_passphrases() -> None:
    vault._validate_passphrase("12345678")

    with pytest.raises(vault.VaultError, match="at least 8 characters"):
        vault._validate_passphrase("1234567")
