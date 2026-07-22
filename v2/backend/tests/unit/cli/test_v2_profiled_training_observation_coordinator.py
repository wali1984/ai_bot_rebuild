from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from v2.backend.app.cli import v2_profiled_training_observation_coordinator as cli
from v2.backend.app.services.native_trainer import (
    profiled_training_observation_coordinator_runtime_credentials_v1 as credential_module,
)
from v2.backend.app.services.native_trainer import (
    profiled_training_observation_coordinator_state_v1 as state_module,
)
from v2.backend.app.services.native_trainer import (
    profiled_training_observation_coordinator_v1 as coordinator_module,
)


def _local_credentials() -> (
    credential_module.ProfiledObservationCoordinatorLocalRoleCredentialsV1
):
    return credential_module.ProfiledObservationCoordinatorLocalRoleCredentialsV1(
        state_hmac_key=b"state-role-key-material-0000000000001",
        manifest_hmac_key=b"manifest-role-key-material-000000002",
        head_hmac_key=b"head-role-key-material-000000000003",
        epoch_hmac_key=b"epoch-role-key-material-00000000004",
    )


def _credentials(
    *,
    external: (
        credential_module.ProfiledObservationCoordinatorExternalWitnessCredentialsV1
        | None
    ) = None,
) -> credential_module.ProfiledObservationCoordinatorRuntimeCredentialsV1:
    return credential_module.ProfiledObservationCoordinatorRuntimeCredentialsV1(
        local_roles=_local_credentials(),
        external_witness=external,
    )


def _waiting_result() -> coordinator_module.ProfiledTrainingObservationCoordinatorResultV1:
    return coordinator_module.ProfiledTrainingObservationCoordinatorResultV1(
        schema_version=(
            coordinator_module.PROFILED_TRAINING_OBSERVATION_COORDINATOR_V1_SCHEMA_VERSION
        ),
        classification=coordinator_module.PROFILED_COORDINATOR_WAITING_EXTERNAL_WITNESS,
        cycle_id="a" * 64,
        publisher_status_sha256="b" * 64,
        observation_time="2026-07-22T12:00:00.000000Z",
        phase=state_module.PROFILED_OBSERVATION_COORDINATOR_HEAD_STAGED,
        transition_sequence=3,
        state_transitions_committed=3,
        publisher_status_read_this_invocation=True,
        new_cycle_started_this_invocation=True,
        witness_runtime_configured=False,
        witness_operations_recovered=0,
        witness_network_append_attempts=0,
        page_receipts_staged_this_invocation=0,
        manifest_id="c" * 64,
        total_profiled_samples=1,
        admitted_example_count=1,
        label_unavailable_count=0,
        head_revision=1,
        signed_head_durably_anchored=False,
        full_consumption_locally_verified=False,
        complete_state_chain_verified=True,
        external_monotonic_manifest_head_verified=False,
        full_consumption_external_ack_verified=False,
        optimizer_admission_authorized=False,
        checkpoint_write_authorized=False,
        model_write_authorized=False,
        prediction_authorized=False,
        paper_trading_authorized=False,
        live_execution_authorized=False,
        order_submission_authorized=False,
        execution_authorized=False,
        runtime_wired=False,
        _construction_token=coordinator_module._RESULT_TOKEN,  # noqa: SLF001
    )


def _args(tmp_path: Path, **overrides: Any) -> SimpleNamespace:
    values = {
        "runtime_root": (tmp_path / "runtime").absolute(),
        "publisher_status_path": (tmp_path / "publisher-status.json").absolute(),
        "feature_ledger_path": (tmp_path / "feature-ledger.sqlite3").absolute(),
        "label_archive_path": (tmp_path / "labels.sqlite3").absolute(),
        "trusted_cost_store_root": (tmp_path / "cost-cas").absolute(),
        "namespace": cli.DEFAULT_NAMESPACE,
        "consumer_lane": cli.DEFAULT_CONSUMER_LANE,
        "state_auth_key_id": cli.DEFAULT_STATE_AUTH_KEY_ID,
        "manifest_auth_key_id": cli.DEFAULT_MANIFEST_AUTH_KEY_ID,
        "head_auth_key_id": cli.DEFAULT_HEAD_AUTH_KEY_ID,
        "epoch_auth_key_id": cli.DEFAULT_EPOCH_AUTH_KEY_ID,
        "page_size": 16,
        "cycle_seconds": 1.0,
        "once": True,
        **overrides,
    }
    return SimpleNamespace(**values)


