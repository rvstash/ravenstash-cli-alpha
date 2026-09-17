from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from channel_policy import (
    channel_for_version,
    compatibility_channel,
    filter_packages,
    manifest,
    normalize_channel,
    version_matches_channel,
)


class ChannelPolicyTests(unittest.TestCase):
    def test_pre_one_releases_share_a_rolling_major_channel(self) -> None:
        self.assertEqual(channel_for_version("0.14.3"), "v0")
        self.assertEqual(channel_for_version("0.15.0~rc.1"), "v0")
        self.assertTrue(version_matches_channel("0.15.0", "v0"))

    def test_major_versions_are_channel_boundaries(self) -> None:
        self.assertEqual(channel_for_version("1.0.9"), "v1")
        self.assertEqual(channel_for_version("1.1.0"), "v1")
        self.assertEqual(channel_for_version("2.0.0"), "v2")

    def test_distribution_is_its_compatibility_channel(self) -> None:
        self.assertEqual(compatibility_channel("v0"), "v0")

    def test_filter_packages_excludes_other_channels(self) -> None:
        packages = (
            "Package: rvs\nVersion: 0.14.3\nArchitecture: amd64\n\n"
            "Package: rvs\nVersion: 0.15.0\nArchitecture: amd64\n"
        )
        selected = filter_packages(packages, "v0")
        self.assertIn("Version: 0.14.3", selected)
        self.assertIn("Version: 0.15.0", selected)

    def test_filter_packages_excludes_other_architectures(self) -> None:
        packages = (
            "Package: rvs\nVersion: 0.14.3\nArchitecture: amd64\n\n"
            "Package: rvs\nVersion: 0.14.3\nArchitecture: arm64\n"
        )
        selected = filter_packages(packages, "v0", "arm64")
        self.assertNotIn("Architecture: amd64", selected)
        self.assertIn("Architecture: arm64", selected)

    def test_invalid_channel_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_channel("stable")

    def test_manifest_maps_each_minor_to_its_latest_stable_patch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            packages = repository / "dists/v0/main/binary-amd64/Packages"
            packages.parent.mkdir(parents=True)
            packages.write_text(
                "Package: rvs\nVersion: 0.14.3\n\n"
                "Package: rvs\nVersion: 0.14.6\n\n"
                "Package: rvs\nVersion: 0.15.1\n",
                encoding="utf-8",
            )

            payload = manifest(repository, "v0")

        self.assertEqual(payload["channels"]["v0"]["latest"], "0.15.1")
        self.assertEqual(
            payload["channels"]["v0"]["minor_targets"],
            {"0.14": "0.14.6", "0.15": "0.15.1"},
        )


if __name__ == "__main__":
    unittest.main()
