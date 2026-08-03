from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from v2.backend.app.services.market_state_integrity import sample_rejection
from v2.backend.app.services.market_state_integrity.trust import TRUST_SCHEMA_VERSION
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    append_snapshot,
    build_archive_record,
    build_archive_record_from_prediction_payload,
    content_sha256,
    verify_record,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import ppo_trainer
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    TrainingExample,
    V2HybridTrainerDataLoader,
    _classification_from_lineage,
    _closed_trade_example_cache_key,
    _extra_contract_rejection_reasons,
    _feedback_trust_rejection_reasons,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer import (
    V2HybridPPOTrainer,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FeatureTensorRecord,
)

FEATURE_CUTOFF = "2026-07-18T00:00:00Z"
AVAILABLE_AT = "2026-07-18T00:00:30Z"
DECISION_TIME = "2026-07-18T00:01:00Z"
LABEL_AVAILABLE_AT = "2026-07-18T00:02:00Z"
TRAINING_OBSERVED_AT = "2026-07-18T00:03:00Z"


class _FallbackModel:
    torch_available = False
    cuda_active = False
    torch = None
    input_dim = 1
    device = "cpu"
    model_id = "temporal-contract-test"
    _fallback_weights = [0.0]

    def forward(self, _tensor: Any) -> SimpleNamespace:
        return SimpleNamespace(
            action_probabilities=[1.0, 0.0, 0.0],
            expected_move_bps=0.0,
        )


def _tensor() -> FeatureTensorRecord:
    return FeatureTensorRecord(
        tensor_id="tensor-temporal",
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot_id="snapshot-temporal",
        values=(0.1,),
        missing_mask=(0,),
        stale_mask=(0,),
        source_availability=(1,),
        feature_names=("ret_pct",),
        source_labels=("unit",),
        missing_feature_names=(),
        stale_feature_names=(),
        data_coverage_percent=100.0,
        source_availability_vector=(1,),
    )


def _sparse_tensor(*, usable_observations: int, inconsistent: bool = False) -> FeatureTensorRecord:
    feature_count = 10
    observed = max(0, min(feature_count, int(usable_observations)))
    missing_mask = tuple(0 if index < observed else 1 for index in range(feature_count))
    source_availability = tuple(
        1 if index < observed else 0 for index in range(feature_count)
    )
    return FeatureTensorRecord(
        tensor_id="tensor-sparse",
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot_id="snapshot-sparse",
        values=tuple(float(index + 1) if index < observed else 0.0 for index in range(feature_count)),
        missing_mask=missing_mask,
        stale_mask=tuple(0 for _ in range(feature_count)),
        source_availability=(source_availability[:-1] if inconsistent else source_availability),
        feature_names=tuple(f"optional_{index}" for index in range(feature_count)),
        source_labels=tuple("unit" for _ in range(feature_count)),
        missing_feature_names=tuple(
            f"optional_{index}" for index in range(observed, feature_count)
        ),
        stale_feature_names=(),
        data_coverage_percent=float(observed * 10),
        source_availability_vector=source_availability,
    )


def _trust_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "accepted_for_training": True,
        "candle_closed_confirmed": True,
        "mtf_snapshot_id": "mtf-temporal",
        "mtf_snapshot_valid": True,
        "mtf_snapshot_reject_reasons": [],
        "replay_snapshot_id": "replay-temporal",
        "feature_cutoff": FEATURE_CUTOFF,
        "available_at": AVAILABLE_AT,
        "decision_time": DECISION_TIME,
        # The model cutoffs need not be equal; each must simply precede the
        # decision that consumes it.
        "masa_feature_cutoff": FEATURE_CUTOFF,
        "ppo_feature_cutoff": AVAILABLE_AT,
        "label_available_at": LABEL_AVAILABLE_AT,
        "features": {"ret_pct": 0.1},
    }
    row.update(overrides)
    return row


def _example(**overrides: Any) -> TrainingExample:
    return TrainingExample(
        symbol="BTCUSDT",
        timeframe="1m",
        tensor=_tensor(),
        label_action_index=1,
        label_expected_move_after_cost_bps=1.0,
        payload_keys=("unit",),
        row_classification="TRAINABLE",
        trust_row=_trust_row(**overrides),
    )


def _archive_record() -> dict[str, Any]:
    features = {"close": 100.0}
    return build_archive_record(
        snapshot_id="snapshot-temporal",
        symbol="BTCUSDT",
        timeframe="1m",
        feature_cutoff=FEATURE_CUTOFF,
        decision_time=DECISION_TIME,
        available_at=AVAILABLE_AT,
        mtf_snapshot_id="mtf-temporal",
        features=features,
        missing_mask={"close": False},
        stale_mask={"close": False},
        source_availability={"ohlcv": True},
        source_hashes={"ohlcv": "hash"},
    )


def test_ppo_uses_canonical_v2_import_identity() -> None:
    assert (
        ppo_trainer.classify_training_sample
        is sample_rejection.classify_training_sample
    )


