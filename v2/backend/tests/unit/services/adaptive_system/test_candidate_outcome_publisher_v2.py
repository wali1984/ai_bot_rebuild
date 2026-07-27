from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from v2.backend.app.services.adaptive_system.candidate_outcome_publisher_v2 import (
    CandidateOutcomePublisherError,
    build_publisher_cycle,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    build_archive_record,
    content_sha256,
)

_CHECKPOINT_ID = "SERVING_ABI_V2_PAPER_fixture"
_CHECKPOINT_SHA = "1" * 64
_WEIGHT_SHA = "2" * 64
_MODEL_FINGERPRINT = "3" * 64
_FEATURE_ABI_SHA = "4" * 64
_POLICY_SHA = "5" * 64
_SOURCE_SHA = "6" * 64


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _sealed(material: dict[str, object], hash_field: str) -> dict[str, object]:
    result = deepcopy(material)
    result[hash_field] = _digest(material)
    return result


def _registry() -> dict[str, object]:
    return {
        "registry_generation": 3,
        "checkpoint_id": _CHECKPOINT_ID,
        "checkpoint_bundle_sha256": _CHECKPOINT_SHA,
        "feature_abi_sha256": _FEATURE_ABI_SHA,
        "receipt_id": "activation-receipt-fixture",
        "paper_only": True,
        "live_eligible": False,
        "checkpoint_bundle": {
            "weight_sha256": _WEIGHT_SHA,
            "model_parameter_fingerprint": _MODEL_FINGERPRINT,
        },
    }


def _snapshot(index: int) -> dict[str, object]:
    return build_archive_record(
        snapshot_id=f"snapshot-{index}",
        symbol="BTCUSDT",
        timeframe="5m",
        feature_cutoff="2026-07-27T20:00:00.000Z",
        decision_time="2026-07-27T20:00:10.000642Z",
        available_at="2026-07-27T20:00:02.000Z",
        mtf_snapshot_id=f"mtf-{index}",
        features={"close": 100.0 + index},
        missing_mask={"close": False},
        stale_mask={"close": False},
        source_availability={"close": "2026-07-27T20:00:01.000Z"},
        source_hashes={"feature_vector_hash": _SOURCE_SHA},
        created_at="2026-07-27T20:00:10Z",
        extra={
            "checkpoint_id": _CHECKPOINT_ID,
            "candle_closed_confirmed": True,
            "latest_unclosed_kline_excluded": True,
            "latest_unclosed_exclusion_method": "CLOSED_KLINE_FILTER_V1",
            "latest_unclosed_exclusion_decision_time_ms": 1_785_182_401_000,
            "latest_closed_kline_close_time_ms": 1_785_182_400_000,
        },
    )


def _intent(index: int) -> dict[str, object]:
    prediction_id = f"prediction-{index}"
    snapshot_id = f"snapshot-{index}"
    base_resource = _sealed(
        {
            "schema_version": "paper_cycle_base_resource_evidence_v1",
            "status": "READY",
            "equity_usd": 3_000.0,
            "available_margin_usd": 3_000.0,
            "drawdown_bps": 0.0,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "rejection_reasons": [],
        },
        "evidence_hash",
    )
    dynamic = _sealed(
        {
            "schema_version": "paper_dynamic_envelope_reservation_evidence_v1",
            "status": "READY",
            "limits": {"max_effective_leverage": 1.0},
            "source_evidence": {
                "candidate_symbol": "BTCUSDT",
                "decision_time": "2026-07-27T20:00:10.000Z",
                "growth_authorization_status": "BLOCKED",
                "growth_authorization_receipt_hash": _SOURCE_SHA,
                "growth_authorization_receipt": {"receipt_id": "growth-fixture"},
                "growth_authorization_rejection_reasons": ["INSUFFICIENT_EVIDENCE"],
            },
            "calculation_input_material": {
                "schema_version": "paper_dynamic_envelope_calculation_input_v2",
                "arguments": {"paper_mode": True, "symbol": "BTCUSDT"},
                "base_envelope": {"max_effective_leverage": 1.0},
                "growth_authorization_receipt_hash": _SOURCE_SHA,
            },
            "calculation_input_hash": _SOURCE_SHA,
            "rejection_reasons": [],
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        },
        "evidence_hash",
    )
    reservation = _sealed(
        {
            "schema_version": "paper_cycle_reservation_snapshot_v1",
            "status": "PASS",
            "candidate_symbol": "BTCUSDT",
            "cycle_identity": f"cycle-{index}",
            "prior_accepted_count": 0,
            "prior_reservations": [],
            "accounting_semantics": {"resource_arithmetic_authority": "EXACT_DECIMAL"},
            "inputs": {"base_equity_usd": 3_000.0},
            "derived": {"remaining_margin_after_buffer_usd": 2_500.0},
            "evidence_bindings": {
                "base_resource_evidence_hash": base_resource["evidence_hash"],
                "dynamic_envelope_evidence_hash": dynamic["evidence_hash"],
            },
            "rejection_reasons": [],
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        },
        "snapshot_hash",
    )
    return {
        "candidate_id": "legacy-model-candidate-id-shared-by-every-row",
        "policy_id": "paper-policy-v2",
        "policy_fingerprint": _POLICY_SHA,
        "prediction_id": prediction_id,
        "preemptive_decision_id": f"preemptive-{index}",
        "checkpoint_id": _CHECKPOINT_ID,
        "checkpoint_generation": 3,
        "feature_abi_sha256": _FEATURE_ABI_SHA,
        "entry_feature_snapshot_id": snapshot_id,
        "feature_snapshot_id": snapshot_id,
        "feature_cutoff": "2026-07-27T20:00:00.000Z",
        "decision_time": "2026-07-27T20:00:10.000Z",
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "side": "LONG",
        "selected_action": "LONG",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "paper_fill_allowed": False,
        "allocator_decision": "BLOCK_EXCHANGE_MIN_ORDER",
        "source_row_canonical_sha256": _SOURCE_SHA,
        "paper_cycle_base_resource_evidence": base_resource,
        "paper_cycle_base_resource_evidence_hash": base_resource["evidence_hash"],
        "paper_dynamic_envelope_reservation_evidence": dynamic,
        "paper_dynamic_envelope_reservation_evidence_hash": dynamic["evidence_hash"],
        "paper_cycle_reservation_snapshot": reservation,
        "paper_cycle_reservation_snapshot_hash": reservation["snapshot_hash"],
        "entry_prediction_snapshot": {
            "prediction_id": prediction_id,
            "symbol": "BTCUSDT",
            "timeframe": "5m",
            "feature_snapshot_id": snapshot_id,
            "feature_cutoff": "2026-07-27T20:00:00.000Z",
            "decision_time": "2026-07-27T20:00:10.000Z",
            "available_at": "2026-07-27T20:00:02.000Z",
            "checkpoint_id": _CHECKPOINT_ID,
            "source_hashes": {"feature_vector_hash": _SOURCE_SHA},
        },
    }


