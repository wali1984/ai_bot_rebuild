from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from v2.backend.app.services.native_trainer.profiled_model_feature_snapshot_record_v1 import (
    PHYSICAL_MODEL_FEATURE_COUNT,
)
from v2.backend.app.services.native_trainer.profiled_pit_replay_projection_v1 import (
    ProfiledPitReplayProjectionV1Error,
    project_profiled_training_sample_to_replay_snapshot_v1,
)
from v2.backend.app.services.native_trainer.profiled_training_ledger_loader_v1 import (
    ProfiledTrainingLedgerSampleV1,
)


def _clock(minutes: int) -> str:
    return (
        (datetime(2026, 7, 1, tzinfo=UTC) + timedelta(minutes=minutes))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _sample() -> ProfiledTrainingLedgerSampleV1:
    """Build the already-admitted loader output boundary without bypassing it."""

    sample = object.__new__(ProfiledTrainingLedgerSampleV1)
    digest = "a" * 64
    values: dict[str, object] = {
        "sequence": 17,
        "durable_snapshot_id": "feature_snapshot_v3_" + digest,
        "record_sha256": digest,
        "frozen_envelope_sha256": "b" * 64,
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "feature_snapshot_id": "feature_snapshot_v3_" + digest,
        "decision_time": _clock(10),
        "feature_cutoff": _clock(8),
        "generated_at": _clock(9),
        "parent_durable_snapshot_id": "feature_snapshot_v3_" + ("c" * 64),
        "parent_record_sha256": "c" * 64,
        "parent_lineage_binding_sha256": "d" * 64,
        "cost_capture_binding_sha256": "e" * 64,
        "cost_capture_artifact_sha256": "f" * 64,
        "cost_capture_receipt_sha256": "1" * 64,
        "cost_cas_object_inventory_sha256": "2" * 64,
        "auxiliary_feature_receipt_sha256s": ("3" * 64,) * 4,
        "expected_holding_horizon_seconds": 900,
        "cost_evidence_available_at": _clock(9),
        "decision_reference_price": 100.0,
        "decision_reference_best_bid": 99.9,
        "decision_reference_best_ask": 100.1,
        "decision_reference_full_spread_bps": 20.0,
        "decision_reference_price_source": "AUTHENTICATED_CAUSAL_COST_ORDERBOOK_DEPTH_CAS_MID",
        "decision_reference_price_available_at": _clock(9),
        "decision_reference_price_binding_sha256": "4" * 64,
        "decision_reference_price_payload_sha256": "5" * 64,
        "decision_reference_price_receipt_sha256": "6" * 64,
        "physical_feature_values": tuple(
            float(index + 1) for index in range(PHYSICAL_MODEL_FEATURE_COUNT)
        ),
        "auxiliary_label_values": (1.0, 2.0, 0.5, 1.0),
        "postcommit_readback_at": _clock(11),
        "trainer_admission_authorized": True,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
        "runtime_wired": False,
    }
    for name, value in values.items():
        object.__setattr__(sample, name, value)
    return sample


def _label() -> dict[str, object]:
    return {
        "schema_version": "profiled_training_finalized_label_binding_v1",
        "label_binding_sha256": "7" * 64,
        "directional_cost_evidence_sha256": "8" * 64,
        "label_path_sha256": "9" * 64,
        "label_range_sha256": "0" * 64,
        "decision_time": _clock(10),
        "label_available_at": _clock(25),
        "label_horizon_seconds": 900,
        "label_target_action": "short",
        "future_labels_not_in_feature_tensor": True,
        "auxiliary_cost_values_excluded_from_model_vector": True,
        "static_action_threshold_used": False,
        "directional_cost_evidence": {
            "fee_bps_per_side": 1.0,
            "full_spread_bps": 2.0,
            "expected_slippage_bps_per_side": 0.5,
            "signed_expected_funding_bps": 1.0,
            "long_round_trip_cost_bps": 6.0,
            "short_round_trip_cost_bps": 4.0,
            "raw_return_bps": -10.0,
            "long_net_bps": -16.0,
            "short_net_bps": 6.0,
        },
    }


def test_projection_preserves_pit_features_and_action_specific_canonical_label() -> None:
    record = project_profiled_training_sample_to_replay_snapshot_v1(
        sample=_sample(),
        label_binding=_label(),
    )

    projection = record["pit_replay_projection"]
    assert record["available_at"] == _clock(9)
    assert record["decision_time"] == _clock(10)
    assert record["candle_closed_confirmed"] is True
    assert record["latest_unclosed_kline_excluded"] is True
    assert "directional_cost_evidence" not in record["features"]
    assert projection["label_binding"]["label_available_at"] == _clock(25)
    assert projection["action_specific_cost_evidence"]["long_round_trip_cost_bps"] == 6.0
    assert projection["action_specific_cost_evidence"]["short_round_trip_cost_bps"] == 4.0
    assert projection["prediction_authorized"] is False


def test_projection_rejects_mismatched_action_specific_cost_economics() -> None:
    label = _label()
    cost = dict(label["directional_cost_evidence"])
    cost["short_round_trip_cost_bps"] = 5.0
    label["directional_cost_evidence"] = cost

    with pytest.raises(
        ProfiledPitReplayProjectionV1Error,
        match="PROFILED_PIT_REPLAY_PROJECTION_DIRECTIONAL_COST_ECONOMICS_INVALID",
    ):
        project_profiled_training_sample_to_replay_snapshot_v1(
            sample=_sample(),
            label_binding=label,
        )