def test_sparse_but_proven_observation_reaches_mask_classification() -> None:
    tensor = _sparse_tensor(usable_observations=1)
    lineage = {
        "missing_feature_names": list(tensor.missing_feature_names),
        "missing_feature_count": len(tensor.missing_feature_names),
        "stale_feature_names": [],
        "stale_feature_count": 0,
        "source_availability": list(tensor.source_availability),
    }

    assert tensor.data_coverage_percent < 20.0
    assert _classification_from_lineage(tensor=tensor, lineage=lineage) == "MISSING_MASKED"


@pytest.mark.parametrize(
    "tensor",
    (
        _sparse_tensor(usable_observations=0),
        _sparse_tensor(usable_observations=1, inconsistent=True),
    ),
)
def test_zero_or_unverifiable_observation_evidence_stays_blocked(
    tensor: FeatureTensorRecord,
) -> None:
    assert _classification_from_lineage(tensor=tensor, lineage=None) == (
        "NO_VERIFIABLE_OBSERVED_FEATURE_EVIDENCE"
    )


@pytest.mark.parametrize(
    ("field_name", "reason"),
    (
        ("feature_cutoff", "FEATURE_CUTOFF_UNPARSEABLE"),
        ("decision_time", "DECISION_TIME_UNPARSEABLE"),
        ("available_at", "AVAILABLE_AT_UNPARSEABLE"),
    ),
)
def test_archive_rejects_timezone_naive_required_clocks(
    field_name: str,
    reason: str,
) -> None:
    record = _archive_record()
    record[field_name] = "2026-07-18T00:00:00"
    record["content_sha256"] = content_sha256(record)

    assert reason in verify_record(record)


def test_archive_does_not_substitute_feature_decision_time_for_decision_time() -> None:
    record = build_archive_record_from_prediction_payload(
        {
            "feature_snapshot_id": "snapshot-temporal",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "feature_cutoff": FEATURE_CUTOFF,
            "available_at": AVAILABLE_AT,
            "feature_decision_time": DECISION_TIME,
            "mtf_snapshot_id": "mtf-temporal",
            "source_hashes": {"feature": "hash"},
            "feature_snapshot": {"features": {"close": 100.0}},
        }
    )

    assert record is not None
    assert record["decision_time"] is None
    assert "MISSING_DECISION_TIME" in verify_record(record)


def test_generic_contract_accepts_distinct_causal_masa_and_ppo_cutoffs() -> None:
    reasons = _extra_contract_rejection_reasons(_trust_row())

    assert "MASA_PPO_CUTOFF_MISMATCH" not in reasons
    assert reasons == []


@pytest.mark.parametrize(
    ("overrides", "reason"),
    (
        ({"decision_time": None, "generated_at": DECISION_TIME}, "DECISION_TIME_MISSING"),
        ({"feature_cutoff": "2026-07-18T00:01:01Z"}, "FEATURE_CUTOFF_AFTER_DECISION_TIME"),
        ({"available_at": "2026-07-18T00:01:01Z"}, "AVAILABLE_AT_AFTER_DECISION_TIME"),
        (
            {"masa_feature_cutoff": "2026-07-18T00:01:01Z"},
            "MASA_FEATURE_CUTOFF_AFTER_PPO_DECISION_TIME",
        ),
        ({"label_available_at": "2026-07-18T00:02:00"}, "LABEL_AVAILABLE_AT_UNPARSEABLE"),
        ({"outcome_available_at": "not-a-clock"}, "OUTCOME_AVAILABLE_AT_UNPARSEABLE"),
    ),
)
def test_generic_contract_fails_closed_on_temporal_violations(
    overrides: dict[str, Any],
    reason: str,
) -> None:
    assert reason in _extra_contract_rejection_reasons(_trust_row(**overrides))


def test_feedback_contract_rejects_naive_required_clock() -> None:
    reasons = _feedback_trust_rejection_reasons(
        _trust_row(
            decision_time="2026-07-18T00:01:00",
            prediction_id="prediction-temporal",
            signal_id="signal-temporal",
            decision_id="decision-temporal",
            feature_snapshot_id="snapshot-temporal",
            symbol="BTCUSDT",
            timeframe="1m",
            selected_action="long",
            model_version="model-temporal",
            checkpoint_id="checkpoint-temporal",
            source_hashes={"feature": "hash"},
        )
    )

    assert "DECISION_TIME_UNPARSEABLE" in reasons


def test_high_confidence_loss_cannot_bypass_missing_trust_lineage() -> None:
    reasons = _feedback_trust_rejection_reasons(
        {
            "confidence_calibrated": 0.99,
            "high_confidence_loss": True,
            "outcome_label": "loss",
        }
    )

    assert "MISSING_TRUST_FEATURE_CUTOFF" in reasons
    assert "MISSING_TRUST_DECISION_TIME" in reasons
    assert "MISSING_TRUST_AVAILABLE_AT" in reasons


