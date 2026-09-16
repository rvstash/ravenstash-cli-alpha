from __future__ import annotations

import io
import json
import os
import tarfile
from pathlib import Path
from typing import Any

import pytest
from rvs import portable_update as portable_update_mod
from rvs.installations import (
    RECEIPT_NAME,
    Installation,
    compatibility_channel,
    detect_portable_installation,
    read_receipt,
    write_receipt,
)
from rvs.portable_update import UpdateError, activate_posix, extract_release, newer
from rvs.update_trust import VerificationError, _release_key, verify_detached


FIXTURES = Path(__file__).parent / "fixtures"


def _installation(tmp_path: Path, version: str = "0.14.3") -> Installation:
    return Installation(
        schema=1,
        method="portable",
        scope="user",
        version=version,
        channel=compatibility_channel(version),
        target="linux-musl-amd64",
        install_root=str(tmp_path / "root"),
        bin_directory=str(tmp_path / "bin"),
    )


def _launcher(path: Path, version: str) -> None:
    path.write_text(f"#!/bin/sh\nprintf 'Ravenstash CLI {version}\\n'\n", encoding="utf-8")
    path.chmod(0o755)


def test_release_key_is_the_pinned_4096_bit_rsa_key() -> None:
    assert _release_key().key_size == 4096


def test_detached_verification_rejects_non_signature_data() -> None:
    with pytest.raises(VerificationError):
        verify_detached(b"manifest", b"not a signature")


def test_detached_verification_accepts_published_inventory_and_rejects_mutation() -> None:
    inventory = (FIXTURES / "rvs-v0.14.3-checksums.txt").read_bytes()
    signature = (FIXTURES / "rvs-v0.14.3-checksums.txt.asc").read_bytes()

    verify_detached(inventory, signature)
    with pytest.raises(VerificationError, match=r"digest prefix|invalid"):
        verify_detached(inventory + b"changed\n", signature)


def test_channel_discovery_authenticates_the_public_manifest(
    httpx2_mock: Any, monkeypatch: Any
) -> None:
    manifest = {
        "schema": 1,
        "recommended": "v0.14",
        "channels": {"v0.14": {"latest": "0.14.3", "status": "supported"}},
    }
    httpx2_mock.add_response(url=portable_update_mod.CHANNELS_URL, json=manifest)
    httpx2_mock.add_response(url=f"{portable_update_mod.CHANNELS_URL}.gpg", content=b"signature")
    verified: list[tuple[bytes, bytes]] = []
    monkeypatch.setattr(
        portable_update_mod,
        "verify_detached",
        lambda subject, signature: verified.append((subject, signature)),
    )

    assert portable_update_mod.fetch_channel_manifest() == manifest
    assert verified and verified[0][1] == b"signature"


@pytest.mark.parametrize(
    ("installed", "candidate", "expected"),
    [
        ("0.14.4rc1", "0.14.4rc2", True),
        ("0.14.4rc2", "0.14.4", True),
        ("0.14.3", "0.14.4", True),
        ("0.14.4", "0.14.3", False),
    ],
)
def test_portable_version_order(installed: str, candidate: str, expected: bool) -> None:
    assert newer(candidate, installed) is expected


def test_receipt_round_trip_and_running_executable_detection(
    tmp_path: Path, monkeypatch: Any
) -> None:
    installation = _installation(tmp_path)
    executable = installation.root / installation.version / "rvs"
    executable.parent.mkdir(parents=True)
    executable.touch()
    receipt = executable.parent / RECEIPT_NAME
    write_receipt(receipt, installation)
    monkeypatch.setattr("rvs.installations.platform_target", lambda: installation.target)

    assert read_receipt(receipt) == installation
    assert (
        detect_portable_installation(executable=executable, installed_version=installation.version)
        == installation
    )


def test_receipt_rejects_root_install_path(tmp_path: Path) -> None:
    installation = _installation(tmp_path)
    invalid = Installation(**{**installation.__dict__, "install_root": "/"})

    with pytest.raises(ValueError, match="invalid install root"):
        write_receipt(tmp_path / "receipt.json", invalid)


def test_extract_release_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "rvs-v0.14.4-linux-musl-amd64.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        content = b"bad"
        member = tarfile.TarInfo("rvs-v0.14.4-linux-musl-amd64/../outside")
        member.size = len(content)
        bundle.addfile(member, io.BytesIO(content))

    with pytest.raises(UpdateError, match="unsafe path"):
        extract_release(archive, tmp_path / "extracted", "0.14.4", "linux-musl-amd64")


@pytest.mark.skipif(os.name == "nt", reason="POSIX activation uses executable symlinks")
def test_posix_activation_switches_all_commands_and_keeps_previous_version(
    tmp_path: Path,
) -> None:
    installation = _installation(tmp_path)
    old = installation.root / installation.version
    old.mkdir(parents=True)
    for command in ("rvs", "ravenstash", "docker-credential-rvs"):
        _launcher(old / command, installation.version)
    installation.bin.mkdir(parents=True)
    for command in ("rvs", "ravenstash", "docker-credential-rvs"):
        (installation.bin / command).symlink_to(old / command)

    extracted = tmp_path / "new"
    extracted.mkdir()
    for command in ("rvs", "ravenstash", "docker-credential-rvs"):
        _launcher(extracted / command, "0.14.4")

    activate_posix(extracted, installation, "0.14.4")

    assert (installation.root / "current").readlink() == Path("0.14.4")
    assert old.is_dir()
    assert read_receipt(installation.root / "0.14.4" / RECEIPT_NAME).version == "0.14.4"
    for command in ("rvs", "ravenstash", "docker-credential-rvs"):
        assert (installation.bin / command).resolve() == installation.root / "0.14.4" / command


@pytest.mark.skipif(os.name == "nt", reason="POSIX activation uses executable symlinks")
def test_posix_activation_rolls_back_before_replacing_an_unowned_command(
    tmp_path: Path,
) -> None:
    installation = _installation(tmp_path)
    old = installation.root / installation.version
    old.mkdir(parents=True)
    for command in ("rvs", "ravenstash", "docker-credential-rvs"):
        _launcher(old / command, installation.version)
    installation.bin.mkdir(parents=True)
    (installation.bin / "rvs").write_text("not installer owned\n", encoding="utf-8")
    (installation.bin / "ravenstash").symlink_to(old / "ravenstash")
    (installation.bin / "docker-credential-rvs").symlink_to(old / "docker-credential-rvs")

    extracted = tmp_path / "new"
    extracted.mkdir()
    for command in ("rvs", "ravenstash", "docker-credential-rvs"):
        _launcher(extracted / command, "0.14.4")

    with pytest.raises(UpdateError, match="non-symlink command"):
        activate_posix(extracted, installation, "0.14.4")

    assert (installation.bin / "rvs").read_text(encoding="utf-8") == "not installer owned\n"
    assert not (installation.root / "current").exists()
    assert not (installation.root / "0.14.4").exists()


def test_receipt_is_non_secret_json(tmp_path: Path) -> None:
    receipt = tmp_path / RECEIPT_NAME
    write_receipt(receipt, _installation(tmp_path))

    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert set(payload) == {
        "bin_directory",
        "channel",
        "install_root",
        "method",
        "schema",
        "scope",
        "target",
        "version",
    }
