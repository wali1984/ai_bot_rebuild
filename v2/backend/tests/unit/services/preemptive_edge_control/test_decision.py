from __future__ import annotations

from v2.backend.app.services.preemptive_edge_control.decision import (
    evaluate_candidate,
    summarize_decisions,
)


def _candidate(**overrides):
    row = {
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "side": "long",
        "strategy_id": "trend_mode",
        "market_regime": "TREND",
        "confidence_raw": 0.72,
        "confidence_calibrated": 0.70,
        "expected_move_after_cost_bps": 18.0,
        "composite_microstructure_trust_score": 0.78,
        "stop_distance_bps": 45.0,
        "ATR_bps": 18.0,
        "spread_bps": 2.0,
        "slippage_bps": 2.0,
        "funding_bps": 0.2,
        "gross_notional_usd": 1000.0,
        "risk_budget_usd": 8.0,
        "advanced_indicator_context": {
            "bullish_fvg_present": False,
            "bearish_fvg_present": False,
            "sweep_risk_long_side": 0.15,
            "trade_tape_confirmation_score": 0.72,
            "fvg_orderbook_trust_confluence": 0.78,
            "fvg_expected_edge_after_cost": 18.0,
            "distance_to_vwap_bps": 4.0,
            "cvd_slope": 0.2,
        },
    }
    row.update(overrides)
    return row


def _guardian(**overrides):
    payload = {
        "status": "ACTIVE",
        "a_grade_new_entries_allowed": True,
        "new_entries_allowed": True,
    }
    payload.update(overrides)
    return payload


def _closed_loss_bucket_rows():
    return [
        {
            "symbol": "BTCUSDT",
            "timeframe": "5m",
            "side": "long",
            "strategy_selected_mode": "trend_mode",
            "market_regime": "TREND",
            "confidence_calibrated": 0.82,
            "realized_pnl_bps": -24.0,
            "realized_net_pnl_usd": -2.4,
            "gross_notional_usd": 1000.0,
            "exit_reason": "TIER_1_ATR_VOLATILITY_STOP",
        }
        for _ in range(3)
    ]


def test_evaluate_candidate_blocks_when_guardian_missing() -> None:
    decision = evaluate_candidate(_candidate())

    assert decision["preemptive_decision"] == "NO_TRADE"
    assert "GUARDIAN_HALTED_OR_MISSING" in decision["preemptive_decision_reasons"]
    assert decision["allow_paper_fill"] is False
    assert decision["allow_live_dry_run"] is False


def test_preemptive_decision_preserves_governed_checkpoint_lineage() -> None:
    decision = evaluate_candidate(
        _candidate(
            prediction_id="prediction-3",
            signal_id="signal-3",
            risk_decision_id="risk-3",
            orchestrator_decision_id="orchestrator-3",
            intent_id="intent-3",
            checkpoint_id="checkpoint-3",
            active_model_registry_generation=3,
            paper_strategy_cohort_id="paper_serving_abi_v2:test",
            feature_abi_sha256="a" * 64,
            feature_builder_sha256="b" * 64,
            expected_move_after_cost_bps_signed=18.0,
            expected_move_after_cost_bps_directional=18.0,
        )
    )

    assert decision["prediction_id"] == "prediction-3"
    assert decision["signal_id"] == "signal-3"
    assert decision["risk_decision_id"] == "risk-3"
    assert decision["orchestrator_decision_id"] == "orchestrator-3"
    assert decision["intent_id"] == "intent-3"
    assert decision["checkpoint_id"] == "checkpoint-3"
    assert decision["checkpoint_generation"] == 3
    assert decision["paper_strategy_cohort_id"] == "paper_serving_abi_v2:test"
    assert decision["feature_abi_sha256"] == "a" * 64
    assert decision["feature_builder_sha256"] == "b" * 64
    assert decision["expected_move_after_cost_bps_signed"] == 18.0
    assert decision["expected_move_after_cost_bps_directional"] == 18.0
    assert decision["routes_to_live"] is False
    assert decision["places_real_order"] is False


def test_evaluate_candidate_blocks_negative_bucket_before_entry() -> None:
    decision = evaluate_candidate(
        _candidate(confidence_calibrated=0.91),
        closed_rows=_closed_loss_bucket_rows(),
        continuous_edge_guardian_gate=_guardian(),
    )

    assert decision["preemptive_decision"] == "NO_TRADE"
    assert decision["preemptive_action"] in {
        "BLOCK_PF_BELOW_1",
        "BLOCK_LOSS_PROBABILITY_TOO_HIGH",
    }
    assert "BUCKET_PF_OR_EXPECTANCY_NEGATIVE" in decision["preemptive_decision_reasons"]
    assert decision["target_notional_usd"] == 0.0


