from __future__ import annotations

import re
import sys
import types
from pathlib import Path

import pytest

from v2.backend.app.cli import v2_native_cuda_trainer_persistent_loop as cli

WAITING_MODULE = "v2.backend.app.services.native_trainer.profiled_training_waiting_runtime_v1"
PUBLISHER_CREDENTIAL_MODULE = (
    "v2.backend.app.services.native_trainer."
    "authenticated_profiled_resident_runtime_credentials_v1"
)
PUBLISHER_SERVICE_MODULE = (
    "v2.backend.app.services.native_trainer.authenticated_profiled_resident_service_v1"
)
PUBLISHER_RUNTIME_MODULE = (
    "v2.backend.app.services.native_trainer.authenticated_profiled_resident_runtime_v1"
)
LEGACY_RUNTIME_MODULE = "v2.backend.app.services.native_trainer.persistent_cuda_trainer_runtime"
CANONICAL_COST_ROOT = (
    "/home/wali/ai_bot_local_data/v2_native_trainer/profiled_base_publisher_v1/"
    "profiled-training-enrichment-cas"
)
PUBLISHER_RELEASE_SHA = "4040411f147fda0de4b44f1996b3f997c52da56d"
PINNED_PYTHON = (
    "/home/wali/ai_bot_local_data/deployments/python_envs/"
    "6360ea33fcfb9f9a81724989bbd32ace2b02bf7eaa7a8771d64d282f423173f0/"
    "bin/python"
)


def _valid_args(tmp_path: Path) -> list[str]:
    return [
        "--mode",
        "waiting-for-authenticated-samples",
        "--repo-root",
        str(tmp_path),
        "--ledger-path",
        str(tmp_path / "ledger.sqlite3"),
        "--trusted-cost-store-root",
        str(tmp_path / "cost-cas"),
        "--interval-seconds",
        "30",
        "--max-rows",
        "250000",
    ]


def _valid_publisher_args(tmp_path: Path) -> list[str]:
    return [
        "--mode",
        "authenticated-profiled-publisher",
        "--repo-root",
        str(tmp_path),
        "--ledger-path",
        str(tmp_path / "ledger.sqlite3"),
        "--trusted-cost-store-root",
        str(tmp_path / "cost-cas"),
        "--interval-seconds",
        "30",
        "--coordinator-runtime-root",
        str(tmp_path / "coordinator"),
        "--model-dir",
        str(tmp_path / "models"),
        "--status-path",
        str(tmp_path / "status" / "status.json"),
        "--namespace",
        "namespace-v1",
        "--consumer-lane",
        "consumer-v1",
        "--state-auth-key-id",
        "state-v1",
        "--manifest-auth-key-id",
        "manifest-v1",
        "--head-auth-key-id",
        "head-v1",
        "--epoch-auth-key-id",
        "epoch-v1",
        "--page-limit",
        "256",
        "--validation-fraction",
        "0.2",
        "--optimizer-input-byte-budget",
        str(8 * 1024 * 1024),
        "--state-resource-budget-bytes",
        str(64 * 1024 * 1024),
        "--checkpoint-serialization-byte-budget",
        str(128 * 1024 * 1024),
        "--once",
    ]


def _install_fake_publisher_modules(
    monkeypatch: pytest.MonkeyPatch,
    *,
    loader_error: str | None = None,
) -> dict[str, object]:
    received: dict[str, object] = {}
    credential_module = types.ModuleType(PUBLISHER_CREDENTIAL_MODULE)
    service_module = types.ModuleType(PUBLISHER_SERVICE_MODULE)

    class FakeCredentialError(RuntimeError):
        def __init__(self, reason: str) -> None:
            self.reason = reason
            super().__init__("secret-must-not-render")

    class FakeServiceError(RuntimeError):
        def __init__(self, *reasons: str) -> None:
            self.reasons = reasons
            super().__init__("secret-must-not-render")

    class FakeConfig:
        def __init__(self, **kwargs: object) -> None:
            received.update(kwargs)

    credentials = object()

    def fake_loader() -> object:
        received["loader_called"] = True
        if loader_error is not None:
            raise FakeCredentialError(loader_error)
        return credentials

    def fake_run(config: object, supplied_credentials: object, *, once: bool) -> int:
        received["config"] = config
        received["credentials"] = supplied_credentials
        received["once"] = once
        return 23

    credential_module.AuthenticatedProfiledResidentCredentialV1Error = (
        FakeCredentialError
    )
    credential_module.load_authenticated_profiled_resident_runtime_credentials_v1 = (
        fake_loader
    )
    service_module.AuthenticatedProfiledResidentServiceConfigV1 = FakeConfig
    service_module.AuthenticatedProfiledResidentServiceV1Error = FakeServiceError
    service_module.run_authenticated_profiled_resident_service_v1 = fake_run
    monkeypatch.setitem(sys.modules, PUBLISHER_CREDENTIAL_MODULE, credential_module)
    monkeypatch.setitem(sys.modules, PUBLISHER_SERVICE_MODULE, service_module)
    monkeypatch.delitem(sys.modules, PUBLISHER_RUNTIME_MODULE, raising=False)
    monkeypatch.delitem(sys.modules, LEGACY_RUNTIME_MODULE, raising=False)
    received["credentials_object"] = credentials
    return received