def test_closed_trade_cache_identity_isolated_by_archive_root_and_content(
    tmp_path: Path,
) -> None:
    row = {"trainer_feedback_id": "feedback-1"}
    content_hash = "a" * 64

    root_a_key = _closed_trade_example_cache_key(
        row,
        archive_root=tmp_path / "root-a",
        snapshot_content_sha256=content_hash,
    )
    root_b_key = _closed_trade_example_cache_key(
        row,
        archive_root=tmp_path / "root-b",
        snapshot_content_sha256=content_hash,
    )
    changed_content_key = _closed_trade_example_cache_key(
        row,
        archive_root=tmp_path / "root-a",
        snapshot_content_sha256="b" * 64,
    )

    assert len({root_a_key, root_b_key, changed_content_key}) == 3


def test_closed_trade_snapshot_prefers_verified_durable_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archived_record = _archive_record()
    append_snapshot(archived_record, root=tmp_path)
    mutable_copy = dict(archived_record)
    mutable_copy["features"] = {"close": 999.0}
    loader = V2HybridTrainerDataLoader(trusted_replay_archive_root=tmp_path)
    monkeypatch.setattr(loader, "_get", lambda _key: mutable_copy)

    snapshot, source = loader._closed_trade_feature_snapshot(  # noqa: SLF001
        row={},
        feature_snapshot_id="snapshot-temporal",
    )

    assert snapshot is not None
    assert snapshot["features"]["close"] == 100.0
    assert source == "durable_feature_snapshot_archive:snapshot-temporal"


def test_unanchored_mutable_snapshot_is_not_training_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mutable_record = _archive_record()
    loader = V2HybridTrainerDataLoader(trusted_replay_archive_root=tmp_path)
    monkeypatch.setattr(loader, "_get", lambda _key: mutable_record)

    snapshot, source = loader._closed_trade_feature_snapshot(  # noqa: SLF001
        row={},
        feature_snapshot_id="snapshot-temporal",
    )

    assert snapshot is None
    assert source is None


def test_mutable_snapshot_with_immutable_hash_anchor_can_recover_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mutable_record = _archive_record()
    loader = V2HybridTrainerDataLoader(trusted_replay_archive_root=tmp_path)
    monkeypatch.setattr(loader, "_get", lambda _key: mutable_record)

    snapshot, source = loader._closed_trade_feature_snapshot(  # noqa: SLF001
        row={
            "durable_feature_snapshot_archive_content_sha256": mutable_record[
                "content_sha256"
            ]
        },
        feature_snapshot_id="snapshot-temporal",
    )

    assert snapshot == mutable_record
    assert source == (
        "verified_mutable_equivalent:v2:features:snapshot:snapshot-temporal"
    )


@pytest.mark.parametrize(
    ("field_name", "value", "reason"),
    (
        ("label_available_at", "2026-07-18T00:02:00", "LABEL_AVAILABLE_AT_UNPARSEABLE"),
        ("outcome_available_at", True, "OUTCOME_AVAILABLE_AT_UNPARSEABLE"),
    ),
)
def test_feedback_contract_rejects_invalid_label_and_outcome_clocks(
    field_name: str,
    value: Any,
    reason: str,
) -> None:
    assert reason in _feedback_trust_rejection_reasons(
        _trust_row(**{field_name: value})
    )


@pytest.mark.parametrize(
    ("overrides", "reason"),
    (
        ({"decision_time": None, "generated_at": DECISION_TIME}, "DECISION_TIME_MISSING"),
        ({"feature_cutoff": "2026-07-18T00:01:01Z"}, "FEATURE_CUTOFF_AFTER_DECISION_TIME"),
        (
            {"masa_feature_cutoff": "2026-07-18T00:01:01Z"},
            "MASA_FEATURE_CUTOFF_AFTER_PPO_DECISION_TIME",
        ),
        ({"outcome_available_at": "2026-07-18T00:02:30"}, "OUTCOME_AVAILABLE_AT_UNPARSEABLE"),
    ),
)
def test_ppo_gate_fails_closed_on_temporal_violations(
    overrides: dict[str, Any],
    reason: str,
) -> None:
    example = _example(**overrides)
    trainer = V2HybridPPOTrainer(
        model=_FallbackModel(),
        training_observed_at=TRAINING_OBSERVED_AT,
    )

    reasons = trainer._extra_rejection_reasons(  # noqa: SLF001
        example,
        example.trust_row or {},
    )

    assert reason in reasons


def test_ppo_gate_accepts_distinct_causal_masa_and_ppo_cutoffs() -> None:
    example = _example()
    trainer = V2HybridPPOTrainer(
        model=_FallbackModel(),
        training_observed_at=TRAINING_OBSERVED_AT,
    )

    reasons = trainer._extra_rejection_reasons(  # noqa: SLF001
        example,
        example.trust_row or {},
    )

    assert "MASA_PPO_CUTOFF_MISMATCH" not in reasons
    assert not any("CUTOFF_AFTER" in reason for reason in reasons)