def test_evaluate_candidate_shadows_overstated_confidence() -> None:
    decision = evaluate_candidate(
        _candidate(confidence_raw=1.0, confidence_calibrated=0.95),
        closed_rows=[],
        continuous_edge_guardian_gate=_guardian(),
    )

    assert decision["preemptive_decision"] in {"SHADOW_ONLY", "NO_TRADE"}
    assert decision["confidence_overstatement_risk"] >= 0.5
    assert decision["admission_confidence"] < decision["calibrated_confidence"]


def test_reduced_size_decision_is_paper_only_and_not_live() -> None:
    decision = evaluate_candidate(
        _candidate(
            microstructure_action="REDUCE_SIZE",
            composite_microstructure_trust_score=0.55,
        ),
        bucket_health={"symbol:BTCUSDT": {"count": 3, "profit_factor": 1.3}},
        continuous_edge_guardian_gate=_guardian(),
    )

    assert decision["preemptive_decision"] in {"REDUCE_SIZE_PAPER_ONLY", "SHADOW_ONLY"}
    if decision["preemptive_decision"] == "REDUCE_SIZE_PAPER_ONLY":
        assert decision["preemptive_action"] == "ALLOW_REDUCE_SIZE_PAPER"
        assert decision["reduce_size_guardian_approved"] is True
    assert decision["routes_to_live"] is False
    assert decision["places_real_order"] is False
    assert decision["allow_live_dry_run"] is False


def test_global_halt_can_emit_paper_only_positive_edge_probation() -> None:
    decision = evaluate_candidate(
        _candidate(
            confidence_raw=0.65,
            confidence_calibrated=0.65,
            microstructure_action="ALLOW",
            composite_microstructure_trust_score=0.82,
            expected_move_after_cost_bps=22.0,
            stop_distance_bps=24.0,
            ATR_bps=12.0,
        ),
        closed_rows=[],
        continuous_edge_guardian_gate=_guardian(
            status="HALTED_PERFORMANCE",
            a_grade_new_entries_allowed=False,
            new_entries_allowed=False,
        ),
        allow_positive_edge_probation=True,
    )

    assert decision["preemptive_decision"] == "POSITIVE_EDGE_PROBATION_PAPER"
    assert decision["preemptive_action"] == "ALLOW_PROBATION_PAPER"
    assert decision["allow_paper_fill"] is True
    assert decision["allow_positive_edge_probation_paper"] is True
    assert decision["allow_live_dry_run"] is False
    assert decision["routes_to_live"] is False
    assert decision["places_real_order"] is False


def test_summarize_decisions_flags_bad_accepted_rows() -> None:
    status = summarize_decisions(
        [evaluate_candidate(_candidate(), continuous_edge_guardian_gate=_guardian())],
        accepted_rows=[
            {
                "paper_opportunity_tier": "A_PLUS_BOOTSTRAP_REDUCED_SIZE",
                "pre_trade_loss_probability": 0.91,
                "continuous_edge_guardian_new_entries_allowed": False,
            }
        ],
        generated_utc="2026-07-07T00:00:00Z",
    )

    assert status["hard_fail"] is True
    assert status["accepted_without_preemptive_decision"] == 1
    assert status["accepted_high_loss_probability_count"] == 1
    assert status["reduced_size_without_guardian_approval_count"] == 1


def test_preemptive_blocks_pf_below_one() -> None:
    decision = evaluate_candidate(
        _candidate(),
        bucket_health={"symbol:BTCUSDT": {"count": 5, "profit_factor": 0.8}},
        continuous_edge_guardian_gate=_guardian(),
    )

    assert decision["preemptive_action"] in {
        "BLOCK_PF_BELOW_1",
        "BLOCK_LOSS_PROBABILITY_TOO_HIGH",
    }
    assert decision["preemptive_allowed"] is False


def test_preemptive_blocks_non_positive_expectancy() -> None:
    decision = evaluate_candidate(
        _candidate(expected_move_after_cost_bps=-1.0),
        closed_rows=[],
        continuous_edge_guardian_gate=_guardian(),
    )

    assert decision["preemptive_action"] in {
        "BLOCK_NEGATIVE_EXPECTANCY",
        "BLOCK_LOSS_PROBABILITY_TOO_HIGH",
    }
    assert decision["preemptive_allowed"] is False