def _inputs(count: int = 2):
    intents = [_intent(index) for index in range(count)]
    snapshots = {f"snapshot-{index}": _snapshot(index) for index in range(count)}
    matrix_rows = [
        {
            "prediction_id": row["prediction_id"],
            "preemptive_decision_id": row["preemptive_decision_id"],
            "checkpoint_id": row["checkpoint_id"],
        }
        for row in intents
    ]
    status = {
        "generated_utc": "2026-07-27T20:01:00.000Z",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "preemptive_candidate_decision_matrix": {
            "schema_version": "preemptive_candidate_decision_matrix_v1",
            "generated_utc": "2026-07-27T20:00:59.000Z",
            "candidate_count": count,
            "rows": matrix_rows,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        },
    }
    return status, intents, snapshots


def _build(status, intents, snapshots):
    return build_publisher_cycle(
        paper_status=status,
        intents=intents,
        registry_payload=_registry(),
        feature_snapshots_by_id=snapshots,
    )


def test_exact_cycle_records_every_candidate_with_unique_decision_identity() -> None:
    status, intents, snapshots = _inputs()
    cycle = _build(status, intents, snapshots)
    assert cycle.source_candidate_count == 2
    assert len(cycle.decision_records) == 2
    assert cycle.candidate_recording_coverage == 1.0
    assert cycle.unexplained_candidate_drops == 0
    assert len({row.decision.candidate_id for row in cycle.decision_records}) == 2
    assert {row.decision.decision_disposition for row in cycle.decision_records} == {
        "INFEASIBLE"
    }
    assert all(row.paper_only is True for row in cycle.decision_records)
    assert all(row.routes_to_live is False for row in cycle.decision_records)


def test_compact_intent_may_omit_finality_and_abi_when_durable_sources_prove_them() -> None:
    status, intents, snapshots = _inputs(1)
    for field in (
        "feature_abi_sha256",
        "entry_feature_latest_closed_kline_close_time_ms",
        "entry_feature_latest_unclosed_kline_excluded",
        "entry_feature_latest_unclosed_exclusion_method",
        "entry_feature_latest_unclosed_exclusion_decision_time_ms",
    ):
        intents[0].pop(field, None)
    record = _build(status, intents, snapshots).decision_records[0]
    assert record.decision.latest_unclosed_kline_excluded is True
    assert record.decision.latest_closed_kline_close_time_ms == 1_785_182_400_000
    model_payload = json.loads(record.decision.model_distributions.payload_json)
    assert _FEATURE_ABI_SHA in model_payload["candidate_source_receipt_sha256s"]
    assert snapshots["snapshot-0"]["content_sha256"] in model_payload[
        "candidate_source_receipt_sha256s"
    ]
    assert len(record.decision.model_distributions.source_receipt_sha256s) == 1


