"""rvn.manifest — project manifest read/write utilities.

Provides detect + per-kind operations (read deps, add dep, remove dep) for:

    pyproject.toml      Python / PEP 621
    requirements.txt    Python legacy
    package.json        Node.js / npm
    pom.xml             Maven / Java
    build.gradle[.kts]  Gradle / Java

All write operations minimise formatting changes: we use tomli_w for TOML
(whitespace is normalised), json.dumps(indent=2) for JSON (preserves most
npm conventions), and string/regex insertion for XML (preserves original
formatting except for the inserted block).
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import tomli_w


ManifestKind = Literal["pyproject", "requirements", "package_json", "pom_xml", "gradle"]
EcoKind = Literal["python", "node", "java"]


@dataclass
class ManifestInfo:
    kind: ManifestKind
    eco: EcoKind
    path: Path


# ── Detection ─────────────────────────────────────────────────────────────────


def detect(cwd: Path = Path(".")) -> ManifestInfo | None:
    """Find the primary project manifest in *cwd*.

    Priority: package.json > pom.xml > build.gradle[.kts] > pyproject.toml
    > requirements.txt.  Returns None if nothing is found.
    """
    checks: list[tuple[ManifestKind, EcoKind, str]] = [
        ("package_json", "node", "package.json"),
        ("pom_xml", "java", "pom.xml"),
        ("gradle", "java", "build.gradle"),
        ("gradle", "java", "build.gradle.kts"),
        ("pyproject", "python", "pyproject.toml"),
        ("requirements", "python", "requirements.txt"),
    ]
    for kind, eco, fname in checks:
        p = cwd / fname
        if p.exists():
            return ManifestInfo(kind, eco, p)
    return None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _norm(name: str) -> str:
    """Normalise a package name for comparison (PEP 503)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _bare(spec: str) -> str:
    """Extract the bare package name from a version spec."""
    return re.split(r"[><=!~^@;[\s]", spec)[0].strip()


# ── pyproject.toml ────────────────────────────────────────────────────────────


def pyproject_read_deps(path: Path) -> list[str]:
    with path.open("rb") as f:
        data = tomllib.load(f)
    return list(data.get("project", {}).get("dependencies", []))


def pyproject_add_dep(path: Path, spec: str) -> bool:
    """Add *spec* to [project.dependencies].

    If a dep with the same normalised name already exists it is replaced.
    Returns True if the file was modified.
    """
    with path.open("rb") as f:
        data = tomllib.load(f)

    project = data.setdefault("project", {})
    deps: list[str] = project.setdefault("dependencies", [])
    new_name = _norm(_bare(spec))

    for i, existing in enumerate(deps):
        if _norm(_bare(existing)) == new_name:
            if existing == spec:
                return False
            deps[i] = spec
            break
    else:
        deps.append(spec)

    project["dependencies"] = deps
    with path.open("wb") as f:
        tomli_w.dump(data, f)
    return True


def pyproject_remove_dep(path: Path, name: str) -> bool:
    """Remove the dep named *name* from [project.dependencies]."""
    normalised = _norm(name)
    with path.open("rb") as f:
        data = tomllib.load(f)

    project = data.get("project", {})
    deps: list[str] = project.get("dependencies", [])
    new_deps = [d for d in deps if _norm(_bare(d)) != normalised]
    if len(new_deps) == len(deps):
        return False

    project["dependencies"] = new_deps
    data["project"] = project
    with path.open("wb") as f:
        tomli_w.dump(data, f)
    return True


# ── requirements.txt ──────────────────────────────────────────────────────────


