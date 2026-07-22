from __future__ import annotations

import json
import os
import re
import stat
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from v2.backend.app.cli import v2_profiled_base_feature_publisher as cli
from v2.backend.app.services.native_trainer import (
    profiled_base_publisher_runtime_credentials as credentials,
)

API_KEY = "publisher-test-account-specific-key"
API_SECRET = "publisher-test-account-specific-secret"  # noqa: S105
FINGERPRINT_HMAC = "publisher-test-independent-fingerprint-hmac-key-32-bytes"
_production_expected_credentials_directory = credentials._expected_credentials_directory  # noqa: SLF001


def _write_credential(directory: Path, name: str, value: str) -> None:
    original_mode = stat.S_IMODE(directory.stat().st_mode)
    directory.chmod(0o700)
    try:
        path = directory / name
        if path.exists():
            path.chmod(0o600)
        path.write_text(f"{value}\n", encoding="utf-8")
        path.chmod(0o400)
    finally:
        directory.chmod(original_mode)


def _write_runtime_credentials(directory: Path) -> None:
    _write_credential(directory, credentials.API_KEY_SYSTEMD_CREDENTIAL, API_KEY)
    _write_credential(directory, credentials.API_SECRET_SYSTEMD_CREDENTIAL, API_SECRET)
    _write_credential(
        directory,
        credentials.FINGERPRINT_HMAC_SYSTEMD_CREDENTIAL,
        FINGERPRINT_HMAC,
    )
    directory.chmod(0o500)


@contextmanager
def _writable_directory(directory: Path):  # type: ignore[no-untyped-def]
    original_mode = stat.S_IMODE(directory.stat().st_mode)
    directory.chmod(0o700)
    try:
        yield
    finally:
        directory.chmod(original_mode)


@pytest.fixture(autouse=True)
def _bind_test_credentials_directory_and_restore_permissions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):  # type: ignore[no-untyped-def]
    """Use a fixture path while production remains fixed to systemd's mount."""

    monkeypatch.setattr(credentials, "_expected_credentials_directory", lambda: tmp_path)
    yield
    if not tmp_path.exists():
        return
    for current, directories, files in os.walk(tmp_path, topdown=True):
        current_path = Path(current)
        current_path.chmod(0o700)
        for directory in directories:
            path = current_path / directory
            if not path.is_symlink():
                path.chmod(0o700)
        for filename in files:
            path = current_path / filename
            if not path.is_symlink():
                path.chmod(0o600)


def _runtime_environment(directory: Path, **overrides: str) -> dict[str, str]:
    return {
        credentials.SYSTEMD_CREDENTIALS_DIRECTORY_ENV: str(directory),
        credentials.TRADER_ID_ENV: credentials.EXPECTED_TRADER_ID,
        credentials.CREDENTIAL_REF_ENV: credentials.EXPECTED_CREDENTIAL_REF,
        # Ambient generic values must be irrelevant to this exact binding.
        "BINANCE_API_KEY": "forbidden-generic-key",
        "BINANCE_API_SECRET": "forbidden-generic-secret",
        **overrides,
    }


def test_exact_systemd_binding_ignores_generic_environment_and_hides_secrets(
    tmp_path: Path,
) -> None:
    _write_runtime_credentials(tmp_path)

    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o500
    for name in (
        credentials.API_KEY_SYSTEMD_CREDENTIAL,
        credentials.API_SECRET_SYSTEMD_CREDENTIAL,
        credentials.FINGERPRINT_HMAC_SYSTEMD_CREDENTIAL,
    ):
        metadata = (tmp_path / name).stat()
        assert metadata.st_uid == os.geteuid()
        assert stat.S_IMODE(metadata.st_mode) == 0o400
        assert metadata.st_nlink == 1

    loaded = credentials.load_profiled_base_publisher_runtime_credentials(
        environ=_runtime_environment(tmp_path)
    )

    binding = loaded.commission_binding
    assert binding.trader_id == credentials.EXPECTED_TRADER_ID
    assert binding.credential_ref == credentials.EXPECTED_CREDENTIAL_REF
    assert binding.api_key_name == credentials.API_KEY_SYSTEMD_CREDENTIAL
    assert binding.api_secret_name == credentials.API_SECRET_SYSTEMD_CREDENTIAL
    assert binding.account_specific is True
    assert binding.read_only_ref is True
    assert binding.is_configured is True
    assert binding.api_key == API_KEY
    assert binding.api_secret == API_SECRET
    assert loaded.fingerprint_hmac_key == FINGERPRINT_HMAC.encode()
    rendered = repr(loaded) + repr(binding)
    assert API_KEY not in rendered
    assert API_SECRET not in rendered
    assert FINGERPRINT_HMAC not in rendered
    assert "forbidden-generic" not in rendered


