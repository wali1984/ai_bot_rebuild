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
OBSERVER_RELEASE_SHA = "76a8ae2fe1f71fd9e1dc2f68775cdeebec8fc236"


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


def test_repository_systemd_unit_pins_only_waiting_mode_and_canonical_paths() -> None:
    root = Path(__file__).resolve().parents[5]
    unit = (
        root / "claude_worklog/systemd/user/ai-bot-v2-native-cuda-trainer-persistent.service"
    ).read_text(encoding="utf-8")
    cli_source = Path(cli.__file__).read_text(encoding="utf-8")

    assert "--mode waiting-for-authenticated-samples" in unit
    assert (
        '--ledger-path "/home/wali/ai_bot_local_data/v2_native_trainer/'
        'durable_feature_snapshot_ledger.sqlite3"'
    ) in unit
    assert f'--trusted-cost-store-root "{CANONICAL_COST_ROOT}"' in unit
    assert "--max-rows 250000" in unit
    assert "StandardOutput=null" in unit
    assert "StandardError=null" in unit
    assert "/usr/bin/env bash" not in unit
    assert "V2_TRAINER_" not in unit
    assert "V2_NATIVE_TRAINER_ADAPTIVE_GPU_CONTROLLER" not in unit
    assert "--no-training" not in unit
    assert "persistent_cuda_trainer_runtime" not in cli_source


def test_repository_systemd_drop_in_pins_immutable_observer_release() -> None:
    root = Path(__file__).resolve().parents[5]
    drop_in = (
        root
        / "claude_worklog/systemd/user/"
        "ai-bot-v2-native-cuda-trainer-persistent.service.d/"
        "90-immutable-release.conf"
    ).read_text(encoding="utf-8")

    assert set(re.findall(r"[0-9a-f]{40}", drop_in)) == {OBSERVER_RELEASE_SHA}
    assert f'Environment="AI_BOT_CODE_SHA={OBSERVER_RELEASE_SHA}"' in drop_in
    assert (
        f"ExecStartPre=/usr/bin/git -C /home/wali/ai_bot_local_data/deployments/"
        f"ai_bot_rebuild/{OBSERVER_RELEASE_SHA} diff --quiet --exit-code "
        f"{OBSERVER_RELEASE_SHA} --"
    ) in drop_in
    assert (
        f"ExecStart=/usr/bin/python3 -I -B /home/wali/ai_bot_local_data/deployments/"
        f"ai_bot_rebuild/{OBSERVER_RELEASE_SHA}/v2/backend/app/cli/"
        "v2_native_cuda_trainer_persistent_loop.py "
        "--mode waiting-for-authenticated-samples"
    ) in drop_in
