"""rvn.runtimes — self-contained runtime download and management.

Downloads pre-built binaries for Python, Node.js, Java (Temurin), and Apache
Maven into ~/.rvn/runtimes/{kind}/{version}/ without touching system paths.

Shell path integration is handled through ~/.rvn/env (source it once in your
rc file via `rvn system setup-shell`).
"""

from __future__ import annotations