def test_optional_loader_returns_complete_bundle_without_weakening_validation(
    tmp_path: Path,
) -> None:
    _write_runtime_credentials(tmp_path)

    loaded = (
        credentials.load_profiled_base_publisher_runtime_credentials_if_available(
            environ=_runtime_environment(tmp_path)
        )
    )

    assert loaded is not None
    assert loaded.commission_binding.api_key == API_KEY
    assert loaded.commission_binding.api_secret == API_SECRET
    assert loaded.fingerprint_hmac_key == FINGERPRINT_HMAC.encode()


def test_optional_loader_accepts_only_absent_final_systemd_directory(
    tmp_path: Path,
) -> None:
    tmp_path.rmdir()

    loaded = (
        credentials.load_profiled_base_publisher_runtime_credentials_if_available(
            environ=_runtime_environment(tmp_path)
        )
    )

    assert loaded is None


def test_optional_loader_rejects_partial_existing_bundle(tmp_path: Path) -> None:
    _write_credential(
        tmp_path,
        credentials.API_KEY_SYSTEMD_CREDENTIAL,
        API_KEY,
    )
    tmp_path.chmod(0o500)

    with pytest.raises(
        credentials.ProfiledBasePublisherCredentialError,
        match="PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIAL_UNAVAILABLE_.*API_SECRET",
    ):
        credentials.load_profiled_base_publisher_runtime_credentials_if_available(
            environ=_runtime_environment(tmp_path)
        )


def test_production_credentials_directory_is_fixed_to_exact_user_unit_path() -> None:
    assert _production_expected_credentials_directory() == Path(
        f"/run/user/{os.geteuid()}/credentials/"
        "ai-bot-v2-profiled-base-feature-publisher.service"
    )


def test_arbitrary_compatible_directory_fails_exact_path_binding_before_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_runtime_credentials(tmp_path)
    monkeypatch.setattr(
        credentials,
        "_expected_credentials_directory",
        lambda: tmp_path.parent / "different-systemd-unit.service",
    )
    open_called = False

    def forbidden_open(_directory: Path) -> int:
        nonlocal open_called
        open_called = True
        raise AssertionError("path mismatch must fail before opening credential material")

    monkeypatch.setattr(credentials, "_open_credentials_directory", forbidden_open)
    with pytest.raises(
        credentials.ProfiledBasePublisherCredentialError,
        match="PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIALS_DIRECTORY_BINDING_INVALID",
    ):
        credentials.load_profiled_base_publisher_runtime_credentials_if_available(
            environ=_runtime_environment(tmp_path)
        )
    assert open_called is False


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        (
            {credentials.TRADER_ID_ENV: "trader-other"},
            "PROFILED_BASE_PUBLISHER_TRADER_ID_BINDING_INVALID",
        ),
        (
            {credentials.CREDENTIAL_REF_ENV: "BINANCE_READONLY"},
            "PROFILED_BASE_PUBLISHER_CREDENTIAL_REF_BINDING_INVALID",
        ),
    ],
)
def test_public_binding_drift_fails_before_secret_read(
    tmp_path: Path,
    overrides: dict[str, str],
    expected: str,
) -> None:
    _write_runtime_credentials(tmp_path)

    with pytest.raises(credentials.ProfiledBasePublisherCredentialError, match=expected):
        credentials.load_profiled_base_publisher_runtime_credentials(
            environ=_runtime_environment(tmp_path, **overrides)
        )


