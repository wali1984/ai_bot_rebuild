from __future__ import annotations

import builtins
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from v2.backend.app.services.native_trainer import (
    durable_feature_snapshot_ledger as ledger_module,
)
from v2.backend.app.services.native_trainer import (
    profiled_training_waiting_runtime_v1 as waiting_runtime,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    DurableFeatureSnapshotLedger,
)
from v2.backend.app.services.native_trainer.profiled_training_waiting_runtime_v1 import (
    PROFILED_CHILD_CANDIDATES_AVAILABLE_STATE,
    WAITING_FOR_AUTHENTICATED_SAMPLES_STATE,
    WAITING_PROBE_FAILED_STATE,
    WAITING_PROBE_INCOMPLETE_STATE,
    WAITING_STATUS_RELATIVE_PATH,
    AuthenticatedSampleProbeV1,
    ProfiledTrainingWaitingConfigV1,
    ProfiledTrainingWaitingRuntimeV1Error,
    inspect_authenticated_profiled_samples_v1,
    run_profiled_training_waiting_cycle_v1,
)

OBSERVED_AT = "2026-07-21T10:00:00.000000Z"
CANONICAL_COST_ROOT_REL = Path("data/profiled_base_publisher_v1/profiled-training-enrichment-cas")
AUTHORITY_FIELDS = (
    "trainer_admission_authorized",
    "training_loop_active",
    "continuous_training_enabled",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
    "execution_authorized",
    "checkpoint_authorized",
    "model_authorized",
    "runtime_wired",
    "automatic_transition_authorized",
)


def test_candidate_contract_constants_match_offline_hardened_loader() -> None:
    # Importing the factory loader is explicitly test/offline-only: its current
    # package dependency eagerly imports trainer modules, which the resident
    # waiting process forbids. This comparison prevents the lightweight status
    # probe from drifting from the full-authentication contract.
    from v2.backend.app.services.native_trainer import (
        profiled_training_ledger_loader_v1 as hardened_loader,
    )
    from v2.backend.app.services.native_trainer.profiled_model_feature_snapshot_record_v1 import (
        PHYSICAL_MODEL_FEATURE_COUNT,
        PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_CLASSIFICATION,
        PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_SCHEMA_VERSION,
        PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_STATUS,
    )

    assert waiting_runtime._PROFILED_LINEAGE_KEY == (
        hardened_loader.PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_KEY
    )
    assert waiting_runtime._PROFILED_LINEAGE_SCHEMA == (
        hardened_loader.PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_SCHEMA_VERSION
    )
    assert waiting_runtime._PROFILED_LINEAGE_CLASSIFICATION == (
        hardened_loader.PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_CLASSIFICATION
    )
    assert waiting_runtime._PROFILED_LINEAGE_STATUS == (
        hardened_loader.PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_STATUS
    )
    assert waiting_runtime._PHYSICAL_PROFILED_FEATURE_COUNT == (
        hardened_loader.PROFILED_TRAINING_PHYSICAL_FEATURE_COUNT
    )
    assert waiting_runtime._AUXILIARY_COST_FEATURE_NAMES == (
        hardened_loader.AUXILIARY_LABEL_ONLY_FEATURE_NAMES
    )
    assert waiting_runtime._EXPECTED_SAMPLE_AUTHORIZATION == (
        hardened_loader._EXPECTED_AUTHORIZATION
    )
    assert waiting_runtime._PARENT_PROFILED_FEATURE_COUNT == PHYSICAL_MODEL_FEATURE_COUNT
    assert (
        waiting_runtime._PARENT_PROFILED_SCHEMA
        == PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_SCHEMA_VERSION
    )
    assert (
        waiting_runtime._PARENT_PROFILED_CLASSIFICATION
        == PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_CLASSIFICATION
    )
    assert waiting_runtime._PARENT_PROFILED_STATUS == (
        PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_STATUS
    )