def test_missing_mode_fails_before_any_runtime_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(sys.modules, WAITING_MODULE, raising=False)
    monkeypatch.delitem(sys.modules, LEGACY_RUNTIME_MODULE, raising=False)
    args = _valid_args(tmp_path)
    del args[:2]

    with pytest.raises(SystemExit) as caught:
        cli.main(args)
    assert caught.value.code == 2
    assert WAITING_MODULE not in sys.modules
    assert LEGACY_RUNTIME_MODULE not in sys.modules


def test_unknown_mode_fails_before_any_runtime_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(sys.modules, WAITING_MODULE, raising=False)
    monkeypatch.delitem(sys.modules, LEGACY_RUNTIME_MODULE, raising=False)
    args = _valid_args(tmp_path)
    args[1] = "training"

    with pytest.raises(SystemExit) as caught:
        cli.main(args)
    assert caught.value.code == 2
    assert WAITING_MODULE not in sys.modules
    assert LEGACY_RUNTIME_MODULE not in sys.modules


def test_valid_mode_dispatches_only_to_waiting_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, object] = {}
    fake_module = types.ModuleType(WAITING_MODULE)

    class FakeConfig:
        def __init__(self, **kwargs: object) -> None:
            received.update(kwargs)

    def fake_loop(config: object) -> int:
        received["config"] = config
        return 17

    fake_module.ProfiledTrainingWaitingConfigV1 = FakeConfig
    fake_module.run_profiled_training_waiting_loop_v1 = fake_loop
    monkeypatch.setitem(sys.modules, WAITING_MODULE, fake_module)
    monkeypatch.delitem(sys.modules, LEGACY_RUNTIME_MODULE, raising=False)

    assert cli.main(_valid_args(tmp_path)) == 17
    assert received["repo_root"] == tmp_path
    assert received["ledger_path"] == tmp_path / "ledger.sqlite3"
    assert received["trusted_cost_store_root"] == tmp_path / "cost-cas"
    assert received["interval_seconds"] == 30.0
    assert received["scan_limit"] == 250_000
    assert LEGACY_RUNTIME_MODULE not in sys.modules


def test_publisher_missing_mode_specific_argument_fails_before_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for module_name in (
        PUBLISHER_CREDENTIAL_MODULE,
        PUBLISHER_SERVICE_MODULE,
        PUBLISHER_RUNTIME_MODULE,
        LEGACY_RUNTIME_MODULE,
    ):
        monkeypatch.delitem(sys.modules, module_name, raising=False)
    args = _valid_publisher_args(tmp_path)
    index = args.index("--coordinator-runtime-root")
    del args[index : index + 2]

    with pytest.raises(SystemExit) as caught:
        cli.main(args)

    assert caught.value.code == 2
    assert PUBLISHER_CREDENTIAL_MODULE not in sys.modules
    assert PUBLISHER_SERVICE_MODULE not in sys.modules
    assert PUBLISHER_RUNTIME_MODULE not in sys.modules
    assert LEGACY_RUNTIME_MODULE not in sys.modules


def test_waiting_mode_rejects_publisher_only_argument_before_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for module_name in (
        WAITING_MODULE,
        PUBLISHER_CREDENTIAL_MODULE,
        PUBLISHER_SERVICE_MODULE,
        PUBLISHER_RUNTIME_MODULE,
        LEGACY_RUNTIME_MODULE,
    ):
        monkeypatch.delitem(sys.modules, module_name, raising=False)
    args = [
        *_valid_args(tmp_path),
        "--coordinator-runtime-root",
        str(tmp_path / "must-not-be-ignored"),
    ]

    with pytest.raises(SystemExit) as caught:
        cli.main(args)

    assert caught.value.code == 2
    assert WAITING_MODULE not in sys.modules
    assert PUBLISHER_CREDENTIAL_MODULE not in sys.modules
    assert PUBLISHER_SERVICE_MODULE not in sys.modules
    assert PUBLISHER_RUNTIME_MODULE not in sys.modules
    assert LEGACY_RUNTIME_MODULE not in sys.modules