@pytest.mark.parametrize(
    ("missing_name", "expected"),
    [
        (
            credentials.TRADER_ID_ENV,
            "PROFILED_BASE_PUBLISHER_TRADER_ID_BINDING_INVALID",
        ),
        (
            credentials.CREDENTIAL_REF_ENV,
            "PROFILED_BASE_PUBLISHER_CREDENTIAL_REF_BINDING_INVALID",
        ),
    ],
)
def test_missing_public_binding_fails_instead_of_defaulting(
    tmp_path: Path,
    missing_name: str,
    expected: str,
) -> None:
    _write_runtime_credentials(tmp_path)
    environment = _runtime_environment(tmp_path)
    environment.pop(missing_name)

    with pytest.raises(credentials.ProfiledBasePublisherCredentialError, match=expected):
        credentials.load_profiled_base_publisher_runtime_credentials(
            environ=environment
        )


def test_missing_exact_credential_never_falls_back_to_generic_environment(
    tmp_path: Path,
) -> None:
    _write_runtime_credentials(tmp_path)
    with _writable_directory(tmp_path):
        (tmp_path / credentials.API_KEY_SYSTEMD_CREDENTIAL).unlink()

    with pytest.raises(
        credentials.ProfiledBasePublisherCredentialError,
        match=(
            "PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIAL_UNAVAILABLE_"
            "ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY_API_KEY"
        ),
    ):
        credentials.load_profiled_base_publisher_runtime_credentials(
            environ=_runtime_environment(tmp_path)
        )


def test_symlinked_directory_and_credential_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credential_directory = tmp_path / "credentials"
    credential_directory.mkdir()
    _write_runtime_credentials(credential_directory)
    directory_link = tmp_path / "credential-link"
    directory_link.symlink_to(credential_directory, target_is_directory=True)
    monkeypatch.setattr(
        credentials,
        "_expected_credentials_directory",
        lambda: directory_link,
    )

    with pytest.raises(
        credentials.ProfiledBasePublisherCredentialError,
        match="PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIALS_DIRECTORY_INVALID",
    ):
        credentials.load_profiled_base_publisher_runtime_credentials(
            environ=_runtime_environment(directory_link)
        )

    api_key_path = credential_directory / credentials.API_KEY_SYSTEMD_CREDENTIAL
    api_key_target = tmp_path / "api-key-target"
    api_key_target.write_text(API_KEY, encoding="utf-8")
    with _writable_directory(credential_directory):
        api_key_path.unlink()
        api_key_path.symlink_to(api_key_target)
    monkeypatch.setattr(
        credentials,
        "_expected_credentials_directory",
        lambda: credential_directory,
    )
    with pytest.raises(
        credentials.ProfiledBasePublisherCredentialError,
        match="PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIAL_UNAVAILABLE_.*API_KEY",
    ):
        credentials.load_profiled_base_publisher_runtime_credentials(
            environ=_runtime_environment(credential_directory)
        )


def test_fifo_credential_fails_without_blocking(tmp_path: Path) -> None:
    _write_runtime_credentials(tmp_path)
    api_key_path = tmp_path / credentials.API_KEY_SYSTEMD_CREDENTIAL
    with _writable_directory(tmp_path):
        api_key_path.unlink()
        os.mkfifo(api_key_path, mode=0o400)

    with pytest.raises(
        credentials.ProfiledBasePublisherCredentialError,
        match="PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIAL_NOT_REGULAR_.*API_KEY",
    ):
        credentials.load_profiled_base_publisher_runtime_credentials(
            environ=_runtime_environment(tmp_path)
        )


@pytest.mark.parametrize("mode", [0o700, 0o540, 0o504])
def test_writable_group_or_world_accessible_credential_directory_is_rejected(
    tmp_path: Path,
    mode: int,
) -> None:
    _write_runtime_credentials(tmp_path)
    tmp_path.chmod(mode)

    with pytest.raises(
        credentials.ProfiledBasePublisherCredentialError,
        match="PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIALS_DIRECTORY_PERMISSIONS_INVALID",
    ):
        credentials.load_profiled_base_publisher_runtime_credentials(
            environ=_runtime_environment(tmp_path)
        )


