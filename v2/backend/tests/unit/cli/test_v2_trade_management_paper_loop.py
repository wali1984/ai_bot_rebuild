from __future__ import annotations

from v2.backend.app.cli import v2_trade_management_paper_loop as paper_loop


def _allowed_allocation(**overrides):
    payload = {
        "allocator_decision": "ALLOW_WITH_SIZE",
        "target_notional_usdt": 1000.0,
        "target_quantity": 10.0,
        "risk_budget_usd": 100.0,
        "gross_notional_usd": 1000.0,
        "allocated_margin_usd": 500.0,
        "expected_fees_usd": 4.0,
        "expected_slippage_usd": 2.0,
        "expected_funding_usd": 1.0,
        "expected_net_pnl_usd": 12.0,
        "expected_shortfall_usd": 150.0,
        "hedge_budget_usd": 10.0,
        "risk_budget_pct": 0.01,
        "risk_budget_pct_of_equity": 0.01,
        "risk_budget_pct_of_available_margin": 0.02,
        "confidence_calibrated": 0.65,
        "expected_move_after_cost_bps": 12.0,
        "model_inputs": {"selected_allocated_margin_usd": 500.0},
    }
    payload.update(overrides)
    return payload


def test_b_grade_exploration_budget_fraction_uses_uncertainty_and_drawdown() -> None:
    low_confidence = paper_loop._b_grade_exploration_budget_fraction(  # noqa: SLF001
        confidence_calibrated=0.55,
        drawdown_bps=0.0,
    )
    higher_confidence = paper_loop._b_grade_exploration_budget_fraction(  # noqa: SLF001
        confidence_calibrated=0.70,
        drawdown_bps=0.0,
    )
    drawdown_reduced = paper_loop._b_grade_exploration_budget_fraction(  # noqa: SLF001
        confidence_calibrated=0.70,
        drawdown_bps=400.0,
    )

    assert 0.0 < low_confidence["risk_budget_fraction_of_normal_adaptive"]
    assert (
        low_confidence["risk_budget_fraction_of_normal_adaptive"]
        < higher_confidence["risk_budget_fraction_of_normal_adaptive"]
        <= paper_loop.B_GRADE_EXPLORATION_MAX_RISK_FRACTION_OF_NORMAL
    )
    assert (
        0.0
        < drawdown_reduced["risk_budget_fraction_of_normal_adaptive"]
        < higher_confidence["risk_budget_fraction_of_normal_adaptive"]
    )


def test_confidence_trial_positive_edge_becomes_b_grade_paper_only_exploration() -> None:
    signal = {
        "paper_confidence_threshold_trial": True,
        "confidence_calibrated": 0.65,
        "expected_move_after_cost_bps": 12.0,
    }
    intent = {
        "confidence_calibrated": 0.65,
        "expected_move_after_cost_bps": 12.0,
        "paper_only": True,
        "places_real_order": False,
    }
    allocation = _allowed_allocation()
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal=signal,
        intent=intent,
        allocation=allocation,
        integrity_gate={"allowed": True},
        local_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=100.0,
    )

    assert classification["paper_opportunity_tier"] == "B_GRADE_EXPLORATION_PAPER"
    assert classification["paper_fill_allowed_source"] == "B_GRADE_EXPLORATION_PAPER_LOCAL_GATE"
    assert classification["strict_paper_fill_allowed_upstream"] is False
    fraction = classification["risk_budget_fraction_of_normal_adaptive"]
    assert 0.0 < fraction <= paper_loop.B_GRADE_EXPLORATION_MAX_RISK_FRACTION_OF_NORMAL

    paper_loop._apply_paper_tier_classification(  # noqa: SLF001
        intent=intent,
        allocation=allocation,
        classification=classification,
    )
    paper_loop._apply_b_grade_exploration_budget_cap(  # noqa: SLF001
        intent=intent,
        allocation=allocation,
        risk_budget_fraction_of_normal_adaptive=fraction,
    )

    assert intent["paper_only"] is True
    assert intent["places_real_order"] is False
    assert allocation["b_grade_exploration_budget_cap_applied"] is True
    assert allocation["normal_adaptive_risk_budget_usd"] == 100.0
    assert allocation["risk_budget_usd"] == round(100.0 * fraction, 8)
    assert allocation["target_notional_usdt"] == round(1000.0 * fraction, 8)
    assert allocation["target_quantity"] == round(10.0 * fraction, 12)
    assert allocation["model_inputs"]["risk_budget_fraction_of_normal_adaptive"] == fraction