def requirements_read_deps(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def requirements_add_dep(path: Path, spec: str) -> bool:
    new_name = _norm(_bare(spec))
    content = path.read_text()
    lines = content.splitlines()

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if _norm(_bare(stripped)) == new_name:
            if stripped == spec:
                return False
            lines[i] = spec
            path.write_text("\n".join(lines) + "\n")
            return True

    path.write_text(content.rstrip("\n") + "\n" + spec + "\n")
    return True


def requirements_remove_dep(path: Path, name: str) -> bool:
    normalised = _norm(name)
    content = path.read_text()
    lines = content.splitlines()
    new_lines = [
        line
        for line in lines
        if not (
            line.strip()
            and not line.strip().startswith("#")
            and _norm(_bare(line.strip())) == normalised
        )
    ]
    if len(new_lines) == len(lines):
        return False
    path.write_text("\n".join(new_lines) + "\n")
    return True


# ── package.json ──────────────────────────────────────────────────────────────


def _parse_npm_spec(spec: str) -> tuple[str, str]:
    """Split 'lodash@4' or '@scope/pkg@^1.0' into (name, version)."""
    if spec.startswith("@"):
        # Scoped: @scope/pkg[@version]
        rest = spec[1:]
        if "@" in rest:
            at = rest.index("@")
            return "@" + rest[:at], rest[at + 1 :]
        return spec, "*"
    if "@" in spec:
        at = spec.index("@")
        return spec[:at], spec[at + 1 :]
    return spec, "*"


def package_json_read_deps(path: Path) -> list[str]:
    data = json.loads(path.read_text())
    result: list[str] = []
    for section in ("dependencies", "devDependencies"):
        for name, ver in data.get(section, {}).items():
            result.append(f"{name}@{ver}")
    return result


def package_json_add_dep(path: Path, spec: str, dev: bool = False) -> bool:
    data = json.loads(path.read_text())
    name, version = _parse_npm_spec(spec)
    section = "devDependencies" if dev else "dependencies"
    existing = data.get(section, {}).get(name)
    if existing == version:
        return False
    data.setdefault(section, {})[name] = version
    path.write_text(json.dumps(data, indent=2) + "\n")
    return True


def package_json_remove_dep(path: Path, name: str) -> bool:
    data = json.loads(path.read_text())
    removed = False
    for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        if name in data.get(section, {}):
            del data[section][name]
            removed = True
    if removed:
        path.write_text(json.dumps(data, indent=2) + "\n")
    return removed


# ── pom.xml ───────────────────────────────────────────────────────────────────


def pom_xml_read_deps(path: Path) -> list[str]:
    """Return dependencies as 'groupId:artifactId:version' strings."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.parse(str(path)).getroot()
        ns_m = re.match(r"\{([^}]+)\}", root.tag)
        nsp = f"{{{ns_m.group(1)}}}" if ns_m else ""
        deps = []
        for dep in root.iter(f"{nsp}dependency"):
            g = dep.find(f"{nsp}groupId")
            a = dep.find(f"{nsp}artifactId")
            v = dep.find(f"{nsp}version")
            if g is not None and a is not None:
                gav = f"{g.text}:{a.text}"
                if v is not None:
                    gav += f":{v.text}"
                deps.append(gav)
        return deps
    except Exception:
        return []


def pom_xml_add_dep(path: Path, coords: str) -> bool:
    """Add a Maven dependency to pom.xml.

    *coords* format: ``groupId:artifactId[:version[:scope]]``

    Uses string insertion before ``</dependencies>`` (or creates the section)
    so original XML formatting is preserved for all untouched lines.
    """
    parts = coords.split(":")
    if len(parts) < 2:
        raise ValueError(
            f"Invalid Maven coordinates '{coords}'. Expected groupId:artifactId[:version[:scope]]"
        )

    group_id, artifact_id = parts[0], parts[1]
    version = parts[2] if len(parts) > 2 else None
    scope = parts[3] if len(parts) > 3 else None

    content = path.read_text()

    lines = [
        "    <dependency>",
        f"      <groupId>{group_id}</groupId>",
        f"      <artifactId>{artifact_id}</artifactId>",
    ]
    if version:
        lines.append(f"      <version>{version}</version>")
    if scope:
        lines.append(f"      <scope>{scope}</scope>")
    lines.append("    </dependency>")
    dep_block = "\n".join(lines)

    if "</dependencies>" in content:
        new_content = content.replace("</dependencies>", dep_block + "\n  </dependencies>", 1)
    elif "</project>" in content:
        section = f"\n  <dependencies>\n{dep_block}\n  </dependencies>\n"
        new_content = content.replace("</project>", section + "</project>", 1)
    else:
        return False

    path.write_text(new_content)
    return True


def pom_xml_remove_dep(path: Path, coords: str) -> bool:
    """Remove a dependency by groupId:artifactId (version ignored)."""
    parts = coords.split(":")
    group_id = parts[0]
    artifact_id = parts[1] if len(parts) > 1 else ""

    content = path.read_text()
    pattern = (
        r"\s*<dependency>\s*"
        rf"<groupId>\s*{re.escape(group_id)}\s*</groupId>\s*"
        rf"<artifactId>\s*{re.escape(artifact_id)}\s*</artifactId>\s*"
        r"(?:<version>[^<]*</version>\s*)?"
        r"(?:<scope>[^<]*</scope>\s*)?"
        r"</dependency>"
    )
    new_content, n = re.subn(pattern, "", content)
    if n > 0:
        path.write_text(new_content)
        return True
    return False


# ── build.gradle / build.gradle.kts ──────────────────────────────────────────


def gradle_add_dep(path: Path, coords: str, configuration: str = "implementation") -> bool:
    """Append a dependency line to the Gradle dependencies block.

    Creates the block if it does not exist.  The Groovy/Kotlin string
    delimiter is chosen based on the file extension.
    """
    q = '"'  # both Groovy and Kotlin DSL accept double-quotes

    dep_line = f"    {configuration}({q}{coords}{q})"
    content = path.read_text()

    match = re.search(r"(dependencies\s*\{)", content)
    if match:
        insert_at = match.end()
        new_content = content[:insert_at] + "\n" + dep_line + content[insert_at:]
    else:
        new_content = content.rstrip("\n") + f"\n\ndependencies {{\n{dep_line}\n}}\n"

    path.write_text(new_content)
    return True


def gradle_remove_dep(path: Path, coords: str) -> bool:
    """Remove a Gradle dependency line that contains *coords*."""
    content = path.read_text()
    lines = content.splitlines(keepends=True)
    escaped = re.escape(coords)
    new_lines = [line for line in lines if not re.search(escaped, line)]
    if len(new_lines) == len(lines):
        return False
    path.write_text("".join(new_lines))
    return True


# ── Convenience dispatcher ────────────────────────────────────────────────────


def read_deps(info: ManifestInfo) -> list[str]:
    if info.kind == "pyproject":
        return pyproject_read_deps(info.path)
    if info.kind == "requirements":
        return requirements_read_deps(info.path)
    if info.kind == "package_json":
        return package_json_read_deps(info.path)
    if info.kind == "pom_xml":
        return pom_xml_read_deps(info.path)
    if info.kind == "gradle":
        return []  # Gradle is hard to parse; skip silently
    return []


def add_dep(info: ManifestInfo, spec: str, *, dev: bool = False) -> bool:
    if info.kind == "pyproject":
        return pyproject_add_dep(info.path, spec)
    if info.kind == "requirements":
        return requirements_add_dep(info.path, spec)
    if info.kind == "package_json":
        return package_json_add_dep(info.path, spec, dev=dev)
    if info.kind == "pom_xml":
        return pom_xml_add_dep(info.path, spec)
    if info.kind == "gradle":
        return gradle_add_dep(info.path, spec)
    return False


def remove_dep(info: ManifestInfo, name: str) -> bool:
    if info.kind == "pyproject":
        return pyproject_remove_dep(info.path, name)
    if info.kind == "requirements":
        return requirements_remove_dep(info.path, name)
    if info.kind == "package_json":
        return package_json_remove_dep(info.path, name)
    if info.kind == "pom_xml":
        return pom_xml_remove_dep(info.path, name)
    if info.kind == "gradle":
        return gradle_remove_dep(info.path, name)
    return False
