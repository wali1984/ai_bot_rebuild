"""Tests for preserving the first allocator pass before tier reduction."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from v2.backend.app.cli import v2_trade_management_paper_loop as paper_loop


def _sealed_normal_and_reduced(monkeypatch):
    normal_decision = "2026-07-17T12:00:01Z"
    normal_pit = {
        "status": "PASS",
        "decision_time": normal_decision,
        "observed_component_times": {
            "entry_price_utc": "2026-07-17T12:00:00Z",
        },
        "rejection_reasons": [],
    }
    intent = {
        "paper_allocation_decision_time": normal_decision,
        "paper_allocation_point_in_time_status": "PASS",
        "paper_allocation_point_in_time_evidence": normal_pit,
        "paper_opportunity_tier": paper_loop.PAPER_TIER_B_GRADE_EXPLORATION,
        "paper_opportunity_tier_reason": "B_GRADE_EXPLORATION_ALLOWED_PAPER_ONLY",
        "paper_fill_allowed_source": "B_GRADE_EXPLORATION_PAPER_GATE",
        "risk_budget_fraction_of_normal_adaptive": 0.1,
        "paper_entry_gate_evaluation_hash": "1" * 64,
        "paper_entry_gate_evaluated_at": "2026-07-17T12:00:03Z",
        "a_plus_gate_evaluation_hash": "2" * 64,
        "a_plus_gate_evaluated_at": "2026-07-17T12:00:04Z",
        "preemptive_decision_id": "pec_normal_contract",
        "preemptive_input_hash": "3" * 64,
        "preemptive_decision_time": "2026-07-17T12:00:02Z",
    }
    normal = {
        "allocation_id": "alloc_normal_contract",
        "allocation_hash": "4" * 64,
        "allocation_input_hash": "5" * 64,
        "target_quantity": 0.02,
        "target_notional_usd": 2000.0,
        "target_notional_usdt": 2000.0,
        "gross_notional_usd": 2000.0,
        "risk_budget_usd": 20.0,
        "expected_max_loss_usd": 20.0,
        "effective_leverage": 2.0,
        "recommended_leverage": 2.0,
        "allocated_margin_usd": 1000.0,
        "recommended_margin_mode": "isolated_paper_simulated",
        "margin_mode_simulated": "isolated_paper_simulated",
    }
    paper_loop._seal_paper_allocator_economic_contract(  # noqa: SLF001
        intent=intent,
        allocation=normal,
        sealed_at=datetime(2026, 7, 17, 12, 0, 1, 500000, tzinfo=timezone.utc),
    )
    intent["normal_adaptive_allocation_id"] = normal["allocation_id"]
    intent["normal_adaptive_allocation_input_hash"] = normal[
        "allocation_input_hash"
    ]
    intent["normal_adaptive_allocator_economic_contract_hash"] = intent[
        "paper_allocator_economic_contract_hash"
    ]
    monkeypatch.setattr(
        paper_loop,
        "_utc_iso",
        lambda: "2026-07-17T12:00:04.500000Z",
    )
    paper_loop._seal_paper_normal_allocation_before_reduction(  # noqa: SLF001
        intent=intent,
        normal_allocation=normal,
    )

    reduced_decision = "2026-07-17T12:00:05Z"
    reduced_pit = {
        "status": "PASS",
        "decision_time": reduced_decision,
        "observed_component_times": {
            "entry_price_utc": "2026-07-17T12:00:00Z",
        },
        "rejection_reasons": [],
    }
    intent["paper_allocation_decision_time"] = reduced_decision
    intent["paper_reduced_allocation_decision_time"] = reduced_decision
    intent["paper_allocation_point_in_time_evidence"] = reduced_pit
    intent["paper_reduced_allocation_point_in_time_evidence_hash"] = (
        paper_loop._paper_canonical_sha256(reduced_pit)  # noqa: SLF001
    )
    reduced = {
        "allocation_id": "alloc_reduced_contract",
        "normal_adaptive_allocation_id": normal["allocation_id"],
        "normal_adaptive_allocation_input_hash": normal["allocation_input_hash"],
        "normal_adaptive_allocator_economic_contract_hash": intent[
            "normal_adaptive_allocator_economic_contract_hash"
        ],
    }
    for field in (
        "normal_adaptive_allocation_decision_time",
        "normal_adaptive_allocation_point_in_time_evidence_hash",
        "normal_adaptive_allocation_contract_hash",
        "normal_adaptive_allocation_contract_sealed_at",
        "normal_adaptive_allocator_economic_contract_receipt_hash",
        "normal_adaptive_allocator_economic_contract_sealed_at",
        "paper_reduced_allocation_decision_time",
        "paper_reduced_allocation_point_in_time_evidence_hash",
    ):
        reduced[field] = intent[field]
    for field in paper_loop.B_GRADE_EXPLORATION_SCALABLE_ALLOCATION_FIELDS:
        if field in normal:
            reduced[f"normal_adaptive_{field}"] = normal[field]
    return intent, reduced


def test_normal_allocation_contract_round_trips_before_reduction(monkeypatch) -> None:
    intent, reduced = _sealed_normal_and_reduced(monkeypatch)

    assert paper_loop._paper_normal_allocation_contract_rejection_reasons(  # noqa: SLF001
        intent,
        reduced,
    ) == []


def test_normal_allocation_contract_detects_reduction_authority_mutation(
    monkeypatch,
) -> None:
    intent, reduced = _sealed_normal_and_reduced(monkeypatch)
    mutated = deepcopy(intent)
    mutated["risk_budget_fraction_of_normal_adaptive"] = 0.2

    reasons = paper_loop._paper_normal_allocation_contract_rejection_reasons(  # noqa: SLF001
        mutated,
        reduced,
    )

    assert "NORMAL_ALLOCATION_REDUCTION_AUTHORITY_MISMATCH" in reasons
