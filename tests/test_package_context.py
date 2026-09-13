from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from rvs import config as cfg_mod
from rvs.artifacts import commands as artifacts_commands
from rvs.artifacts.targets import parse_target, resolve_target
from rvs.cli import app
from rvs.client import ApiClient
from rvs.native import runner as native_runner
from typer.testing import CliRunner


if TYPE_CHECKING:
    from pathlib import Path


runner = CliRunner()


class Response:
    def __init__(self, value: Any) -> None:
        self.value = value

    def json(self) -> Any:
        return self.value


def customer(
    customer_id: str,
    label: str,
    account_type: str = "organization",
) -> dict[str, Any]:
    return {
        "account_ref": customer_id,
        "account_handle": label,
        "account_type": account_type,
        "account_label": label,
        "organization_role": "member" if account_type == "organization" else "owner",
        "authority_revision": 4,
    }


def remote(
    *,
    owner: dict[str, Any],
    family: str,
    name: str,
    kind: str,
    suffix: str,
) -> dict[str, Any]:
    return {
        "account": owner,
        "remote_cache": {
            "id": f"remote-{suffix}",
            "public_id": name,
            "unique_id": f"unique-{suffix}",
            "remote_cache_ref": f"rc_{suffix.ljust(8, '2')}",
            "source_type": family,
            "source_id": f"source-{suffix}",
            "official_slug": name if family == "official" else None,
            "remote_name": name if family == "custom" else None,
            "format": kind,
            "created_at": "2026-01-01T00:00:00Z",
        },
    }


class FakeApi:
    def __init__(self, customers: list[dict[str, Any]], remotes: list[dict[str, Any]]) -> None:
        self.customers = customers
        self.remotes = remotes
        self.calls: list[tuple[str, str, Any]] = []

    def get(self, path: str, params: dict[str, Any] | None = None) -> Response:
        self.calls.append(("GET", path, params))
        if path == "/accounts":
            return Response({"items": self.customers, "next_cursor": None})
        if path == "/remote-caches":
            selected = [
                item
                for item in self.remotes
                if params is None
                or (
                    (
                        not params.get("account_ref")
                        or item["account"]["account_ref"] == params["account_ref"]
                    )
                    and (
                        not params.get("format")
                        or item["remote_cache"]["format"] == params["format"]
                    )
                )
            ]
            return Response({"items": selected, "next_cursor": None})
        raise AssertionError(path)

    def issue_native(self, path: str, payload: dict):
        assert payload["duration_seconds"] == 14400
        return self.post(path, json=payload)

    def post(self, path: str, json: dict[str, Any] | None = None) -> Response:
        self.calls.append(("POST", path, json))
        if path == "/remote-package-credentials":
            assert json is not None
            name = str(json["remote_cache_ref"])
            prefix = "o" if name == "rc_py222222" else "c"
            public_name = "pypiorg" if prefix == "o" else "piwheels"
            return Response(
                {
                    "access_token": "rvs_sltEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEA",
                    "native_path": f"/{prefix}/{public_name}",
                }
            )
        raise AssertionError(path)


