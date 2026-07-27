from __future__ import annotations

from copy import deepcopy

import pytest

from v2.backend.app.services.adaptive_system.candidate_outcome_maturer_v2 import (
    LABELER_VERSION_SHA256,
    CandidateOutcomeMaturationError,
    CandidateOutcomeMaturationPending,
    counterfactual_reference_side,
    first_label_close_at_or_after,
    mature_candidate,
    required_label_range,
)
from v2.backend.tests.unit.services.adaptive_system.test_candidate_outcome_publisher_v2 import (
    _build,
    _inputs,
)


def _record():
    status, intents, snapshots = _inputs(1)
    intent = intents[0]
    intent.update(
        {
            "entry_price": 100.1,
            "paper_execution_mark_price": 100.0,
            "observed_bid": 99.9,
            "observed_ask": 100.1,
            "observed_spread_bps": 20.0,
            "fee_bps": 1.0,
            "expected_slippage_bps": 2.0,
            "expected_funding_bps": 0.5,
            "depth_derived_price_impact_bps": 3.0,
            "stop_distance_bps": 100.0,
            "expected_move_after_cost_bps": 80.0,
        }
    )
    return _build(status, intents, snapshots).decision_records[0]


def _hold_record():
    status, intents, snapshots = _inputs(1)
    intent = intents[0]
    intent.update(
        {
            "side": "HOLD",
            "selected_action": "HOLD",
            "allocator_decision": "BLOCK_POLICY_SELECTED_FLAT",
            "entry_price": 100.0,
            "paper_execution_mark_price": 100.0,
            "observed_bid": 99.9,
            "observed_ask": 100.1,
            "observed_spread_bps": 20.0,
            "fee_bps": 1.0,
            "expected_slippage_bps": 2.0,
            "expected_funding_bps": 0.5,
            "depth_derived_price_impact_bps": 3.0,
            "stop_distance_bps": 100.0,
            "expected_move_after_cost_bps": 0.0,
        }
    )
    return _build(status, intents, snapshots).decision_records[0]


def _rows_and_proof(record):
    start, end, expected = required_label_range(record)
    rows = []
    for index in range(expected):
        close_ms = start + index * 300_000
        close = 100.0 + index
        rows.append(
            {
                "symbol": record.decision.symbol,
                "timeframe": "5m",
                "candle_close_time": close_ms,
                "event_time": close_ms + 20,
                "ingested_at": close_ms + 30,
                "available_at": close_ms + 30,
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "is_closed": True,
                "candle_closed_confirmed": True,
                "feature_eligible": True,
                "candle_id": f"candle-{index}",
            }
        )
    proof = {
        "status": "VERIFIED_CANONICAL_5M_LABEL_RANGE",
        "symbol": record.decision.symbol,
        "start_close_time_ms": start,
        "end_close_time_ms": end,
        "expected_rows": expected,
        "loaded_rows": expected,
        "training_observed_at_ms": end + 1_000,
        "range_sha256": "a" * 64,
        "append_receipt_sha256": ["b" * 64],
        "postcommit_readback_receipt_sha256": ["c" * 64],
        "canonical_payloads_verified": True,
        "content_sha256_verified": True,
        "append_transaction_precommit_receipts_verified": True,
        "postcommit_readback_receipts_verified": True,
        "record_chain_formula_verified": True,
        "pit_available_at_verified": True,
        "contiguous_path_verified": True,
        "transaction_snapshot_verified": True,
    }
    return rows, proof