def test_preemptive_blocks_high_confidence_loss_cluster() -> None:
    decision = evaluate_candidate(
        _candidate(confidence_calibrated=0.91),
        closed_rows=_closed_loss_bucket_rows(),
        continuous_edge_guardian_gate=_guardian(),
    )

    assert decision["high_confidence_loss_cluster_active"] is True
    assert decision["preemptive_allowed"] is False


def test_preemptive_blocks_atr_stop_cluster() -> None:
    decision = evaluate_candidate(
        _candidate(),
        bucket_health={
            "symbol:BTCUSDT": {
                "count": 5,
                "profit_factor": 1.2,
                "atr_stop_rate": 0.8,
            }
        },
        continuous_edge_guardian_gate=_guardian(),
    )

    assert decision["atr_stop_cluster_active"] is True
    assert decision["preemptive_action"] in {
        "BLOCK_ATR_STOP_CLUSTER",
        "BLOCK_LOSS_PROBABILITY_TOO_HIGH",
    }


def test_preemptive_blocks_bucket_quarantine() -> None:
    decision = evaluate_candidate(
        _candidate(),
        closed_rows=[],
        continuous_edge_guardian_gate=_guardian(),
        bucket_quarantine_status={"blocked_bucket_keys": ["symbol:BTCUSDT"]},
    )

    assert decision["bucket_quarantine_active"] is True
    assert decision["preemptive_action"] == "BLOCK_BUCKET_QUARANTINE"
    assert decision["preemptive_allowed"] is False


def test_paper_exploration_treats_broad_quarantine_as_advisory_only() -> None:
    decision = evaluate_candidate(
        _candidate(
            tier="PAPER_RISK_CONTROLLER_EXPLORATION",
            paper_only=True,
            routes_to_live=False,
            places_real_order=False,
            paper_risk_controller_exploration=True,
            microstructure_action="ALLOW",
            composite_microstructure_trust_score=0.84,
            expected_move_after_cost_bps=60.0,
            stop_distance_bps=24.0,
            ATR_bps=12.0,
        ),
        closed_rows=[],
        continuous_edge_guardian_gate=_guardian(
            status="HALTED_AFTER_PIT_THRESHOLD_MET",
            a_grade_new_entries_allowed=False,
            new_entries_allowed=False,
        ),
        bucket_quarantine_status={"blocked_bucket_keys": ["side:long"]},
        allow_paper_risk_controller_exploration=True,
    )

    assert decision["preemptive_decision"] == "PAPER_RISK_CONTROLLER_EXPLORATION"
    assert "BUCKET_QUARANTINE_MATCH" not in decision["preemptive_decision_reasons"]
    assert decision["bucket_quarantine_active"] is False
    assert decision["matched_quarantined_bucket_keys"] == []
    assert decision["advisory_quarantined_bucket_keys"] == ["side:long"]
    assert decision["routes_to_live"] is False
    assert decision["places_real_order"] is False


def test_paper_exploration_exact_quarantine_still_blocks() -> None:
    decision = evaluate_candidate(
        _candidate(
            tier="PAPER_RISK_CONTROLLER_EXPLORATION",
            paper_only=True,
            routes_to_live=False,
            places_real_order=False,
            paper_risk_controller_exploration=True,
            microstructure_action="ALLOW",
            composite_microstructure_trust_score=0.84,
            expected_move_after_cost_bps=60.0,
            stop_distance_bps=24.0,
            ATR_bps=12.0,
        ),
        closed_rows=[],
        continuous_edge_guardian_gate=_guardian(
            status="HALTED_AFTER_PIT_THRESHOLD_MET",
            a_grade_new_entries_allowed=False,
            new_entries_allowed=False,
        ),
        bucket_quarantine_status={"blocked_bucket_keys": ["symbol:BTCUSDT"]},
        allow_paper_risk_controller_exploration=True,
    )

    assert decision["preemptive_decision"] == "NO_TRADE"
    assert "BUCKET_QUARANTINE_MATCH" in decision["preemptive_decision_reasons"]
    assert decision["bucket_quarantine_active"] is True
    assert decision["matched_quarantined_bucket_keys"] == ["symbol:BTCUSDT"]
    assert decision["advisory_quarantined_bucket_keys"] == []
    assert decision["routes_to_live"] is False
    assert decision["places_real_order"] is False
