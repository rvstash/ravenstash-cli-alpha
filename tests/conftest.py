"""Shared test isolation."""

import pytest
from rvs.account import commands as account_cmd


@pytest.fixture(autouse=True)
def _forget_verified_identities():
    """The CLI verifies an identity once per process; each test is its own process."""
    account_cmd._identities.clear()
    yield
    account_cmd._identities.clear()
