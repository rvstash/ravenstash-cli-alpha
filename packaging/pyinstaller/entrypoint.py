"""Frozen executable entrypoint for PyInstaller builds."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    if Path(sys.argv[0]).stem == "docker-credential-rvs":
        from rvs.oci.credential_helper import main as credential_helper_main

        credential_helper_main()
        return
    from rvs.cli import app

    app()


if __name__ == "__main__":
    main()
