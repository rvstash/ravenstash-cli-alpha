from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from channel_policy import (
    channel_for_version,
    compatibility_channel,
    filter_packages,
    normalize_channel,
    version_matches_channel,
)


class ChannelPolicyTests(unittest.TestCase):
    def test_pre_one_minor_is_a_compatibility_boundary(self) -> None:
        self.assertEqual(channel_for_version("0.14.3"), "v0.14")
        self.assertEqual(channel_for_version("0.15.0~rc.1"), "v0.15")
        self.assertFalse(version_matches_channel("0.15.0", "v0.14"))

    def test_every_minor_is_a_compatibility_boundary(self) -> None:
        self.assertEqual(channel_for_version("1.0.9"), "v1.0")
        self.assertEqual(channel_for_version("1.1.0"), "v1.1")
        self.assertEqual(channel_for_version("2.0.0"), "v2.0")

    def test_distribution_is_its_compatibility_channel(self) -> None:
        self.assertEqual(compatibility_channel("v0.14"), "v0.14")

    def test_filter_packages_excludes_other_channels(self) -> None:
        packages = (
            "Package: rvs\nVersion: 0.14.3\nArchitecture: amd64\n\n"
            "Package: rvs\nVersion: 0.15.0\nArchitecture: amd64\n"
        )
        selected = filter_packages(packages, "v0.14")
        self.assertIn("Version: 0.14.3", selected)
        self.assertNotIn("Version: 0.15.0", selected)

    def test_filter_packages_excludes_other_architectures(self) -> None:
        packages = (
            "Package: rvs\nVersion: 0.14.3\nArchitecture: amd64\n\n"
            "Package: rvs\nVersion: 0.14.3\nArchitecture: arm64\n"
        )
        selected = filter_packages(packages, "v0.14", "arm64")
        self.assertNotIn("Architecture: amd64", selected)
        self.assertIn("Architecture: arm64", selected)

    def test_invalid_channel_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_channel("stable")


if __name__ == "__main__":
    unittest.main()
