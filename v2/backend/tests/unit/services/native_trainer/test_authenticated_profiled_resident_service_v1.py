from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from dataclasses import asdict, fields, replace
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from v2.backend.app.services.native_trainer import (
    authenticated_profiled_resident_service_v1 as service,
)
from v2.backend.app.services.native_trainer.authenticated_profiled_resident_runtime_credentials_v1 import (  # noqa: E501
    AuthenticatedProfiledResidentLocalRoleCredentialsV1,
    AuthenticatedProfiledResidentRuntimeCredentialsV1,
    AuthenticatedProfiledResidentWitnessVerifierCredentialsV1,
)

_RUNTIME_MODULE = (
    "v2.backend.app.services.native_trainer.authenticated_profiled_resident_runtime_v1"
)
_PUBLIC_KEY = bytes(range(32))
_LOCAL_KEYS = {
    "state_hmac_key": b"state-service-role-key-material-0000000001",
    "manifest_hmac_key": b"manifest-service-role-key-material-00000002",
    "head_hmac_key": b"head-service-role-key-material-00000000003",
    "epoch_hmac_key": b"epoch-service-role-key-material-0000000004",
}
_SENSITIVE_MARKER = "provider-sensitive-value-must-never-reach-status"


def _private_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def _config(tmp_path: Path) -> service.AuthenticatedProfiledResidentServiceConfigV1:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(exist_ok=True)
    status_parent = _private_directory(tmp_path / "status")
    return service.AuthenticatedProfiledResidentServiceConfigV1(
        repo_root=repo_root.absolute(),
        coordinator_runtime_root=(tmp_path / "coordinator").absolute(),
        feature_ledger_path=(tmp_path / "ledger.sqlite3").absolute(),
        trusted_immutable_cost_store_root=(tmp_path / "cost-cas").absolute(),
        model_dir=(tmp_path / ".local_models" / "resident").absolute(),
        status_path=(status_parent / "resident-status.json").absolute(),
        namespace="profiled-observation-v1",
        consumer_lane="trainer-resident-v1",
        state_auth_key_id="state-key-v1",
        manifest_auth_key_id="manifest-key-v1",
        head_auth_key_id="head-key-v1",
        epoch_auth_key_id="epoch-key-v1",
        page_limit=7,
        validation_fraction=0.2,
        optimizer_input_byte_budget=8 * 1024 * 1024,
        state_resource_budget_bytes=64 * 1024 * 1024,
        checkpoint_serialization_byte_budget=128 * 1024 * 1024,
        interval_seconds=2.5,
    )


def _credentials(
    *,
    witness: bool,
) -> AuthenticatedProfiledResidentRuntimeCredentialsV1:
    verifier = (
        AuthenticatedProfiledResidentWitnessVerifierCredentialsV1(
            witness_id="independent-witness-v1",
            expected_public_key_sha256=hashlib.sha256(_PUBLIC_KEY).hexdigest(),
            public_key_bytes=_PUBLIC_KEY,
        )
        if witness
        else None
    )
    return AuthenticatedProfiledResidentRuntimeCredentialsV1(
        local_roles=AuthenticatedProfiledResidentLocalRoleCredentialsV1(**_LOCAL_KEYS),
        witness_verifier=verifier,
    )