def test_parser_defaults_are_absolute_and_resource_only() -> None:
    args = cli.build_parser().parse_args([])

    assert args.runtime_root.is_absolute()
    assert args.publisher_status_path.is_absolute()
    assert args.feature_ledger_path.is_absolute()
    assert args.label_archive_path.is_absolute()
    assert args.trusted_cost_store_root.is_absolute()
    assert 0 < args.page_size <= cli.MAX_PROFILED_OBSERVATION_PAGE_ROWS
    assert args.cycle_seconds > 0


@pytest.mark.parametrize("value", ["0", "4097", "nan", "1.5"])
def test_page_size_rejects_out_of_contract_values(value: str) -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--page-size", value])


def test_status_is_canonical_self_hashed_and_preserves_all_false_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "_canonical_clock", lambda: "2026-07-22T13:00:00.000000Z")
    status_path = (tmp_path / "runtime" / "status.json").absolute()
    payload = cli._status_payload(_waiting_result(), status_path=status_path)  # noqa: SLF001
    unsigned = {name: value for name, value in payload.items() if name != "status_sha256"}

    assert payload["status_sha256"] == hashlib.sha256(
        cli._canonical_bytes(unsigned)  # noqa: SLF001
    ).hexdigest()
    assert payload["local_status_integrity_only"] is True
    for name in (
        "external_monotonic_manifest_head_verified",
        "full_consumption_external_ack_verified",
        "optimizer_admission_authorized",
        "checkpoint_write_authorized",
        "model_write_authorized",
        "prediction_authorized",
        "paper_trading_authorized",
        "live_execution_authorized",
        "order_submission_authorized",
        "execution_authorized",
        "runtime_wired",
    ):
        assert payload[name] is False