def test_candidate_contract_requires_exact_parent_child_bit_identity() -> None:
    parent_names = [f"profile_feature_{index}" for index in range(35)]
    parent_values = [float(index) for index in range(35)]
    parent_labels = [f"source_{index}" for index in range(35)]
    parent_roots = [f"{index:064x}" for index in range(35)]
    shared = {
        "append_transaction_id": "feature_snapshot_append_" + "a" * 64,
        "append_receipt_sha256": "b" * 64,
        "postcommit_receipt_sha256": "c" * 64,
        "postcommit_readback_at": "2026-07-21T10:00:00.000000Z",
    }
    parent_envelope = {
        "ordered_feature_names": parent_names,
        "feature_values": parent_values,
        "ordered_feature_source_labels": parent_labels,
        "feature_source_receipt_sha256s": parent_roots,
        "source_lineage_material": {
            "schema_version": waiting_runtime._PARENT_PROFILED_SCHEMA,
            "classification": waiting_runtime._PARENT_PROFILED_CLASSIFICATION,
            "status": waiting_runtime._PARENT_PROFILED_STATUS,
            "physical_model_feature_count": 35,
            "authorization": dict(waiting_runtime._EXPECTED_PARENT_AUTHORIZATION),
        },
        "provenance_classification": "CANONICAL_V3",
        "legacy_v1_snapshot_id": None,
        "strict_training_eligible": False,
        "missing_mask": [0] * 35,
        "stale_mask": [0] * 35,
        "source_availability_mask": [1] * 35,
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "tensor_decision_time": "2026-07-21T10:05:00.000000Z",
        "masa_feature_cutoff": "2026-07-21T10:00:00.000000Z",
        "ppo_decision_time": "2026-07-21T10:05:00.000000Z",
    }
    parent = SimpleNamespace(
        sequence=1,
        record={"frozen_envelope": parent_envelope},
        **shared,
    )
    child_envelope = {
        **{
            field: parent_envelope[field]
            for field in (
                "symbol",
                "timeframe",
                "tensor_decision_time",
                "masa_feature_cutoff",
                "ppo_decision_time",
            )
        },
        "ordered_feature_names": [
            *parent_names,
            *waiting_runtime._AUXILIARY_COST_FEATURE_NAMES,
        ],
        "feature_values": [*parent_values, 1.0, 2.0, 3.0, 4.0],
        "ordered_feature_source_labels": [
            *parent_labels,
            "cost_fee",
            "cost_spread",
            "cost_slippage",
            "cost_funding",
        ],
        "feature_source_receipt_sha256s": [
            *parent_roots,
            "d" * 64,
            "e" * 64,
            "f" * 64,
            "1" * 64,
        ],
        "source_lineage_material": {
            waiting_runtime._PROFILED_LINEAGE_KEY: {
                "schema_version": waiting_runtime._PROFILED_LINEAGE_SCHEMA,
                "classification": waiting_runtime._PROFILED_LINEAGE_CLASSIFICATION,
                "status": waiting_runtime._PROFILED_LINEAGE_STATUS,
                "physical_feature_count": 39,
                "authorization": dict(waiting_runtime._EXPECTED_SAMPLE_AUTHORIZATION),
                "parent_model_record_binding": {"durable_snapshot_id": "profiled-parent-id"},
            }
        },
        "provenance_classification": "CANONICAL_V3",
        "legacy_v1_snapshot_id": None,
        "strict_training_eligible": True,
        "strict_training_ineligibility_reasons": [],
        "temporal_rejection_reasons": [],
        "missing_mask": [0] * 39,
        "stale_mask": [0] * 39,
        "source_availability_mask": [1] * 39,
    }
    item = SimpleNamespace(
        sequence=2,
        record={"frozen_envelope": child_envelope},
        **shared,
    )
    ledger = SimpleNamespace(get_snapshot=lambda _snapshot_id: parent)
    assert waiting_runtime._profiled_child_candidate_rejection(item, ledger=ledger) is None

    tampered_item = copy.deepcopy(item)
    tampered_item.record["frozen_envelope"]["feature_values"][0] = -1.0
    assert (
        waiting_runtime._profiled_child_candidate_rejection(
            tampered_item,
            ledger=ledger,
        )
        == "PROFILED_CHILD_PARENT_BIT_IDENTITY_INVALID"
    )