def _waiting_result() -> object:
    from v2.backend.app.services.native_trainer.authenticated_profiled_resident_runtime_v1 import (  # noqa: E501
        AUTHENTICATED_PROFILED_RESIDENT_RUNTIME_V1_SCHEMA_VERSION,
        PROFILED_RESIDENT_WAITING_LOCAL_COMPLETION,
        AuthenticatedProfiledResidentRuntimeResultV1,
    )

    return AuthenticatedProfiledResidentRuntimeResultV1(
        schema_version=AUTHENTICATED_PROFILED_RESIDENT_RUNTIME_V1_SCHEMA_VERSION,
        classification=PROFILED_RESIDENT_WAITING_LOCAL_COMPLETION,
        cycle_id=None,
        state_event_sha256=None,
        manifest_id=None,
        completion_event_sha256=None,
        external_authorization_envelope_sha256=None,
        witness_namespace=None,
        admitted_example_count=0,
        base_checkpoint_id=None,
        candidate_checkpoint_id=None,
        candidate_checkpoint_generation=None,
        optimizer_execution_completed=False,
        checkpoint_publication_completed=False,
        already_published=False,
        checkpoint_artifact_verified=False,
        resident_runtime_active=True,
        checkpoint_write_authorized=False,
        prediction_authorized=False,
        serving_authorized=False,
        serving_activation_authorized=False,
        serving_promotion_authorized=False,
        trading_authorized=False,
        paper_trading_authorized=False,
        live_execution_authorized=False,
        exchange_access_authorized=False,
        deployment_authorized=False,
        order_submission_authorized=False,
        execution_authorized=False,
        runtime_wired=False,
    )


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        (
            {"repo_root": Path("relative")},
            "PROFILED_RESIDENT_SERVICE_REPO_ROOT_INVALID",
        ),
        ({"namespace": "bad namespace"}, "PROFILED_RESIDENT_SERVICE_CONFIG_INVALID"),
        (
            {"manifest_auth_key_id": "state-key-v1"},
            "PROFILED_RESIDENT_SERVICE_CONFIG_INVALID",
        ),
        ({"page_limit": 0}, "PROFILED_RESIDENT_SERVICE_CONFIG_INVALID"),
        ({"validation_fraction": 1.0}, "PROFILED_RESIDENT_SERVICE_CONFIG_INVALID"),
        (
            {"optimizer_input_byte_budget": 0},
            "PROFILED_RESIDENT_SERVICE_CONFIG_INVALID",
        ),
        ({"interval_seconds": True}, "PROFILED_RESIDENT_SERVICE_CONFIG_INVALID"),
    ],
)
def test_config_validation_fails_closed(
    tmp_path: Path,
    overrides: dict[str, Any],
    reason: str,
) -> None:
    valid = _config(tmp_path)

    with pytest.raises(service.AuthenticatedProfiledResidentServiceV1Error) as caught:
        replace(valid, **overrides)

    assert caught.value.reasons == (reason,)


def test_witness_absent_once_parks_without_import_or_runtime_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(sys.modules, _RUNTIME_MODULE, raising=False)
    events: list[tuple[str, str]] = []

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("witness-absent mode must not enter the runtime")

    result = service.run_authenticated_profiled_resident_service_v1(
        _config(tmp_path),
        _credentials(witness=False),
        once=True,
        runtime_builder=forbidden,
        cycle_runner=forbidden,
        writer=lambda _config, payload: events.append(
            ("write", str(payload["classification"]))
        ),
        emit=lambda payload: events.append(("emit", str(payload["classification"]))),
    )

    assert result == 0
    assert _RUNTIME_MODULE not in sys.modules
    assert events == [
        ("write", service.PROFILED_RESIDENT_SERVICE_WAITING_WITNESS),
        ("emit", service.PROFILED_RESIDENT_SERVICE_WAITING_WITNESS),
    ]


def test_continuous_witness_wait_exits_cleanly_on_keyboard_interrupt(
    tmp_path: Path,
) -> None:
    statuses: list[str] = []

    def interrupted_sleep(seconds: float) -> None:
        assert seconds == 2.5
        raise KeyboardInterrupt

    result = service.run_authenticated_profiled_resident_service_v1(
        _config(tmp_path),
        _credentials(witness=False),
        sleep=interrupted_sleep,
        writer=lambda _config, payload: statuses.append(
            f"write:{payload['classification']}"
        ),
        emit=lambda payload: statuses.append(f"emit:{payload['classification']}"),
    )

    assert result == 0
    assert statuses == [
        f"write:{service.PROFILED_RESIDENT_SERVICE_WAITING_WITNESS}",
        f"emit:{service.PROFILED_RESIDENT_SERVICE_WAITING_WITNESS}",
    ]


