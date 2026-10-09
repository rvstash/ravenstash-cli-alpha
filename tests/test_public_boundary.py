"""Keep the tracked tree free of private names, paths, credentials, and artifacts.

This is a defense-in-depth policy check over every tracked file. It is not a
substitute for reviewing the tree before publication, nor for a dedicated
secret scanner.

Private names are never written here. Each one is stored as a digest and
compared with the words of every tracked file, so this file can be published
with the tree it guards. To forbid another term, add the value printed by::

    python -c "import hashlib, sys; print(hashlib.sha256(
        b'public-boundary:' + sys.argv[1].lower().encode()).hexdigest())" 'the term'

A term is one to three words joined by single ``-``, ``/``, ``.`` or space
characters; matching ignores case. The digests keep the terms out of plain
text and out of searches. They do not protect a term somebody can guess.
"""

import hashlib
import re
import shutil
import subprocess
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

import pytest


if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping


ROOT = Path(__file__).resolve().parent.parent
THIS_FILE = Path(__file__).resolve().relative_to(ROOT).as_posix()

# Digests of private names, locations, and coordinates that must never reach
# the tree, matched as whole words. Ordinary public words stay allowed because
# only these exact terms are listed.
PRIVATE_TERMS: dict[str, frozenset[str]] = {
    "private service name": frozenset(
        {
            "0363624966b517b9f795c9389990dfc6e0960ec786de9e1500940879542849a5",
            "07b3822bc5c3746a464f329cbf9902bc273b896eecbb600de099376f382ce2e5",
            "1289f5e22e7f480098bab37d32056a88dcff40cd4f484dcb4db06ee54b70dacc",
            "1a91192a8becfd00ab4051144a4b67a00e9ed8e7bb977e286760a64b8507b721",
            "2bc035844118435eba0d8704222b33e178198c5d73c88de79ebc89180cfe86d3",
            "39ccbf54846c142b397ba91f42aaab73cde42dcc710de5c937acb1a5639fb047",
            "5f1f626970cbefff8251137ad3c4eef837a57dbca5fa2a68997251630e3da0ff",
            "985756dd48974b5499bab40c63ed342c73466e0a5ed321f139215b7b0c555684",
            "d6abaf7b7ec092091793b6423b386937ceca2cd354dd8beb834fc4223e4603ee",
            "e9e8e4a61cc9c34152fe39c3818e9d62c2c8c10b2631beee6a13004358aa5011",
            "f0c15e081b7ed48d45f3a4622a4f054deea2238979f7f103ba5c0a63fe432a38",
        }
    ),
    "private repository": frozenset(
        {
            "145ba50b3e79600432f340653602d40255fa41478680540473572d9e053176ac",
            "437c4e9bc502d4b58896316d0a2a7290521a7587389d7401bdc2f6e954fde42c",
            "44a6955a0e388343f23c06cf41fa904c4bc4de3cfc47066b4683580d79d50bf8",
            "546a9cffdf564bfac83252a8e2687c3c7ce67fa4b069498e32697e375b29f950",
            "565afed5e38ec00e1f70a33236e6140482218809f3bc99a3d7e1d50def8ee808",
            "78ce09380fe4ee298aaf3287eb289ca9c11d759dc77a6846a6cab8e95a5f8a51",
            "a37d5e459173920c19ba3d343fa02a8d089772539beb4041468e3a70a61034ba",
        }
    ),
    "private workspace path": frozenset(
        {
            "0bdc664b7b339ca4a2f44ef83b8fe759a862aa1aabc9308c98c1f6fb392ae9ac",
            "3a4583d6025ae9a069337467a5c277482ef5585fac8ab1c66ad694b11dab4254",
            "6d014f50df8c2913e08f54affa8dd6fbcd962254fb42b8ec08af02ce22c0b236",
            "71005fd19face8ce5b01aa80567c29fa432381bf81cf938596fab11884854b07",
            "722fb198ff9373e5a09055b15fbbe0604f482050c0e448308e5ef7bdc60f83db",
            "7d828d862e9fc2ff57eba40367df81227b041939f208617b52208a2653e5c3d4",
            "86ef4b8877f1c9bc66ca474bd415ba8cffc2068267a54f1636ba0a9c9fbcc5e8",
            "8c8910a23ac1285419c43e7821b4650dd4f5bbf9e5cf779f43ecb1ce7d985af4",
            "8f287961d17be4e7cd4c7598d1e9fee25184ec8614d9bbf1cb45bf277e6b836b",
            "9e4910e03bccd287dc8b28ae359d4090b6c604bab934add1ea90e0f5340d664b",
            "b71b3a7b12a08b8c97cb5ae2868882dbf5123bb5d3f9d1ddac9136c2c8c0d541",
            "c2b5fcaa5023d44d474e542ffe63633e85b9698498ed7262b0799d1ed8735ea6",
            "e08f23fbe0c7a885e390802cffecf98981dfd4ac139f446fe8b5f39af7ea28d3",
            "e15767771158605828e63ad4763e7e92c71588f34abacacb96a3036a2149d3d3",
            "f657001e153a3f8ad00b3c6bdfdc66195d2484b89dfc08caa7e70ce5d7218f89",
        }
    ),
    "private environment coordinate": frozenset(
        {
            "156aa5a6e62ee5b693bd23b53192e3a705eb465f0c92773c6068ddc589cf4a50",
            "e9c6684b2686da3626660a1064853faab4dff9500f80424d781f95a4fa94ae3d",
        }
    ),
}

