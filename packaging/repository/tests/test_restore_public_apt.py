from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from restore_public_apt import package_paths, public_fetcher, restore_public_repository


class Response(io.BytesIO):
    def geturl(self) -> str:
        return "https://releases.ravenstash.com/rvs/apt/channels.json"

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *_args) -> None:
        self.close()


class RestorePublicAptTests(unittest.TestCase):
    def test_package_paths_reject_parent_traversal(self) -> None:
        packages = "Package: rvs\nFilename: ../outside.deb\n"
        with self.assertRaises(SystemExit):
            package_paths(packages)

    @patch("restore_public_apt.time.sleep")
    @patch("restore_public_apt.urllib.request.urlopen")
    def test_public_fetch_retries_a_transient_failure(self, urlopen, sleep) -> None:
        urlopen.side_effect = [urllib.error.URLError("transient"), Response(b"manifest")]
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "channels.json"
            public_fetcher("https://releases.ravenstash.com/rvs/apt")("channels.json", destination)
            self.assertEqual(destination.read_bytes(), b"manifest")
        sleep.assert_called_once_with(1)

    @patch("restore_public_apt.verify")
    @patch("restore_public_apt.verify_signature")
    def test_restore_fetches_authenticated_distributions_and_packages(
        self,
        verify_signature,
        verify,
    ) -> None:
        package_path = "pool/main/r/rvs/rvs_0.3.2_amd64_test.deb"
        packages = (
            f"Package: rvs\nVersion: 0.3.2\nArchitecture: amd64\nFilename: {package_path}\n"
        ).encode()
        digest = hashlib.sha256(packages).hexdigest()
        release = (f"SHA256:\n {digest} {len(packages)} main/binary-amd64/Packages\n").encode()
        manifest = json.dumps(
            {
                "channels": {"v0.3": {}},
                "recommended": "v0.3",
                "schema": 1,
            }
        ).encode()
        files = {
            "channels.json": manifest,
            "channels.json.gpg": b"manifest signature",
            package_path: b"deb",
        }
        for distribution in ("stable", "v0.3"):
            prefix = f"dists/{distribution}"
            files[f"{prefix}/InRelease"] = b"inrelease"
            files[f"{prefix}/Release"] = release
            files[f"{prefix}/Release.gpg"] = b"release signature"
            files[f"{prefix}/main/binary-amd64/Packages"] = packages
            files[f"{prefix}/main/binary-amd64/by-hash/SHA256/{digest}"] = packages

        def authenticate(_keyring, signature, content=None):
            if signature.name == "channels.json.gpg":
                return manifest
            return release if content is None else content.read_bytes()

        verify_signature.side_effect = authenticate
        requested: list[str] = []

        def fetch(path: str, destination: Path) -> None:
            requested.append(path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(files[path])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            keyring = root / "trusted.gpg"
            keyring.write_bytes(b"trusted key")
            destination = root / "repository"
            restore_public_repository(destination, keyring, fetch)

            self.assertEqual((destination / package_path).read_bytes(), b"deb")
            self.assertEqual((destination / "ravenstash-rvs.gpg").read_bytes(), b"trusted key")
            self.assertEqual(requested.count(package_path), 1)
            verify.assert_called_once_with(destination, keyring)


if __name__ == "__main__":
    unittest.main()