def test_slot_mapping_and_required_range_cover_exact_arbitrary_horizon() -> None:
    assert first_label_close_at_or_after(300_000 - 1) == 300_000 - 1
    assert first_label_close_at_or_after(300_000) == 600_000 - 1
    record = _record()
    start, end, expected = required_label_range(record)
    assert (start + 1) % 300_000 == 0
    assert (end + 1) % 300_000 == 0
    assert expected == ((end - start) // 300_000) + 1
    assert end >= record.decision.decision_time_ms + 3_600_000


def test_rejected_candidate_matures_complete_labels_without_paper_profit() -> None:
    record = _record()
    rows, proof = _rows_and_proof(record)
    matured = mature_candidate(
        record,
        rows=rows,
        proof=proof,
        label_generated_at_ms=proof["training_observed_at_ms"] + 1,
    )
    labels = matured.matured_labels
    assert labels is not None
    assert matured.archive_sequence == 2
    assert matured.previous_archive_record_sha256 == record.content_sha256()
    assert labels.eventual_disposition == "INFEASIBLE"
    assert labels.labeler_version_sha256 == LABELER_VERSION_SHA256
    assert labels.counts_as_paper_profit is False
    assert labels.actual_paper_outcome is None
    assert tuple(item.horizon_seconds for item in labels.horizon_labels) == (
        300,
        900,
        1_800,
        3_600,
    )
    assert all(
        scenario.counts_as_paper_profit is False
        and scenario.actual_accounting_effect is False
        for arm in labels.counterfactual_outcomes
        for scenario in arm.scenarios
    )
    assert labels.fees_bps == 2.0
    assert labels.slippage_bps == 4.0
    assert labels.market_impact_bps == 6.0


def test_hold_candidate_matures_balanced_missed_edge_without_realized_profit() -> None:
    record = _hold_record()
    rows, proof = _rows_and_proof(record)
    matured = mature_candidate(
        record,
        rows=rows,
        proof=proof,
        label_generated_at_ms=proof["training_observed_at_ms"] + 1,
    )
    labels = matured.matured_labels
    assert labels is not None
    unhedged = next(
        arm for arm in labels.counterfactual_outcomes if arm.arm_name == "unhedged"
    )
    alternative_side = next(
        arm
        for arm in labels.counterfactual_outcomes
        if arm.arm_name == "alternative_side"
    )
    scenario_by_side = {
        scenario.scenario_id.rsplit("-", 1)[-1]: scenario
        for scenario in alternative_side.scenarios
    }

    assert all(scenario.gross_pnl_bps == 0.0 for scenario in unhedged.scenarios)
    assert set(scenario_by_side) == {"LONG", "SHORT"}
    assert scenario_by_side["LONG"].gross_pnl_bps == pytest.approx(
        -scenario_by_side["SHORT"].gross_pnl_bps
    )
    assert labels.counts_as_paper_profit is False
    assert labels.actual_paper_outcome is None
    assert counterfactual_reference_side(record.decision.candidate_id) in {
        "LONG",
        "SHORT",
    }


def test_maturation_is_deterministic_for_identical_evidence_and_time() -> None:
    record = _record()
    rows, proof = _rows_and_proof(record)
    first = mature_candidate(
        record,
        rows=rows,
        proof=proof,
        label_generated_at_ms=proof["training_observed_at_ms"] + 1,
    )
    second = mature_candidate(
        record,
        rows=deepcopy(rows),
        proof=deepcopy(proof),
        label_generated_at_ms=proof["training_observed_at_ms"] + 1,
    )
    assert first == second
    assert first.content_sha256() == second.content_sha256()


def test_range_gaps_future_availability_and_unverified_proof_fail_closed() -> None:
    record = _record()
    rows, proof = _rows_and_proof(record)
    rows.pop(1)
    with pytest.raises(CandidateOutcomeMaturationError, match="exact_row_count_required"):
        mature_candidate(
            record,
            rows=rows,
            proof=proof,
            label_generated_at_ms=proof["training_observed_at_ms"] + 1,
        )

    rows, proof = _rows_and_proof(record)
    rows[-1]["available_at"] = proof["training_observed_at_ms"] + 1
    with pytest.raises(CandidateOutcomeMaturationError, match="available_after_observation"):
        mature_candidate(
            record,
            rows=rows,
            proof=proof,
            label_generated_at_ms=proof["training_observed_at_ms"] + 2,
        )

    rows, proof = _rows_and_proof(record)
    proof["status"] = "BLOCKED_CANONICAL_5M_LABEL_ARCHIVE_MISSING"
    with pytest.raises(CandidateOutcomeMaturationPending, match="verified_complete_range_required"):
        mature_candidate(
            record,
            rows=rows,
            proof=proof,
            label_generated_at_ms=proof["training_observed_at_ms"] + 1,
        )


def test_selected_trade_waits_for_real_close_and_accounting() -> None:
    status, intents, snapshots = _inputs(1)
    intent = intents[0]
    intent.update(
        {
            "paper_fill_allowed": True,
            "allocator_decision": "ALLOW_WITH_SIZE",
            "entry_price": 100.1,
            "paper_execution_mark_price": 100.0,
            "observed_bid": 99.9,
            "observed_ask": 100.1,
            "observed_spread_bps": 20.0,
            "fee_bps": 1.0,
            "expected_slippage_bps": 2.0,
            "expected_funding_bps": 0.5,
            "depth_derived_price_impact_bps": 3.0,
        }
    )
    record = _build(status, intents, snapshots).decision_records[0]
    rows, proof = _rows_and_proof(record)
    with pytest.raises(
        CandidateOutcomeMaturationPending,
        match="reconciled_actual_paper_close_required",
    ):
        mature_candidate(
            record,
            rows=rows,
            proof=proof,
            label_generated_at_ms=proof["training_observed_at_ms"] + 1,
        )
