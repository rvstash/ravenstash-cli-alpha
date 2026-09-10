import io
import json
import sys

import pytest
from rvs.oci import credential_helper
from rvs.oci.registry import normalized_registry_host


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("https://OCI.example./v1/", "oci.example"),
        ("oci.example:5000", "oci.example:5000"),
        ("https://[::1]:5000/", "[::1]:5000"),
        ("[::1]", "[::1]"),
        ("", ""),
        ("https:///", ""),
    ],
)
def test_registry_authority_preserves_host_and_port(address, expected):
    assert normalized_registry_host(address) == expected


@pytest.mark.parametrize(
    ("server", "requested", "allowed"),
    [
        ("oci.example", "https://OCI.example./v1/", True),
        ("[::1]:5000", "http://[::1]:5000", True),
        ("[::1]:5000", "http://[::1]:5001", False),
        ("oci.example", "another.example", False),
        ("https:///", "https:///", False),
    ],
)
def test_credential_helper_checks_canonical_authority(
    monkeypatch, tmp_path, capsys, server, requested, allowed
):
    broker = tmp_path / "broker.json"
    broker.write_text(
        json.dumps({"server": server, "username": "__token__", "secret": "test-secret"})
    )
    broker.chmod(0o600)
    monkeypatch.setenv("RVS_OCI_CREDENTIAL_FILE", str(broker))
    monkeypatch.setattr(sys, "argv", ["docker-credential-rvs", "get"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(requested))
    if allowed:
        credential_helper.main()
        assert json.loads(capsys.readouterr().out)["Secret"] == "test-secret"
    else:
        with pytest.raises(SystemExit, match="1"):
            credential_helper.main()
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "test-secret" not in captured.err
