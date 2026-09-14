from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
APPEND = ROOT / "packaging/repository/append_and_sign_apt.sh"


def _run(command: list[str], *, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        pytest.fail(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result.stdout


def _build_deb(root: Path, version: str, architecture: str) -> Path:
    package = root / f"package-{version}-{architecture}"
    (package / "DEBIAN").mkdir(parents=True)
    (package / "usr/bin").mkdir(parents=True)
    (package / "DEBIAN/control").write_text(
        "\n".join(
            (
                "Package: rvs",
                f"Version: {version}",
                f"Architecture: {architecture}",
                "Section: utils",
                "Priority: optional",
                "Maintainer: Ravenstash Test <test@example.com>",
                "Description: repository test package",
                "",
            )
        ),
        encoding="utf-8",
    )
    executable = package / "usr/bin/rvs"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    output = root / f"rvs_{version}_{architecture}.deb"
    _run(["dpkg-deb", "--build", str(package), str(output)])
    return output


@pytest.mark.skipif(
    any(shutil.which(command) is None for command in ("apt-ftparchive", "dpkg-deb", "gpg")),
    reason="APT repository tooling is unavailable",
)
def test_new_architecture_keeps_older_channel_indexes_valid(tmp_path: Path) -> None:
    gpg_home = tmp_path / "gnupg"
    gpg_home.mkdir(mode=0o700)
    base_env = os.environ | {"GNUPGHOME": str(gpg_home)}
    _run(
        [
            "gpg",
            "--batch",
            "--passphrase",
            "",
            "--quick-generate-key",
            "RVS Repository Test <test@example.com>",
            "rsa2048",
            "sign",
            "0",
        ],
        env=base_env,
    )
    listing = _run(["gpg", "--batch", "--with-colons", "--list-secret-keys"], env=base_env)
    fingerprint = next(
        line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr:")
    )
    keyring = tmp_path / "rvs.gpg"
    with keyring.open("wb") as stream:
        subprocess.run(
            ["gpg", "--batch", "--export", fingerprint],
            check=True,
            stdout=stream,
            env=base_env,
        )

    common_env = base_env | {
        "RVS_APT_GPG_KEY_ID": fingerprint,
        "RVS_APT_GPG_FINGERPRINT": fingerprint,
        "RVS_APT_PROMOTE_CHANNEL": "0",
    }
    bootstrap = tmp_path / "bootstrap"
    bootstrap.mkdir()
    (bootstrap / "BOOTSTRAP").touch()
    v03 = tmp_path / "v03"
    _run(
        [
            str(APPEND),
            str(bootstrap),
            str(_build_deb(tmp_path, "0.3.1", "amd64")),
            str(v03),
            str(keyring),
        ],
        env=common_env | {"RVS_APT_CHANNEL": "v0.3"},
    )
    amd64 = tmp_path / "amd64"
    _run(
        [
            str(APPEND),
            str(v03),
            str(_build_deb(tmp_path, "0.12.1", "amd64")),
            str(amd64),
            str(keyring),
        ],
        env=common_env | {"RVS_APT_CHANNEL": "v0.12"},
    )
    multarch = tmp_path / "multarch"
    _run(
        [
            str(APPEND),
            str(amd64),
            str(_build_deb(tmp_path, "0.12.1", "arm64")),
            str(multarch),
            str(keyring),
        ],
        env=common_env | {"RVS_APT_CHANNEL": "v0.12"},
    )

    assert (multarch / "dists/v0.3/main/binary-arm64/Packages").read_text() == ""
    assert (
        "Architecture: arm64" in (multarch / "dists/v0.12/main/binary-arm64/Packages").read_text()
    )
