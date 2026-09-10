"""Ephemeral, read-only Docker credential-helper protocol for Ravenstash OCI."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .registry import normalized_registry_host


def _broker() -> dict[str, str]:
    path_value = os.environ.get("RVS_OCI_CREDENTIAL_FILE")
    if not path_value:
        raise RuntimeError("Ravenstash OCI credential broker is unavailable")
    path = Path(path_value)
    stat = path.stat()
    if stat.st_mode & 0o077:
        raise RuntimeError("Ravenstash OCI credential broker permissions are unsafe")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Ravenstash OCI credential broker is invalid")
    required = {"server", "username", "secret"}
    if not required.issubset(payload) or not all(
        isinstance(payload[key], str) and payload[key] for key in required
    ):
        raise RuntimeError("Ravenstash OCI credential broker is invalid")
    return payload


def main() -> None:
    operation = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        payload = _broker()
        if operation == "get":
            requested = sys.stdin.read().strip()
            server = normalized_registry_host(payload["server"])
            if not server or normalized_registry_host(requested) != server:
                raise RuntimeError("credentials are not available for this registry")
            print(
                json.dumps(
                    {"Username": payload["username"], "Secret": payload["secret"]},
                    separators=(",", ":"),
                )
            )
            return
        if operation == "list":
            print(json.dumps({payload["server"]: payload["username"]}))
            return
        if operation in {"store", "erase"}:
            raise RuntimeError("the ephemeral Ravenstash helper is read-only")
        raise RuntimeError("unsupported credential-helper operation")
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