def _config(tmp_path: Path) -> ProfiledTrainingWaitingConfigV1:
    repo_root = tmp_path / "repo"
    (repo_root / WAITING_STATUS_RELATIVE_PATH.parent).mkdir(parents=True)
    return ProfiledTrainingWaitingConfigV1(
        repo_root=repo_root,
        ledger_path=(tmp_path / "data/ledger.sqlite3").absolute(),
        trusted_cost_store_root=(tmp_path / CANONICAL_COST_ROOT_REL).absolute(),
        interval_seconds=30.0,
        scan_limit=250_000,
    )


def _probe_result(
    profiled_child_candidate_count: int,
    *,
    scan_complete: bool = True,
) -> AuthenticatedSampleProbeV1:
    return AuthenticatedSampleProbeV1(
        authenticated_sample_count=None,
        strict_training_eligible_row_count=profiled_child_candidate_count,
        profiled_child_candidate_count=profiled_child_candidate_count,
        excluded_record_count=0,
        exclusions_by_reason={},
        integrity_verified_record_count=profiled_child_candidate_count,
        integrity_verified_append_receipt_count=profiled_child_candidate_count,
        integrity_observation_sha256="a" * 64,
        archive_chain_sha256="b" * 64,
        ledger_integrity_verified=True,
        full_sample_authentication_performed=False,
        scan_complete=scan_complete,
        runtime_scalability_status="FACTORY_ONLY_TEST_PROBE",
    )


def _assert_no_runtime_authority(payload: dict[str, Any]) -> None:
    assert payload["service_process_active"] is True
    for field in AUTHORITY_FIELDS:
        assert payload[field] is False, field
    assert payload["checkpoint_id"] is None
    assert payload["checkpoint_path"] is None
    assert payload["model_id"] is None
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []


def test_zero_samples_writes_only_dedicated_truthful_waiting_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    real_import = builtins.__import__
    forbidden_imports = (
        "redis",
        "torch",
        "v2.backend.app.services.native_trainer.persistent_cuda_trainer_runtime",
        "v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model",
        "v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint",
    )

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if any(name == item or name.startswith(f"{item}.") for item in forbidden_imports):
            raise AssertionError(f"forbidden waiting-mode import: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    payload = run_profiled_training_waiting_cycle_v1(
        config,
        probe=lambda *_args, **_kwargs: _probe_result(0),
        clock=lambda: OBSERVED_AT,
    )

    assert payload["state"] == WAITING_FOR_AUTHENTICATED_SAMPLES_STATE
    assert payload["operator_promotion_required"] is False
    assert payload["authenticated_sample_inventory"]["authenticated_sample_count"] is None
    assert payload["authenticated_sample_inventory"]["authenticated_samples_available"] is None
    assert payload["authenticated_sample_producer"] == {
        "trusted_cost_store_root": str(config.trusted_cost_store_root),
        "materialized": False,
        "state": "NOT_YET_MATERIALIZED",
    }
    _assert_no_runtime_authority(payload)
    files = {path for path in config.repo_root.rglob("*") if path.is_file()}
    assert files == {config.status_path}
    assert json.loads(config.status_path.read_text(encoding="utf-8")) == payload