# Digests of private environment codes, keyed by their length. A code is
# matched anywhere inside a word because it is embedded in longer identifiers.
EMBEDDED_CODES: dict[int, frozenset[str]] = {
    6: frozenset(
        {
            "1abbd9ba27dadecc14567115f71ee9932df4316afb5694269935201688db8443",
            "f874a30711d8c7652b9be01e46d3e06ba8963f32f887ac2b21d10dc1dfd19727",
        }
    ),
    8: frozenset(
        {
            "9db7ee82019f8aaf0fd803790459c24703a07609ad20701dcda83d6613ab3c47",
        }
    ),
}
EMBEDDED_CODE_CATEGORY = "private environment coordinate"

WORD = re.compile(r"[A-Za-z0-9_]+")
TERM_JOINERS = frozenset("-/. ")
TERM_WORDS = 3

# Credential and key formats reveal nothing private, so they stay readable.
CREDENTIAL = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\bAKIA[0-9A-Z]{16}\b"
    r"|\bgh[pousr]_[A-Za-z0-9]{36}\b|hooks\.slack\.com/services/|\bxox[abprs]-[A-Za-z0-9-]+"
)

# Pre-release repository identities are replaced when the public repositories
# are exported; until then each may appear only in the files listed for it.
PRE_RELEASE_IDENTITY_FILES: dict[str, frozenset[str]] = {
    "ravenstash-cli-alpha": frozenset(
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
    ),
    "examples-alpha": frozenset(),
    "ravenstash-skills-alpha": frozenset(),
}

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


@cache
def _digest(term: str) -> str:
    return hashlib.sha256(b"public-boundary:" + term.lower().encode("utf-8")).hexdigest()


def _phrases(line: str) -> Iterator[tuple[int, str]]:
    """Yield every run of one to three words joined by single term joiners."""
    words = [match.span() for match in WORD.finditer(line)]
    for index, (start, end) in enumerate(words):
        yield start, line[start:end]
        for following_start, following_end in words[index + 1 : index + TERM_WORDS]:
            if following_start != end + 1 or line[end] not in TERM_JOINERS:
                break
            end = following_end
            yield start, line[start:end]


def _private_terms(
    text: str, terms: Mapping[str, frozenset[str]], codes: Mapping[int, frozenset[str]]
) -> Iterator[tuple[int, int, str]]:
    """Yield the line, column, and category of each forbidden term in ``text``."""
    for number, line in enumerate(text.splitlines(), start=1):
        for column, phrase in _phrases(line):
            digest = _digest(phrase)
            for category, digests in terms.items():
                if digest in digests:
                    yield number, column + 1, category
        for word in WORD.finditer(line):
            for length, digests in codes.items():
                for offset in range(len(word.group()) - length + 1):
                    if _digest(word.group()[offset : offset + length]) in digests:
                        yield number, word.start() + offset + 1, EMBEDDED_CODE_CATEGORY


