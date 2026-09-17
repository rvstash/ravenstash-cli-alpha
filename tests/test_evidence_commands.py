from __future__ import annotations

import hashlib
import json
import os
from typing import TYPE_CHECKING, Any

import pytest
from rvs import output
from rvs.artifacts import evidence_commands
from typer.testing import CliRunner


if TYPE_CHECKING:
    from pathlib import Path


runner = CliRunner()


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def json(self) -> dict[str, object]:
        return self.payload


class _DocumentResponse:
    def __init__(self, payload: bytes, etag: str) -> None:
        self.content = payload
        self.headers = {"etag": etag}

    def json(self) -> dict[str, object]:
        import json

        return json.loads(self.content)


class _Client:
    def __init__(self) -> None:
        self.payload: dict[str, object] | None = None

    def post(self, path: str, *, json: dict[str, object]) -> _Response:
        assert path == "/package-evidence/intents"
        self.payload = json
        return _Response(
            {
                **json,
                "evidence_intent_ref": "pe_23456789abcdefghijkmn",
                "state": "prepared",
                "analysis_state": "not_started",
                "bound_artifact_refs": [],
            }
        )


def test_hash_file_streams_and_records_identity(tmp_path: Path) -> None:
    path = tmp_path / "bom.cdx.json"
    path.write_bytes(b'{"bomFormat":"CycloneDX"}')

    result = evidence_commands._hash_file(path, max_bytes=1024)

    assert result.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result.size == path.stat().st_size
    evidence_commands._require_unchanged(result)


def test_hash_file_rejects_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    link = tmp_path / "bom.cdx.json"
    link.symlink_to(source)

    with pytest.raises(SystemExit):
        evidence_commands._hash_file(link, max_bytes=1024)


def test_upload_identity_check_rejects_changed_file(tmp_path: Path) -> None:
    path = tmp_path / "bom.cdx.json"
    path.write_text("{}", encoding="utf-8")
    result = evidence_commands._hash_file(path, max_bytes=1024)
    path.write_text('{"changed":true}', encoding="utf-8")
    os.utime(path, ns=(result.modified_ns + 1, result.modified_ns + 1))

    with pytest.raises(SystemExit):
        evidence_commands._require_unchanged(result)


def test_stage_coordinate_validation_accepts_matching_python_release(
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "demo_package-1.2.0-py3-none-any.whl"
    sdist = tmp_path / "demo_package-1.2.0.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")

    evidence_commands._validate_distribution_coordinates(
        [
            evidence_commands._hash_file(wheel, max_bytes=1024),
            evidence_commands._hash_file(sdist, max_bytes=1024),
        ],
        format="pypi",
        package="demo-package",
        version="1.2.0",
    )


