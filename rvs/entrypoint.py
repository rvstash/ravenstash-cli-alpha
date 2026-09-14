"""Lightweight process entry point for the CLI and credential helper."""

from __future__ import annotations

import sys
from pathlib import Path


def _version_requested(arguments: list[str]) -> bool:
    return len(arguments) == 1 and arguments[0] in {"--version", "-V"}


def main() -> None:
    """Dispatch fast, standalone paths before importing the full CLI graph."""
    if Path(sys.argv[0]).stem == "docker-credential-rvs":
        from .oci.credential_helper import main as credential_helper_main

        credential_helper_main()
        return

    if _version_requested(sys.argv[1:]):
        from importlib.metadata import PackageNotFoundError, version

        try:
            release = version("ravenstash-cli")
        except PackageNotFoundError:
            release = "dev"
        print(f"Ravenstash CLI {release}")
        return

    from .cli import app
    from .config import ConfigError

    try:
        app()
    except ConfigError as exc:
        from . import output

        output.fatal(f"{exc}. Run `rvs profile delete --all` to reset the local configuration.")


if __name__ == "__main__":
    main()
