from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prune_apt_repository import channel_key, prune


def _distribution(root: Path, name: str, version: str, package: str) -> None:
    binary = root / "dists" / name / "main" / "binary-amd64"
    binary.mkdir(parents=True)
    (root / "dists" / name / "InRelease").write_text("signed", encoding="utf-8")
    (binary / "Packages").write_text(
        f"Package: rvs\nVersion: {version}\nFilename: {package}\n",
        encoding="utf-8",
    )


def _package(root: Path, name: str) -> str:
    relative = f"pool/main/r/rvs/{name}"
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"deb")
    return relative


class PruneAptRepositoryTests(unittest.TestCase):
    def test_channel_key_uses_numeric_ordering(self) -> None:
        self.assertLess(channel_key("v0.9"), channel_key("v0.12"))
        self.assertLess(channel_key("v0.12"), channel_key("v1.0"))

    def test_prune_retains_only_minimum_and_newer_channels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_package = _package(root, "rvs_0.11.1_amd64_old.deb")
            twelve_package = _package(root, "rvs_0.12.2_amd64_twelve.deb")
            thirteen_package = _package(root, "rvs_0.13.4_amd64_thirteen.deb")
            _distribution(root, "stable", "0.3.2", old_package)
            _distribution(root, "v0.11", "0.11.1", old_package)
            _distribution(root, "v0.12", "0.12.2", twelve_package)
            _distribution(root, "v0.13", "0.13.4", thirteen_package)
            (root / "channels.json").write_text(
                json.dumps({"recommended": "v0.13"}), encoding="utf-8"
            )
            (root / "channels.json.gpg").write_bytes(b"old signature")

            plan = prune(root, "v0.12")

            self.assertEqual(plan["removed_distributions"], ["stable", "v0.11"])
            self.assertEqual(plan["retained_distributions"], ["v0.12", "v0.13"])
            self.assertEqual(plan["removed_packages"], [old_package])
            self.assertFalse((root / old_package).exists())
            self.assertTrue((root / twelve_package).is_file())
            self.assertTrue((root / thirteen_package).is_file())
            self.assertFalse((root / "channels.json.gpg").exists())
            channels = json.loads((root / "channels.json").read_text(encoding="utf-8"))
            self.assertEqual(set(channels["channels"]), {"v0.12", "v0.13"})
            self.assertEqual(channels["recommended"], "v0.13")

    def test_prune_requires_the_minimum_channel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "dists").mkdir()

            with self.assertRaisesRegex(ValueError, "minimum retained channel is not published"):
                prune(root, "v0.12")


if __name__ == "__main__":
    unittest.main()