def test_available_samples_require_operator_promotion_and_never_gain_authority(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    payload = run_profiled_training_waiting_cycle_v1(
        config,
        probe=lambda *_args, **_kwargs: _probe_result(3),
        clock=lambda: OBSERVED_AT,
    )

    assert payload["state"] == PROFILED_CHILD_CANDIDATES_AVAILABLE_STATE
    assert payload["operator_promotion_required"] is True
    assert payload["automatic_transition_authorized"] is False
    assert payload["authenticated_sample_inventory"]["authenticated_sample_count"] is None
    assert payload["authenticated_sample_inventory"]["profiled_child_candidate_count"] == 3
    assert (
        payload["authenticated_sample_inventory"]["full_sample_authentication_performed"] is False
    )
    _assert_no_runtime_authority(payload)


def test_incomplete_scan_never_requests_promotion_even_if_candidate_was_seen(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    payload = run_profiled_training_waiting_cycle_v1(
        config,
        probe=lambda *_args, **_kwargs: _probe_result(3, scan_complete=False),
        clock=lambda: OBSERVED_AT,
    )

    inventory = payload["authenticated_sample_inventory"]
    assert payload["state"] == WAITING_PROBE_INCOMPLETE_STATE
    assert payload["operator_promotion_required"] is False
    assert inventory["profiled_child_candidate_count"] == 3
    assert inventory["strict_training_eligible_row_count_exact"] is False
    _assert_no_runtime_authority(payload)


def test_readiness_probe_streams_bounded_pages_and_uses_one_row_overflow_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _config(tmp_path)
    config = ProfiledTrainingWaitingConfigV1(
        repo_root=base.repo_root,
        ledger_path=base.ledger_path,
        trusted_cost_store_root=base.trusted_cost_store_root,
        interval_seconds=base.interval_seconds,
        scan_limit=5,
    )
    config.ledger_path.parent.mkdir(parents=True)
    for path in (
        config.ledger_path,
        Path(f"{config.ledger_path}-wal"),
        Path(f"{config.ledger_path}-shm"),
    ):
        path.write_bytes(b"materialized")

    class TrackedItem:
        alive = 0
        max_alive = 0

        def __init__(self, sequence: int) -> None:
            self.sequence = sequence
            self.record: dict[str, object] = {}
            type(self).alive += 1
            type(self).max_alive = max(type(self).max_alive, type(self).alive)

        def __del__(self) -> None:
            type(self).alive -= 1

    report = SimpleNamespace(
        integrity_verified=True,
        verified_records=6,
        verified_append_receipts=6,
        verified_postcommit_receipts=6,
        verified_projection_outbox_rows=6,
        total_record_bytes=600,
        archive_chain_sha256="a" * 64,
    )

    class FakeLedger:
        query_limits: list[int] = []

        def __init__(self, _path: Path) -> None:
            pass

        def verify_integrity_streaming(self) -> SimpleNamespace:
            return report

        def query_fixed_cutoff(self, **kwargs: Any) -> list[TrackedItem]:
            limit = int(kwargs["limit"])
            after = int(kwargs["after_sequence"])
            type(self).query_limits.append(limit)
            return [
                TrackedItem(sequence)
                for sequence in range(after + 1, min(6, after + limit) + 1)
            ]

        def get_snapshot(self, _snapshot_id: str) -> None:
            raise AssertionError("non-profile rows cannot request parent snapshots")

    monkeypatch.setattr(ledger_module, "DurableFeatureSnapshotLedger", FakeLedger)
    monkeypatch.setattr(ledger_module, "MAX_QUERY_ROWS", 2)

    result = inspect_authenticated_profiled_samples_v1(
        config,
        training_observed_at=OBSERVED_AT,
    )

    assert result.strict_training_eligible_row_count == 5
    assert result.profiled_child_candidate_count == 0
    assert result.scan_complete is False
    assert FakeLedger.query_limits == [2, 2, 1, 1]
    assert TrackedItem.max_alive <= 3


def test_probe_failure_stays_resident_in_failed_closed_status(tmp_path: Path) -> None:
    config = _config(tmp_path)

    class ProbeFailure(RuntimeError):
        reasons = ("PROFILED_TRAINING_TEST_FAILURE", "unsafe reason with spaces")

    def fail_probe(*_args: Any, **_kwargs: Any) -> AuthenticatedSampleProbeV1:
        raise ProbeFailure("must not be copied into status")

    payload = run_profiled_training_waiting_cycle_v1(
        config,
        probe=fail_probe,
        clock=lambda: OBSERVED_AT,
    )
    assert payload["state"] == WAITING_PROBE_FAILED_STATE
    assert payload["authenticated_sample_inventory"]["probe_error"] == {
        "error_type": "ProbeFailure",
        "reason_codes": ["PROFILED_TRAINING_TEST_FAILURE"],
    }
    assert "must not be copied" not in config.status_path.read_text(encoding="utf-8")
    _assert_no_runtime_authority(payload)


def test_missing_ledger_sidecars_publish_failure_without_materializing_them(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    payload = run_profiled_training_waiting_cycle_v1(
        config,
        clock=lambda: OBSERVED_AT,
    )

    assert payload["state"] == WAITING_PROBE_FAILED_STATE
    assert payload["authenticated_sample_inventory"]["probe_error"] == {
        "error_type": "ProfiledTrainingWaitingRuntimeV1Error",
        "reason_codes": ["ledger_main_file_not_materialized"],
    }
    assert not config.ledger_path.parent.exists()
    assert {path for path in config.repo_root.rglob("*") if path.is_file()} == {config.status_path}
    _assert_no_runtime_authority(payload)


def test_atomic_replacement_removes_stale_authority_fields(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.status_path.write_text(
        json.dumps(
            {
                "training_loop_active": True,
                "prediction_authorized": True,
                "checkpoint_id": "stale-checkpoint",
                "model_id": "stale-model",
            }
        ),
        encoding="utf-8",
    )
    payload = run_profiled_training_waiting_cycle_v1(
        config,
        probe=lambda *_args, **_kwargs: _probe_result(0),
        clock=lambda: OBSERVED_AT,
    )

    persisted = json.loads(config.status_path.read_text(encoding="utf-8"))
    assert persisted == payload
    _assert_no_runtime_authority(persisted)
    assert "stale-checkpoint" not in config.status_path.read_text(encoding="utf-8")
    assert "stale-model" not in config.status_path.read_text(encoding="utf-8")


def test_status_symlink_is_rejected_without_mutating_target(tmp_path: Path) -> None:
    config = _config(tmp_path)
    victim = tmp_path / "victim.json"
    victim.write_text("unchanged\n", encoding="utf-8")
    config.status_path.symlink_to(victim)

    with pytest.raises(
        ProfiledTrainingWaitingRuntimeV1Error,
        match="waiting_status_target_not_regular_file",
    ):
        run_profiled_training_waiting_cycle_v1(
            config,
            probe=lambda *_args, **_kwargs: _probe_result(0),
            clock=lambda: OBSERVED_AT,
        )
    assert victim.read_text(encoding="utf-8") == "unchanged\n"


def test_hardened_empty_ledger_probe_does_not_materialize_absent_cost_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    config.ledger_path.parent.mkdir(parents=True)
    ledger = DurableFeatureSnapshotLedger(config.ledger_path)
    ledger.initialize()
    # The publisher/writer owns SQLite sidecar materialization. The waiting
    # observer must never create these coordination files itself.
    ledger.verify_integrity_streaming()
    before = {
        path.relative_to(config.ledger_path.parent): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in config.ledger_path.parent.rglob("*")
        if path.is_file()
    }
    real_import = builtins.__import__
    forbidden_imports = (
        "redis",
        "torch",
        "v2.backend.app.services.native_trainer.profiled_training_ledger_loader_v1",
        "v2.backend.app.services.native_trainer.persistent_cuda_trainer_runtime",
        "v2.backend.app.services.native_trainer.hybrid_cuda_trainer",
    )

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if any(name == item or name.startswith(f"{item}.") for item in forbidden_imports):
            raise AssertionError(f"forbidden readiness-probe import: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    result = inspect_authenticated_profiled_samples_v1(
        config,
        training_observed_at=OBSERVED_AT,
    )

    after = {
        path.relative_to(config.ledger_path.parent): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in config.ledger_path.parent.rglob("*")
        if path.is_file()
    }
    assert result.authenticated_sample_count is None
    assert result.strict_training_eligible_row_count == 0
    assert result.ledger_integrity_verified is True
    assert result.full_sample_authentication_performed is False
    assert not config.trusted_cost_store_root.exists()
    assert after == before