def _private_term_findings(
    tracked: Mapping[str, str | None],
    terms: Mapping[str, frozenset[str]],
    codes: Mapping[int, frozenset[str]],
) -> list[str]:
    """Locate forbidden terms in tracked paths and text without repeating them."""
    findings = []
    for path, text in tracked.items():
        for _number, column, category in _private_terms(path, terms, codes):
            findings.append(f"{path}: {category} in the path at column {column}")
        for number, column, category in _private_terms(text or "", terms, codes):
            findings.append(f"{path}:{number}:{column}: {category}")
    return findings


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


def test_a_fresh_add_keeps_every_tracked_file(tracked: dict[str, str | None]) -> None:
    # A tracked file that an ignore rule matches survives only until the tree is
    # added to a new repository, where it is silently dropped.
    git = shutil.which("git")
    assert git is not None
    present = [path for path in tracked if (ROOT / path).is_file()]
    ignored = subprocess.run(
        [git, "check-ignore", "--no-index", "-z", "--stdin"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        input="\0".join(present).encode("utf-8"),
    )

    assert ignored.returncode in (0, 1), ignored.stderr
    assert [path for path in ignored.stdout.decode("utf-8").split("\0") if path] == []


def test_tracked_files_contain_no_private_names(tracked: dict[str, str | None]) -> None:
    assert _private_term_findings(tracked, PRIVATE_TERMS, EMBEDDED_CODES) == []


def test_private_term_digests_are_well_formed() -> None:
    digests = [digest for group in PRIVATE_TERMS.values() for digest in group]
    codes = [digest for group in EMBEDDED_CODES.values() for digest in group]

    # The counts only ever grow: a term leaves these sets through review, not by accident.
    assert len(digests) == len(set(digests)) >= 35
    assert len(codes) == len(set(codes)) >= 3
    assert all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in digests + codes)


def test_private_term_matcher_reports_planted_terms() -> None:
    # Synthetic stand-ins: one word, one three-word path, and one embedded code.
    terms = {
        "planted name": frozenset({_digest("zqplantedname")}),
        "planted path": frozenset({_digest("zqa-planted/sample")}),
    }
    codes = {7: frozenset({_digest("zq7x9kw")})}
    text = "\n".join(
        [
            "An ordinary line mentions nothing.",
            "Deploys through ZQPlantedName today.",
            "see zqa-planted/sample.md, not zqa-planted/samples or zqa_planted/sample",
            "host=cluster-abzq7x9kwcd.example.test",
            "zqplantednames and xzqplantedname are different words",
        ]
    )

    assert list(_private_terms(text, terms, codes)) == [
        (2, 17, "planted name"),
        (3, 5, "planted path"),
        (4, 16, "private environment coordinate"),
    ]
    assert _private_term_findings(
        {"docs/zqplantedname/notes.md": "clean", "README.md": text, "logo.png": None},
        terms,
        codes,
    ) == [
        "docs/zqplantedname/notes.md: planted name in the path at column 6",
        "README.md:2:17: planted name",
        "README.md:3:5: planted path",
        "README.md:4:16: private environment coordinate",
    ]
    assert _private_term_findings({"README.md": text}, PRIVATE_TERMS, EMBEDDED_CODES) == []


def test_tracked_text_contains_no_keys_or_credentials(tracked: dict[str, str | None]) -> None:
    findings = [
        f"{path}:{number}"
        for path, text in tracked.items()
        if text is not None
        for number, line in enumerate(text.splitlines(), start=1)
        if CREDENTIAL.search(line)
    ]

    assert findings == []


@pytest.mark.parametrize("identity", sorted(PRE_RELEASE_IDENTITY_FILES))
def test_pre_release_identity_stays_in_its_identity_files(
    tracked: dict[str, str | None], identity: str
) -> None:
    allowed = PRE_RELEASE_IDENTITY_FILES[identity]
    carriers = {
        path
        for path, text in tracked.items()
        if path != THIS_FILE and (identity in path or identity in (text or ""))
    }

    assert carriers <= allowed
    # A file that no longer carries the identity leaves the allowlist.
    assert allowed <= set(tracked)


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
