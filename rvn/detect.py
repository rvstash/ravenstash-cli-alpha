"""Auto-detection of registry kind from project context or package spec.

Detection sources
-----------------
``detect_kind_from_project(cwd)``
    Inspects files in a directory (package.json, pom.xml, pyproject.toml, …)
    to pick the most likely registry kind.

``detect_kind_from_package_spec(spec)``
    Infers the registry kind from a package name / version spec:
    - Maven GAV ``com.example:mylib:1.0`` → ``"maven"``
    - npm scoped ``@scope/pkg``           → ``"npm"``
    - Everything else                     → ``"pypi"``

``kind_for_tool(tool)``
    Maps a package-manager executable name to a registry kind:
    pip / pip3 / uv → ``"pypi"``
    npm / yarn / pnpm → ``"npm"``
    mvn / gradle / sbt → ``"maven"``
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path


# ── Maven GAV ─────────────────────────────────────────────────────────────────
# groupId must contain at least one dot (distinguishes from npm/pypi).
# Accepts:  com.example:mylib  or  com.example:mylib:1.0  or  com.example:mylib:1.0:jar
_MAVEN_GAV = re.compile(
    r"^[a-z][a-z0-9_.-]*\.[a-z0-9_.-]+:[a-zA-Z][a-zA-Z0-9_.-]*(:[a-zA-Z0-9_.-]*)?"
)


# ── Project-level detection ───────────────────────────────────────────────────


def detect_kind_from_project(cwd: Path) -> str | None:
    """Guess registry kind by inspecting files present in *cwd*.

    Returns ``"npm"``, ``"maven"``, ``"pypi"``, or ``None`` when no
    recognisable project files are found.

    Detection priority:
    1. ``package.json``                              → npm
    2. ``pom.xml`` or ``build.gradle[.kts]``         → maven
    3. ``pyproject.toml`` / ``setup.py`` / ``setup.cfg`` → pypi
    4. ``dist/*.whl`` or ``dist/*.tar.gz``           → pypi
    """
    if (cwd / "package.json").exists():
        return "npm"
    if (
        (cwd / "pom.xml").exists()
        or any(cwd.glob("build.gradle*"))
        or (cwd / "settings.gradle").exists()
    ):
        return "maven"
    if (
        (cwd / "pyproject.toml").exists()
        or (cwd / "setup.py").exists()
        or (cwd / "setup.cfg").exists()
    ):
        return "pypi"
    dist = cwd / "dist"
    if dist.is_dir() and (list(dist.glob("*.whl")) or list(dist.glob("*.tar.gz"))):
        return "pypi"
    return None


def detect_all_kinds(cwd: Path) -> list[str]:
    """Return ALL registry kinds detectable in *cwd* (zero, one, or more).

    Unlike :func:`detect_kind_from_project`, which returns the first match,
    this function accumulates every detected kind so the caller can decide
    whether the project is unambiguous (exactly one kind) or mixed.

    Detection order: npm → maven → pypi
    """
    kinds: list[str] = []
    if (cwd / "package.json").exists():
        kinds.append("npm")
    if (
        (cwd / "pom.xml").exists()
        or any(cwd.glob("build.gradle*"))
        or (cwd / "settings.gradle").exists()
    ):
        kinds.append("maven")
    if (
        (cwd / "pyproject.toml").exists()
        or (cwd / "setup.py").exists()
        or (cwd / "setup.cfg").exists()
    ):
        kinds.append("pypi")
    if not kinds:
        dist = cwd / "dist"
        if dist.is_dir() and (list(dist.glob("*.whl")) or list(dist.glob("*.tar.gz"))):
            kinds.append("pypi")
    return kinds


# ── Package-spec detection ────────────────────────────────────────────────────


def detect_kind_from_package_spec(spec: str) -> str | None:
    """Infer registry kind from a package name or version spec.

    Returns ``"maven"``, ``"npm"``, ``"pypi"``, or ``None``.
    """
    # Strip version specifiers to get the bare name
    name = re.split(r"[><=!~^@]", spec)[0].strip()

    if _MAVEN_GAV.match(name):
        return "maven"
    # npm scoped: @scope/package
    if spec.lstrip().startswith("@") and "/" in spec:
        return "npm"
    # PyPI is the safe fallback for anything that looks like a plain name
    return "pypi"


# ── Tool → kind mapping ───────────────────────────────────────────────────────

_TOOL_KIND: dict[str, str] = {
    "pip": "pypi",
    "pip3": "pypi",
    "uv": "pypi",
    "npm": "npm",
    "yarn": "npm",
    "pnpm": "npm",
    "npx": "npm",
    "mvn": "maven",
    "mvnw": "maven",
    "maven": "maven",
    "gradle": "maven",
    "gradlew": "maven",
    "sbt": "maven",
}


def kind_for_tool(tool: str) -> str | None:
    """Return the registry kind implied by a package-manager tool name."""
    return _TOOL_KIND.get(tool.lower())


# ── Human-readable label ──────────────────────────────────────────────────────

_KIND_LABEL: dict[str, str] = {
    "pypi": "PyPI (Python)",
    "npm": "npm (Node)",
    "maven": "Maven (JVM)",
}


def kind_label(kind: str) -> str:
    return _KIND_LABEL.get(kind, kind)
