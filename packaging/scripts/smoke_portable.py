"""Smoke-test a native portable bundle without network credentials."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


def main() -> None:
    bundle = Path(sys.argv[1]).resolve()
    identity = re.fullmatch(
        r"rvs-v(?P<version>.+)-(?:linux(?:-musl)?|macos|windows)-(?:amd64|arm64)",
        bundle.name,
    )
    if identity is None:
        raise SystemExit(f"unexpected bundle directory name: {bundle.name}")
    suffix = ".exe" if os.name == "nt" else ""
    expected = ["rvs", "ravenstash", "docker-credential-rvs"]
    for name in expected:
        path = bundle / f"{name}{suffix}"
        if not path.is_file():
            raise SystemExit(f"missing executable: {path}")
    environment = os.environ.copy()
    environment.pop("RVS_TOKEN", None)
    temporary_home = bundle.parent / "smoke-home"
    temporary_home.mkdir(mode=0o700, exist_ok=True)
    environment["RVS_HOME"] = str(temporary_home / ".rvs")
    version = subprocess.run(
        [str(bundle / f"rvs{suffix}"), "--version"],
        check=True,
        env=environment,
        capture_output=True,
        text=True,
    )
    if version.stdout.strip() != f"Ravenstash CLI {identity.group('version')}":
        raise SystemExit(f"bundle version mismatch: {version.stdout.strip()}")
    print(version.stdout, end="")
    subprocess.run(
        [str(bundle / f"rvs{suffix}"), "--help"],
        check=True,
        env=environment,
        stdout=subprocess.DEVNULL,
    )
    status = subprocess.run(
        [str(bundle / f"ravenstash{suffix}"), "auth", "status"],
        check=False,
        env=environment,
        stdout=subprocess.DEVNULL,
    )
    if status.returncode != 1:
        raise SystemExit(f"unexpected unauthenticated status exit code: {status.returncode}")


if __name__ == "__main__":
    main()
