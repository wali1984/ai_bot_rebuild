"""Authentic PAPER growth-receipt fixtures for allocator boundary tests."""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any, cast

from v2.backend.app.cli import v2_trade_management_paper_loop as paper_loop
from v2.backend.app.services.adaptive_capital_allocator import (
    AllocationInput,
    AllocationResult,
    RiskEnvelope,
)
from v2.backend.app.services.adaptive_capital_allocator.allocator import (
    PAPER_ALLOCATOR_LIQUIDITY_SOURCE_HASH_LINEAGE_KEY,
    PAPER_ALLOCATOR_LIQUIDITY_SOURCE_MATERIAL_LINEAGE_KEY,
    PAPER_ALLOCATOR_REGIME_SOURCE_HASH_LINEAGE_KEY,
    PAPER_ALLOCATOR_REGIME_SOURCE_MATERIAL_LINEAGE_KEY,
    PAPER_GROWTH_ENVELOPE_AUTHORIZATION_HASH_LINEAGE_KEY,
    PAPER_GROWTH_ENVELOPE_AUTHORIZATION_LINEAGE_KEY,
)
from v2.backend.app.services.adaptive_capital_allocator.dynamic_envelope import (
    calculate_dynamic_risk_envelope,
)

DECISION_TIME = "2026-07-19T12:00:01Z"
CHECKPOINT_ID = "allocator-test-promoted-checkpoint"


def promoted_trainer_status(
    checkpoint_id: str = CHECKPOINT_ID,
) -> dict[str, Any]:
    return {
        "schema_version": "v2_native_rl_masa_ppo_cuda_trainer_status_v1",
        "generated_utc": "2026-07-19T12:00:00Z",
        "status_payload_expires_at": "2026-07-19T12:10:00Z",
        "status_publication_status": "ACTIVE",
        "cycle_id": "allocator-test-cycle",
        "process_instance_id": "allocator-test-process",
        "status_publication": {
            "schema_version": "v2_trainer_expiring_status_publication_v1",
            "publication_complete": True,
            "component_results": {
                "blocked_staging_status": True,
                "heartbeat": True,
                "metrics": True,
                "feature_schema_status": True,
                "status": True,
            },
            "generated_utc": "2026-07-19T12:00:00Z",
            "expires_at": "2026-07-19T12:10:00Z",
            "cycle_id": "allocator-test-cycle",
            "process_instance_id": "allocator-test-process",
        },
        "current_cycle_learning_envelope_identity": {
            "cycle_id": "allocator-test-cycle",
            "process_instance_id": "allocator-test-process",
            "checkpoint_id": checkpoint_id,
            "candidate_policy_fingerprint": "a" * 64,
            "envelope_sha256": "d" * 64,
        },
        "runtime_readiness_status": "READY",
        "trainer_learning_ready": True,
        "checkpoint_id": checkpoint_id,
        "candidate_policy_fingerprint": "a" * 64,
        "checkpoint_promotion_allowed": True,
        "checkpoint_promotion_reason": ("PIT_EDGE_CONFIDENCE_PARETO_SERVING_PROMOTION_PASS"),
        "mandatory_pit_edge_gate_passed": True,
        "validation_split_pit_safe": True,
        "validation_policy_edge_status": "VALID",
        "validation_policy_edge_after_cost_bps": 20.0,
        "validation_policy_edge_lower_confidence_bound_bps": 10.0,
        "validation_policy_edge_rows_evaluated": 30,
        "model_serving_allowed": True,
        "model_serving_source": "VERIFIED_PROMOTED_SERVING_CHECKPOINT",
        "current_cycle_verified_serving_checkpoint_evidence": {
            "checkpoint_artifact_verified": True,
            "causal_order_verified": True,
            "lineage_kind": "VERIFIED_SERVING_POLICY",
            "checkpoint_id": checkpoint_id,
            "parent_checkpoint_id": "allocator-test-parent",
            "model_parameter_fingerprint": "a" * 64,
            "parent_policy_fingerprint": "c" * 64,
            "weight_file_sha256": "b" * 64,
            "exact_optimizer_contract_durable": True,
            "ledger_disposition": "SERVING_PROMOTED",
            "generated_utc": "2026-07-19T11:59:00Z",
            "manager_semantic_verification_recomputed_this_cycle": True,
        },
    }