def test_publisher_mode_rejects_waiting_only_argument_before_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for module_name in (
        WAITING_MODULE,
        PUBLISHER_CREDENTIAL_MODULE,
        PUBLISHER_SERVICE_MODULE,
        PUBLISHER_RUNTIME_MODULE,
        LEGACY_RUNTIME_MODULE,
    ):
        monkeypatch.delitem(sys.modules, module_name, raising=False)
    args = [*_valid_publisher_args(tmp_path), "--max-rows", "250000"]

    with pytest.raises(SystemExit) as caught:
        cli.main(args)

    assert caught.value.code == 2
    assert WAITING_MODULE not in sys.modules
    assert PUBLISHER_CREDENTIAL_MODULE not in sys.modules
    assert PUBLISHER_SERVICE_MODULE not in sys.modules
    assert PUBLISHER_RUNTIME_MODULE not in sys.modules
    assert LEGACY_RUNTIME_MODULE not in sys.modules


def test_publisher_dispatch_maps_every_explicit_argument_without_runtime_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received = _install_fake_publisher_modules(monkeypatch)

    assert cli.main(_valid_publisher_args(tmp_path)) == 23
    assert received == {
        "repo_root": tmp_path,
        "coordinator_runtime_root": tmp_path / "coordinator",
        "feature_ledger_path": tmp_path / "ledger.sqlite3",
        "trusted_immutable_cost_store_root": tmp_path / "cost-cas",
        "model_dir": tmp_path / "models",
        "status_path": tmp_path / "status" / "status.json",
        "namespace": "namespace-v1",
        "consumer_lane": "consumer-v1",
        "state_auth_key_id": "state-v1",
        "manifest_auth_key_id": "manifest-v1",
        "head_auth_key_id": "head-v1",
        "epoch_auth_key_id": "epoch-v1",
        "page_limit": 256,
        "validation_fraction": 0.2,
        "optimizer_input_byte_budget": 8 * 1024 * 1024,
        "state_resource_budget_bytes": 64 * 1024 * 1024,
        "checkpoint_serialization_byte_budget": 128 * 1024 * 1024,
        "interval_seconds": 30.0,
        "loader_called": True,
        "config": received["config"],
        "credentials": received["credentials_object"],
        "once": True,
        "credentials_object": received["credentials_object"],
    }
    assert PUBLISHER_RUNTIME_MODULE not in sys.modules
    assert LEGACY_RUNTIME_MODULE not in sys.modules


def test_publisher_credential_error_returns_non_restarting_config_status_safely(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    received = _install_fake_publisher_modules(
        monkeypatch,
        loader_error="PROFILED_RESIDENT_CREDENTIAL_TEST_FAILURE",
    )

    assert cli.main(_valid_publisher_args(tmp_path)) == cli.CONFIG_EXIT_STATUS == 78
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "PROFILED_RESIDENT_CONFIGURATION_ERROR:"
        "PROFILED_RESIDENT_CREDENTIAL_TEST_FAILURE\n"
    )
    assert "secret-must-not-render" not in captured.err
    assert "config" not in received
    assert PUBLISHER_RUNTIME_MODULE not in sys.modules
    assert LEGACY_RUNTIME_MODULE not in sys.modules


