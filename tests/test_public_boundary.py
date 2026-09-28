"""Keep the tracked tree free of private names, paths, credentials, and artifacts.

This is a defense-in-depth policy check over every tracked file. It is not a
substitute for reviewing the tree before publication, nor for a dedicated
secret scanner.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
THIS_FILE = Path(__file__).resolve().relative_to(ROOT).as_posix()

# Private names, locations, and coordinates that must never reach the tree.
# Each pattern is precise so ordinary public words ("server", "API", "release
# environment", Maven Central) stay allowed.
FORBIDDEN_TEXT = {
    "private service name": re.compile(
        r"\bdev[-_ ]?api\b|\bedge-downloader\b|\bremote-streamer\b|\bsecurity-scanner\b"
        r"|\bnotification-router\b|\bbackoffice\b|\bPkg service\b|\bCentral service\b",
        re.IGNORECASE,
    ),
    "private repository": re.compile(
        r"\bk8s-platform-ops\b|\bplatform-contracts\b|\bsecurity-contracts\b|\brspecs\b"
        r"|github\.com/teamravenstash\b",
        re.IGNORECASE,
    ),
    "private workspace path": re.compile(
        r"public/cli/|docs/engineering/|docs/tasks/|infra/terraform|apps/(?:devapi|central"
        r"|artifacts|webapp|website)\b|projects/ravenstash\b"
    ),
    "private environment coordinate": re.compile(
        r"hxa159|fkwx4375|xku357|\binfisical\b|\bkubeconfig-production\b", re.IGNORECASE
    ),
    "private key or credential": re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\bAKIA[0-9A-Z]{16}\b"
        r"|\bgh[pousr]_[A-Za-z0-9]{36}\b|hooks\.slack\.com/services/|\bxox[abprs]-[A-Za-z0-9-]+"
    ),
}

# The pre-release repository identity is replaced when the public repository is
# exported; until then it may appear only in these files.
PRE_RELEASE_IDENTITY = re.compile(r"ravenstash-cli-alpha")
PRE_RELEASE_IDENTITY_FILES = frozenset(
    {
        ".github/ISSUE_TEMPLATE/config.yml",
        "CHANGELOG.md",
        "SECURITY.md",
        "SUPPORT.md",
        "packaging/install.ps1",
        "packaging/install.sh",
        "pyproject.toml",
        "rvs/portable_update.py",
        "rvs/update.py",
        "tests/test_packaging.py",
        "tests/test_update.py",
    }
)

# Generated output, caches, and local artifacts are never tracked.
FORBIDDEN_PATHS = re.compile(
    r"(^|/)(__pycache__|\.venv|node_modules|dist|build|\.pytest_cache|\.ruff_cache)/"
    r"|\.egg-info(/|$)|\.py[co]$|(^|/)\.coverage$"
    r"|\.(whl|deb|rpm|dmg|msi|exe|dll|so|dylib|tgz|zip)$|\.tar\.(gz|xz|bz2)$"
)

# The public contributor guide must stand alone when the repository is cloned.
AGENTS_FORBIDDEN = re.compile(r"\binternal\b|\bparent\b|\bwrapper\b|\.\./", re.IGNORECASE)

# Markdown links must stay inside the repository or use an absolute URL.
MARKDOWN_LINK = re.compile(r"\]\((?!https?://|mailto:|#)([^)\s]+)\)")


def _tracked_files() -> list[str]:
    git = shutil.which("git")
    if git is None or not (ROOT / ".git").exists():
        pytest.skip("the public-boundary check runs in a Git checkout")
    listed = subprocess.run(
        [git, "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    ).stdout
    return [path for path in listed.decode("utf-8").split("\0") if path]


def _text(path: str) -> str | None:
    try:
        return (ROOT / path).read_text(encoding="utf-8")
    except UnicodeDecodeError, FileNotFoundError, IsADirectoryError:
        return None


@pytest.fixture(scope="module")
def tracked() -> dict[str, str | None]:
    return {path: _text(path) for path in _tracked_files()}


def test_no_generated_or_local_artifacts_are_tracked(tracked: dict[str, str | None]) -> None:
    assert [path for path in tracked if FORBIDDEN_PATHS.search(path)] == []


@pytest.mark.parametrize("category", sorted(FORBIDDEN_TEXT))
def test_tracked_text_contains_no_private_names_or_credentials(
    tracked: dict[str, str | None], category: str
) -> None:
    pattern = FORBIDDEN_TEXT[category]
    findings = [
        f"{path}:{number}: {match.group(0)}"
        for path, text in tracked.items()
        if text is not None and path != THIS_FILE
        for number, line in enumerate(text.splitlines(), start=1)
        for match in pattern.finditer(line)
    ]

    assert findings == [], f"{category} in tracked files"


def test_pre_release_identity_stays_in_its_identity_files(
    tracked: dict[str, str | None],
) -> None:
    carriers = {
        path
        for path, text in tracked.items()
        if text is not None and path != THIS_FILE and PRE_RELEASE_IDENTITY.search(text)
    }

    assert carriers <= PRE_RELEASE_IDENTITY_FILES
    # A file that no longer carries the identity leaves the allowlist.
    assert PRE_RELEASE_IDENTITY_FILES <= set(tracked)


def test_contributor_guide_stands_alone(tracked: dict[str, str | None]) -> None:
    guide = tracked.get("AGENTS.md")

    assert guide is not None
    assert AGENTS_FORBIDDEN.findall(guide) == []


def test_markdown_links_stay_inside_the_repository(tracked: dict[str, str | None]) -> None:
    broken = []
    for path, text in tracked.items():
        if text is None or not path.endswith(".md"):
            continue
        base = (ROOT / path).parent
        for target in MARKDOWN_LINK.findall(text):
            resolved = (base / target.split("#", 1)[0]).resolve()
            if not resolved.is_relative_to(ROOT) or not resolved.exists():
                broken.append(f"{path}: {target}")

    assert broken == []