def test_witness_present_emits_running_then_exact_30_field_resident_result(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    credentials = _credentials(witness=True)
    waiting = _waiting_result()
    runtime_config = object()
    events: list[str] = []
    payloads: list[dict[str, Any]] = []

    def runtime_builder(**kwargs: object) -> object:
        assert kwargs == {"config": config, "credentials": credentials}
        events.append("build")
        return runtime_config

    def cycle_runner(observed: object) -> object:
        assert observed is runtime_config
        events.append("cycle")
        return waiting

    def writer(_config: object, payload: dict[str, Any]) -> None:
        events.append(f"write:{payload['classification']}")
        payloads.append(payload)

    def emit(payload: dict[str, Any]) -> None:
        events.append(f"emit:{payload['classification']}")

    result = service.run_authenticated_profiled_resident_service_v1(
        config,
        credentials,
        once=True,
        runtime_builder=runtime_builder,
        cycle_runner=cycle_runner,
        writer=writer,
        emit=emit,
    )

    assert result == 0
    assert events == [
        f"write:{service.PROFILED_RESIDENT_SERVICE_CYCLE_RUNNING}",
        f"emit:{service.PROFILED_RESIDENT_SERVICE_CYCLE_RUNNING}",
        "build",
        "cycle",
        f"write:{waiting.classification}",
        f"emit:{waiting.classification}",
    ]
    material = payloads[-1]["resident_result"]
    assert len(material) == 30
    assert set(material) == {descriptor.name for descriptor in fields(waiting)}
    assert material == asdict(waiting)


@pytest.mark.parametrize("failure_stage", ["build", "cycle"])
def test_runtime_failure_writes_safe_fail_closed_once(
    tmp_path: Path,
    failure_stage: str,
) -> None:
    payloads: list[dict[str, Any]] = []

    def runtime_builder(**_kwargs: object) -> object:
        if failure_stage == "build":
            raise RuntimeError(f"builder failed with {_SENSITIVE_MARKER}")
        return object()

    def cycle_runner(_runtime_config: object) -> object:
        raise RuntimeError(f"cycle failed with {_SENSITIVE_MARKER}")

    result = service.run_authenticated_profiled_resident_service_v1(
        _config(tmp_path),
        _credentials(witness=True),
        once=True,
        runtime_builder=runtime_builder,
        cycle_runner=cycle_runner,
        writer=lambda _config, payload: payloads.append(dict(payload)),
        emit=lambda _payload: None,
    )

    assert result == 1
    assert [payload["classification"] for payload in payloads] == [
        service.PROFILED_RESIDENT_SERVICE_CYCLE_RUNNING,
        service.PROFILED_RESIDENT_SERVICE_FAIL_CLOSED,
    ]
    assert payloads[-1]["error"] == {
        "error_type": "RuntimeError",
        "reason_codes": [],
    }
    assert _SENSITIVE_MARKER not in json.dumps(payloads)


def test_arbitrary_exception_reason_and_type_are_redacted_from_status(
    tmp_path: Path,
) -> None:
    payloads: list[dict[str, Any]] = []

    class ProviderSecretFailure(RuntimeError):
        reasons = (_SENSITIVE_MARKER,)

    def runtime_builder(**_kwargs: object) -> object:
        raise ProviderSecretFailure(_SENSITIVE_MARKER)

    result = service.run_authenticated_profiled_resident_service_v1(
        _config(tmp_path),
        _credentials(witness=True),
        once=True,
        runtime_builder=runtime_builder,
        writer=lambda _config, payload: payloads.append(dict(payload)),
        emit=lambda _payload: None,
    )

    assert result == 1
    assert payloads[-1]["error"] == {
        "error_type": "UnexpectedRuntimeError",
        "reason_codes": [],
    }
    assert _SENSITIVE_MARKER not in json.dumps(payloads)


def test_status_write_is_atomic_private_and_self_hashed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    credentials = _credentials(witness=False)
    payload = service.build_authenticated_profiled_resident_service_status_v1(
        config=config,
        credentials=credentials,
        classification=service.PROFILED_RESIDENT_SERVICE_WAITING_WITNESS,
    )

    service.write_authenticated_profiled_resident_service_status_v1(config, payload)

    raw = config.status_path.read_bytes()
    stored = json.loads(raw)
    observed_hash = stored.pop("status_sha256")
    assert stored["local_status_integrity_only"] is True
    canonical = json.dumps(
        stored,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    assert raw.endswith(b"\n")
    assert observed_hash == hashlib.sha256(canonical).hexdigest()
    assert stat.S_IMODE(config.status_path.stat().st_mode) == 0o600
    assert list(config.status_path.parent.iterdir()) == [config.status_path]


@pytest.mark.parametrize("target_kind", ["symlink", "writable", "hardlink"])
def test_unsafe_status_target_is_rejected(
    tmp_path: Path,
    target_kind: str,
) -> None:
    config = _config(tmp_path)
    if target_kind == "symlink":
        target = tmp_path / "outside-status.json"
        target.write_text("{}")
        config.status_path.symlink_to(target)
    else:
        config.status_path.write_text("{}")
        config.status_path.chmod(0o600)
        if target_kind == "writable":
            config.status_path.chmod(0o622)
        else:
            os.link(config.status_path, config.status_path.parent / "status-hardlink")
    payload = service.build_authenticated_profiled_resident_service_status_v1(
        config=config,
        credentials=_credentials(witness=False),
        classification=service.PROFILED_RESIDENT_SERVICE_WAITING_WITNESS,
    )

    with pytest.raises(service.AuthenticatedProfiledResidentServiceV1Error) as caught:
        service.write_authenticated_profiled_resident_service_status_v1(config, payload)

    assert caught.value.reasons == (
        "PROFILED_RESIDENT_SERVICE_STATUS_TARGET_INVALID",
    )


def test_runtime_builder_maps_exact_paths_keys_and_resource_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    root = _private_directory(config.coordinator_runtime_root)
    for relative in (
        "state-cas",
        "state-cas/sha256",
        "staging-cas",
        "staging-cas/sha256",
        "completion-authorization-cas",
        "completion-authorization-cas/sha256",
    ):
        _private_directory(root / relative)
    credentials = _credentials(witness=True)
    captured: dict[str, Any] = {"stores": []}

    class FakeStore:
        def __init__(self, path: Path) -> None:
            self.path = path
            captured["stores"].append(path)

    class FakeStateStore:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs
            captured["state"] = kwargs

    class FakeJournal:
        def __init__(self, path: Path, *, immutable_store: object) -> None:
            self.path = path
            self.immutable_store = immutable_store
            captured["journal"] = (path, immutable_store)

    class FakeLedger:
        def __init__(self, path: Path) -> None:
            self.path = path
            captured["ledger"] = path

    class FakeRuntimeConfig:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs
            captured["runtime"] = kwargs

    module_attributes = {
        _RUNTIME_MODULE: (
            "AuthenticatedProfiledResidentRuntimeConfigV1",
            FakeRuntimeConfig,
        ),
        "v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger": (
            "DurableFeatureSnapshotLedger",
            FakeLedger,
        ),
        "v2.backend.app.services.native_trainer.immutable_source_payload_store": (
            "ImmutableSourcePayloadStore",
            FakeStore,
        ),
        "v2.backend.app.services.native_trainer."
        "profiled_optimizer_external_completion_authorization_journal_v1": (
            "ProfiledOptimizerCompletionAuthorizationJournalV1",
            FakeJournal,
        ),
        "v2.backend.app.services.native_trainer."
        "profiled_training_observation_coordinator_state_v1": (
            "ProfiledTrainingObservationCoordinatorStateStoreV1",
            FakeStateStore,
        ),
    }
    for module_name, (attribute, value) in module_attributes.items():
        fake_module = ModuleType(module_name)
        setattr(fake_module, attribute, value)
        monkeypatch.setitem(sys.modules, module_name, fake_module)

    built = service.build_authenticated_profiled_resident_runtime_config_v1(
        config=config,
        credentials=credentials,
    )

    assert isinstance(built, FakeRuntimeConfig)
    assert captured["stores"] == [
        root / "state-cas",
        root / "completion-authorization-cas",
        root / "staging-cas",
    ]
    assert captured["ledger"] == config.feature_ledger_path
    state = captured["state"]
    assert state["pointer_path"] == root / "state" / "current.json"
    assert state["namespace"] == config.namespace
    assert state["consumer_lane"] == config.consumer_lane
    for role in ("state", "manifest", "head", "epoch"):
        assert state[f"{role}_auth_key_id"] == getattr(config, f"{role}_auth_key_id")
        assert state[f"{role}_hmac_key"] == getattr(
            credentials.local_roles,
            f"{role}_hmac_key",
        )
    journal_path, journal_store = captured["journal"]
    assert journal_path == root / "completion-authorization" / "journal.sqlite3"
    assert journal_store.path == root / "completion-authorization-cas"
    runtime = captured["runtime"]
    assert runtime["completion_staging_store"].path == root / "staging-cas"
    assert runtime["trusted_immutable_cost_store_root"] == (
        config.trusted_immutable_cost_store_root
    )
    assert runtime["repo_root"] == config.repo_root
    assert runtime["model_dir"] == config.model_dir
    assert runtime["witness_namespace"] == config.namespace
    assert runtime["witness_id"] == credentials.witness_verifier.witness_id
    assert runtime["witness_public_key_bytes"] == _PUBLIC_KEY
    assert runtime["expected_witness_public_key_sha256"] == hashlib.sha256(
        _PUBLIC_KEY
    ).hexdigest()
    assert runtime["page_limit"] == config.page_limit
    assert runtime["validation_fraction"] == config.validation_fraction
    assert runtime["optimizer_input_byte_budget"] == (
        config.optimizer_input_byte_budget
    )
    assert runtime["state_resource_budget_bytes"] == config.state_resource_budget_bytes
    assert runtime["checkpoint_serialization_byte_budget"] == (
        config.checkpoint_serialization_byte_budget
    )