def test_atomic_status_write_is_framed_private_and_readback_exact(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    root.mkdir(mode=0o700)
    path = root / "status.json"
    payload = {"a": 1, "b": False}

    cli._atomic_write_status(path, payload)  # noqa: SLF001

    expected = cli._canonical_bytes(payload) + b"\n"  # noqa: SLF001
    assert path.read_bytes() == expected
    metadata = path.stat()
    assert stat.S_IMODE(metadata.st_mode) == 0o600
    assert metadata.st_nlink == 1


def test_atomic_status_write_rejects_destination_symlink(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    root.mkdir(mode=0o700)
    target = root / "target"
    target.write_text("untouched", encoding="utf-8")
    path = root / "status.json"
    path.symlink_to(target)

    with pytest.raises(
        cli.ProfiledObservationCoordinatorCliError,
        match="PROFILED_COORDINATOR_CLI_STATUS_SYMLINK_FORBIDDEN",
    ):
        cli._atomic_write_status(path, {"safe": True})  # noqa: SLF001
    assert target.read_text(encoding="utf-8") == "untouched"


def test_build_runtime_without_witness_creates_no_witness_state(tmp_path: Path) -> None:
    args = _args(tmp_path)

    runtime, status_path = cli._build_runtime(  # noqa: SLF001
        args=args,
        credentials=_credentials(),
    )
    try:
        assert type(runtime.coordinator) is (
            coordinator_module.ProfiledTrainingObservationCoordinatorV1
        )
        assert runtime.witness_client is None
        assert status_path == args.runtime_root / "coordinator_status_v1.json"
        assert not (args.runtime_root / "witness").exists()
        assert not (args.runtime_root / "witness-cas").exists()
    finally:
        runtime.close()


def test_build_runtime_with_witness_restores_journal_without_network(
    tmp_path: Path,
) -> None:
    public_key = bytes(range(32))
    external = (
        credential_module.ProfiledObservationCoordinatorExternalWitnessCredentialsV1(
            base_url="https://witness.example.test/v1",
            witness_id="independent-witness-v1",
            expected_public_key_sha256=hashlib.sha256(public_key).hexdigest(),
            timeout_seconds=1.0,
            bearer_token="independent-witness-test-bearer",  # noqa: S106
            public_key_bytes=public_key,
        )
    )

    runtime, _status_path = cli._build_runtime(  # noqa: SLF001
        args=_args(tmp_path),
        credentials=_credentials(external=external),
    )
    try:
        assert runtime.witness_client is not None
        assert (tmp_path / "runtime/witness/journal.sqlite3").is_file()
        assert (tmp_path / "runtime/witness-cas").is_dir()
    finally:
        runtime.close()


def test_run_once_writes_full_status_and_bounded_summary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "runtime"
    root.mkdir(mode=0o700)
    path = root / "status.json"
    calls = 0

    class FakeCoordinator:
        def run_once(self) -> Any:
            nonlocal calls
            calls += 1
            return _waiting_result()

    runtime = cli._CoordinatorRuntime(FakeCoordinator(), None)  # type: ignore[arg-type]  # noqa: SLF001
    assert cli._run_loop(  # noqa: SLF001
        args=SimpleNamespace(once=True, cycle_seconds=1.0),
        runtime=runtime,
        status_path=path,
    ) == 0

    summary = json.loads(capsys.readouterr().out)
    full = json.loads(path.read_text(encoding="ascii"))
    assert calls == 1
    assert summary["schema_version"] == cli.CLI_SUMMARY_SCHEMA_VERSION
    assert summary["classification"] == (
        coordinator_module.PROFILED_COORDINATOR_WAITING_EXTERNAL_WITNESS
    )
    assert full["schema_version"] == cli.CLI_STATUS_SCHEMA_VERSION
    assert full["optimizer_admission_authorized"] is False


def test_main_configuration_failure_is_observable_without_secret_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "must-never-appear"  # noqa: S105

    def fail_credentials() -> Any:
        raise credential_module.ProfiledObservationCoordinatorCredentialError(
            "PROFILED_COORDINATOR_TEST_CONFIGURATION_INVALID"
        ) from RuntimeError(secret)

    monkeypatch.setattr(
        cli,
        "load_profiled_observation_coordinator_runtime_credentials_v1",
        fail_credentials,
    )
    runtime_root = (tmp_path / "runtime").absolute()

    assert cli.main(["--runtime-root", str(runtime_root), "--once"]) == 78
    captured = capsys.readouterr()
    assert secret not in captured.err
    payload = json.loads(captured.err)
    assert payload["classification"] == "FAIL_CLOSED"
    assert payload["optimizer_admission_authorized"] is False
    persisted = json.loads(
        (runtime_root / "coordinator_status_v1.json").read_text(encoding="ascii")
    )
    assert persisted == payload


def test_relative_runtime_root_fails_as_configuration_not_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["--runtime-root", "relative", "--once"]) == 78
    payload = json.loads(capsys.readouterr().err)
    assert payload["reason"] == "PROFILED_COORDINATOR_CLI_RUNTIME_ROOT_INVALID"
    assert payload["runtime_wired"] is False


def test_no_exchange_or_generic_secret_environment_names_are_consumed() -> None:
    source = Path(cli.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "BINANCE_API_KEY",
        "BINANCE_API_SECRET",
        "COINAPI_KEY",
        "MORALIS_API_KEY",
        "EnvironmentFile",
    ):
        assert forbidden not in source
    assert "leverage_mutated" not in source
    assert "margin_mutated" not in source
    assert "order_submitted" not in source
    assert os.environ.get("LIVE_GATE", "blocked_human_only") is not None


def test_tracked_unit_is_hardened_bounded_and_has_no_downstream_transition() -> None:
    repo_root = Path(__file__).resolve().parents[5]
    unit = (
        repo_root
        / "claude_worklog/systemd/user/"
        "ai-bot-v2-profiled-training-observation-coordinator.service"
    ).read_text(encoding="utf-8")

    assert unit.count("LoadCredential=") == 4
    for name in (
        credential_module.STATE_HMAC_SYSTEMD_CREDENTIAL,
        credential_module.MANIFEST_HMAC_SYSTEMD_CREDENTIAL,
        credential_module.HEAD_HMAC_SYSTEMD_CREDENTIAL,
        credential_module.EPOCH_HMAC_SYSTEMD_CREDENTIAL,
    ):
        assert f"LoadCredential={name}:" in unit
    for forbidden in (
        credential_module.WITNESS_BEARER_SYSTEMD_CREDENTIAL,
        credential_module.WITNESS_PUBLIC_KEY_SYSTEMD_CREDENTIAL,
        "EnvironmentFile=",
        "ImportCredential=",
        "BINANCE_API_KEY",
        "BINANCE_API_SECRET",
        "ExecStartPost=",
        "OnSuccess=",
        "PartOf=ai-bot-v2-native-cuda-trainer",
        "Wants=ai-bot-v2-native-cuda-trainer",
        "Requires=ai-bot-v2-native-cuda-trainer",
        "trade-management-paper-loop",
    ):
        assert forbidden not in unit
    assert unit.count("ExecStart=") == 1
    assert "Type=simple" in unit
    assert "Restart=on-failure" in unit
    assert "RestartPreventExitStatus=2 78" in unit
    assert "LIVE_GATE=blocked_human_only" in unit
    assert "ProtectSystem=strict" in unit
    assert "ProtectHome=read-only" in unit
    assert "NoNewPrivileges=true" in unit
    assert "CapabilityBoundingSet=\n" in unit
    assert "MemoryMax=4G" in unit
    assert "CPUQuota=100%" in unit
    assert (
        "ReadWritePaths=/home/wali/ai_bot_local_data/v2_native_trainer/"
        "profiled_training_observation_coordinator_v1" in unit
    )
    assert (
        "-m v2.backend.app.cli.v2_profiled_training_observation_coordinator"
        in unit
    )


def test_external_witness_dropin_is_complete_template_not_active_base_config() -> None:
    repo_root = Path(__file__).resolve().parents[5]
    dropin = (
        repo_root
        / "claude_worklog/systemd/user/"
        "ai-bot-v2-profiled-training-observation-coordinator.service.d/"
        "80-external-witness.conf.example"
    ).read_text(encoding="utf-8")

    assert dropin.count("LoadCredential=") == 2
    assert credential_module.WITNESS_BEARER_SYSTEMD_CREDENTIAL in dropin
    assert credential_module.WITNESS_PUBLIC_KEY_SYSTEMD_CREDENTIAL in dropin
    for name in (
        credential_module.WITNESS_BASE_URL_ENV,
        credential_module.WITNESS_ID_ENV,
        credential_module.WITNESS_PUBLIC_KEY_SHA256_ENV,
        credential_module.WITNESS_TIMEOUT_SECONDS_ENV,
    ):
        assert f"Environment={name}=" in dropin
    assert "PRIVATE_KEY" not in dropin
    assert "http://" not in dropin
    assert "same-host signer does not satisfy" in dropin


def test_credential_contract_matches_unit_and_preserves_authority_boundary() -> None:
    repo_root = Path(__file__).resolve().parents[5]
    contract = (
        repo_root
        / "claude_worklog/systemd/user/"
        "ai-bot-v2-profiled-training-observation-coordinator.credentials.md"
    ).read_text(encoding="utf-8")
    unit = (
        repo_root
        / "claude_worklog/systemd/user/"
        "ai-bot-v2-profiled-training-observation-coordinator.service"
    ).read_text(encoding="utf-8")

    for name in (
        credential_module.STATE_HMAC_SYSTEMD_CREDENTIAL,
        credential_module.MANIFEST_HMAC_SYSTEMD_CREDENTIAL,
        credential_module.HEAD_HMAC_SYSTEMD_CREDENTIAL,
        credential_module.EPOCH_HMAC_SYSTEMD_CREDENTIAL,
    ):
        assert name in contract
        assert name in unit
    assert "raw 32-byte" in contract
    assert "same-host" in contract
    assert "local-integrity-only" in contract
    assert "optimizer step" in contract
    assert "all false" in contract


def test_immutable_dropin_pins_one_exact_committed_release() -> None:
    repo_root = Path(__file__).resolve().parents[5]
    dropin = (
        repo_root
        / "claude_worklog/systemd/user/"
        "ai-bot-v2-profiled-training-observation-coordinator.service.d/"
        "90-immutable-release.conf"
    ).read_text(encoding="utf-8")
    release_sha = "0936557c844b6c9f27f4e080a6040e2b0358c061"
    release_root = (
        "/home/wali/ai_bot_local_data/deployments/ai_bot_rebuild/" + release_sha
    )

    assert dropin.count(release_sha) >= 8
    assert f'Environment="AI_BOT_CODE_SHA={release_sha}"' in dropin
    assert f"WorkingDirectory={release_root}" in dropin
    assert f"ReadOnlyPaths={release_root}" in dropin
    assert f"/usr/bin/git -C {release_root} diff --quiet --exit-code {release_sha} --" in dropin
    assert (
        f"ExecStart={release_root}/.venv/bin/python3 -B -m "
        "v2.backend.app.cli.v2_profiled_training_observation_coordinator"
        in dropin
    )
    assert dropin.count("ExecStart=\n") == 1
    assert dropin.count("ExecStartPre=\n") == 1
    assert "Desktop/AI BOT REBUILD/.venv" not in dropin