def test_short_signed_edge_can_be_a_grade_when_strict_gate_allowed() -> None:
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={
            "selected_action": "short",
            "confidence_calibrated": 0.80,
            "expected_move_after_cost_bps": -12.0,
        },
        intent={
            "side": "short",
            "confidence_calibrated": 0.80,
            "expected_move_after_cost_bps": -12.0,
        },
        allocation=_allowed_allocation(expected_move_after_cost_bps=-12.0),
        integrity_gate={"allowed": True},
        local_trade_gates_pass=True,
        paper_fill_allowed_upstream=True,
        portfolio_drawdown_bps=0.0,
    )

    assert classification["paper_opportunity_tier"] == "A_GRADE_EXECUTION_PAPER"
    assert classification["paper_fill_allowed_source"] == "STRICT_UPSTREAM_PAPER_FILL_GATE"


def test_dynamic_positive_edge_below_a_grade_becomes_b_grade_when_exploration_gates_pass() -> None:
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={
            "selected_action": "long",
            "confidence_calibrated": 0.64,
            "expected_move_after_cost_bps": 8.0,
        },
        intent={
            "side": "long",
            "confidence_calibrated": 0.64,
            "expected_move_after_cost_bps": 8.0,
            "paper_only": True,
            "places_real_order": False,
        },
        allocation=_allowed_allocation(confidence_calibrated=0.64, expected_move_after_cost_bps=8.0),
        integrity_gate={"allowed": True},
        local_trade_gates_pass=False,
        exploration_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=100.0,
    )

    assert classification["paper_opportunity_tier"] == "B_GRADE_EXPLORATION_PAPER"
    assert classification["paper_opportunity_tier_reason"] == "DYNAMIC_POSITIVE_EDGE_BELOW_A_GRADE_EXPLORATION"
    assert classification["paper_only"] is True
    assert classification["places_real_order"] is False
    assert classification["risk_budget_fraction_of_normal_adaptive"] > 0.0


def test_positive_edge_below_a_grade_row_becomes_dynamic_b_grade_exploration() -> None:
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={"selected_action": "long", "confidence_calibrated": 0.65, "expected_move_after_cost_bps": 12.0},
        intent={"side": "long", "confidence_calibrated": 0.65, "expected_move_after_cost_bps": 12.0},
        allocation=_allowed_allocation(),
        integrity_gate={"allowed": True},
        local_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=0.0,
    )

    assert classification["paper_opportunity_tier"] == "B_GRADE_EXPLORATION_PAPER"
    assert classification["paper_opportunity_tier_reason"] == "DYNAMIC_POSITIVE_EDGE_BELOW_A_GRADE_EXPLORATION"
    assert classification["paper_only"] is True
    assert classification["places_real_order"] is False


def test_negative_edge_trial_is_no_trade_not_b_grade_exploration() -> None:
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={
            "paper_confidence_threshold_trial": True,
            "confidence_calibrated": 0.65,
            "expected_move_after_cost_bps": -1.0,
        },
        intent={"confidence_calibrated": 0.65, "expected_move_after_cost_bps": -1.0},
        allocation=_allowed_allocation(expected_move_after_cost_bps=-1.0),
        integrity_gate={"allowed": True},
        local_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=0.0,
    )

    assert classification["paper_opportunity_tier"] == "NO_TRADE"
    assert classification["paper_opportunity_tier_reason"] == "EXPECTED_EDGE_NOT_FAVORABLE_AFTER_COST"


def test_exploration_tier_status_separates_legacy_missing_tiers() -> None:
    status = paper_loop._paper_exploration_tier_status(  # noqa: SLF001
        accepted_rows=[
            {"fill_id": "legacy-1"},
            {
                "fill_id": "b-1",
                "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
                "risk_budget_fraction_of_normal_adaptive": 0.12,
                "b_grade_exploration_budget_cap_applied": True,
                "paper_only": True,
                "places_real_order": False,
            },
        ],
        blocked_rows=[{"paper_opportunity_tier": "NO_TRADE"}],
        shadow_rows=[{"paper_opportunity_tier": "SHADOW_ONLY"}],
        held_rows=[],
    )

    assert "missing" not in status["tier_counts"]
    assert status["accepted_tier_counts"] == {"B_GRADE_EXPLORATION_PAPER": 1}
    assert status["legacy_accepted_without_tier_count"] == 1
    assert status["b_grade_exploration_accepted_count"] == 1
    assert status["b_grade_exploration_live_routing_blocked"] is True


