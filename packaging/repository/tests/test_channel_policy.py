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
        self.assertEqual(channel_for_version("0.3.9"), "v0.3")
        self.assertEqual(channel_for_version("0.4.0~rc.1"), "v0.4")
        self.assertFalse(version_matches_channel("0.4.0", "v0.3"))

    def test_post_one_major_is_a_compatibility_boundary(self) -> None:
        self.assertEqual(channel_for_version("1.9.0"), "v1")
        self.assertEqual(channel_for_version("2.0.0"), "v2")

    def test_legacy_stable_never_moves_beyond_v03(self) -> None:
        self.assertEqual(compatibility_channel("stable"), "v0.3")

    def test_filter_packages_excludes_other_channels(self) -> None:
        packages = (
            "Package: rvs\nVersion: 0.3.1\nArchitecture: amd64\n\n"
            "Package: rvs\nVersion: 0.4.0\nArchitecture: amd64\n"
        )
        selected = filter_packages(packages, "v0.3")
        self.assertIn("Version: 0.3.1", selected)
        self.assertNotIn("Version: 0.4.0", selected)

    def test_filter_packages_excludes_other_architectures(self) -> None:
        packages = (
            "Package: rvs\nVersion: 0.12.1\nArchitecture: amd64\n\n"
            "Package: rvs\nVersion: 0.12.1\nArchitecture: arm64\n"
        )
        selected = filter_packages(packages, "v0.12", "arm64")
        self.assertNotIn("Architecture: amd64", selected)
        self.assertIn("Architecture: arm64", selected)

    def test_invalid_channel_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_channel("stable")


if __name__ == "__main__":
    unittest.main()