def test_foreign_owned_credential_directory_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_runtime_credentials(tmp_path)
    original_fstat = credentials.os.fstat

    def foreign_directory_owner(descriptor: int):  # type: ignore[no-untyped-def]
        metadata = original_fstat(descriptor)
        if stat.S_ISDIR(metadata.st_mode):
            return SimpleNamespace(
                st_mode=metadata.st_mode,
                st_uid=os.geteuid() + 1,
                st_nlink=metadata.st_nlink,
            )
        return metadata

    monkeypatch.setattr(credentials.os, "fstat", foreign_directory_owner)
    with pytest.raises(
        credentials.ProfiledBasePublisherCredentialError,
        match="PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIALS_DIRECTORY_OWNER_INVALID",
    ):
        credentials.load_profiled_base_publisher_runtime_credentials(
            environ=_runtime_environment(tmp_path)
        )


def test_credential_directory_with_non_systemd_link_count_is_rejected(
    tmp_path: Path,
) -> None:
    _write_runtime_credentials(tmp_path)
    with _writable_directory(tmp_path):
        (tmp_path / "unexpected-subdirectory").mkdir()

    with pytest.raises(
        credentials.ProfiledBasePublisherCredentialError,
        match="PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIALS_DIRECTORY_LINK_COUNT_INVALID",
    ):
        credentials.load_profiled_base_publisher_runtime_credentials(
            environ=_runtime_environment(tmp_path)
        )


@pytest.mark.parametrize("mode", [0o600, 0o440, 0o404])
def test_writable_group_or_world_readable_credential_file_is_rejected(
    tmp_path: Path,
    mode: int,
) -> None:
    _write_runtime_credentials(tmp_path)
    (tmp_path / credentials.API_KEY_SYSTEMD_CREDENTIAL).chmod(mode)

    with pytest.raises(
        credentials.ProfiledBasePublisherCredentialError,
        match="PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIAL_PERMISSIONS_INVALID_.*API_KEY",
    ):
        credentials.load_profiled_base_publisher_runtime_credentials(
            environ=_runtime_environment(tmp_path)
        )


def test_foreign_owned_credential_file_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_runtime_credentials(tmp_path)
    original_fstat = credentials.os.fstat

    def foreign_file_owner(descriptor: int):  # type: ignore[no-untyped-def]
        metadata = original_fstat(descriptor)
        if stat.S_ISREG(metadata.st_mode):
            return SimpleNamespace(
                st_mode=metadata.st_mode,
                st_uid=os.geteuid() + 1,
                st_nlink=metadata.st_nlink,
            )
        return metadata

    monkeypatch.setattr(credentials.os, "fstat", foreign_file_owner)
    with pytest.raises(
        credentials.ProfiledBasePublisherCredentialError,
        match="PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIAL_OWNER_INVALID_.*API_KEY",
    ):
        credentials.load_profiled_base_publisher_runtime_credentials(
            environ=_runtime_environment(tmp_path)
        )


def test_hard_linked_credential_file_is_rejected(tmp_path: Path) -> None:
    _write_runtime_credentials(tmp_path)
    api_key_path = tmp_path / credentials.API_KEY_SYSTEMD_CREDENTIAL
    with _writable_directory(tmp_path):
        os.link(api_key_path, tmp_path / "credential-hard-link")

    with pytest.raises(
        credentials.ProfiledBasePublisherCredentialError,
        match="PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIAL_LINK_COUNT_INVALID_.*API_KEY",
    ):
        credentials.load_profiled_base_publisher_runtime_credentials(
            environ=_runtime_environment(tmp_path)
        )