def strict_growth_performance_status() -> dict[str, Any]:
    closed_rows = []
    for index in range(30):
        realized_bps = 50.0 if index < 24 else -10.0
        closed_rows.append(
            {
                "paper_only": True,
                "position_id": f"strict-position-{index:02d}",
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "side": "long",
                "paper_opportunity_tier": "POSITIVE_EDGE_PROBATION_PAPER",
                "realized_net_pnl_bps": realized_bps,
                "realized_net_pnl_usd": realized_bps / 100.0,
                "outcome_event_time": "2026-07-19T11:58:00Z",
                "exit_price_utc": "2026-07-19T11:58:30Z",
                "outcome_available_at": "2026-07-19T11:59:30Z",
                "gross_notional_usd": 100.0,
            }
        )
    return cast(
        dict[str, Any],
        paper_loop._paper_performance_circuit_breaker_status(  # noqa: SLF001
            closed_rows,
            generated_utc=DECISION_TIME,
        ),
    )


def authorize_growth(
    row: AllocationInput,
    configured_base: RiskEnvelope | None = None,
) -> tuple[AllocationInput, RiskEnvelope, dict[str, Any]]:
    """Bind exact component receipts and return their replayed envelope."""

    base = configured_base or RiskEnvelope()
    symbol = str(row.symbol).strip().upper()
    timeframe = str(row.timeframe).strip().lower()
    signal: dict[str, Any] = {}
    market_microstructure = {"liquidity_score": row.liquidity_score}
    intent: dict[str, Any] = {
        "allocator_market_evidence_status": "READY",
        "regime_score": row.regime_score,
        "microstructure_trust_score": 1.0,
        "microstructure_adaptive_minimum": 0.5,
        "microstructure_action": "ALLOW",
    }
    liquidity, liquidity_source, liquidity_reason = paper_loop._derive_allocator_liquidity_score(  # noqa: SLF001
        intent={},
        signal=signal,
        prediction={},
        features={},
        market_microstructure=market_microstructure,
        spread_bps=row.spread_bps,
        feature_source_name="allocator-test-final-feature",
    )
    regime, regime_source, regime_reason = paper_loop._derive_allocator_regime_score(  # noqa: SLF001
        intent=dict(intent),
        signal=signal,
        prediction={},
        features={},
        feature_source_name="allocator-test-final-feature",
    )
    assert liquidity == row.liquidity_score
    assert regime == row.regime_score
    liquidity_material, regime_material = paper_loop._paper_allocator_market_score_source_materials(  # noqa: SLF001
        symbol=symbol,
        timeframe=timeframe,
        intent=intent,
        signal=signal,
        prediction={},
        features={},
        market_microstructure=market_microstructure,
        feature_source_name="allocator-test-final-feature",
        spread_bps=row.spread_bps,
        base_liquidity_score=liquidity,
        base_liquidity_source=liquidity_source,
        base_liquidity_reason=liquidity_reason,
        final_liquidity_score=liquidity,
        regime_score=regime,
        regime_source=regime_source,
        regime_reason=regime_reason,
    )
    lineage = dict(row.lineage_ids)
    lineage[PAPER_ALLOCATOR_LIQUIDITY_SOURCE_MATERIAL_LINEAGE_KEY] = liquidity_material
    lineage[PAPER_ALLOCATOR_LIQUIDITY_SOURCE_HASH_LINEAGE_KEY] = paper_loop._paper_canonical_sha256(
        liquidity_material
    )  # noqa: SLF001
    lineage[PAPER_ALLOCATOR_REGIME_SOURCE_MATERIAL_LINEAGE_KEY] = regime_material
    lineage[PAPER_ALLOCATOR_REGIME_SOURCE_HASH_LINEAGE_KEY] = paper_loop._paper_canonical_sha256(
        regime_material
    )  # noqa: SLF001
    row = replace(row, lineage_ids=lineage)
    pit = {
        "status": "PASS",
        "decision_time": DECISION_TIME,
        "decision_time_semantics": "TEST_IMMUTABLE_CANDIDATE_CUTOFF",
        "observed_component_times": {
            "entry_spread_available_at": "2026-07-19T11:59:50Z",
            "entry_feature_available_at": "2026-07-19T11:59:55Z",
        },
        "rejection_reasons": [],
    }
    checkpoint = paper_loop._paper_promoted_checkpoint_growth_receipt(  # noqa: SLF001
        promoted_trainer_status(),
        candidate_checkpoint_id=CHECKPOINT_ID,
        candidate_checkpoint_id_source="signal.checkpoint_id",
        decision_time=DECISION_TIME,
    )
    edge = paper_loop._paper_strict_after_cost_edge_growth_receipt(  # noqa: SLF001
        strict_growth_performance_status(),
        decision_time=DECISION_TIME,
    )
    context = paper_loop._paper_candidate_market_context_growth_receipt(  # noqa: SLF001
        intent=intent,
        allocation_input=row,
        point_in_time_evidence=pit,
        decision_time=DECISION_TIME,
    )
    authorization = paper_loop._paper_candidate_growth_authorization_receipt(  # noqa: SLF001
        symbol=symbol,
        decision_time=DECISION_TIME,
        checkpoint_receipt=checkpoint,
        edge_receipt=edge,
        market_context_receipt=context,
    )
    assert authorization["status"] == "READY", authorization["rejection_reasons"]
    edge_material = edge["source_material"]
    arguments = {
        "win_rate": edge_material["strict_after_cost_edge_win_rate"],
        "profit_factor": edge_material["strict_after_cost_edge_profit_factor_numeric"],
        "closed_trade_count": edge_material["after_cost_edge_evidence_count"],
        "current_drawdown_pct": 0.0,
        "model_avg_confidence": row.confidence_calibrated,
        "paper_mode": True,
        "after_cost_edge_lower_bound_bps": edge_material["after_cost_edge_lower_bound_bps"],
        "after_cost_edge_scale_bps": edge_material["after_cost_edge_scale_bps"],
        "after_cost_edge_resolution_bps": edge_material["after_cost_edge_resolution_bps"],
        "after_cost_edge_evidence_count": edge_material["after_cost_edge_evidence_count"],
        "after_cost_edge_evidence_source": edge_material["after_cost_edge_evidence_source"],
        "edge_available_at": edge_material["after_cost_edge_available_at"],
        "liquidity_score": context["liquidity_score"],
        "regime_quality_score": context["regime_quality_score"],
        "market_context_source": context["market_context_source"],
        "market_context_available_at": context["market_context_available_at"],
        "decision_time": DECISION_TIME,
        "symbol": symbol,
    }
    calculation = {
        "schema_version": "paper_dynamic_envelope_calculation_input_v2",
        "base_envelope": asdict(base),
        "arguments": arguments,
        "growth_authorization_receipt": authorization,
        "growth_authorization_receipt_hash": authorization["evidence_hash"],
    }
    envelope = calculate_dynamic_risk_envelope(
        base_envelope=base,
        **arguments,
    )
    receipt = paper_loop._paper_dynamic_envelope_reservation_evidence(  # noqa: SLF001
        envelope,
        evidence={"test_fixture": "AUTHENTIC_COMPONENT_RECEIPTS"},
        calculation_input_material=calculation,
    )
    assert receipt["status"] == "READY", receipt["rejection_reasons"]
    lineage[PAPER_GROWTH_ENVELOPE_AUTHORIZATION_LINEAGE_KEY] = receipt
    lineage[PAPER_GROWTH_ENVELOPE_AUTHORIZATION_HASH_LINEAGE_KEY] = receipt["evidence_hash"]
    return replace(row, lineage_ids=lineage), envelope, receipt


def allocate_authorized_growth(
    row: AllocationInput,
    configured_base: RiskEnvelope | None = None,
) -> AllocationResult:
    from v2.backend.app.services.adaptive_capital_allocator import (  # noqa: PLC0415
        allocate_paper_candidate,
    )

    authorized_row, envelope, _receipt = authorize_growth(row, configured_base)
    return allocate_paper_candidate(authorized_row, envelope)
