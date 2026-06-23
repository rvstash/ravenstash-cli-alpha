"""Filesystem path helpers for rvn user state."""

from __future__ import annotations

import os
from pathlib import Path


def rvn_home() -> Path:
    """Return the rvn user-state directory.

    Defaults to ``~/.rvn`` and can be overridden with ``RVN_HOME``.  This keeps
    packaged installs independent from user configuration and runtime state.
    """
    configured = os.environ.get("RVN_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".rvn"


def rvn_path(*parts: str) -> Path:
    """Return a path below :func:`rvn_home`."""
    return rvn_home().joinpath(*parts)