@pytest.mark.parametrize(
    ("credential_name", "value", "expected"),
    [
        (
            credentials.FINGERPRINT_HMAC_SYSTEMD_CREDENTIAL,
            "too-short",
            "PROFILED_BASE_PUBLISHER_COMMISSION_FINGERPRINT_HMAC_SECRET_INVALID",
        ),
        (
            credentials.FINGERPRINT_HMAC_SYSTEMD_CREDENTIAL,
            API_KEY,
            "PROFILED_BASE_PUBLISHER_FINGERPRINT_HMAC_MUST_DIFFER_FROM_API_KEY",
        ),
        (
            credentials.FINGERPRINT_HMAC_SYSTEMD_CREDENTIAL,
            API_SECRET,
            "PROFILED_BASE_PUBLISHER_FINGERPRINT_HMAC_MUST_DIFFER_FROM_API_SECRET",
        ),
        (
            credentials.API_KEY_SYSTEMD_CREDENTIAL,
            "first-line\nsecond-line",
            "PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIAL_NOT_SINGLE_LINE_.*API_KEY",
        ),
        (
            credentials.API_SECRET_SYSTEMD_CREDENTIAL,
            "x" * (credentials.MAX_SYSTEMD_CREDENTIAL_BYTES + 1),
            "PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIAL_TOO_LARGE_.*API_SECRET",
        ),
    ],
)
def test_invalid_or_reused_secret_fails_closed_without_rendering_value(
    tmp_path: Path,
    credential_name: str,
    value: str,
    expected: str,
) -> None:
    _write_runtime_credentials(tmp_path)
    _write_credential(tmp_path, credential_name, value)

    with pytest.raises(credentials.ProfiledBasePublisherCredentialError, match=expected) as exc:
        credentials.load_profiled_base_publisher_runtime_credentials_if_available(
            environ=_runtime_environment(tmp_path)
        )
    assert value not in str(exc.value)