def test_repository_systemd_unit_commissions_local_non_promotable_publisher() -> None:
    root = Path(__file__).resolve().parents[5]
    unit = (
        root / "claude_worklog/systemd/user/ai-bot-v2-native-cuda-trainer-persistent.service"
    ).read_text(encoding="utf-8")

    assert "--mode locally-authenticated-profiled-research-publisher" in unit
    assert "--mode authenticated-profiled-publisher" not in unit
    assert "--mode waiting-for-authenticated-samples" not in unit
    assert (
        '--ledger-path "/home/wali/ai_bot_local_data/v2_native_trainer/'
        'durable_feature_snapshot_ledger.sqlite3"'
    ) in unit
    assert f'--trusted-cost-store-root "{CANONICAL_COST_ROOT}"' in unit
    assert (
        '--publisher-status-path "/home/wali/ai_bot_local_data/v2_native_trainer/'
        'profiled_base_publisher_v1/profiled_base_publisher_status_v1.json"'
    ) in unit
    assert (
        '--label-archive-path "/home/wali/ai_bot_local_data/v2_native_trainer/'
        'canonical_finalized_5m_label_archive.sqlite3"'
    ) in unit
    assert (
        '--local-research-runtime-root "/home/wali/ai_bot_local_data/'
        'v2_native_trainer/local_profiled_research_v1"'
    ) in unit
    assert (
        '--model-dir "/home/wali/Desktop/AI BOT REBUILD/.local_models/'
        'v2_native_rl_masa_ppo"'
    ) in unit
    assert "--page-limit 256" in unit
    assert "--scan-limit 250000" in unit
    assert "--validation-fraction 0.2" in unit
    assert "--optimizer-input-byte-budget 8388608" in unit
    assert "--state-resource-budget-bytes 67108864" in unit
    assert "--checkpoint-serialization-byte-budget 134217728" in unit
    assert "--max-rows" not in unit
    assert "StandardOutput=journal" in unit
    assert "StandardError=journal" in unit
    assert "PrivateDevices=false" in unit
    assert "RestrictAddressFamilies=AF_UNIX" in unit
    assert "RestartPreventExitStatus=2 78" in unit
    assert "Environment=CUBLAS_WORKSPACE_CONFIG=:4096:8" in unit
    assert "Wants=ai-bot-v2-profiled-base-feature-publisher.service" in unit
    assert (
        "ExecStartPre=+/usr/bin/install -d -m 0700 "
        "/home/wali/ai_bot_local_data/v2_native_trainer/"
        "local_profiled_research_v1"
    ) in unit
    assert (
        "ReadWritePaths=-/home/wali/ai_bot_local_data/v2_native_trainer/"
        "local_profiled_research_v1"
    ) in unit
    assert (
        "ReadOnlyPaths=/home/wali/ai_bot_local_data/v2_native_trainer\n"
    ) in unit
    assert "ReadOnlyPaths=/home/wali/ai_bot_local_data/v2_native_trainer/" not in unit
    assert unit.count("LoadCredential=") == 5
    assert "profiled_local_research_authorization_hmac_key" in unit
    assert "profiled_observation_witness_ed25519_public_key" not in unit
    assert "bearer" not in unit.lower()
    assert "moralis" not in unit.lower()
    assert "coinapi" not in unit.lower()


def test_repository_systemd_drop_in_pins_immutable_publisher_release() -> None:
    root = Path(__file__).resolve().parents[5]
    drop_in = (
        root
        / "claude_worklog/systemd/user/"
        "ai-bot-v2-native-cuda-trainer-persistent.service.d/"
        "90-immutable-release.conf"
    ).read_text(encoding="utf-8")

    assert set(re.findall(r"ai_bot_rebuild/([0-9a-f]{40})", drop_in)) == {
        PUBLISHER_RELEASE_SHA
    }
    assert f'Environment="AI_BOT_CODE_SHA={PUBLISHER_RELEASE_SHA}"' in drop_in
    assert f"ConditionFileIsExecutable={PINNED_PYTHON}" in drop_in
    assert (
        f"ExecStartPre=/usr/bin/git -C /home/wali/ai_bot_local_data/deployments/"
        f"ai_bot_rebuild/{PUBLISHER_RELEASE_SHA} diff --quiet --exit-code "
        f"{PUBLISHER_RELEASE_SHA} --"
    ) in drop_in
    assert (
        f"ExecStart={PINNED_PYTHON} -I -B /home/wali/ai_bot_local_data/deployments/"
        f"ai_bot_rebuild/{PUBLISHER_RELEASE_SHA}/v2/backend/app/cli/"
        "v2_native_cuda_trainer_persistent_loop.py "
        "--mode locally-authenticated-profiled-research-publisher"
    ) in drop_in
    assert "--mode authenticated-profiled-publisher" not in drop_in
    assert "--mode waiting-for-authenticated-samples" not in drop_in


def test_repository_optional_witness_drop_in_is_verifier_only() -> None:
    root = Path(__file__).resolve().parents[5]
    example = (
        root
        / "claude_worklog/systemd/user/"
        "ai-bot-v2-native-cuda-trainer-persistent.service.d/"
        "80-external-witness-verifier.conf.example"
    ).read_text(encoding="utf-8")
    contract = (
        root
        / "claude_worklog/systemd/user/"
        "ai-bot-v2-native-cuda-trainer-persistent.credentials.md"
    ).read_text(encoding="utf-8")

    assert example.count("LoadCredential=") == 1
    assert "profiled_observation_witness_ed25519_public_key" in example
    assert "PROFILED_OBSERVATION_WITNESS_ID" in example
    assert "PROFILED_OBSERVATION_WITNESS_PUBLIC_KEY_SHA256" in example
    assert "bearer" not in example.lower()
    assert "WAITING_EXTERNAL_WITNESS_CONFIGURATION" in contract
    assert "local_status_integrity_only" in contract