def test_truncated_matrix_and_mismatched_universe_fail_closed() -> None:
    status, intents, snapshots = _inputs()
    status["preemptive_candidate_decision_matrix"]["rows"].pop()
    with pytest.raises(CandidateOutcomePublisherError, match="diagnostic_matrix_truncated"):
        _build(status, intents, snapshots)

    status, intents, snapshots = _inputs()
    intents[0]["preemptive_decision_id"] = "different-preemptive-id"
    with pytest.raises(CandidateOutcomePublisherError, match="identity_universe_mismatch"):
        _build(status, intents, snapshots)


def test_missing_or_mutated_durable_snapshot_fails_closed() -> None:
    status, intents, snapshots = _inputs(1)
    with pytest.raises(CandidateOutcomePublisherError, match="schema_mismatch"):
        _build(status, intents, {})

    snapshots["snapshot-0"]["latest_unclosed_kline_excluded"] = False
    with pytest.raises(CandidateOutcomePublisherError, match="content_digest_mismatch"):
        _build(status, intents, snapshots)


def test_rehashed_contradictory_finality_and_future_availability_fail_closed() -> None:
    status, intents, snapshots = _inputs(1)
    snapshot = snapshots["snapshot-0"]
    snapshot["latest_unclosed_kline_excluded"] = False
    snapshot["content_sha256"] = content_sha256(snapshot)
    with pytest.raises(CandidateOutcomePublisherError, match="must_be_true"):
        _build(status, intents, snapshots)

    status, intents, snapshots = _inputs(1)
    snapshot = snapshots["snapshot-0"]
    snapshot["available_at"] = "2026-07-27T20:00:11.000Z"
    intents[0]["entry_prediction_snapshot"]["available_at"] = (
        "2026-07-27T20:00:11.000Z"
    )
    snapshot["content_sha256"] = content_sha256(snapshot)
    with pytest.raises(CandidateOutcomePublisherError, match="clock_order_invalid"):
        _build(status, intents, snapshots)


def test_snapshot_producer_decision_may_precede_later_candidate_decision() -> None:
    status, intents, snapshots = _inputs(1)
    snapshot = snapshots["snapshot-0"]
    snapshot["decision_time"] = "2026-07-27T20:00:05.000Z"
    snapshot["content_sha256"] = content_sha256(snapshot)
    cycle = _build(status, intents, snapshots)
    assert cycle.candidate_recording_coverage == 1.0


def test_snapshot_producer_decision_after_candidate_fails_closed() -> None:
    status, intents, snapshots = _inputs(1)
    snapshot = snapshots["snapshot-0"]
    snapshot["decision_time"] = "2026-07-27T20:00:11.000Z"
    snapshot["content_sha256"] = content_sha256(snapshot)
    with pytest.raises(
        CandidateOutcomePublisherError,
        match="source_decision_after_candidate_decision",
    ):
        _build(status, intents, snapshots)


def test_registry_and_live_authority_mismatches_fail_closed() -> None:
    status, intents, snapshots = _inputs(1)
    intents[0]["feature_abi_sha256"] = "9" * 64
    with pytest.raises(CandidateOutcomePublisherError, match="feature_abi_mismatch"):
        _build(status, intents, snapshots)

    status, intents, snapshots = _inputs(1)
    intents[0]["places_real_order"] = True
    with pytest.raises(CandidateOutcomePublisherError, match="must_be_false"):
        _build(status, intents, snapshots)


def test_optional_compact_finality_cannot_contradict_durable_archive() -> None:
    status, intents, snapshots = _inputs(1)
    intents[0]["entry_feature_latest_closed_kline_close_time_ms"] = 1
    with pytest.raises(CandidateOutcomePublisherError, match="durable_feature_snapshot_mismatch"):
        _build(status, intents, snapshots)


def test_portfolio_sources_are_hash_verified_and_projected_without_nested_receipt_copy() -> None:
    status, intents, snapshots = _inputs(1)
    record = _build(status, intents, snapshots).decision_records[0]
    payload = json.loads(record.decision.portfolio_state.payload_json)
    assert payload["base_resource"]["equity_usd"] == 3_000.0
    assert payload["reservation"]["derived"]["remaining_margin_after_buffer_usd"] == (
        2_500.0
    )
    assert payload["dynamic_envelope"]["source_evidence"][
        "growth_authorization_status"
    ] == "BLOCKED"
    assert "growth_authorization_receipt" not in payload["dynamic_envelope"][
        "source_evidence"
    ]
    assert len(record.decision.portfolio_state.payload_json) < 10_000

    intents[0]["paper_dynamic_envelope_reservation_evidence"]["limits"][
        "max_effective_leverage"
    ] = 2.0
    with pytest.raises(CandidateOutcomePublisherError, match="producer_hash_mismatch"):
        _build(status, intents, snapshots)


def test_source_payloads_are_not_mutated() -> None:
    status, intents, snapshots = _inputs(1)
    before = deepcopy((status, intents, snapshots))
    _build(status, intents, snapshots)
    assert (status, intents, snapshots) == before