def test_cli_injects_protected_binding_and_never_uses_secret_argv_or_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_runtime_credentials(tmp_path)
    monkeypatch.setenv(credentials.SYSTEMD_CREDENTIALS_DIRECTORY_ENV, str(tmp_path))
    monkeypatch.setenv(credentials.TRADER_ID_ENV, credentials.EXPECTED_TRADER_ID)
    monkeypatch.setenv(credentials.CREDENTIAL_REF_ENV, credentials.EXPECTED_CREDENTIAL_REF)
    monkeypatch.setenv("BINANCE_API_KEY", "forbidden-generic-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "forbidden-generic-secret")
    monkeypatch.setattr(cli, "_raw_redis_client", lambda _url: object())
    observed: dict[str, Any] = {}

    class FakePublisher:
        def __init__(self, **kwargs: Any) -> None:
            observed.update(kwargs)
            self.status_path = tmp_path / "status.json"

        def run_cycle(self) -> dict[str, Any]:
            return {
                "classification": "NO_ELIGIBLE_SOURCE_WINDOWS",
                "authority_semantics": {},
            }

    monkeypatch.setattr(cli, "ProfiledBaseFeaturePublisherV1", FakePublisher)
    monkeypatch.setattr(cli, "_STOP", False)

    assert cli.main(["--once"]) == 0
    capture_factory = observed["commission_capture_function"]
    assert capture_factory.func is cli.capture_binance_usdm_commission_rate_v1
    binding = capture_factory.keywords["credential_binding"]
    assert binding.api_key == API_KEY
    assert binding.api_secret == API_SECRET
    assert observed["commission_fingerprint_hmac_key"] == FINGERPRINT_HMAC.encode()
    rendered = capsys.readouterr().out
    summary = json.loads(rendered)
    assert summary["credential_ref_read_only_assertion"] is True
    assert (
        summary["credential_ref_read_only_assertion_semantics"]
        == "OPERATOR_PROVISIONING_LABEL_NOT_BINANCE_PERMISSION_PROOF"
    )
    assert summary["exchange_key_permissions_proven_by_connector"] is False
    for secret in (
        API_KEY,
        API_SECRET,
        FINGERPRINT_HMAC,
        "forbidden-generic-key",
        "forbidden-generic-secret",
    ):
        assert secret not in rendered
    parser_options = {
        option
        for action in cli.build_parser()._actions  # noqa: SLF001
        for option in action.option_strings
    }
    assert not any(
        "secret" in option.lower() or "hmac" in option.lower()
        for option in parser_options
    )


def test_cli_absent_imported_bundle_runs_masked_without_commission_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(credentials.TRADER_ID_ENV, credentials.EXPECTED_TRADER_ID)
    monkeypatch.setenv(credentials.CREDENTIAL_REF_ENV, credentials.EXPECTED_CREDENTIAL_REF)
    monkeypatch.setenv(credentials.SYSTEMD_CREDENTIALS_DIRECTORY_ENV, str(tmp_path))
    tmp_path.rmdir()
    redis_client = object()
    monkeypatch.setattr(cli, "_raw_redis_client", lambda _url: redis_client)
    observed: dict[str, Any] = {}

    class FakePublisher:
        def __init__(self, **kwargs: Any) -> None:
            observed.update(kwargs)
            self.status_path = Path("profiled-masked-status.json").absolute()

        def run_cycle(self) -> dict[str, Any]:
            return {
                "classification": "CYCLE_COMPLETE_MASKED_COST_OBSERVATIONS",
                "commission_cost_mode": cli.MASKED_COST_OBSERVATION_MODE,
                "commission_credentials_available": False,
                "masked_cost_observation_symbol_count": 1,
                "masked_cost_observation_replay_symbol_count": 0,
                "authority_semantics": {
                    "published_child_trainer_admission_authorized": False,
                },
            }

    monkeypatch.setattr(cli, "ProfiledBaseFeaturePublisherV1", FakePublisher)
    monkeypatch.setattr(cli, "_STOP", False)

    assert cli.main(["--once"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert observed["redis_client"] is redis_client
    assert observed["commission_cost_mode"] == cli.MASKED_COST_OBSERVATION_MODE
    assert "commission_capture_function" not in observed
    assert "commission_fingerprint_hmac_key" not in observed
    assert summary["commission_credentials_available"] is False
    assert summary["published_child_trainer_admission_authorized"] is False
    assert summary["masked_cost_observation_symbol_count"] == 1


def test_tracked_unit_is_protected_bounded_and_has_no_auto_transition() -> None:
    repo_root = Path(__file__).resolve().parents[6]
    unit = (
        repo_root
        / "claude_worklog/systemd/user/ai-bot-v2-profiled-base-feature-publisher.service"
    ).read_text(encoding="utf-8")

    assert "EnvironmentFile=" not in unit
    assert "BINANCE_API_KEY=" not in unit
    assert "BINANCE_API_SECRET=" not in unit
    assert "PROFILED_BASE_COMMISSION_FINGERPRINT_HMAC_SECRET=" not in unit
    assert "BINANCE_REST_FALLBACK_ALLOWED=true" not in unit
    assert f"ALPHAFORGE_INITIAL_TRADER_ID={credentials.EXPECTED_TRADER_ID}" in unit
    assert (
        f"ALPHAFORGE_INITIAL_TRADER_BINANCE_CREDENTIAL_REF="
        f"{credentials.EXPECTED_CREDENTIAL_REF}" in unit
    )
    for forbidden_name in (
        credentials.API_KEY_SYSTEMD_CREDENTIAL,
        credentials.API_SECRET_SYSTEMD_CREDENTIAL,
        credentials.FINGERPRINT_HMAC_SYSTEMD_CREDENTIAL,
    ):
        assert forbidden_name not in unit
    assert "ImportCredential=" not in unit
    assert unit.count("LoadCredential=") == 1
    assert (
        "LoadCredential=binance_bracket_evidence_hmac_key:"
        "%h/.config/ai-bot-v2/credentials/binance-bracket-evidence/evidence-hmac.cred"
        in unit
    )
    assert (
        "PROFILED_BASE_COMMISSION_BROKER_DATA_ROOT=/home/wali/ai_bot_local_data/"
        "v2_authenticated_evidence/binance_usdm_commission_broker_v1" in unit
    )
    assert (
        "ReadOnlyPaths=/home/wali/ai_bot_local_data/v2_authenticated_evidence/"
        "binance_usdm_commission_broker_v1" in unit
    )
    assert "BINANCE_USDM_REST_BASE_URL=https://fapi.binance.com" in unit
    assert "BINANCE_BRACKET_EVIDENCE_HMAC_KEY_ID=binance-bracket-evidence-v1" in unit
    assert (
        "Wants=network-online.target "
        "ai-bot-v2-binance-usdm-commission-evidence-broker.service" in unit
    )
    assert unit.count("ExecStart=") == 1
    assert "Type=simple" in unit
    assert "Restart=on-failure" in unit
    assert "RestartPreventExitStatus=2 78" in unit
    assert "StartLimitBurst=3" in unit
    assert "MemoryMax=4G" in unit
    assert "CPUQuota=200%" in unit
    assert "ProtectSystem=strict" in unit
    assert "ProtectHome=read-only" in unit
    assert "NoNewPrivileges=true" in unit
    assert "ReadWritePaths=/home/wali/ai_bot_local_data/v2_native_trainer" in unit
    assert "PROFILED_BASE_PUBLISHER_STATE_PATH=/home/wali/" in unit
    assert "PROFILED_BASE_PUBLISHER_STATUS_PATH=/home/wali/" in unit
    assert "PROFILED_BASE_FEATURE_LEDGER_PATH=/home/wali/" in unit
    assert "LIVE_GATE=blocked_human_only" in unit
    for forbidden in (
        "ExecStartPost=",
        "OnSuccess=",
        "PartOf=ai-bot-v2-native-cuda-trainer",
        "Wants=ai-bot-v2-native-cuda-trainer",
        "Requires=ai-bot-v2-native-cuda-trainer",
    ):
        assert forbidden not in unit


def test_documented_credential_contract_matches_unit_names() -> None:
    repo_root = Path(__file__).resolve().parents[6]
    contract = (
        repo_root
        / "claude_worklog/systemd/user/ai-bot-v2-profiled-base-feature-publisher.credentials.md"
    ).read_text(encoding="utf-8")

    for forbidden_name in (
        credentials.API_KEY_SYSTEMD_CREDENTIAL,
        credentials.API_SECRET_SYSTEMD_CREDENTIAL,
        credentials.FINGERPRINT_HMAC_SYSTEMD_CREDENTIAL,
    ):
        assert forbidden_name not in contract
    assert "binance_bracket_evidence_hmac_key" in contract
    assert "at least 32 UTF-8 bytes" in contract
    assert "GET /fapi/v1/commissionRate" in contract
    assert "host-shared Redis budget" in contract
    assert "no automatic downstream" in contract
    assert "no trainer admission" in contract
    assert "[1,1,1,1]" in contract
    assert "ImportCredential=" in contract
    assert "publisher unit contains zero" in contract
    assert "API-key, API-secret, commission-fingerprint-key" in contract


def test_publisher_immutable_dropin_uses_one_release_and_read_only_broker_root() -> None:
    repo_root = Path(__file__).resolve().parents[6]
    dropin = (
        repo_root
        / "claude_worklog/systemd/user/"
        "ai-bot-v2-profiled-base-feature-publisher.service.d/"
        "90-immutable-release.conf"
    ).read_text(encoding="utf-8")
    release_shas = set(
        re.findall(r"deployments/ai_bot_rebuild/([0-9a-f]{40})", dropin)
    )

    assert release_shas == {"85f3ae173fe42e5af20d1bc9cb16effe3d1e85fc"}
    assert "AI_BOT_CODE_SHA=85f3ae173fe42e5af20d1bc9cb16effe3d1e85fc" in dropin
    assert "diff --quiet --exit-code 85f3ae173fe42e5af20d1bc9cb16effe3d1e85fc --" in dropin
    assert (
        "ReadOnlyPaths=/home/wali/ai_bot_local_data/v2_authenticated_evidence/"
        "binance_usdm_commission_broker_v1" in dropin
    )
    assert "WorkingDirectory=/home/wali/Desktop/AI BOT REBUILD" not in dropin