def test_merge_persistent_accepted_fills_preserves_policy_funding_metadata() -> None:
    prior = {
        "fill_id": "fill-1",
        "ledger_row_id": "fill-1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "signal_id": "sig-1",
        "prediction_id": "pred-1",
        "risk_decision_id": "risk-1",
        "orchestrator_decision_id": "orch-1",
        "entry_price": 100.0,
        "entry_price_source": "prior_entry",
        "entry_price_utc": "2026-06-21T00:00:00Z",
        "fill_price": 100.0,
        "fill_price_source": "prior_fill",
        "fill_price_utc": "2026-06-21T00:00:00Z",
        "quantity": 1.0,
        "notional": 100.0,
        "notional_usdt": 100.0,
        "adaptive_capital_policy_version": "ADAPTIVE_CAPITAL_ALLOCATOR_V1",
        "policy_activated_at": "2026-06-21T00:00:00Z",
        "expected_funding_bps": 1.25,
        "funding_rate": 0.000125,
        "funding_interval_seconds": 3600.0,
        "adaptive_allocation": {
            "adaptive_capital_policy_version": "ADAPTIVE_CAPITAL_ALLOCATOR_V1",
            "policy_activated_at": "2026-06-21T00:00:00Z",
            "expected_funding_bps": 1.25,
            "expected_funding_usd": 0.0125,
            "model_inputs": {
                "funding_rate": 0.000125,
                "funding_interval_seconds": 3600.0,
            },
        },
    }
    current = {
        "fill_id": "fill-1",
        "ledger_row_id": "fill-1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "signal_id": "sig-1",
        "prediction_id": "pred-1",
        "risk_decision_id": "risk-1",
        "orchestrator_decision_id": "orch-1",
        "entry_price": 101.0,
        "fill_price": 101.0,
        "fill_price_utc": "2026-06-21T00:01:00Z",
        "quantity": 1.0,
        "notional": 101.0,
        "latest_price": 102.0,
        "latest_price_source": "current_mark",
        "latest_price_utc": "2026-06-21T00:02:00Z",
        "expected_funding_bps": 2.0,
        "adaptive_allocation": {
            "expected_funding_bps": 2.0,
            "model_inputs": {
                "expected_funding_bps": 2.0,
            },
        },
    }

    merged = paper_loop._merge_persistent_accepted_fills(  # noqa: SLF001
        {"fill-1": prior},
        [current],
    )

    assert len(merged) == 1
    row = merged[0]
    assert row["entry_price"] == 100.0
    assert row["fill_price"] == 100.0
    assert row["fill_price_utc"] == "2026-06-21T00:00:00Z"
    assert row["latest_price"] == 102.0
    assert row["paper_fill_persistence_status"] == "EXISTING_FILL_IMMUTABLE_FIELDS_PRESERVED"
    assert row["adaptive_capital_policy_version"] == "ADAPTIVE_CAPITAL_ALLOCATOR_V1"
    assert row["policy_activated_at"] == "2026-06-21T00:00:00Z"
    assert row["expected_funding_bps"] == 2.0
    assert row["funding_rate"] == 0.000125
    assert row["funding_interval_seconds"] == 3600.0
    allocation = row["adaptive_allocation"]
    assert allocation["adaptive_capital_policy_version"] == "ADAPTIVE_CAPITAL_ALLOCATOR_V1"
    assert allocation["policy_activated_at"] == "2026-06-21T00:00:00Z"
    assert allocation["expected_funding_bps"] == 2.0
    assert allocation["expected_funding_usd"] == 0.0125
    assert allocation["model_inputs"]["expected_funding_bps"] == 2.0
    assert allocation["model_inputs"]["funding_rate"] == 0.000125
    assert allocation["model_inputs"]["funding_interval_seconds"] == 3600.0
