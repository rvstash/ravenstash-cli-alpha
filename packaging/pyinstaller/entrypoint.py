"""Frozen executable entrypoint for PyInstaller builds."""

from __future__ import annotations

from rvn.cli import app


if __name__ == "__main__":
    app()