def test_stage_coordinate_validation_rejects_mixed_python_release(
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "other_package-1.2.0-py3-none-any.whl"
    wheel.write_bytes(b"wheel")

    with pytest.raises(SystemExit):
        evidence_commands._validate_distribution_coordinates(
            [evidence_commands._hash_file(wheel, max_bytes=1024)],
            format="pypi",
            package="demo-package",
            version="1.2.0",
        )


@pytest.mark.parametrize(
    ("format", "package", "version", "filename"),
    [
        ("npm", "@scope/demo-package", "2.0.0", "scope-demo-package-2.0.0.tgz"),
        ("maven", "org.example:demo", "3.1.0", "demo-3.1.0-sources.jar"),
    ],
)
def test_stage_coordinate_validation_accepts_native_filenames(
    tmp_path: Path,
    format: str,
    package: str,
    version: str,
    filename: str,
) -> None:
    artifact = tmp_path / filename
    artifact.write_bytes(b"artifact")

    evidence_commands._validate_distribution_coordinates(
        [evidence_commands._hash_file(artifact, max_bytes=1024)],
        format=format,
        package=package,
        version=version,
    )


def test_evidence_help_keeps_profile_and_analysis_context_distinct() -> None:
    result = runner.invoke(evidence_commands.app, ["stage", "--help"])

    assert result.exit_code == 0
    assert "--profile" in result.output
    assert "--analysis-context" in result.output
    assert "--analysis-profile" not in result.output


def test_stage_emits_stable_json_without_upload_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    distribution = tmp_path / "demo-1.0.0-py3-none-any.whl"
    distribution.write_bytes(b"wheel")
    evidence = tmp_path / "bom.cdx.json"
    evidence.write_text("{}", encoding="utf-8")
    client = _Client()
    monkeypatch.setattr(
        evidence_commands,
        "_repository_target",
        lambda **_kwargs: (client, "ar_23456789"),
    )

    async_uploads: list[Any] = []

    def fake_upload(
        _client: _Client,
        intent: dict[str, object],
        files: list[tuple[str, evidence_commands.FileDigest]],
    ) -> dict[str, object]:
        async_uploads.extend(files)
        return {**intent, "state": "evidence_ready"}

    monkeypatch.setattr(evidence_commands, "_upload_evidence", fake_upload)
    output.set_json(True)
    try:
        result = runner.invoke(
            evidence_commands.app,
            [
                "stage",
                str(distribution),
                "--target",
                "ar_23456789",
                "--format",
                "pypi",
                "--package",
                "demo",
                "--version",
                "1.0.0",
                "--evidence",
                f"cyclonedx={evidence}",
                "--analysis-context",
                "pypi-cpython313-linux-x86_64-base",
                "--profile",
                "work",
            ],
        )
    finally:
        output.set_json(False)

    assert result.exit_code == 0
    assert "evidence_intent_ref" in result.output
    assert "upload_request" not in result.output
    assert client.payload is not None
    assert client.payload["analysis_context_id"] == "pypi-cpython313-linux-x86_64-base"
    assert len(async_uploads) == 1


def test_list_forwards_cursor_and_preserves_page_in_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ListClient:
        params: dict[str, object] | None = None

        def get(self, path: str, *, params: dict[str, object]) -> _Response:
            assert path == "/package-evidence/intents"
            self.params = params
            return _Response(
                {
                    "items": [
                        {
                            "evidence_intent_ref": "pe_23456789abcdefghijkmn",
                            "package": "demo",
                            "version": "1.0.0",
                            "scope": "artifact",
                            "state": "active",
                            "analysis_state": "complete",
                        }
                    ],
                    "next_cursor": "next-page",
                }
            )

    client = ListClient()
    monkeypatch.setattr(
        evidence_commands,
        "_repository_target",
        lambda **_kwargs: (client, "ar_23456789"),
    )
    output.set_json(True)
    try:
        result = runner.invoke(
            evidence_commands.app,
            [
                "list",
                "--target",
                "ar_23456789",
                "--format",
                "pypi",
                "--limit",
                "25",
                "--cursor",
                "current-page",
            ],
        )
    finally:
        output.set_json(False)

    assert result.exit_code == 0
    assert json.loads(result.stdout)["next_cursor"] == "next-page"
    assert client.params == {
        "target": "in/ar_23456789",
        "format": "pypi",
        "limit": 25,
        "cursor": "current-page",
    }


def test_sbom_download_verifies_semantic_snapshot_etag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import json

    snapshot = "a" * 64
    payload = json.dumps(
        {
            "metadata": {
                "timestamp": "2026-09-17T00:00:00Z",
                "properties": [
                    {
                        "name": "ravenstash:sbom:snapshot-digest",
                        "value": snapshot,
                    }
                ],
            },
        }
    ).encode()

    class DocumentClient:
        def get(self, _path: str, *, params: object = None) -> _DocumentResponse:
            return _DocumentResponse(payload, f'"sha256:{snapshot}"')

    monkeypatch.setattr(
        evidence_commands.ApiClient,
        "from_profile",
        lambda _profile: DocumentClient(),
    )
    destination = tmp_path / "bom.cdx.json"

    evidence_commands._download_document(
        artifact_ref="pa_23456789abcdefghijkmn",
        kind="sbom",
        destination=destination,
        profile="work",
        analysis_context="observed",
    )

    assert destination.read_bytes() == payload
