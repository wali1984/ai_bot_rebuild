from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from v2.backend.app.cli import v2_native_cuda_trainer_persistent_loop as cli

_CREDENTIAL_MODULE = (
    "v2.backend.app.services.native_trainer."
    "authenticated_profiled_resident_runtime_credentials_v1"
)
_SERVICE_MODULE = (
    "v2.backend.app.services.native_trainer."
    "locally_authenticated_profiled_research_service_v1"
)
_LEGACY_MODULE = "v2.backend.app.services.native_trainer.persistent_cuda_trainer_runtime"


def _args(tmp_path: Path) -> list[str]:
    runtime_root = tmp_path / "runtime"
    return [
        "--mode",
        "locally-authenticated-profiled-research-publisher",
        "--repo-root",
        str(tmp_path),
        "--ledger-path",
        str(tmp_path / "ledger.sqlite3"),
        "--trusted-cost-store-root",
        str(tmp_path / "cost-cas"),
        "--interval-seconds",
        "30",
        "--publisher-status-path",
        str(tmp_path / "publisher-status.json"),
        "--label-archive-path",
        str(tmp_path / "labels.sqlite3"),
        "--local-research-runtime-root",
        str(runtime_root),
        "--model-dir",
        str(tmp_path / ".local_models" / "model"),
        "--status-path",
        str(runtime_root / "status.json"),
        "--manifest-auth-key-id",
        "manifest-v1",
        "--local-research-auth-key-id",
        "local-research-v1",
        "--page-limit",
        "256",
        "--scan-limit",
        "250000",
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


def _install_fakes(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    received: dict[str, object] = {}
    credential_module = types.ModuleType(_CREDENTIAL_MODULE)
    service_module = types.ModuleType(_SERVICE_MODULE)

    class FakeCredentialError(RuntimeError):
        def __init__(self, reason: str) -> None:
            self.reason = reason

    class FakeServiceError(RuntimeError):
        def __init__(self, *reasons: str) -> None:
            self.reasons = reasons

    class FakeConfig:
        def __init__(self, **kwargs: object) -> None:
            received.update(kwargs)

    supplied_credentials = types.SimpleNamespace(
        local_research_hmac_key=b"local-research-test-key-material-0000001"
    )

    def loader() -> object:
        received["loader_called"] = True
        return supplied_credentials

    def run(config: object, credentials: object, *, once: bool) -> int:
        received["config"] = config
        received["credentials"] = credentials
        received["once"] = once
        return 29

    credential_module.AuthenticatedProfiledResidentCredentialV1Error = (
        FakeCredentialError
    )
    credential_module.load_authenticated_profiled_resident_runtime_credentials_v1 = (
        loader
    )
    service_module.LocallyAuthenticatedProfiledResearchServiceConfigV1 = FakeConfig
    service_module.LocallyAuthenticatedProfiledResearchServiceV1Error = (
        FakeServiceError
    )
    service_module.run_locally_authenticated_profiled_research_service_v1 = run
    monkeypatch.setitem(sys.modules, _CREDENTIAL_MODULE, credential_module)
    monkeypatch.setitem(sys.modules, _SERVICE_MODULE, service_module)
    monkeypatch.delitem(sys.modules, _LEGACY_MODULE, raising=False)
    received["credentials_object"] = supplied_credentials
    return received


def test_local_research_mode_maps_every_explicit_argument_without_legacy_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received = _install_fakes(monkeypatch)

    assert cli.main(_args(tmp_path)) == 29
    assert received == {
        "repo_root": tmp_path,
        "publisher_status_path": tmp_path / "publisher-status.json",
        "feature_ledger_path": tmp_path / "ledger.sqlite3",
        "label_archive_path": tmp_path / "labels.sqlite3",
        "trusted_immutable_cost_store_root": tmp_path / "cost-cas",
        "runtime_root": tmp_path / "runtime",
        "model_dir": tmp_path / ".local_models" / "model",
        "status_path": tmp_path / "runtime" / "status.json",
        "manifest_auth_key_id": "manifest-v1",
        "local_research_auth_key_id": "local-research-v1",
        "page_limit": 256,
        "scan_limit": 250_000,
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
    assert _LEGACY_MODULE not in sys.modules


def test_local_research_mode_missing_authorizer_id_fails_before_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(sys.modules, _CREDENTIAL_MODULE, raising=False)
    monkeypatch.delitem(sys.modules, _SERVICE_MODULE, raising=False)
    args = _args(tmp_path)
    index = args.index("--local-research-auth-key-id")
    del args[index : index + 2]

    with pytest.raises(SystemExit) as caught:
        cli.main(args)

    assert caught.value.code == 2
    assert _CREDENTIAL_MODULE not in sys.modules
    assert _SERVICE_MODULE not in sys.modules


def test_local_research_mode_missing_credential_exits_as_configuration_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    received = _install_fakes(monkeypatch)
    credentials = received["credentials_object"]
    credentials.local_research_hmac_key = None

    assert cli.main(_args(tmp_path)) == cli.CONFIG_EXIT_STATUS == 78
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "LOCAL_PROFILED_RESEARCH_CONFIGURATION_ERROR:"
        "LOCAL_PROFILED_RESEARCH_AUTHORIZATION_CREDENTIAL_REQUIRED\n"
    )
    assert "config" not in received


def test_local_research_mode_rejects_external_coordinator_authority_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(sys.modules, _CREDENTIAL_MODULE, raising=False)
    monkeypatch.delitem(sys.modules, _SERVICE_MODULE, raising=False)

    with pytest.raises(SystemExit) as caught:
        cli.main(
            [
                *_args(tmp_path),
                "--coordinator-runtime-root",
                str(tmp_path / "coordinator"),
            ]
        )

    assert caught.value.code == 2
    assert _CREDENTIAL_MODULE not in sys.modules
    assert _SERVICE_MODULE not in sys.modules
