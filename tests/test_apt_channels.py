from __future__ import annotations

import pytest
from rvs.apt_channels import (
    channel_for_version,
    channel_order,
    normalize_channel,
    version_matches_channel,
)


@pytest.mark.parametrize(
    ("version", "channel"),
    (
        ("0.14.3", "v0.14"),
        ("0.14.4~rc.1", "v0.14"),
        ("0.15.0", "v0.15"),
        ("1.0.0", "v1.0"),
        ("1.12.3", "v1.12"),
        ("2.0.0", "v2.0"),
    ),
)
def test_channel_for_version(version: str, channel: str) -> None:
    assert channel_for_version(version) == channel
    assert version_matches_channel(version, channel)


@pytest.mark.parametrize("value", ("stable", "v0", "v0.14.3", "v01", "latest"))
def test_invalid_channels_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_channel(value)


def test_channel_order_crosses_pre_one_and_stable_boundaries() -> None:
    assert channel_order("v0.14") < channel_order("0.15") < channel_order("v1.0")
