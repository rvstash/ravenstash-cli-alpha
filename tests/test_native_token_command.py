from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from rvs import output
from rvs.artifacts import auth_commands
from rvs.auth import credentials
from rvs.cli import app
from rvs.client import ApiClient, ApiError
from typer.testing import CliRunner


SECRET = "rvs_slt" + "A" * 43
runner = CliRunner()


@pytest.fixture
def issuer(monkeypatch):
    output.set_json(False)
    client = Mock()
    client.issue_native.return_value = httpx.Response(
        200,
        json={
            "access_token": SECRET,
            "expires_in": 14400,
            "operations": ["download"],
            "native_path": "/in_abcdefgh/r_abcdefgh",
        },
    )
    target = SimpleNamespace(
        target_type="repository",
        repository_unique_ref="r_abcdefgh",
        namespace_unique_ref="in_abcdefgh",
        namespace_name_cache="space",
        repository_name_cache="packages",
        namespace_realm="internal",
        registry_kind="pypi",
    )

    def resolve(*args, **kwargs):
        print("Resolved fixture target")
        return "fixture", SimpleNamespace(customer_id="customer"), target

    monkeypatch.setattr(auth_commands, "resolve_target", resolve)
    monkeypatch.setattr(ApiClient, "from_profile", lambda *args, **kwargs: client)
    yield client
    output.set_json(False)


def test_manual_default_prints_only_the_secret_to_stdout(issuer):
    result = runner.invoke(app, ["artifacts", "auth", "print-token", "--target", "space/packages"])
    assert result.exit_code == 0, result.output
    assert result.stdout == SECRET + "\n"
    assert "Resolved fixture target" in result.stderr
    path, payload = issuer.issue_native.call_args.args
    assert path == "/package-credentials"
    assert payload["duration_seconds"] == 14400
    assert payload["operations"] == ["download"]
    assert payload["registry_kind"] == "pypi"


def test_manual_kind_is_required_only_when_target_is_ambiguous(issuer, monkeypatch):
    target = SimpleNamespace(
        target_type="repository",
        repository_unique_ref="r_abcdefgh",
        namespace_unique_ref="in_abcdefgh",
        namespace_name_cache="space",
        repository_name_cache="packages",
        namespace_realm="internal",
        registry_kind=None,
    )
    monkeypatch.setattr(
        auth_commands,
        "resolve_target",
        lambda *args, **kwargs: ("fixture", SimpleNamespace(customer_id="customer"), target),
    )

    result = runner.invoke(app, ["art", "auth", "print-token", "--target", "space/packages"])

    assert result.exit_code == 1
    assert "supports more than one package format" in result.stderr
    issuer.issue_native.assert_not_called()


def test_manual_json_and_publish_are_explicit(issuer):
    import json

    result = runner.invoke(
        app,
        [
            "artifacts",
            "auth",
            "print-token",
            "--target",
            "space/packages",
            "--kind",
            "container",
            "--access",
            "publish",
            "--duration",
            "12h",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["access_token"] == SECRET
    assert issuer.issue_native.call_args.args[1]["duration_seconds"] == 43200
    assert issuer.issue_native.call_args.args[1]["operations"] == ["download", "upload"]


def test_manual_admin_requests_delete_without_changing_publish(issuer):
    result = runner.invoke(
        app,
        [
            "artifacts",
            "auth",
            "print-token",
            "--target",
            "space/packages",
            "--kind",
            "container",
            "--access",
            "admin",
        ],
    )
    assert result.exit_code == 0, result.output
    assert result.stdout == SECRET + "\n"
    assert issuer.issue_native.call_args.args[1]["operations"] == ["download", "upload", "delete"]


@pytest.mark.parametrize("duration", ["14m", "0h", "13h", "4", "forever"])
def test_invalid_lifetime_is_rejected_before_issuance(issuer, duration):
    result = runner.invoke(
        app,
        [
            "artifacts",
            "auth",
            "print-token",
            "--target",
            "space/packages",
            "--kind",
            "npm",
            "--duration",
            duration,
        ],
    )
    assert result.exit_code != 0
    assert result.stdout == ""
    issuer.issue_native.assert_not_called()


@pytest.mark.parametrize(
    "token", ["", "rst_old", "header.payload.signature", SECRET, "rvs_ust" + "A" * 42 + "B"]
)
def test_invalid_environment_override_never_uses_the_stored_login(monkeypatch, token):
    monkeypatch.setenv("RVS_TOKEN", token)
    stored = Mock(side_effect=AssertionError("Stored session must not be consulted"))
    monkeypatch.setattr(credentials, "selected_credential_store", stored)
    with pytest.raises(SystemExit):
        credentials.get_token("fixture")
    assert credentials.token_source("fixture") == "RVS_TOKEN"
    stored.assert_not_called()


@pytest.mark.parametrize("marker", ["rvs_ust", "rvs_uot", "rvs_oat"])
def test_current_automation_override_has_priority(monkeypatch, marker):
    token = marker + "A" * 43
    monkeypatch.setenv("RVS_TOKEN", token)
    assert credentials.get_token("fixture") == token


def test_native_issuance_retries_are_bounded_and_respect_retry_after(monkeypatch):
    client = ApiClient("https://api.example.test", "source")
    reply = httpx.Response(200, json={"access_token": SECRET})
    post = Mock(
        side_effect=[
            ApiError(503, "busy", retry_after=2),
            httpx.ReadTimeout("lost response"),
            reply,
        ]
    )
    monkeypatch.setattr(client, "post", post)
    sleep = Mock()
    monkeypatch.setattr("rvs.client.time.sleep", sleep)
    assert client.issue_native("/package-credentials", {}) is reply
    assert post.call_count == 3
    assert sleep.call_args_list[0].args[0] >= 2
    assert all(call.kwargs["retry"] is False for call in post.call_args_list)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422])
def test_native_issuance_does_not_retry_denials(monkeypatch, status):
    client = ApiClient("https://api.example.test", "source")
    post = Mock(side_effect=ApiError(status, "denied"))
    monkeypatch.setattr(client, "post", post)
    with pytest.raises(ApiError):
        client.issue_native("/package-credentials", {})
    assert post.call_count == 1


def test_issuance_retry_policy_cannot_be_used_for_an_arbitrary_mutation(monkeypatch):
    client = ApiClient("https://api.example.test", "source")
    post = Mock()
    monkeypatch.setattr(client, "post", post)
    with pytest.raises(ValueError):
        client.issue_native("/repositories", {})
    post.assert_not_called()