def isolate(monkeypatch, tmp_path: Path, *, profiles: tuple[str, ...] = ("alice",)) -> None:
    config_dir = tmp_path / ".rvs"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    profile_tables = "\n".join(
        f"""
[profiles.{profile}]
api_url = "https://api.example.test"
account_ref = "personal-{profile}"
""".strip()
        for profile in profiles
    )
    config_file.write_text(
        f'config_version = 4\ndefault_profile = "{profiles[0]}"\n\n{profile_tables}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_file)
    monkeypatch.setattr(cfg_mod, "PROFILE_ENV_FILE", config_dir / "profiles.env")
    monkeypatch.delenv("RVS_PROFILE", raising=False)
    monkeypatch.delenv("RVS_CUSTOMER_ID", raising=False)
    monkeypatch.delenv("RVS_SESSION_ID", raising=False)


def test_target_parser_keeps_private_and_mirror_namespaces_disjoint() -> None:
    bare = parse_target("acme/backend")
    stable_internal = parse_target("in_abcdefgh/r_abcdefgh")
    stable_global = parse_target("gn_abcdefgh/r_abcdefgh")

    assert bare.target_type == "repository"
    assert bare.namespace_realm is None
    assert stable_internal.namespace_realm == "internal"
    assert stable_global.namespace_realm == "global"
    assert parse_target("mirror:pypiorg").target_type == "official_cache"
    assert parse_target("custom-mirror:piwheels").target_type == "custom_cache"


@pytest.mark.parametrize(
    "selector", ["global:acme/backend", "internal:acme/backend", "@acme/backend"]
)
def test_obsolete_target_notation_fails_before_repository_probe(monkeypatch, selector) -> None:
    class NoProbeClient:
        def get(self, *_args, **_kwargs):
            raise AssertionError("global target must not probe private repositories")

    monkeypatch.setattr(
        ApiClient,
        "from_profile",
        staticmethod(lambda profile=None: NoProbeClient()),
    )

    with pytest.raises(SystemExit):
        resolve_target(selector, profile="alice")


@pytest.mark.parametrize("selector", ["cache:pypiorg", "custom-cache:piwheels"])
def test_target_parser_rejects_removed_cache_aliases(selector: str) -> None:
    with pytest.raises(SystemExit):
        parse_target(selector)


def test_account_and_official_cache_selection_are_visible_and_clearable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    isolate(monkeypatch, tmp_path)
    personal = customer("personal-alice", "Alice", "personal")
    acme = customer("acme", "acme")
    fake = FakeApi(
        [personal, acme],
        [remote(owner=acme, family="official", name="pypiorg", kind="pypi", suffix="pypi")],
    )
    monkeypatch.setattr(ApiClient, "from_profile", staticmethod(lambda profile=None: fake))

    switched = runner.invoke(app, ["account", "use", "org:acme"])
    selected = runner.invoke(app, ["art", "select", "mirror:pypiorg"])

    assert switched.exit_code == 0, switched.output
    assert selected.exit_code == 0, selected.output
    saved = cfg_mod.selected_artifact_target("alice", "acme")
    assert saved is not None
    assert saved.target_type == "official_cache"
    assert saved.stable_selector == "mirror:rc_pypi2222"

    cleared = runner.invoke(app, ["art", "clear"])
    assert cleared.exit_code == 0, cleared.output
    assert cfg_mod.selected_artifact_target("alice", "acme") is None


def test_handle_selection_preserves_customer_id_and_canonical_case(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    owner = {**customer("acme-id", "Acme"), "account_handle": "acmeHQ"}
    other = {**customer("other-id", "acmeHQ"), "account_handle": "other-hq"}
    fake = FakeApi([owner, other], [])
    monkeypatch.setattr(ApiClient, "from_profile", staticmethod(lambda profile=None: fake))
    selected = runner.invoke(app, ["account", "use", "ACMEHQ"])
    assert selected.exit_code == 0, selected.output
    assert "acmeHQ" in selected.output
    assert cfg_mod.current_customer_id("alice") == "acme-id"
    cached = cfg_mod.cached_account("alice", "acme-id")
    assert cached is not None
    assert cached.customer_handle == "acmeHQ"
    assert cached.customer_unique_ref == owner["account_ref"]


def test_repository_resolution_rejects_cross_customer_response(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    calls = []

    class ForeignRepositoryApi:
        def get(self, path, params):
            calls.append((path, params))
            return Response({"account": customer("foreign", "Foreign")})

    monkeypatch.setattr(
        ApiClient, "from_profile", staticmethod(lambda profile=None: ForeignRepositoryApi())
    )
    with pytest.raises(SystemExit):
        resolve_target("main/packages", profile="alice", customer_id="selected")
    assert calls == [
        (
            "/repositories/resolve",
            {
                "selector": "main/packages",
                "account_ref": "selected",
            },
        )
    ]
    assert cfg_mod.cached_account("alice", "foreign") is None


def test_custom_cache_kind_collision_requires_disambiguation(monkeypatch, tmp_path: Path) -> None:
    isolate(monkeypatch, tmp_path)
    personal = customer("personal-alice", "Alice", "personal")
    remotes = [
        remote(owner=personal, family="custom", name="piwheels", kind="pypi", suffix="py"),
        remote(owner=personal, family="custom", name="piwheels", kind="maven", suffix="mv"),
    ]
    fake = FakeApi([personal], remotes)
    monkeypatch.setattr(ApiClient, "from_profile", staticmethod(lambda profile=None: fake))

    ambiguous = runner.invoke(app, ["art", "select", "custom-mirror:piwheels"])
    selected = runner.invoke(
        app,
        ["art", "select", "custom-mirror:piwheels", "--format", "pypi"],
    )

    assert ambiguous.exit_code == 1
    assert "ambiguous" in ambiguous.output
    assert selected.exit_code == 0, selected.output
    assert cfg_mod.selected_artifact_target("alice", "personal-alice").registry_kind == "pypi"


def test_two_login_profiles_keep_separate_actor_state_for_the_same_org(
    monkeypatch,
    tmp_path: Path,
) -> None:
    isolate(monkeypatch, tmp_path, profiles=("alice", "bob"))
    acme = customer("acme", "acme")
    fake = FakeApi(
        [acme], [remote(owner=acme, family="official", name="pypiorg", kind="pypi", suffix="pypi")]
    )
    monkeypatch.setattr(ApiClient, "from_profile", staticmethod(lambda profile=None: fake))

    assert runner.invoke(app, ["account", "use", "org:acme", "--profile", "alice"]).exit_code == 0
    assert (
        runner.invoke(app, ["art", "select", "mirror:pypiorg", "--profile", "alice"]).exit_code == 0
    )
    assert runner.invoke(app, ["account", "use", "org:acme", "--profile", "bob"]).exit_code == 0

    assert cfg_mod.selected_artifact_target("alice", "acme") is not None
    assert cfg_mod.selected_artifact_target("bob", "acme") is None


def test_one_shot_account_does_not_switch_the_active_account(monkeypatch, tmp_path: Path) -> None:
    isolate(monkeypatch, tmp_path)
    personal = customer("personal-alice", "Alice", "personal")
    acme = customer("acme", "acme")
    fake = FakeApi([personal, acme], [])
    monkeypatch.setattr(ApiClient, "from_profile", staticmethod(lambda profile=None: fake))

    result = runner.invoke(app, ["art", "current", "--account", "org:acme"])

    assert result.exit_code == 0, result.output
    assert "acme" in result.output
    assert cfg_mod.current_customer_id("alice") == "personal-alice"


def test_account_switch_is_local_to_an_integrated_shell(monkeypatch, tmp_path: Path) -> None:
    isolate(monkeypatch, tmp_path)
    personal = customer("personal-alice", "Alice", "personal")
    acme = customer("acme", "acme")
    fake = FakeApi([personal, acme], [])
    monkeypatch.setattr(ApiClient, "from_profile", staticmethod(lambda profile=None: fake))
    monkeypatch.setenv("RVS_SESSION_ID", "terminal-a")

    switched = runner.invoke(app, ["account", "use", "org:acme"])

    assert switched.exit_code == 0, switched.output
    assert cfg_mod.current_customer_id("alice") == "acme"
    monkeypatch.setenv("RVS_SESSION_ID", "terminal-b")
    assert cfg_mod.current_customer_id("alice") == "personal-alice"


def test_native_wrapper_uses_selected_cache_and_one_shot_does_not_mutate_it(
    monkeypatch,
    tmp_path: Path,
) -> None:
    isolate(monkeypatch, tmp_path)
    personal = customer("personal-alice", "Alice", "personal")
    remotes = [
        remote(owner=personal, family="official", name="pypiorg", kind="pypi", suffix="py"),
        remote(owner=personal, family="custom", name="piwheels", kind="pypi", suffix="custom"),
    ]
    fake = FakeApi([personal], remotes)
    monkeypatch.setattr(ApiClient, "from_profile", staticmethod(lambda profile=None: fake))
    assert runner.invoke(app, ["art", "select", "mirror:pypiorg"]).exit_code == 0

    calls: list[tuple[list[str], dict[str, str]]] = []

    class Completed:
        returncode = 0

    monkeypatch.setattr(native_runner.tools, "pip_cmd", lambda: ["/bin/pip"])
    monkeypatch.setattr(
        native_runner.subprocess,
        "run",
        lambda cmd, *, env, check: calls.append((cmd, env.copy())) or Completed(),
    )

    result = runner.invoke(
        app,
        ["pip", "--rvs-target", "custom-mirror:piwheels", "install", "numpy"],
    )

    assert result.exit_code == 0, result.output
    assert calls[0][0] == [
        "/bin/pip",
        "install",
        "--index-url",
        "https://mirror.pypi.rvsta.sh/c/piwheels/simple/",
        "numpy",
    ]
    assert cfg_mod.selected_artifact_target("alice", "personal-alice").display_selector == (
        "mirror:pypiorg"
    )


def test_artifacts_install_uses_account_scoped_official_default_without_selection(
    monkeypatch,
    tmp_path: Path,
) -> None:
    isolate(monkeypatch, tmp_path)
    monkeypatch.delenv("PIP_KEYRING_PROVIDER", raising=False)
    personal = customer("personal-alice", "Alice", "personal")
    fake = FakeApi(
        [personal],
        [remote(owner=personal, family="official", name="pypiorg", kind="pypi", suffix="py")],
    )
    monkeypatch.setattr(ApiClient, "from_profile", staticmethod(lambda profile=None: fake))
    calls: list[tuple[list[str], dict[str, str]]] = []
    monkeypatch.setattr(artifacts_commands.tools, "pip_cmd", lambda: ["/bin/pip"])
    monkeypatch.setattr(
        artifacts_commands.subprocess,
        "run",
        lambda cmd, *, env, check: calls.append((cmd, env.copy())),
    )

    result = runner.invoke(app, ["art", "install", "requests", "--format", "pypi"])

    assert result.exit_code == 0, result.output
    assert calls[0][0] == ["/bin/pip", "install", "requests"]
    assert calls[0][1]["PIP_INDEX_URL"] == ("https://mirror.pypi.rvsta.sh/o/pypiorg/simple/")
    assert "PIP_KEYRING_PROVIDER" not in calls[0][1]
    assert cfg_mod.selected_artifact_target("alice", "personal-alice") is None


def test_artifacts_repo_one_liner_alias_is_rejected(monkeypatch, tmp_path: Path) -> None:
    isolate(monkeypatch, tmp_path)
    calls: list[tuple[list[str], str | None]] = []
    monkeypatch.setattr(
        artifacts_commands,
        "pypi_install",
        lambda packages, repo, profile, customer_id: calls.append((packages, repo)),
    )

    result = runner.invoke(
        app,
        [
            "art",
            "--target",
            "acme/backend",
            "--format",
            "pypi",
            "install",
            "internal-lib",
        ],
    )

    assert result.exit_code != 0
    assert calls == []


class CrossAccountApi:
    def __init__(self):
        self.calls = []
        self.owner = customer("org-foreign", "OtherOrg")

    def get(self, path, params=None):
        self.calls.append((path, params))
        assert path == "/repositories/resolve"
        return Response(
            {
                "account": self.owner,
                "repository": {
                    "namespace_unique_ref": "in_23456789",
                    "namespace_name": "engineering",
                    "namespace_realm": "internal",
                    "repository_unique_ref": "r_abcdefgh",
                    "repository_name": "packages",
                    "formats": [{"format": "pypi", "upstream_config_revision": 1}],
                },
            }
        )

    def issue_native(self, path, payload):
        assert payload["duration_seconds"] == 14400
        return self.post(path, json=payload)

    def post(self, path, json=None):
        self.calls.append((path, json))
        assert path == "/package-credentials"
        assert json["repository_unique_ref"] == "r_abcdefgh"
        assert json["formats"] == ["pypi"]
        return Response(
            {
                "access_token": "rvs_sltCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCA",
                "native_paths": {"pypi": "/engineering/packages"},
                "formats": ["pypi"],
                "token_type": "bearer",
                "expires_in": 14400,
            }
        )


def test_stable_cross_account_target_reports_owner_without_switching(monkeypatch, tmp_path, capsys):
    isolate(monkeypatch, tmp_path)
    fake = CrossAccountApi()
    monkeypatch.setattr(ApiClient, "from_profile", staticmethod(lambda profile=None: fake))
    _, owner, target = resolve_target("in_23456789/r_abcdefgh", profile="alice", kind="pypi")
    assert fake.calls == [
        (
            "/repositories/resolve",
            {
                "selector": "in_23456789/r_abcdefgh",
                "format": "pypi",
            },
        )
    ]
    assert owner.customer_id == target.customer_id == "org-foreign"
    assert cfg_mod.current_customer_id("alice") == "personal-alice"
    assert "OtherOrg" in capsys.readouterr().out


def test_cross_account_selection_stays_in_current_context_and_uses_owner_credentials(
    monkeypatch, tmp_path
):
    from rvs.artifacts.targets import registry_context

    isolate(monkeypatch, tmp_path)
    fake = CrossAccountApi()
    monkeypatch.setattr(ApiClient, "from_profile", staticmethod(lambda profile=None: fake))
    result = runner.invoke(app, ["art", "select", "in_23456789/r_abcdefgh"])
    assert result.exit_code == 0, result.output
    assert "another account" in result.output
    assert cfg_mod.current_customer_id("alice") == "personal-alice"
    saved = cfg_mod.selected_artifact_target("alice", "personal-alice")
    assert saved is not None and saved.customer_id == "org-foreign"
    assert cfg_mod.selected_artifact_target("alice", "org-foreign") is None
    context = registry_context(kind="pypi", profile="alice")
    assert context.customer_id == "org-foreign"
    assert context.token == "rvs_sltCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCA"
    assert cfg_mod.current_customer_id("alice") == "personal-alice"


@pytest.mark.parametrize("selector", ["r_abcdefgh", "in_23456789/r_abcdefgh"])
def test_management_stable_reference_crosses_account_with_json_hint(
    monkeypatch, tmp_path, selector
):
    import json

    from rvs import output
    from rvs.artifacts.commands import _resolve_repository_entry

    isolate(monkeypatch, tmp_path)
    fake = CrossAccountApi()
    monkeypatch.setattr(ApiClient, "from_profile", staticmethod(lambda profile=None: fake))
    messages = []
    monkeypatch.setattr(
        output.err_console, "print", lambda text, **kwargs: messages.append(json.loads(text))
    )
    output.set_json(True)
    try:
        entry = _resolve_repository_entry(selector, "alice")
    finally:
        output.set_json(False)
    assert entry["account"]["account_ref"] == "org-foreign"
    assert fake.calls == [("/repositories/resolve", {"selector": selector})]
    assert messages[0]["event"] == "cross_account_resource"
    assert messages[0]["selected_account_ref"] == "personal-alice"
    assert messages[0]["owner_account_ref"] == "org-foreign"
    assert cfg_mod.current_customer_id("alice") == "personal-alice"


def test_management_readable_name_cannot_cross_account(monkeypatch, tmp_path):
    from rvs.artifacts.commands import _resolve_repository_entry

    isolate(monkeypatch, tmp_path)
    fake = CrossAccountApi()
    monkeypatch.setattr(ApiClient, "from_profile", staticmethod(lambda profile=None: fake))
    with pytest.raises(SystemExit):
        _resolve_repository_entry("engineering/packages", "alice")
    assert fake.calls[0][1]["account_ref"] == "personal-alice"


def test_unauthorized_stable_reference_keeps_api_denial(monkeypatch, tmp_path):
    from rvs.client import ApiError

    isolate(monkeypatch, tmp_path)

    class DeniedApi:
        def get(self, path, params):
            raise ApiError(404, "Repository not found")

    monkeypatch.setattr(ApiClient, "from_profile", staticmethod(lambda profile=None: DeniedApi()))
    with pytest.raises(SystemExit):
        resolve_target("in_23456789/r_abcdefgh", profile="alice")
    assert cfg_mod.current_customer_id("alice") == "personal-alice"


@pytest.mark.parametrize("json_output", [False, True])
def test_cross_account_print_token_keeps_stdout_secret_only(monkeypatch, tmp_path, json_output):
    import json

    isolate(monkeypatch, tmp_path)
    fake = CrossAccountApi()
    monkeypatch.setattr(ApiClient, "from_profile", staticmethod(lambda profile=None: fake))
    args = ["art", "token", "mint", "--target", "in_23456789/r_abcdefgh"]
    if json_output:
        args.insert(0, "--json")
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    secret = "rvs_sltCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCA"
    if json_output:
        assert json.loads(result.stdout)["access_token"] == secret
    else:
        assert result.stdout == secret + "\n"
    assert "another account" in result.stderr
    assert secret not in result.stderr
    assert cfg_mod.current_customer_id("alice") == "personal-alice"


def test_cross_account_issuance_denial_does_not_fallback_or_switch(monkeypatch, tmp_path):
    from rvs.artifacts.targets import registry_context
    from rvs.client import ApiError

    isolate(monkeypatch, tmp_path)

    class DeniedIssuance(CrossAccountApi):
        def issue_native(self, path, payload):
            self.calls.append((path, payload))
            raise ApiError(403, "Source grants do not allow the target")

    fake = DeniedIssuance()
    monkeypatch.setattr(ApiClient, "from_profile", staticmethod(lambda profile=None: fake))
    with pytest.raises(SystemExit):
        registry_context(kind="pypi", target="in_23456789/r_abcdefgh", profile="alice")
    assert [path for path, _ in fake.calls] == ["/repositories/resolve", "/package-credentials"]
    assert cfg_mod.current_customer_id("alice") == "personal-alice"
