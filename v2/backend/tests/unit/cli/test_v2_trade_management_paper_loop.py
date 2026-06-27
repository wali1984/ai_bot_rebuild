from __future__ import annotations

import json

import pytest

from v2.backend.app.cli import v2_trade_management_paper_loop as paper_loop


class _FakeRedis:
    def __init__(self, payloads: dict[str, object]):
        self.payloads = {
            key: value if isinstance(value, str) else json.dumps(value)
            for key, value in payloads.items()
        }

    def get(self, key: str):
        return self.payloads.get(key)


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
        "hedge_enabled": True,
        "risk_budget_pct": 0.01,
        "risk_budget_pct_of_equity": 0.01,
        "risk_budget_pct_of_available_margin": 0.02,
        "confidence_calibrated": 0.65,
        "expected_move_after_cost_bps": 12.0,
        "model_inputs": {"selected_allocated_margin_usd": 500.0},
    }
    payload.update(overrides)
    return payload


def test_paper_adaptive_sizing_runtime_status_exposes_full_candidate_allocations(
    monkeypatch,
) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-22T13:30:00Z")
    allocation_rows = [
        _allowed_allocation(
            allocation_id=f"alloc-{index}",
            allocator_decision=(
                "ALLOW_WITH_SIZE" if index % 2 == 0 else "BLOCK_LOW_CONFIDENCE"
            ),
            paper_opportunity_tier="B_GRADE_EXPLORATION_PAPER",
        )
        for index in range(30)
    ]

    status = paper_loop._paper_adaptive_sizing_runtime_status(allocation_rows)  # noqa: SLF001

    assert status["paper_candidates_with_allocation"] == 30
    assert status["candidate_allocation_count"] == 30
    assert [row["allocation_id"] for row in status["candidate_allocations"]] == [
        row["allocation_id"] for row in allocation_rows
    ]
    assert all(row["paper_only"] is True for row in status["candidate_allocations"])
    assert all(row["places_real_order"] is False for row in status["candidate_allocations"])
    assert all(row["test_order"] is False for row in status["candidate_allocations"])
    assert all(row["leverage_mutation"] is False for row in status["candidate_allocations"])
    assert all(row["margin_mode_mutation"] is False for row in status["candidate_allocations"])
    assert status["candidate_allocations_complete"] is True
    assert status["candidate_allocations_source"] == (
        "paper_loop_allocation_rows_before_sample_truncation"
    )
    assert status["candidate_allocations_selected_before_outcome"] is True
    assert status["candidate_allocations_future_labels_used_as_features"] is False
    assert len(status["sample_allocations"]) == 25
    assert status["sample_allocations"] == status["candidate_allocations"][:25]
    assert status["accepted_allocation_count"] == 15
    assert status["blocked_allocation_count"] == 15
    assert status["allocator_decision_counts"] == {
        "ALLOW_WITH_SIZE": 15,
        "BLOCK_LOW_CONFIDENCE": 15,
    }
    assert status["paper_only"] is True
    assert status["places_real_order"] is False
    assert status["test_orders"] is False
    assert status["leverage_mutation"] is False
    assert status["margin_mode_mutation"] is False
    assert status["old_redis_writes"] is False
    assert status["generated_utc"] == "2026-06-22T13:30:00Z"


def test_running_cycle_heartbeat_uses_challenger_owner_and_long_ttl(monkeypatch) -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.writes: list[tuple[str, str, int | None]] = []

        def set(self, key: str, value: str, ex: int | None = None) -> None:
            self.writes.append((key, value, ex))

    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-27T04:30:00Z")
    fake = FakeRedis()

    written = paper_loop._write_paper_runtime_heartbeat(  # noqa: SLF001
        fake,
        started_at="2026-06-27T04:29:00Z",
        cycle_state="RUNNING_CYCLE",
    )

    assert written is True
    assert len(fake.writes) == 1
    key, raw_payload, ttl = fake.writes[0]
    payload = json.loads(raw_payload)
    assert key == f"{paper_loop.V2_REDIS_PREFIX}paper:heartbeat"
    assert ttl == paper_loop.PAPER_RUNTIME_HEARTBEAT_TTL_SECONDS
    assert ttl > paper_loop.PAPER_RUNTIME_TRANSIENT_TTL_SECONDS
    assert payload["cycle_state"] == "RUNNING_CYCLE"
    assert payload["finished_at"] is None
    assert payload["candidate_id"] == paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID
    assert payload["policy_id"] == paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID
    assert payload["paper_policy_owner"] == paper_loop.PAPER_POLICY_OWNER_CHALLENGER_V2
    assert payload["model_source"] == paper_loop.CHALLENGER_V2_MODEL_SOURCE
    assert payload["current_allowed_paper_owner"] == paper_loop.PAPER_POLICY_OWNER_CHALLENGER_V2
    assert payload["paper_only"] is True
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False
    assert payload["writes_legacy_redis"] is False


def test_candidate_publication_derives_paper_accounting_aliases_from_decision_time_sources(
    monkeypatch,
) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-22T13:30:00Z")
    allocation = _allowed_allocation(
        allocation_id="alloc-accounting",
        paper_opportunity_tier="B_GRADE_EXPLORATION_PAPER",
        side="short",
        entry_price=100.0,
        fill_price=100.0,
        expected_move_after_cost_bps=-50.0,
        depth_price_impact_bps=0.75,
        hedge_budget_usd=0.0,
        hedge_enabled=None,
    )
    allocation.pop("take_profit_price", None)
    allocation.pop("take_profit_structure", None)
    allocation.pop("depth_impact_bps", None)

    status = paper_loop._paper_adaptive_sizing_runtime_status([allocation])  # noqa: SLF001
    published = status["candidate_allocations"][0]

    assert published["paper_only"] is True
    assert published["places_real_order"] is False
    assert published["allocator_decision"] == "ALLOW_WITH_SIZE"
    assert published["paper_opportunity_tier"] == "B_GRADE_EXPLORATION_PAPER"
    assert published["depth_impact_bps"] == 0.75
    assert published["take_profit_price"] == 99.5
    assert published["take_profit_structure"] == "decision_time_expected_move_or_price_target"
    assert published["hedge_enabled"] is False
    normalized = published["paper_accounting_normalized_fields"]
    assert {
        "target_field": "depth_impact_bps",
        "source_field": "depth_price_impact_bps",
        "normalization": "paper_depth_price_impact_alias",
    } in normalized
    assert {
        "target_field": "take_profit_price",
        "source_field": "expected_move_after_cost_bps",
        "normalization": "paper_expected_move_take_profit_price",
    } in normalized
    assert {
        "target_field": "hedge_enabled",
        "source_field": "hedge_budget_usd",
        "normalization": "paper_hedge_enabled_from_reserved_budget",
    } in normalized


def test_candidate_publication_derives_bounded_hedge_contract_from_budget(monkeypatch) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-22T13:30:00Z")
    allocation = _allowed_allocation(
        allocation_id="alloc-hedge",
        paper_opportunity_tier="B_GRADE_EXPLORATION_PAPER",
        timeframe="1h",
        hedge_budget_usd=10.0,
        expected_shortfall_usd=150.0,
        expected_fees_usd=4.0,
        expected_slippage_usd=2.0,
        expected_funding_usd=1.0,
        model_inputs={
            "selected_allocated_margin_usd": 500.0,
            "selected_hedge_budget_pct_of_risk": 0.1,
            "hedge_budget_selection_reason": "correlation_drawdown_volatility_cost_pressure",
        },
    )

    status = paper_loop._paper_adaptive_sizing_runtime_status([allocation])  # noqa: SLF001
    published = status["candidate_allocations"][0]

    assert published["hedge_enabled"] is True
    assert published["hedge_parent_id"] == "alloc-hedge"
    assert published["hedge_child_id"] == "alloc-hedge:paper_hedge"
    assert published["hedge_intent"] == "expected_shortfall_reduction"
    assert published["hedge_ratio"] == 0.1
    assert published["expected_shortfall_before"] == 150.0
    assert published["hedge_expected_shortfall_reduction_usd"] == 10.0
    assert published["expected_shortfall_after"] == 140.0
    assert published["maximum_duration"] == 7200
    assert published["unwind_plan"] == "close_with_parent_or_timeout"
    assert published["hedge_cost_usd"] == 0.7
    normalized = published["paper_accounting_normalized_fields"]
    assert {
        "target_field": "hedge_parent_id",
        "source_field": "allocation_or_prediction_id",
        "normalization": "paper_bounded_hedge_parent_id",
    } in normalized
    assert {
        "target_field": "expected_shortfall_after",
        "source_field": "expected_shortfall_before:hedge_expected_shortfall_reduction_usd",
        "normalization": "paper_bounded_hedge_expected_shortfall_after",
    } in normalized
    assert published["paper_only"] is True
    assert published["places_real_order"] is False


def test_candidate_publication_disables_hedge_when_cost_exceeds_shortfall_reduction(
    monkeypatch,
) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-22T13:30:00Z")
    allocation = _allowed_allocation(
        allocation_id="alloc-hedge-cost-blocked",
        paper_opportunity_tier="B_GRADE_EXPLORATION_PAPER",
        timeframe="1h",
        hedge_budget_usd=0.5,
        expected_shortfall_usd=150.0,
        expected_fees_usd=4.0,
        expected_slippage_usd=2.0,
        expected_funding_usd=1.0,
        model_inputs={
            "selected_allocated_margin_usd": 500.0,
            "selected_hedge_budget_pct_of_risk": 0.1,
            "hedge_budget_selection_reason": "correlation_drawdown_volatility_cost_pressure",
        },
    )

    status = paper_loop._paper_adaptive_sizing_runtime_status([allocation])  # noqa: SLF001
    published = status["candidate_allocations"][0]

    assert published["hedge_enabled"] is False
    assert published["hedge_budget_usd"] == 0.0
    assert published["hedge_expected_shortfall_reduction_usd"] == 0.0
    assert published["expected_shortfall_before"] == 150.0
    assert published["expected_shortfall_after"] == 150.0
    assert published["hedge_cost_usd"] == 0.7
    assert published["pre_hedge_admission_block_hedge_budget_usd"] == 0.5
    assert (
        published["hedge_admission_block_reason"]
        == "paper_bounded_hedge_expected_shortfall_reduction_not_greater_than_costs"
    )
    assert "hedge_parent_id" not in published
    assert "hedge_child_id" not in published
    assert "hedge_intent" not in published
    assert "hedge_ratio" not in published
    assert {
        "target_field": "hedge_enabled",
        "source_field": "hedge_expected_shortfall_reduction_usd:hedge_cost_usd",
        "normalization": "paper_bounded_hedge_expected_shortfall_reduction_not_greater_than_costs",
    } in published["paper_accounting_normalized_fields"]


def test_candidate_publication_derives_zero_liquidation_rare_event_stress_suite(monkeypatch) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-22T13:30:00Z")
    allocation = _allowed_allocation(
        allocation_id="alloc-stress",
        paper_opportunity_tier="B_GRADE_EXPLORATION_PAPER",
        entry_atr_bps=40.0,
        expected_move_after_cost_bps=50.0,
        actual_observed_spread_entry_bps=1.0,
        bid_ask_spread_bps_fallback=False,
        depth_price_impact_bps=2.0,
        depth_utilization_pct=0.1,
        allocator_liquidity_score=0.9,
        expected_funding_bps=0.5,
        correlation_exposure_pct=0.2,
        liquidation_pressure=0.3,
        mark_index_divergence_bps=4.0,
        latency_ms=100.0,
        recommended_leverage=2.0,
        liquidation_buffer_bps=500.0,
    )

    status = paper_loop._paper_adaptive_sizing_runtime_status([allocation])  # noqa: SLF001
    published = status["candidate_allocations"][0]
    stress = published["pre_entry_stress_tests"]

    assert status["rare_event_stress_complete_candidate_count"] == 1
    assert status["rare_event_stress_partial_candidate_count"] == 0
    assert published["rare_event_stress_status"] == "COMPLETE_RARE_EVENT_STRESS_SUITE"
    assert published["rare_event_stress_missing_inputs"] == []
    assert stress["status"] == "COMPLETE_RARE_EVENT_STRESS_SUITE"
    assert stress["gap_shock"]["adverse_move_bps"] == 100.0
    assert stress["spread_explosion"]["adverse_move_bps"] == 5.0
    assert stress["double_sided_liquidation_cascade"]["adverse_move_bps"] == 187.5
    assert stress["execution_uncertainty_bps"] == 4.0
    assert stress["correlation_stress_bps"] == 20.0
    assert stress["maintenance_margin_uncertainty_bps"] == 50.0
    assert published["modeled_999_adverse_move_bps"] == 187.5
    assert published["rare_event_required_liquidation_buffer_bps"] == 261.5
    assert stress["liquidation_buffer_covers_required"] is True
    assert {
        "target_field": "pre_entry_stress_tests",
        "source_field": "decision_time_candidate_market_risk_context",
        "normalization": "paper_zero_liquidation_rare_event_stress_suite",
    } in published["paper_accounting_normalized_fields"]
    assert published["paper_only"] is True
    assert published["places_real_order"] is False


def test_paper_adaptive_sizing_status_blocks_missing_tier_allocations(monkeypatch) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-22T13:30:00Z")
    allocation = _allowed_allocation(allocation_id="alloc-missing-tier")

    status = paper_loop._paper_adaptive_sizing_runtime_status([allocation])  # noqa: SLF001
    published = status["candidate_allocations"][0]

    assert status["accepted_allocation_count"] == 0
    assert status["blocked_allocation_count"] == 1
    assert status["unclassified_allocation_publication_block_count"] == 1
    assert status["non_executable_tier_publication_block_count"] == 1
    assert published["paper_opportunity_tier"] == "SHADOW_ONLY"
    assert published["paper_opportunity_tier_reason"] == (
        "MISSING_OR_INVALID_EXPLICIT_PAPER_OPPORTUNITY_TIER"
    )
    assert published["allocator_decision"] == "BLOCK_NON_EXECUTABLE_PAPER_TIER"
    assert published["original_allocator_decision_before_paper_tier_block"] == "ALLOW_WITH_SIZE"
    assert published["pre_paper_tier_block_gross_notional_usd"] == 1000.0
    assert published["gross_notional_usd"] == 0.0
    assert published["places_real_order"] is False
    assert allocation["allocator_decision"] == "ALLOW_WITH_SIZE"


def test_current_cycle_candidate_allocations_exclude_historical_accepted_rows() -> None:
    current_allocation = _allowed_allocation(
        allocation_id="current",
        paper_opportunity_tier="B_GRADE_EXPLORATION_PAPER",
    )
    historical_allocation = _allowed_allocation(
        allocation_id="historical-a-grade",
        paper_opportunity_tier="A_GRADE_EXECUTION_PAPER",
    )
    lifecycle_blocked_allocation = _allowed_allocation(
        allocation_id="lifecycle-blocked",
        paper_opportunity_tier="A_GRADE_EXECUTION_PAPER",
    )

    rows = paper_loop._current_cycle_candidate_allocation_rows(  # noqa: SLF001
        intents=[{"adaptive_allocation": current_allocation}],
        historical_accepted_rows=[{"adaptive_allocation": historical_allocation}],
        lifecycle_blocked_rows=[{"adaptive_allocation": lifecycle_blocked_allocation}],
    )

    assert rows == [current_allocation]


def test_current_cycle_candidate_allocations_publish_intent_runtime_evidence() -> None:
    current_allocation = _allowed_allocation(
        allocation_id="current",
        paper_opportunity_tier="B_GRADE_EXPLORATION_PAPER",
    )
    intent = {
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "side": "long",
        "adaptive_allocation": current_allocation,
        "paper_fill_allowed": True,
        "paper_tier_local_fill_allowed": True,
        "paper_runtime_market_evidence_rejection_reasons": [],
        "market_cost_evidence_status": "COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE",
        "fee_bps": 4.0,
        "fee_bps_source": "exchange_fee_schedule",
        "fee_bps_fallback": False,
        "expected_funding_bps": 1.25,
        "expected_funding_bps_source": "funding_snapshot",
        "expected_funding_bps_fallback": False,
        "latency_ms": 125.0,
        "maker_probability": 0.0,
        "taker_probability": 1.0,
        "quantity": 1.0,
        "notional": 100.0,
        "notional_usdt": 100.0,
        "partial_fill_count": 1,
        "partial_fills": [{"quantity": 1.0, "price": 100.0}],
        "mark_price": 100.1,
        "index_price": 100.0,
        "entry_feature_available_at": "2026-06-22T12:59:00Z",
        "entry_feature_cutoff": "2026-06-22T12:58:59Z",
        "entry_feature_decision_time": "2026-06-22T13:00:00Z",
    }

    rows = paper_loop._current_cycle_candidate_allocation_rows(  # noqa: SLF001
        intents=[intent],
    )

    assert rows[0]["allocation_id"] == "current"
    assert rows[0]["paper_fill_allowed"] is True
    assert rows[0]["paper_runtime_market_evidence_rejection_reasons"] == []
    assert rows[0]["market_cost_evidence_status"] == "COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE"
    assert rows[0]["fee_bps"] == 4.0
    assert rows[0]["fee_bps_source"] == "exchange_fee_schedule"
    assert rows[0]["expected_funding_bps_source"] == "funding_snapshot"
    assert rows[0]["latency_ms"] == 125.0
    assert rows[0]["quantity"] == 1.0
    assert rows[0]["notional"] == 100.0
    assert rows[0]["notional_usdt"] == 100.0
    assert rows[0]["partial_fill_count"] == 1
    assert rows[0]["entry_feature_available_at"] == "2026-06-22T12:59:00Z"
    assert "paper_fill_allowed" not in current_allocation


def test_build_allocation_input_uses_configured_paper_fee_schedule_when_missing() -> None:
    intent = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "entry_price": 100.0,
        "confidence_calibrated": 0.8,
        "expected_move_after_cost_bps": 14.0,
        "market_state_integrity_score": 92.0,
    }
    signal = {
        "timeframe": "1m",
        "price_target": 100.0,
        "expected_funding_bps": 0.5,
    }
    allocation_input = paper_loop._build_allocation_input(  # noqa: SLF001
        intent=intent,
        signal=signal,
        prediction={"features": {}},
        portfolio_context={
            "equity": 10000.0,
            "available_margin": 9000.0,
            "wallet_balance": 10000.0,
            "drawdown_bps": 0.0,
        },
        symbol_exposures={},
        total_exposure=0.0,
        market_microstructure={
            "bid_ask_spread_bps": 1.2,
            "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK",
            "orderbook_depth_usd": 100000.0,
            "orderbook_depth_source": "orderbook_top5",
        },
    )

    # AllocationInput uses the configured paper fee schedule when no explicit fee evidence.
    configured = paper_loop._configured_paper_fee_bps()  # noqa: SLF001
    assert allocation_input.fee_bps == configured
    # Configured fee is production-grade: it IS recorded in intent, not marked as fallback.
    assert intent["fee_bps"] == configured
    assert intent["fee_bps_source"] == paper_loop.PAPER_CONFIGURED_FEE_SCHEDULE_SOURCE  # noqa: SLF001
    assert intent["fee_bps_fallback"] is False
    assert intent["fee_bps_for_allocator"] == configured
    assert intent["fee_bps_configured_schedule"] is True
    assert intent["fee_bps_unavailable_reason"] is None
    assert intent["market_cost_evidence_status"] == "COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE"
    assert "MISSING_FEES" not in (intent.get("market_cost_evidence_missing_fields") or [])


def test_read_v2_feature_snapshot_missing_timeframe_does_not_default_to_1m() -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.keys: list[str] = []

        def get(self, key: str):
            self.keys.append(key)
            return None

    fake = FakeRedis()

    snapshot = paper_loop._read_v2_feature_snapshot(  # noqa: SLF001
        fake,
        "BTCUSDT",
        None,
        decision_time="2026-06-22T13:00:00Z",
    )

    assert snapshot["features"] == {}
    assert snapshot["unavailable_reason"] == paper_loop.MISSING_THESIS_TIMEFRAME_BLOCK_REASON
    assert fake.keys == []


def test_build_allocation_input_marks_missing_thesis_timeframe_unknown() -> None:
    intent = {
        "symbol": "BTCUSDT",
        "side": "long",
        "entry_price": 100.0,
        "confidence_calibrated": 0.8,
        "expected_move_after_cost_bps": 14.0,
        "market_state_integrity_score": 92.0,
    }

    allocation_input = paper_loop._build_allocation_input(  # noqa: SLF001
        intent=intent,
        signal={
            "price_target": 100.0,
            "fee_bps": 2.5,
            "expected_funding_bps": 0.5,
        },
        prediction={"features": {}},
        portfolio_context={
            "equity": 10000.0,
            "available_margin": 9000.0,
            "wallet_balance": 10000.0,
            "drawdown_bps": 0.0,
        },
        symbol_exposures={},
        total_exposure=0.0,
        market_microstructure={
            "bid_ask_spread_bps": 1.2,
            "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK",
            "orderbook_depth_usd": 100000.0,
            "orderbook_depth_source": "orderbook_top5",
        },
    )

    assert allocation_input.timeframe == paper_loop.UNKNOWN_THESIS_TIMEFRAME
    assert intent["timeframe_attribution_status"] == "MISSING_THESIS_TIMEFRAME"
    assert intent["timeframe_attribution_rejection_reason"] == paper_loop.MISSING_THESIS_TIMEFRAME_BLOCK_REASON


def test_standalone_1m_without_dedicated_bucket_is_shadow_blocked() -> None:
    intent = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "thesis_timeframe": "1m",
        "strategy_id": "paper_runtime_momentum",
        "paper_fill_allowed": True,
    }

    gate = paper_loop._paper_standalone_1m_eligibility_gate(  # noqa: SLF001
        symbol="BTCUSDT",
        thesis_timeframe="1m",
        side="long",
        intent=intent,
        signal={"timeframe": "1m"},
        prediction={},
        feature_snapshot={"timeframe": "1m", "features": {}},
        risk={},
        strategy_router={"selected_mode": "paper_runtime_momentum"},
    )
    paper_loop._apply_paper_standalone_1m_gate(intent, gate)  # noqa: SLF001

    assert gate["allowed"] is False
    assert gate["standalone_1m_thesis"] is True
    assert gate["dedicated_strategy_bucket"] is False
    assert gate["blockers"] == [paper_loop.PAPER_STANDALONE_1M_BLOCK_REASON]
    assert intent["paper_fill_allowed"] is False
    assert intent["paper_standalone_1m_eligibility_blocked"] is True
    assert intent["paper_fill_block_reason"] == paper_loop.PAPER_STANDALONE_1M_GATE_BLOCK_REASON
    assert paper_loop.PAPER_STANDALONE_1M_BLOCK_REASON in intent["paper_fill_gate_block_reasons"]
    assert f"standalone_1m_eligibility:{paper_loop.PAPER_STANDALONE_1M_BLOCK_REASON}" in intent[
        "local_block_reasons"
    ]


def test_standalone_1m_with_dedicated_bucket_remains_eligible_for_paper_gate() -> None:
    intent = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "thesis_timeframe": "1m",
        "strategy_id": "standalone_1m_scalp",
        "paper_fill_allowed": True,
    }

    gate = paper_loop._paper_standalone_1m_eligibility_gate(  # noqa: SLF001
        symbol="BTCUSDT",
        thesis_timeframe="1m",
        side="long",
        intent=intent,
        signal={},
        prediction={},
        feature_snapshot={"timeframe": "1m", "features": {}},
        risk={},
        strategy_router={"selected_mode": "standalone_1m_scalp"},
    )
    paper_loop._apply_paper_standalone_1m_gate(intent, gate)  # noqa: SLF001

    assert gate["allowed"] is True
    assert gate["dedicated_strategy_bucket"] is True
    assert intent["paper_fill_allowed"] is True
    assert "paper_standalone_1m_eligibility_blocked" not in intent


def test_higher_timeframe_thesis_can_use_1m_execution_timing() -> None:
    intent = {
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "thesis_timeframe": "1h",
        "execution_timeframe": "1m",
        "paper_fill_allowed": True,
    }

    gate = paper_loop._paper_standalone_1m_eligibility_gate(  # noqa: SLF001
        symbol="BTCUSDT",
        thesis_timeframe="1h",
        side="long",
        intent=intent,
        signal={"execution_timeframe": "1m", "timeframe": "1h"},
        prediction={},
        feature_snapshot={"execution_timeframe": "1m", "timeframe": "1m", "features": {}},
        risk={},
        strategy_router={"selected_mode": "paper_runtime_momentum"},
    )
    paper_loop._apply_paper_standalone_1m_gate(intent, gate)  # noqa: SLF001

    assert gate["allowed"] is True
    assert gate["standalone_1m_thesis"] is False
    assert gate["higher_timeframe_timing_role_allowed"] is True
    assert intent["paper_fill_allowed"] is True


def _reentry_candidate(
    *,
    candle: str = "2026-06-25T13:00:00Z",
    prediction_id: str = "pred-new",
    signal_id: str = "sig-new",
    decision_id: str = "dec-new",
    feature_snapshot_id: str = "fs-new",
    expected_edge: float = 12.0,
) -> dict:
    intent = {
        "paper_fill_allowed": True,
        "expected_move_after_cost_bps": expected_edge,
        "entry_feature_cutoff": candle,
        "generated_utc": "2026-06-25T13:01:00Z",
    }
    return paper_loop._paper_reentry_dedup_candidate_row(  # noqa: SLF001
        symbol="BTCUSDT",
        thesis_timeframe="1h",
        side="long",
        intent=intent,
        signal={"signal_id": signal_id},
        prediction={
            "prediction_id": prediction_id,
            "feature_snapshot_id": feature_snapshot_id,
            "generated_at": "2026-06-25T13:01:00Z",
        },
        feature_snapshot={
            "feature_snapshot_id": feature_snapshot_id,
            "feature_cutoff": candle,
            "features": {},
        },
        risk={"decision_id": decision_id, "risk_decision_id": f"risk-{decision_id}"},
        strategy_router={"selected_mode": "paper_runtime_momentum"},
    )


def test_paper_reentry_dedup_blocks_same_prediction_id() -> None:
    candidate = _reentry_candidate(prediction_id="pred-1")
    previous = [
        {
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "side": "LONG",
            "strategy_id": "paper_runtime_momentum",
            "prediction_id": "pred-1",
            "signal_id": "sig-old",
            "feature_snapshot_id": "fs-old",
            "thesis_candle_close_time": "2026-06-25T13:00:00Z",
            "paper_result": "FILLED_PAPER_ONLY",
        }
    ]

    gate = paper_loop._paper_reentry_dedup_gate(previous, candidate)  # noqa: SLF001
    intent = {"paper_fill_allowed": True}
    paper_loop._apply_paper_reentry_dedup_gate(intent, gate)  # noqa: SLF001

    assert gate["allowed"] is False
    assert "same_prediction_id" in gate["blockers"]
    assert "prediction_id" in gate["duplicate_identity_fields"]
    assert intent["paper_fill_allowed"] is False
    assert intent["paper_reentry_dedup_blocked"] is True
    assert intent["paper_fill_block_reason"] == paper_loop.PAPER_REENTRY_DEDUP_GATE_BLOCK_REASON


def test_paper_reentry_dedup_blocks_same_candle_same_thesis_without_material_change() -> None:
    candidate = _reentry_candidate(expected_edge=10.0)
    previous = [
        {
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "side": "LONG",
            "strategy_id": "paper_runtime_momentum",
            "prediction_id": "pred-old",
            "signal_id": "sig-old",
            "feature_snapshot_id": "fs-old",
            "thesis_candle_close_time": "2026-06-25T13:00:00Z",
            "expected_move_after_cost_bps": 10.0,
            "paper_result": "POSITION_CLOSED_PAPER_ONLY",
        }
    ]

    gate = paper_loop._paper_reentry_dedup_gate(previous, candidate)  # noqa: SLF001

    assert gate["allowed"] is False
    assert "same_candle_same_thesis" in gate["blockers"]
    assert "same_symbol_side_strategy_without_material_change" in gate["blockers"]


def test_paper_reentry_dedup_blocks_partial_close_reentry_without_material_change() -> None:
    candidate = _reentry_candidate(expected_edge=10.0)
    previous = [
        {
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "side": "LONG",
            "strategy_id": "paper_runtime_momentum",
            "prediction_id": "pred-old",
            "signal_id": "sig-old",
            "feature_snapshot_id": "fs-old",
            "thesis_candle_close_time": "2026-06-25T13:00:00Z",
            "expected_move_after_cost_bps": 10.0,
            "close_reason": "partial_take_profit",
            "paper_result": "POSITION_CLOSED_PAPER_ONLY",
        }
    ]

    gate = paper_loop._paper_reentry_dedup_gate(previous, candidate)  # noqa: SLF001

    assert gate["allowed"] is False
    assert "partial_close_reentry_without_material_change" in gate["blockers"]


def test_paper_reentry_dedup_allows_new_finalized_thesis_candle() -> None:
    candidate = _reentry_candidate(
        candle="2026-06-25T14:00:00Z",
        prediction_id="pred-new",
        signal_id="sig-new",
        decision_id="dec-new",
        feature_snapshot_id="fs-new",
        expected_edge=10.0,
    )
    previous = [
        {
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "side": "LONG",
            "strategy_id": "paper_runtime_momentum",
            "prediction_id": "pred-old",
            "signal_id": "sig-old",
            "feature_snapshot_id": "fs-old",
            "thesis_candle_close_time": "2026-06-25T13:00:00Z",
            "expected_move_after_cost_bps": 10.0,
            "paper_result": "POSITION_CLOSED_PAPER_ONLY",
        }
    ]

    gate = paper_loop._paper_reentry_dedup_gate(previous, candidate)  # noqa: SLF001

    assert gate["allowed"] is True
    assert gate["blockers"] == []
    assert gate["permitted_reentry_reasons"] == ["new_finalized_thesis_candle"]


def test_build_allocation_input_prefers_explicit_fee_over_configured_schedule() -> None:
    intent = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "entry_price": 100.0,
        "confidence_calibrated": 0.8,
        "expected_move_after_cost_bps": 14.0,
        "market_state_integrity_score": 92.0,
    }
    allocation_input = paper_loop._build_allocation_input(  # noqa: SLF001
        intent=intent,
        signal={
            "timeframe": "1m",
            "price_target": 100.0,
            "fee_bps": 2.5,
            "expected_funding_bps": 0.5,
        },
        prediction={"features": {}},
        portfolio_context={
            "equity": 10000.0,
            "available_margin": 9000.0,
            "wallet_balance": 10000.0,
            "drawdown_bps": 0.0,
        },
        symbol_exposures={},
        total_exposure=0.0,
        market_microstructure={
            "bid_ask_spread_bps": 1.2,
            "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK",
            "orderbook_depth_usd": 100000.0,
            "orderbook_depth_source": "orderbook_top5",
        },
    )

    assert allocation_input.fee_bps == 2.5
    assert intent["fee_bps"] == 2.5
    assert intent["fee_bps_source"] == "signal.fee_bps"
    assert intent["fee_bps_configured_schedule"] is False


def test_build_allocation_input_preserves_signed_short_edge_for_allocator() -> None:
    intent = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "short",
        "entry_price": 100.0,
        "confidence_calibrated": 0.8,
        "expected_move_after_cost_bps": -42.0,
        "market_state_integrity_score": 92.0,
    }

    allocation_input = paper_loop._build_allocation_input(  # noqa: SLF001
        intent=intent,
        signal={
            "timeframe": "1m",
            "price_target": 99.0,
            "fee_bps": 2.5,
            "expected_funding_bps": 0.5,
        },
        prediction={"features": {}},
        portfolio_context={
            "equity": 10000.0,
            "available_margin": 9000.0,
            "wallet_balance": 10000.0,
            "drawdown_bps": 0.0,
        },
        symbol_exposures={},
        total_exposure=0.0,
        market_microstructure={
            "bid_ask_spread_bps": 1.2,
            "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK",
            "orderbook_depth_usd": 100000.0,
            "orderbook_depth_source": "orderbook_top5",
        },
    )

    assert allocation_input.action == "short"
    # Signed edge is passed directly; allocator negates internally for short (max(0, -signed_edge)).
    assert allocation_input.expected_move_after_cost_bps == -42.0
    assert intent["paper_allocation_signed_edge_normalized"] is True
    assert intent["paper_allocation_signed_expected_move_after_cost_bps"] == -42.0
    assert "paper_allocation_signed_edge_preserved" not in intent
    assert "paper_allocation_signed_edge_mismatch" not in intent


def test_write_payload_atomically_replaces_invalid_json(tmp_path) -> None:
    path = tmp_path / "trainer_feedback_outcomes.json"
    path.write_text('{"trainer_feedback_outcomes": []}\\n }\\n}\\n', encoding="utf-8")

    paper_loop.write_payload(
        {
            "paper_only": True,
            "places_real_order": False,
            "trainer_feedback_outcomes": [{"trainer_feedback_id": "fb-1"}],
        },
        path,
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["paper_only"] is True
    assert payload["places_real_order"] is False
    assert payload["trainer_feedback_outcomes"] == [{"trainer_feedback_id": "fb-1"}]
    assert not list(tmp_path.glob("*.tmp"))


def test_compact_accepted_fill_state_omits_snapshot_but_keeps_trust_and_execution() -> None:
    compact = paper_loop._compact_accepted_fill_for_state(  # noqa: SLF001
        {
            "fill_id": "fill-1",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "side": "long",
            "prediction_id": "pred-1",
            "signal_id": "sig-1",
            "decision_id": "dec-1",
            "feature_snapshot_id": "fs-1",
            "entry_feature_snapshot_id": "fs-1",
            "feature_cutoff": "2026-06-22T12:59:00Z",
            "decision_time": "2026-06-22T13:00:00Z",
            "available_at": "2026-06-22T12:59:01Z",
            "entry_feature_snapshot": {"features": {"very_large": [1, 2, 3]}},
            "entry_price": 100.0,
            "fill_price": 100.0,
            "quantity": 2.0,
            "notional_usdt": 200.0,
            "maker_probability": 0.0,
            "taker_probability": 1.0,
            "maker_taker_probability_source": (
                "PAPER_MARKETABLE_SINGLE_FILL_FROM_OBSERVED_SPREAD_AND_V2_PRICE"
            ),
            "selector_policy_fingerprint": "selector-fp-1",
            "frozen_selector_fingerprint": "selector-fp-1",
            "candidate_selected_before_outcome": True,
            "candidate_selected_after_outcome": False,
            "post_outcome_candidate_selection": False,
            "future_labels_used_as_features": False,
            "latency_ms": 125.0,
            "partial_fill_count": 1,
            "partial_fills": [{"quantity": 2.0, "price": 100.0}],
            "mark_price": 100.1,
            "index_price": 100.0,
            "mark_index_source": "V2_MARKET_FUNDING_PREMIUM_INDEX:v2:market:funding:BTCUSDT",
            "adaptive_allocation": {
                "gross_notional_usd": 200.0,
                "recommended_leverage": 2.0,
                "take_profit_structure": "decision_time_expected_move_or_price_target",
                "take_profit_price": 101.5,
                "hedge_enabled": False,
                "depth_impact_bps": 0.25,
                "model_inputs": {
                    "confidence_calibrated": 0.75,
                    "huge_feature_vector": [9, 9, 9],
                },
            },
        }
    )

    assert compact["accepted_fill_state_compacted"] is True
    assert compact["entry_feature_snapshot_omitted_from_state"] is True
    assert "entry_feature_snapshot" not in compact
    assert compact["prediction_id"] == "pred-1"
    assert compact["feature_snapshot_id"] == "fs-1"
    assert compact["entry_feature_snapshot_id"] == "fs-1"
    assert compact["maker_probability"] == 0.0
    assert compact["taker_probability"] == 1.0
    assert compact["selector_policy_fingerprint"] == "selector-fp-1"
    assert compact["frozen_selector_fingerprint"] == "selector-fp-1"
    assert compact["candidate_selected_before_outcome"] is True
    assert compact["candidate_selected_after_outcome"] is False
    assert compact["post_outcome_candidate_selection"] is False
    assert compact["future_labels_used_as_features"] is False
    assert compact["latency_ms"] == 125.0
    assert compact["partial_fill_count"] == 1
    assert compact["mark_price"] == 100.1
    assert compact["index_price"] == 100.0
    assert compact["adaptive_allocation"]["gross_notional_usd"] == 200.0
    assert compact["adaptive_allocation"]["recommended_leverage"] == 2.0
    assert compact["adaptive_allocation"]["take_profit_structure"] == (
        "decision_time_expected_move_or_price_target"
    )
    assert compact["adaptive_allocation"]["take_profit_price"] == 101.5
    assert compact["adaptive_allocation"]["hedge_enabled"] is False
    assert compact["adaptive_allocation"]["depth_impact_bps"] == 0.25
    assert compact["adaptive_allocation"]["model_inputs"]["confidence_calibrated"] == 0.75
    assert "huge_feature_vector" not in compact["adaptive_allocation"]["model_inputs"]


def test_read_existing_accepted_fills_prefers_compact_file_state(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "paper_accepted_fills_state.json"
    state_path.write_text(
        json.dumps(
            {
                "accepted_fills": [
                    {
                        "fill_id": "file-fill",
                        "ledger_row_id": "file-fill",
                        "symbol": "BTCUSDT",
                        "prediction_id": "file-pred",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(paper_loop, "PAPER_ACCEPTED_FILLS_STATE_PATH", state_path)
    redis_client = _FakeRedis(
        {
            "v2:paper:ledger": {
                "accepted": [
                    {
                        "fill_id": "redis-fill",
                        "ledger_row_id": "redis-fill",
                        "symbol": "ETHUSDT",
                        "prediction_id": "redis-pred",
                    }
                ]
            }
        }
    )

    rows = paper_loop._read_existing_accepted_fills(redis_client)  # noqa: SLF001

    assert list(rows) == ["file-fill"]
    assert rows["file-fill"]["prediction_id"] == "file-pred"


def test_feedback_context_fallback_preserves_pre_outcome_candidate_provenance() -> None:
    close_event = {"trainer_feedback_id": "fb-1", "prediction_id": "pred-1"}
    source_context = {
        "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
        "selector_policy_fingerprint": "selector-fp-1",
        "frozen_selector_fingerprint": "selector-fp-1",
        "candidate_selected_before_outcome": True,
        "candidate_selected_after_outcome": False,
        "post_outcome_candidate_selection": False,
        "future_labels_used_as_features": False,
    }

    enriched = paper_loop._with_feedback_context_fallback(close_event, source_context)  # noqa: SLF001

    assert enriched["paper_opportunity_tier"] == "B_GRADE_EXPLORATION_PAPER"
    assert enriched["selector_policy_fingerprint"] == "selector-fp-1"
    assert enriched["frozen_selector_fingerprint"] == "selector-fp-1"
    assert enriched["candidate_selected_before_outcome"] is True
    assert enriched["candidate_selected_after_outcome"] is False
    assert enriched["post_outcome_candidate_selection"] is False
    assert enriched["future_labels_used_as_features"] is False


def test_existing_ledger_payload_overlays_lifecycle_state(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "paper_lifecycle_state.json"
    state_path.write_text(
        json.dumps(
            {
                "accepted_fills": [{"fill_id": "state-fill", "symbol": "BTCUSDT"}],
                "closed_trades": [{"trainer_feedback_id": "close-1", "source_fill_ids": ["state-fill"]}],
                "outcome_labels": [{"trainer_feedback_id": "close-1", "winner": True}],
                "open_positions": [{"position_id": "pos-1", "symbol": "BTCUSDT"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(paper_loop, "PAPER_LIFECYCLE_STATE_PATH", state_path)
    redis_client = _FakeRedis(
        {
            "v2:paper:ledger": {
                "redis_ledger_compacted": True,
                "accepted": [{"fill_id": "redis-sample"}],
                "closed_trades": [{"trainer_feedback_id": "redis-close"}],
            }
        }
    )

    ledger = paper_loop._read_existing_ledger_payload(redis_client)  # noqa: SLF001

    assert ledger["accepted"] == [{"fill_id": "state-fill", "symbol": "BTCUSDT"}]
    assert ledger["accepted_count"] == 1
    assert ledger["closed_trades"] == [
        {"trainer_feedback_id": "close-1", "source_fill_ids": ["state-fill"]}
    ]
    assert ledger["closed_trade_count"] == 1
    assert ledger["outcome_labels"] == [{"trainer_feedback_id": "close-1", "winner": True}]
    assert ledger["outcome_label_count"] == 1
    assert ledger["open_positions"] == [{"position_id": "pos-1", "symbol": "BTCUSDT"}]
    assert ledger["lifecycle_state_source"] == str(state_path)


def test_attach_paper_sizing_preserves_decision_time_context_on_allocation() -> None:
    intent = {
        "intent_id": "intent-1",
        "source_intent_id": "intent-1",
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "side": "short",
        "selected_action": "short",
        "decision_time": "2026-06-22T13:00:00Z",
        "available_at": "2026-06-22T12:59:10Z",
        "feature_cutoff": "2026-06-22T12:45:00Z",
        "entry_feature_snapshot_id": "fs-1",
        "entry_feature_available_at": "2026-06-22T12:59:10Z",
        "entry_feature_generated_at": "2026-06-22T12:59:05Z",
        "entry_feature_cutoff": "2026-06-22T12:45:00Z",
        "entry_feature_decision_time": "2026-06-22T13:00:00Z",
        "feature_snapshot_id": "fs-1",
        "prediction_id": "pred-1",
        "signal_id": "sig-1",
        "risk_decision_id": "risk-1",
        "orchestrator_decision_id": "orch-1",
        "strategy_id": "trend_mode",
        "strategy_family": "trend_mode",
        "strategy_regime_labels": ["trend"],
        "entry_atr_bps": 42.5,
        "liquidity_score": 0.8,
        "regime_score": 0.7,
        "actual_observed_spread_entry_bps": 1.25,
        "expected_slippage_bps": 0.75,
        "fee_bps": 4.0,
        "expected_funding_bps": 0.5,
        "orderbook_depth_usd": 250000.0,
        "correlation_exposure_pct": 0.12,
        "maker_probability": 0.4,
        "taker_probability": 0.6,
        "maker_taker_probability_source": "PAPER_FILL_MODEL_FROM_OBSERVED_DEPTH",
        "latency_ms": 37.0,
        "partial_fill_count": 1,
        "partial_fills": [{"quantity": 10.0, "price": 100.0}],
        "mark_index_divergence_bps": 0.3,
        "mark_price": 100.03,
        "index_price": 100.0,
        "margin_mode_simulated": "cross_paper_simulated",
        "generated_utc": "2026-06-22T13:00:01Z",
        "live_gate": "blocked_human_only",
    }
    allocation = _allowed_allocation(
        allocator_decision="BLOCK_LOW_CONFIDENCE",
        recommended_margin_mode="isolated_paper_simulated",
    )

    paper_loop._attach_paper_sizing(intent, allocation)  # noqa: SLF001

    assert allocation["selector_policy_fingerprint"] == (
        paper_loop.OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT
    )
    assert intent["selector_policy_fingerprint"] == (
        paper_loop.OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT
    )
    assert allocation["frozen_selector_fingerprint"] == (
        paper_loop.OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT
    )
    assert intent["frozen_selector_fingerprint"] == (
        paper_loop.OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT
    )
    assert allocation["candidate_selected_before_outcome"] is True
    assert intent["candidate_selected_before_outcome"] is True
    assert intent["candidate_selected_after_outcome"] is False
    assert intent["post_outcome_candidate_selection"] is False
    assert allocation["future_labels_used_as_features"] is False
    assert intent["future_labels_used_as_features"] is False
    assert allocation["paper_only"] is True
    assert allocation["places_real_order"] is False
    assert allocation["side"] == "short"
    assert allocation["action"] == "short"
    assert allocation["strategy"] == "trend_mode"
    assert allocation["strategy_family"] == "trend_mode"
    assert allocation["decision_time"] == "2026-06-22T13:00:00Z"
    assert allocation["available_at"] == "2026-06-22T12:59:10Z"
    assert allocation["feature_cutoff"] == "2026-06-22T12:45:00Z"
    assert allocation["entry_feature_snapshot_id"] == "fs-1"
    assert allocation["prediction_id"] == "pred-1"
    assert allocation["signal_id"] == "sig-1"
    assert allocation["risk_decision_id"] == "risk-1"
    assert allocation["entry_atr_bps"] == 42.5
    assert allocation["liquidity_score"] == 0.8
    assert allocation["actual_observed_spread_entry_bps"] == 1.25
    assert allocation["entry_spread_bps"] == 1.25
    assert allocation["expected_slippage_bps"] == 0.75
    assert allocation["fee_bps"] == 4.0
    assert allocation["expected_funding_bps"] == 0.5
    assert allocation["orderbook_depth_usd"] == 250000.0
    assert allocation["correlation_exposure_pct"] == 0.12
    assert allocation["maker_probability"] == 0.4
    assert allocation["taker_probability"] == 0.6
    assert allocation["maker_taker_probability_source"] == "PAPER_FILL_MODEL_FROM_OBSERVED_DEPTH"
    assert allocation["latency_ms"] == 37.0
    assert allocation["partial_fill_count"] == 1
    assert allocation["partial_fills"] == [{"quantity": 10.0, "price": 100.0}]
    assert allocation["mark_index_divergence_bps"] == 0.3
    assert allocation["mark_price"] == 100.03
    assert allocation["index_price"] == 100.0
    assert allocation["margin_mode"] == "cross_paper_simulated"
    assert allocation["generated_at"] == "2026-06-22T12:59:05Z"
    assert allocation["live_gate"] == "blocked_human_only"


def test_v2_mark_index_evidence_uses_positive_premium_index_values() -> None:
    redis_client = _FakeRedis({
        "v2:market:funding:BANKUSDT": {
            "symbol": "BANKUSDT",
            "markPrice": "0.03776715",
            "indexPrice": "0.03768583",
            "time": 1782175051004,
        },
    })

    evidence = paper_loop._read_v2_mark_index_evidence(redis_client, "BANKUSDT")  # noqa: SLF001

    assert evidence["mark_price"] == 0.03776715
    assert evidence["index_price"] == 0.03768583
    assert evidence["mark_index_divergence_bps"] > 0.0
    assert evidence["mark_index_source"] == (
        "V2_MARKET_FUNDING_PREMIUM_INDEX:v2:market:funding:BANKUSDT"
    )
    assert evidence["mark_index_available_at"].endswith("Z")


def test_v2_mark_index_evidence_does_not_fabricate_zero_or_missing_values() -> None:
    redis_client = _FakeRedis({
        "v2:market:funding:BTCUSDT": {
            "symbol": "BTCUSDT",
            "markPrice": "0",
            "indexPrice": "0",
            "time": 1782175051004,
        },
        "v2:market:prices:BTCUSDT": {
            "symbol": "BTCUSDT",
            "funding": None,
            "fetched_utc": "2026-06-22T13:00:00Z",
        },
    })

    evidence = paper_loop._read_v2_mark_index_evidence(redis_client, "BTCUSDT")  # noqa: SLF001

    assert evidence == {}


def test_attach_paper_execution_evidence_builds_pre_outcome_fill_metadata() -> None:
    intent = {
        "symbol": "BANKUSDT",
        "entry_price_provenance_present": True,
        "entry_spread_decision_time": "2026-06-22T13:00:00.000Z",
        "generated_utc": "2026-06-22T13:00:00.100Z",
        "fill_price_utc": "2026-06-22T13:00:00.250Z",
        "fill_price": 100.0,
        "quantity": 2.5,
        "notional_usdt": 250.0,
        "actual_observed_spread_entry_bps": 1.2,
    }
    mark_index = {
        "mark_price": 100.03,
        "index_price": 100.0,
        "mark_index_divergence": 0.0003,
        "mark_index_divergence_bps": 3.0,
        "mark_index_source": "V2_MARKET_FUNDING_PREMIUM_INDEX:v2:market:funding:BANKUSDT",
        "mark_index_available_at": "2026-06-22T13:00:00.000Z",
    }

    paper_loop._attach_paper_execution_evidence(intent, mark_index)  # noqa: SLF001

    assert intent["latency_ms"] == 250.0
    assert intent["latency_source"] == "PAPER_DECISION_TO_FILL_RUNTIME_TIMESTAMPS"
    assert intent["maker_probability"] == 0.0
    assert intent["taker_probability"] == 1.0
    assert intent["maker_taker_probability_source"] == (
        "PAPER_MARKETABLE_SINGLE_FILL_FROM_OBSERVED_SPREAD_AND_V2_PRICE"
    )
    assert intent["partial_fill_count"] == 1
    assert intent["fill_count"] == 1
    assert intent["partial_fills"][0]["paper_only"] is True
    assert intent["partial_fills"][0]["places_real_order"] is False
    assert intent["mark_price"] == 100.03
    assert intent["index_price"] == 100.0
    assert intent["mark_index_source"] == mark_index["mark_index_source"]


def test_attach_paper_execution_evidence_uses_non_future_latency_source() -> None:
    intent = {
        "symbol": "AGTUSDT",
        "entry_price_provenance_present": True,
        "entry_spread_decision_time": "2026-06-22T13:00:00.251Z",
        "decision_time": "2026-06-22T13:00:00.000Z",
        "generated_utc": "2026-06-22T13:00:00.250Z",
        "fill_price_utc": "2026-06-22T13:00:00.250Z",
        "fill_price": 0.020898,
        "quantity": 3762.351700169794,
        "notional_usdt": 78.62562583,
        "actual_observed_spread_entry_bps": 6.22,
    }

    paper_loop._attach_paper_execution_evidence(intent, {})  # noqa: SLF001

    assert intent["latency_ms"] == 250.0
    assert intent["partial_fill_count"] == 1
    assert intent["partial_fills"][0]["quantity"] == 3762.351700169794


def test_attach_paper_execution_evidence_prefers_feature_decision_over_spread_capture() -> None:
    intent = {
        "symbol": "AGTUSDT",
        "entry_price_provenance_present": True,
        "entry_feature_decision_time": "2026-06-22T13:00:00.000Z",
        "decision_time": "2026-06-22T13:00:00.000Z",
        "entry_spread_decision_time": "2026-06-22T13:00:00.100Z",
        "entry_spread_captured_at": "2026-06-22T13:00:00.100Z",
        "generated_utc": "2026-06-22T13:00:00.200Z",
        "fill_price_utc": "2026-06-22T13:00:00.250Z",
        "fill_price": 0.020898,
        "quantity": 3762.351700169794,
        "notional_usdt": 78.62562583,
        "actual_observed_spread_entry_bps": 6.22,
    }

    paper_loop._attach_paper_execution_evidence(intent, {})  # noqa: SLF001

    assert intent["latency_ms"] == 250.0
    assert intent["latency_source"] == "PAPER_DECISION_TO_FILL_RUNTIME_TIMESTAMPS"


def test_attach_paper_execution_evidence_refreshes_partial_fill_after_size_change() -> None:
    intent = {
        "symbol": "DEXEUSDT",
        "entry_price_provenance_present": True,
        "decision_time": "2026-06-22T13:00:00.000Z",
        "fill_price_utc": "2026-06-22T13:00:00.250Z",
        "fill_price": 22.58,
        "quantity": 6.0,
        "notional_usdt": 135.48,
        "actual_observed_spread_entry_bps": 2.0,
    }

    paper_loop._attach_paper_execution_evidence(intent, {})  # noqa: SLF001
    assert intent["partial_fills"][0]["quantity"] == 6.0
    assert intent["partial_fills"][0]["notional_usd"] == 135.48

    intent["quantity"] = 1.5
    intent["notional"] = 33.87
    intent["notional_usdt"] = 33.87

    paper_loop._attach_paper_execution_evidence(intent, {})  # noqa: SLF001

    assert intent["partial_fill_count"] == 1
    assert intent["partial_fills"][0]["quantity"] == 1.5
    assert intent["partial_fills"][0]["notional_usd"] == 33.87
    assert intent["all_partial_fills"][0]["quantity"] == 1.5


def test_attach_paper_sizing_copies_target_fields_for_execution_evidence() -> None:
    intent = {
        "entry_price": 100.0,
        "fill_price": 100.0,
        "fill_price_utc": "2026-06-22T13:00:00.250Z",
        "decision_time": "2026-06-22T13:00:00.000Z",
        "generated_utc": "2026-06-22T13:00:00.250Z",
        "entry_price_provenance_present": True,
        "actual_observed_spread_entry_bps": 1.2,
    }
    allocation = _allowed_allocation(
        adaptive_capital_policy_version="ADAPTIVE_CAPITAL_ALLOCATOR_V1",
        recommended_leverage=2.0,
        effective_leverage=2.0,
        recommended_margin_mode="isolated_paper_simulated",
        stop_distance_bps=25.0,
        liquidation_price_estimate=50.0,
        liquidation_buffer_bps=9000.0,
        capital_allocation_reason="adaptive_allocation_from_test",
        final_size_reason="adaptive_allocation_from_test",
        model_inputs={
            "selected_allocated_margin_usd": 500.0,
            "selected_leverage": 2.0,
            "selected_margin_mode": "isolated_paper_simulated",
            "selected_hedge_budget_pct_of_risk": 0.1,
        },
    )

    paper_loop._attach_paper_sizing(intent, allocation)  # noqa: SLF001
    paper_loop._attach_paper_execution_evidence(intent, {})  # noqa: SLF001

    assert intent["target_notional_usdt"] == 1000.0
    assert intent["target_quantity"] == 10.0
    assert intent["quantity"] == 10.0
    assert intent["notional_usdt"] == 1000.0
    assert intent["paper_sizing_complete"] is True
    assert intent["partial_fill_count"] == 1
    assert intent["partial_fills"][0]["notional_usd"] == 1000.0


def test_depth_price_impact_uses_orderbook_top5_vwap_after_sizing() -> None:
    intent = {
        "symbol": "BTCUSDT",
        "side": "long",
        "entry_price": 100.0,
        "fill_price": 100.0,
        "quantity": 2.0,
        "notional_usdt": 200.0,
    }
    market_microstructure = {
        "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BTCUSDT",
        "best_bid": 99.99,
        "best_ask": 100.0,
        "mid_price": 99.995,
        "ask_depth_usd": 500.0,
        "bid_depth_usd": 600.0,
        "ask_levels_top5": [
            {"price": 100.0, "quantity": 1.0},
            {"price": 100.2, "quantity": 2.0},
        ],
        "bid_levels_top5": [
            {"price": 99.99, "quantity": 6.0},
        ],
    }

    paper_loop._attach_depth_price_impact_evidence(intent, market_microstructure)  # noqa: SLF001

    assert intent["entry_orderbook_depth_usd"] == 500.0
    assert intent["entry_orderbook_depth_side"] == "ask"
    assert intent["depth_price_impact_bps"] == pytest.approx(10.0005)
    assert intent["depth_price_impact_source"] == (
        "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BTCUSDT:"
        "ask_levels_top5:top5_vwap_vs_touch"
    )
    assert intent["depth_price_impact_model"] == "ORDERBOOK_TOP5_VWAP_VS_TOUCH"
    assert intent["depth_price_impact_fill_complete"] is True
    assert intent["depth_utilization_pct"] == 0.4


def test_runtime_cost_capture_contract_marks_complete_production_grade_cost() -> None:
    intent = {
        "symbol": "BANKUSDT",
        "timeframe": "15m",
        "side": "long",
        "strategy_id": "trend_follow",
        "decision_time": "2026-06-22T13:00:00.000Z",
        "feature_cutoff": "2026-06-22T12:45:00.000Z",
        "available_at": "2026-06-22T12:59:58.000Z",
        "entry_feature_available_at": "2026-06-22T12:59:58.000Z",
        "entry_feature_generated_at": "2026-06-22T12:59:58.000Z",
        "entry_feature_cutoff": "2026-06-22T12:45:00.000Z",
        "entry_feature_decision_time": "2026-06-22T13:00:00.000Z",
        "entry_feature_candle_closed_confirmed": True,
        "feature_vector_hash": "fv-hash-1",
        "selected_action": "long",
        "expected_move_bps": 20.0,
        "expected_move_after_cost_bps": 12.0,
        "score": 0.72,
        "entry_price_provenance_present": True,
        "entry_spread_source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BANKUSDT",
        "entry_spread_available_at": "2026-06-22T12:59:59.500Z",
        "entry_spread_decision_time": "2026-06-22T13:00:00.000Z",
        "actual_observed_spread_entry_bps": 1.2,
        "expected_slippage_bps": 0.8,
        "expected_slippage_source": "MODELED_FROM_OBSERVED_ORDERBOOK",
        "fee_bps": 4.0,
        "fee_bps_source": "CONFIGURED_PAPER_FEE_SCHEDULE",
        "fee_bps_configured_schedule": True,
        "expected_funding_bps": 0.5,
        "expected_funding_bps_source": "V2_MARKET_FUNDING_PREMIUM_INDEX",
        "funding_rate": 0.00005,
        "funding_interval_seconds": 28800,
        "fill_price": 100.0,
        "fill_price_utc": "2026-06-22T13:00:00.250Z",
        "entry_price": 100.0,
        "quantity": 2.5,
        "notional_usdt": 250.0,
        "gross_notional_usd": 250.0,
        "allocated_margin_usd": 125.0,
        "recommended_leverage": 2.0,
        "recommended_margin_mode": "isolated_paper_simulated",
        "adaptive_allocation": {},
    }
    market_microstructure = {
        "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BANKUSDT",
        "entry_spread_available_at": "2026-06-22T12:59:59.500Z",
        "best_bid": 99.99,
        "best_ask": 100.01,
        "mid_price": 100.0,
        "bid_depth_usd": 10000.0,
        "ask_depth_usd": 12000.0,
        "orderbook_depth_usd": 10000.0,
        "market_depth_usd": 10000.0,
        "ask_levels_top5": [
            {"price": 100.01, "quantity": 10.0},
        ],
        "bid_levels_top5": [
            {"price": 99.99, "quantity": 10.0},
        ],
    }
    mark_index = {
        "mark_price": 100.03,
        "index_price": 100.0,
        "mark_index_divergence_bps": 3.0,
        "mark_index_source": "V2_MARKET_FUNDING_PREMIUM_INDEX:v2:market:funding:BANKUSDT",
        "mark_index_available_at": "2026-06-22T12:59:59.000Z",
    }

    paper_loop._attach_depth_price_impact_evidence(intent, market_microstructure)  # noqa: SLF001
    paper_loop._attach_paper_execution_evidence(intent, mark_index)  # noqa: SLF001
    paper_loop._attach_runtime_cost_capture_contract(  # noqa: SLF001
        intent,
        market_microstructure,
        signal={"policy_fingerprint": "policy-fp-1"},
        prediction={"model_source": "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA"},
    )

    assert intent["candidate_id"] == paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID
    assert intent["paper_policy_owner"] == paper_loop.PAPER_POLICY_OWNER_CHALLENGER_V2
    assert intent["predicted_direction"] == "long"
    assert intent["predicted_move_bps"] == 20.0
    assert intent["score"] == 0.72
    assert intent["order_size"] == 250.0
    assert intent["observed_bid"] == 99.99
    assert intent["observed_ask"] == 100.01
    assert intent["top_book_bid_depth_usd"] == 10000.0
    assert intent["top_book_ask_depth_usd"] == 12000.0
    assert intent["depth_derived_price_impact_bps"] == 0.0
    assert intent["maker_taker_assumption"] == "taker"
    assert intent["fee_schedule"]["fee_bps"] == 4.0
    assert intent["holding_period_funding_bps"] == 0.5
    assert intent["latency_reserve_bps"] == 0.0
    assert intent["partial_fill_estimate"]["expected_fill_probability"] == 1.0
    assert intent["cost_source_timestamp"] == "2026-06-22T12:59:59.500Z"
    assert intent["cost_evidence_freshness_ms"] == 500.0
    assert intent["runtime_cost_capture_missing_fields"] == []
    assert intent["fallback_cost_flag"] is False
    assert intent["fallback"] is False
    assert intent["production_grade_cost_flag"] is True
    assert intent["routes_to_live"] is False
    assert intent["counts_as_a_grade_evidence"] is False
    assert intent["paper_canary_fixed_notional_allowed"] is False
    assert paper_loop._paper_policy_owner_open_rejection_reasons(intent) == []  # noqa: SLF001
    assert intent["paper_policy_owner_open_allowed"] is True
    assert intent["adaptive_allocation"]["production_grade_cost_flag"] is True

    rows = paper_loop._current_cycle_candidate_allocation_rows(intents=[intent])  # noqa: SLF001
    assert rows[0]["candidate_id"] == paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID
    assert rows[0]["predicted_direction"] == "long"
    assert rows[0]["production_grade_cost_flag"] is True
    assert rows[0]["routes_to_live"] is False


def test_runtime_cost_capture_rejects_orderbook_timestamp_after_feature_decision() -> None:
    intent = {
        "symbol": "BANKUSDT",
        "timeframe": "15m",
        "side": "long",
        "decision_time": "2026-06-22T13:00:00.000Z",
        "entry_feature_decision_time": "2026-06-22T13:00:00.000Z",
        "entry_spread_decision_time": "2026-06-22T13:05:00.000Z",
        "entry_price_provenance_present": True,
        "entry_price": 100.0,
        "actual_observed_spread_entry_bps": 2.0,
        "expected_slippage_bps": 0.8,
        "expected_slippage_source": "MODELED_FROM_OBSERVED_ORDERBOOK",
        "fee_bps": 4.0,
        "fee_bps_source": "CONFIGURED_PAPER_FEE_SCHEDULE",
        "expected_funding_bps": 0.5,
        "expected_funding_bps_source": "V2_MARKET_FUNDING_PREMIUM_INDEX",
        "funding_rate": 0.00005,
        "fill_price": 100.0,
        "fill_price_utc": "2026-06-22T13:05:00.250Z",
        "quantity": 2.5,
        "notional_usdt": 250.0,
        "gross_notional_usd": 250.0,
        "allocated_margin_usd": 125.0,
        "recommended_leverage": 2.0,
        "recommended_margin_mode": "isolated_paper_simulated",
        "adaptive_allocation": {},
    }
    market_microstructure = {
        "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BANKUSDT",
        "entry_spread_available_at": "2026-06-22T13:00:05.000Z",
        "entry_spread_captured_at": "2026-06-22T13:05:00.000Z",
        "best_bid": 99.99,
        "best_ask": 100.01,
        "mid_price": 100.0,
        "bid_depth_usd": 10000.0,
        "ask_depth_usd": 12000.0,
        "orderbook_depth_usd": 10000.0,
        "market_depth_usd": 10000.0,
        "ask_levels_top5": [
            {"price": 100.01, "quantity": 10.0},
        ],
        "bid_levels_top5": [
            {"price": 99.99, "quantity": 10.0},
        ],
    }
    mark_index = {
        "mark_price": 100.03,
        "index_price": 100.0,
        "mark_index_divergence_bps": 3.0,
        "mark_index_source": "V2_MARKET_FUNDING_PREMIUM_INDEX:v2:market:funding:BANKUSDT",
        "mark_index_available_at": "2026-06-22T12:59:59.000Z",
    }

    paper_loop._attach_depth_price_impact_evidence(intent, market_microstructure)  # noqa: SLF001
    paper_loop._attach_paper_execution_evidence(intent, mark_index)  # noqa: SLF001
    paper_loop._attach_runtime_cost_capture_contract(  # noqa: SLF001
        intent,
        market_microstructure,
        signal={"policy_fingerprint": "policy-fp-1"},
        prediction={"model_source": "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA"},
    )
    reasons = paper_loop._paper_policy_owner_open_rejection_reasons(intent)  # noqa: SLF001

    assert intent["cost_source_timestamp"] == "2026-06-22T13:00:05.000Z"
    assert intent["runtime_cost_capture_decision_time"] == "2026-06-22T13:00:00.000Z"
    assert intent["cost_evidence_freshness_ms"] == -5000.0
    assert intent["runtime_cost_capture_temporal_reject_reasons"] == [
        "COST_SOURCE_TIMESTAMP_AFTER_DECISION_TIME"
    ]
    assert intent["production_grade_cost_flag"] is False
    assert intent["fallback_cost_flag"] is True
    assert "temporal:COST_SOURCE_TIMESTAMP_AFTER_DECISION_TIME" in reasons
    assert intent["paper_policy_owner_open_allowed"] is False


def test_runtime_cost_capture_uses_explicit_paper_admission_decision_time() -> None:
    intent = {
        "symbol": "BANKUSDT",
        "timeframe": "15m",
        "side": "long",
        "decision_time": "2026-06-22T13:00:00.000Z",
        "entry_feature_decision_time": "2026-06-22T13:00:00.000Z",
        "paper_admission_decision_time": "2026-06-22T13:05:00.000Z",
        "entry_price_provenance_present": True,
        "entry_price": 100.0,
        "actual_observed_spread_entry_bps": 2.0,
        "expected_slippage_bps": 0.8,
        "expected_slippage_source": "MODELED_FROM_OBSERVED_ORDERBOOK",
        "fee_bps": 4.0,
        "fee_bps_source": "CONFIGURED_PAPER_FEE_SCHEDULE",
        "expected_funding_bps": 0.5,
        "expected_funding_bps_source": "V2_MARKET_FUNDING_PREMIUM_INDEX",
        "funding_rate": 0.00005,
        "fill_price": 100.0,
        "fill_price_utc": "2026-06-22T13:05:00.250Z",
        "quantity": 2.5,
        "notional_usdt": 250.0,
        "gross_notional_usd": 250.0,
        "allocated_margin_usd": 125.0,
        "recommended_leverage": 2.0,
        "recommended_margin_mode": "isolated_paper_simulated",
        "adaptive_allocation": {},
    }
    market_microstructure = {
        "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BANKUSDT",
        "entry_spread_available_at": "2026-06-22T13:00:05.000Z",
        "entry_spread_captured_at": "2026-06-22T13:05:00.000Z",
        "best_bid": 99.99,
        "best_ask": 100.01,
        "mid_price": 100.0,
        "bid_depth_usd": 10000.0,
        "ask_depth_usd": 12000.0,
        "orderbook_depth_usd": 10000.0,
        "market_depth_usd": 10000.0,
        "ask_levels_top5": [
            {"price": 100.01, "quantity": 10.0},
        ],
        "bid_levels_top5": [
            {"price": 99.99, "quantity": 10.0},
        ],
    }
    mark_index = {
        "mark_price": 100.03,
        "index_price": 100.0,
        "mark_index_divergence_bps": 3.0,
        "mark_index_source": "V2_MARKET_FUNDING_PREMIUM_INDEX:v2:market:funding:BANKUSDT",
        "mark_index_available_at": "2026-06-22T12:59:59.000Z",
    }

    paper_loop._attach_depth_price_impact_evidence(intent, market_microstructure)  # noqa: SLF001
    paper_loop._attach_paper_execution_evidence(intent, mark_index)  # noqa: SLF001
    paper_loop._attach_runtime_cost_capture_contract(  # noqa: SLF001
        intent,
        market_microstructure,
        signal={"policy_fingerprint": "policy-fp-1"},
        prediction={"model_source": "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA"},
    )

    assert intent["model_decision_time"] == "2026-06-22T13:00:00.000Z"
    assert intent["runtime_cost_capture_decision_time"] == "2026-06-22T13:05:00.000Z"
    assert intent["cost_source_timestamp"] == "2026-06-22T13:00:05.000Z"
    assert intent["cost_evidence_freshness_ms"] == 295000.0
    assert intent["runtime_cost_capture_temporal_reject_reasons"] == []
    assert intent["production_grade_cost_flag"] is True
    assert intent["fallback_cost_flag"] is False
    assert paper_loop._paper_policy_owner_open_rejection_reasons(intent) == []  # noqa: SLF001


def test_runtime_cost_capture_prefers_final_paper_notional_for_order_size() -> None:
    intent = {
        "symbol": "BANKUSDT",
        "side": "long",
        "order_size": 1000.0,
        "order_size_usd": 1000.0,
        "gross_notional_usd": 250.0,
        "notional_usdt": 250.0,
    }

    paper_loop._attach_runtime_cost_capture_contract(intent, {})  # noqa: SLF001

    assert intent["order_size"] == 250.0
    assert intent["order_size_usd"] == 250.0


def test_runtime_cost_capture_contract_fallback_rows_do_not_pass_challenger_owner_gate() -> None:
    intent = {
        "symbol": "BANKUSDT",
        "timeframe": "15m",
        "side": "long",
        "decision_time": "2026-06-22T13:00:00.000Z",
        "entry_price_provenance_present": True,
        "fill_price": 100.0,
        "fill_price_utc": "2026-06-22T13:00:00.250Z",
        "quantity": 2.5,
        "notional_usdt": 250.0,
        "expected_slippage_bps": 0.8,
        "expected_slippage_source": "MODELED_FROM_OBSERVED_ORDERBOOK",
        "fee_bps": 4.0,
        "fee_bps_source": "CONFIGURED_PAPER_FEE_SCHEDULE",
        "expected_funding_bps": 0.5,
        "expected_funding_bps_source": "V2_MARKET_FUNDING_PREMIUM_INDEX",
        "funding_rate": 0.00005,
        "mark_index_divergence_bps": 0.0,
    }

    paper_loop._attach_paper_execution_evidence(intent, {})  # noqa: SLF001
    paper_loop._attach_runtime_cost_capture_contract(intent, {})  # noqa: SLF001
    reasons = paper_loop._paper_policy_owner_open_rejection_reasons(intent)  # noqa: SLF001

    assert intent["fallback_cost_flag"] is True
    assert intent["production_grade_cost_flag"] is False
    assert "observed_bid" in intent["runtime_cost_capture_missing_fields"]
    assert "top_book_bid_depth_usd" in intent["runtime_cost_capture_missing_fields"]
    assert "depth_derived_price_impact_bps" in intent["runtime_cost_capture_missing_fields"]
    assert "cost_source_timestamp" in intent["runtime_cost_capture_missing_fields"]
    assert "CHALLENGER_COST_CAPTURE_NOT_PRODUCTION_GRADE" in reasons
    assert "missing:observed_bid" in reasons
    assert intent["paper_policy_owner_open_allowed"] is False


def test_runtime_cost_capture_marks_zero_size_no_trade_rows_complete_without_training_credit() -> None:
    intent = {
        "symbol": "BANKUSDT",
        "timeframe": "15m",
        "side": "long",
        "decision_time": "2026-06-22T13:00:00.000Z",
        "entry_price_provenance_present": True,
        "entry_price": 100.0,
        "fill_price": 100.0,
        "fill_price_utc": "2026-06-22T13:00:00.250Z",
        "paper_opportunity_tier": paper_loop.PAPER_TIER_NO_TRADE,
        "paper_fill_allowed": False,
        "allocator_decision": "BLOCK_NON_EXECUTABLE_PAPER_TIER",
        "actual_observed_spread_entry_bps": 2.0,
        "expected_slippage_bps": 0.8,
        "expected_slippage_source": "MODELED_FROM_OBSERVED_ORDERBOOK",
        "fee_bps": 4.0,
        "fee_bps_source": "CONFIGURED_PAPER_FEE_SCHEDULE",
        "expected_funding_bps": 0.5,
        "expected_funding_bps_source": "V2_MARKET_FUNDING_PREMIUM_INDEX",
        "funding_rate": 0.00005,
        "mark_index_divergence_bps": 0.0,
    }
    market_microstructure = {
        "source": "V2_TRADE_TERMINAL_ORDERBOOK_PAYLOAD",
        "entry_spread_available_at": "2026-06-22T12:59:59.500Z",
        "best_bid": 99.99,
        "best_ask": 100.01,
        "mid_price": 100.0,
        "bid_ask_spread_bps": 2.0,
        "bid_depth_usd": 10000.0,
        "ask_depth_usd": 12000.0,
        "orderbook_depth_usd": 10000.0,
        "market_depth_usd": 10000.0,
    }

    paper_loop._attach_paper_execution_evidence(intent, {})  # noqa: SLF001
    paper_loop._attach_runtime_cost_capture_contract(  # noqa: SLF001
        intent,
        market_microstructure,
    )

    assert intent["production_grade_cost_flag"] is True
    assert intent["fallback_cost_flag"] is False
    assert intent["counts_as_production_grade_training_evidence"] is False
    assert intent["runtime_cost_capture_order_cost_applicable"] is False
    assert intent["runtime_cost_capture_no_order_reason"] == "NO_TRADE_ZERO_SIZE_PAPER_INTENT"
    assert intent["runtime_cost_capture_missing_fields"] == []
    assert intent["runtime_cost_capture_explained_missing_fields"] == []
    assert intent["runtime_cost_capture_unexplained_missing_fields"] == []
    assert intent["depth_derived_price_impact_bps"] == 0.0
    assert intent["depth_price_impact_source"] == "NO_ORDER_ZERO_SIZE_NO_MARKET_IMPACT"
    assert intent["paper_canary_fixed_notional_allowed"] is False
    assert intent["routes_to_live"] is False
    assert intent["places_real_order"] is False


def test_old_policy_owner_cannot_open_new_economic_paper_fills() -> None:
    intent = {
        "paper_policy_owner": paper_loop.PAPER_POLICY_OWNER_OLD_POLICY,
        "production_grade_cost_flag": True,
    }

    reasons = paper_loop._paper_policy_owner_open_rejection_reasons(intent)  # noqa: SLF001

    assert reasons == ["OLD_POLICY_NEW_ECONOMIC_PAPER_OPENS_DISABLED"]
    assert intent["paper_policy_owner_open_allowed"] is False
    assert intent["paper_policy_owner_open_block_reason"] == "OLD_POLICY_NEW_ECONOMIC_PAPER_OPENS_DISABLED"


def test_missing_owner_attribution_rows_are_explicit_pre_cutover_not_challenger_credit() -> None:
    row = {
        "fill_id": "fill-pre-cutover",
        "ledger_row_id": "fill-pre-cutover",
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "side": "long",
        "decision": "ACCEPTED_PAPER_FILL",
        "counts_as_a_grade_evidence": True,
        "a_grade_promotion_allowed": True,
    }

    normalized = paper_loop._normalize_paper_owner_attribution(row)  # noqa: SLF001
    compact = paper_loop._compact_accepted_fill_for_state(normalized)  # noqa: SLF001

    assert normalized["candidate_id"] == paper_loop.UNATTRIBUTED_PRE_CUTOVER_CANDIDATE_ID
    assert normalized["policy_id"] == paper_loop.UNATTRIBUTED_PRE_CUTOVER_CANDIDATE_ID
    assert normalized["paper_policy_owner"] == paper_loop.PAPER_POLICY_OWNER_UNATTRIBUTED_PRE_CUTOVER
    assert normalized["policy_fingerprint"] == paper_loop.UNATTRIBUTED_PRE_CUTOVER_POLICY_FINGERPRINT
    assert normalized["model_source"] == paper_loop.UNATTRIBUTED_PRE_CUTOVER_MODEL_SOURCE
    assert normalized["paper_owner_attribution_complete"] is False
    assert set(normalized["paper_owner_attribution_missing_fields"]) == {
        "candidate_id",
        "model_source",
        "paper_policy_owner",
        "policy_fingerprint",
        "policy_id",
    }
    assert normalized["paper_owner_attribution_blocks_challenger_credit"] is True
    assert normalized["counts_as_a_grade_evidence"] is False
    assert normalized["a_grade_promotion_allowed"] is False
    assert normalized["challenger_credit_allowed"] is False
    assert compact["candidate_id"] == paper_loop.UNATTRIBUTED_PRE_CUTOVER_CANDIDATE_ID
    assert compact["paper_owner_attribution_status"] == "INCOMPLETE_OR_PRE_CUTOVER_OWNER_ATTRIBUTION"


def test_pre_cutover_owner_attribution_does_not_keep_challenger_model_identity() -> None:
    row = {
        "fill_id": "fill-old-normalized",
        "ledger_row_id": "fill-old-normalized",
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "decision": "ACCEPTED_PAPER_FILL",
        "candidate_id": paper_loop.UNATTRIBUTED_PRE_CUTOVER_CANDIDATE_ID,
        "policy_id": paper_loop.UNATTRIBUTED_PRE_CUTOVER_CANDIDATE_ID,
        "paper_policy_owner": paper_loop.PAPER_POLICY_OWNER_UNATTRIBUTED_PRE_CUTOVER,
        "policy_fingerprint": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT,
        "model_source": paper_loop.CHALLENGER_V2_MODEL_SOURCE,
    }

    normalized = paper_loop._normalize_paper_owner_attribution(row)  # noqa: SLF001

    assert normalized["candidate_id"] == paper_loop.UNATTRIBUTED_PRE_CUTOVER_CANDIDATE_ID
    assert normalized["policy_id"] == paper_loop.UNATTRIBUTED_PRE_CUTOVER_CANDIDATE_ID
    assert normalized["paper_policy_owner"] == paper_loop.PAPER_POLICY_OWNER_UNATTRIBUTED_PRE_CUTOVER
    assert normalized["policy_fingerprint"] == paper_loop.UNATTRIBUTED_PRE_CUTOVER_POLICY_FINGERPRINT
    assert normalized["model_source"] == paper_loop.UNATTRIBUTED_PRE_CUTOVER_MODEL_SOURCE
    assert normalized["paper_owner_attribution_complete"] is False
    assert normalized["paper_owner_attribution_missing_fields"] == ["pre_cutover_owner_attribution"]
    assert normalized["counts_as_a_grade_evidence"] is False


def test_active_cuda_owner_attribution_rewrites_stale_frozen_candidate_id() -> None:
    row = {
        "fill_id": "fill-stale-frozen-candidate",
        "ledger_row_id": "fill-stale-frozen-candidate",
        "symbol": "ETHUSDT",
        "timeframe": "5m",
        "side": "short",
        "decision": "ACCEPTED_PAPER_FILL",
        "candidate_id": paper_loop.CHALLENGER_V2_FROZEN_CANDIDATE_ID,
        "policy_id": paper_loop.CHALLENGER_V2_FROZEN_CANDIDATE_ID,
        "paper_policy_owner": paper_loop.PAPER_POLICY_OWNER_CHALLENGER_V2,
        "policy_fingerprint": paper_loop.OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT,
        "model_source": paper_loop.CHALLENGER_V2_MODEL_SOURCE,
    }

    normalized = paper_loop._normalize_paper_owner_attribution(row)  # noqa: SLF001

    assert normalized["candidate_id"] == paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID
    assert normalized["policy_id"] == paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID
    assert normalized["policy_fingerprint"] == paper_loop.CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT
    assert normalized["model_source"] == paper_loop.CHALLENGER_V2_MODEL_SOURCE
    assert normalized["paper_owner_attribution_complete"] is True
    assert normalized["paper_owner_attribution_missing_fields"] == []
    assert normalized["paper_owner_attribution_blocks_challenger_credit"] is False


def test_active_cuda_owner_attribution_keeps_unknown_candidate_mismatch_blocked() -> None:
    row = {
        "fill_id": "fill-unknown-candidate",
        "ledger_row_id": "fill-unknown-candidate",
        "symbol": "ETHUSDT",
        "timeframe": "5m",
        "side": "short",
        "decision": "ACCEPTED_PAPER_FILL",
        "candidate_id": "challenger_v2_unknown_candidate",
        "policy_id": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID,
        "paper_policy_owner": paper_loop.PAPER_POLICY_OWNER_CHALLENGER_V2,
        "policy_fingerprint": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT,
        "model_source": paper_loop.CHALLENGER_V2_MODEL_SOURCE,
    }

    normalized = paper_loop._normalize_paper_owner_attribution(row)  # noqa: SLF001

    assert normalized["candidate_id"] == "challenger_v2_unknown_candidate"
    assert normalized["policy_id"] == paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID
    assert normalized["paper_owner_attribution_complete"] is False
    assert normalized["paper_owner_attribution_blocks_challenger_credit"] is True
    assert normalized["counts_as_a_grade_evidence"] is False
    assert normalized["challenger_credit_allowed"] is False


def test_owner_attribution_status_allows_current_challenger_and_quarantines_history() -> None:
    current = paper_loop._normalize_paper_owner_attribution(  # noqa: SLF001
        {
            "fill_id": "fill-current",
            "ledger_row_id": "fill-current",
            "symbol": "ETHUSDT",
            "timeframe": "1h",
            "side": "short",
            "decision": "ACCEPTED_PAPER_FILL",
            "candidate_id": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID,
            "policy_id": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID,
            "paper_policy_owner": paper_loop.PAPER_POLICY_OWNER_CHALLENGER_V2,
            "policy_fingerprint": paper_loop.CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT,
            "model_source": paper_loop.CHALLENGER_V2_MODEL_SOURCE,
        }
    )
    historical = paper_loop._normalize_paper_owner_attribution(  # noqa: SLF001
        {
            "fill_id": "fill-pre-cutover",
            "ledger_row_id": "fill-pre-cutover",
            "symbol": "BTCUSDT",
            "timeframe": "15m",
            "side": "long",
            "decision": "ACCEPTED_PAPER_FILL",
        }
    )

    status = paper_loop._paper_owner_attribution_status(  # noqa: SLF001
        [historical, current],
        current_accepted_rows=[current],
    )

    assert status["status"] == "PASS_CURRENT_ACCEPTED_OWNER_ATTRIBUTION"
    assert status["current_accepted_count"] == 1
    assert status["current_incomplete_count"] == 0
    assert status["persistent_incomplete_or_pre_cutover_count"] == 1
    assert status["current_owner_counts"] == {paper_loop.PAPER_POLICY_OWNER_CHALLENGER_V2: 1}
    assert status["persistent_owner_counts"][paper_loop.PAPER_POLICY_OWNER_UNATTRIBUTED_PRE_CUTOVER] == 1
    assert status["pre_cutover_rows_block_challenger_credit"] is True


def test_runtime_market_evidence_requires_execution_evidence_fields() -> None:
    base_intent = {
        "entry_price_provenance_present": True,
        "entry_feature_available_at": "2026-06-22T12:59:00Z",
        "entry_feature_generated_at": "2026-06-22T12:59:00Z",
        "entry_feature_cutoff": "2026-06-22T12:58:59Z",
        "entry_feature_decision_time": "2026-06-22T13:00:00Z",
        "entry_feature_candle_closed_confirmed": True,
        "actual_observed_spread_entry_bps": 1.2,
        "bid_ask_spread_bps_fallback": False,
        "expected_slippage_bps": 0.8,
        "expected_slippage_source": "MODELED_FROM_OBSERVED_SPREAD_VOLATILITY_LIQUIDITY",
        "expected_slippage_bps_fallback": False,
        "fee_bps": 4.0,
        "fee_bps_source": "exchange_fee_schedule",
        "fee_bps_fallback": False,
        "expected_funding_bps": 1.5,
        "expected_funding_bps_source": "funding_snapshot",
        "expected_funding_bps_fallback": False,
        "orderbook_depth_usd": 10000.0,
        "orderbook_depth_source": "orderbook_top5",
        "squeeze_evidence_score": 0.1,
        "squeeze_evidence_source": "DIRECT_SQUEEZE_OR_MAJOR_MOVE_EVIDENCE_SCORE",
        "latency_ms": 250.0,
        "maker_probability": 0.0,
        "taker_probability": 1.0,
        "maker_taker_probability_source": "PAPER_MARKETABLE_SINGLE_FILL_FROM_OBSERVED_SPREAD_AND_V2_PRICE",
        "partial_fill_count": 1,
        "partial_fills": [{"quantity": 2.5, "price": 100.0}],
        "mark_price": 100.03,
        "index_price": 100.0,
    }

    assert paper_loop._paper_runtime_market_evidence_rejection_reasons(base_intent) == []  # noqa: SLF001

    missing_mark_index = dict(base_intent)
    missing_mark_index.pop("mark_price")
    reasons = paper_loop._paper_runtime_market_evidence_rejection_reasons(missing_mark_index)  # noqa: SLF001

    assert "MISSING_MARK_INDEX_DIVERGENCE_EVIDENCE" in reasons

    missing_cost_provenance = dict(base_intent)
    missing_cost_provenance.pop("fee_bps")
    missing_cost_provenance.pop("expected_funding_bps_source")
    missing_cost_provenance["orderbook_depth_usd"] = None
    reasons = paper_loop._paper_runtime_market_evidence_rejection_reasons(missing_cost_provenance)  # noqa: SLF001

    assert "MISSING_EXPLICIT_FEE_BPS_AT_DECISION_TIME" in reasons
    assert "MISSING_EXPLICIT_FUNDING_BPS_AT_DECISION_TIME" in reasons
    assert "MISSING_MARKET_DEPTH_EVIDENCE" in reasons


def test_prefill_market_evidence_does_not_require_partial_fill_ledger() -> None:
    candidate = {
        "entry_price_provenance_present": True,
        "entry_feature_available_at": "2026-06-22T12:59:00Z",
        "entry_feature_generated_at": "2026-06-22T12:59:00Z",
        "entry_feature_cutoff": "2026-06-22T12:58:59Z",
        "entry_feature_decision_time": "2026-06-22T13:00:00Z",
        "entry_feature_candle_closed_confirmed": True,
        "actual_observed_spread_entry_bps": 1.2,
        "bid_ask_spread_bps_fallback": False,
        "expected_slippage_bps": 0.8,
        "expected_slippage_source": "MODELED_FROM_OBSERVED_SPREAD_VOLATILITY_LIQUIDITY",
        "expected_slippage_bps_fallback": False,
        "fee_bps": 4.0,
        "fee_bps_source": "exchange_fee_schedule",
        "fee_bps_fallback": False,
        "expected_funding_bps": 1.5,
        "expected_funding_bps_source": "funding_snapshot",
        "expected_funding_bps_fallback": False,
        "orderbook_depth_usd": 10000.0,
        "orderbook_depth_source": "orderbook_top5",
        "squeeze_evidence_score": 0.1,
        "squeeze_evidence_source": "DIRECT_SQUEEZE_OR_MAJOR_MOVE_EVIDENCE_SCORE",
        "latency_ms": 250.0,
        "maker_probability": 0.0,
        "taker_probability": 1.0,
        "maker_taker_probability_source": "PAPER_MARKETABLE_SINGLE_FILL_FROM_OBSERVED_SPREAD_AND_V2_PRICE",
        "mark_price": 100.03,
        "index_price": 100.0,
    }

    prefill_reasons = paper_loop._paper_runtime_market_evidence_rejection_reasons(  # noqa: SLF001
        candidate,
        require_fill_ledger=False,
    )
    postfill_reasons = paper_loop._paper_runtime_market_evidence_rejection_reasons(candidate)  # noqa: SLF001

    assert prefill_reasons == []
    assert "MISSING_PARTIAL_FILL_LEDGER_EVIDENCE" in postfill_reasons


def test_b_grade_model_quality_status_computes_metrics_by_context_bucket(monkeypatch) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-22T13:30:00Z")
    rows = [
        {
            "paper_only": True,
            "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
            "calibration_label_purpose": "B_GRADE_EXPLORATION_OUTCOME_LABEL",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "selected_action": "long",
            "strategy_id": "trend",
            "market_regime_at_entry": "bull",
            "confidence_calibrated": 0.8,
            "expected_move_after_cost_bps": 10.0,
            "realized_net_pnl_bps": 12.0,
            "directional_outcome": "UP",
            "action_was_profitable": True,
        },
        {
            "paper_only": True,
            "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
            "calibration_label_purpose": "B_GRADE_EXPLORATION_OUTCOME_LABEL",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "selected_action": "short",
            "strategy_id": "trend",
            "market_regime_at_entry": "bull",
            "confidence_calibrated": 0.7,
            "expected_move_after_cost_bps": -8.0,
            "realized_net_pnl_bps": -6.0,
            "directional_outcome": "UP",
            "action_was_profitable": False,
        },
        {
            "paper_only": True,
            "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
            "calibration_label_purpose": "B_GRADE_EXPLORATION_OUTCOME_LABEL",
            "symbol": "ETHUSDT",
            "timeframe": "5m",
            "selected_action": "short",
            "strategy_id": "breakout",
            "market_regime_at_entry": "bear",
            "confidence_calibrated": 0.6,
            "expected_move_after_cost_bps": 5.0,
            "realized_net_pnl_bps": 4.0,
            "directional_outcome": "DOWN",
            "action_was_profitable": True,
        },
        {
            "paper_only": True,
            "paper_opportunity_tier": "SHADOW_ONLY",
            "realized_net_pnl_bps": 99.0,
        },
    ]

    status = paper_loop._paper_b_grade_model_quality_status(rows)  # noqa: SLF001

    assert status["status"] == "ACTIVE_B_GRADE_REALIZED_QUALITY_METRICS"
    assert status["generated_utc"] == "2026-06-22T13:30:00Z"
    assert status["scope"] == "B_GRADE_EXPLORATION_PAPER_CLOSED_OUTCOMES_ONLY"
    assert status["counts_as_a_grade_evidence"] is False
    assert status["a_grade_promotion_allowed"] is False
    assert status["sample_count"] == 3
    assert status["b_grade_closed_outcome_count"] == 3
    assert status["rows_rejected_by_reason"] == {"NOT_B_GRADE_EXPLORATION_OUTCOME": 1}
    assert status["directional_accuracy"] == pytest.approx(2 / 3)
    assert status["expected_move_mae"] == pytest.approx(5 / 3)
    assert status["brier_score"] == pytest.approx(0.23)
    assert status["precision"] == pytest.approx(2 / 3)
    assert status["recall"] is None
    assert status["false_positive_rate"] == pytest.approx(1 / 3)
    assert status["after_cost_expectancy_bps"] == pytest.approx(10 / 3)
    assert status["expectancy_95pct_lower_confidence_bound_bps"] < 0.0
    assert status["win_rate_after_cost"] == pytest.approx(2 / 3)
    assert status["win_rate_95pct_lower_confidence_bound"] < 0.90
    assert status["profit_factor"] == pytest.approx(16 / 6)
    assert status["trade_outcome_counts"] == {"WIN": 2, "LOSS": 1, "BREAKEVEN": 0}
    buckets = status["metrics_by_symbol_timeframe_side_strategy_regime_confidence_bucket"]
    assert status["metrics_by_bucket"] == buckets
    assert status["bucket_count"] == 3
    assert status["published_bucket_count"] == 3
    assert status["metric_summary"]["bucket_count"] == 3
    assert status["metric_summary"]["published_bucket_count"] == 3
    assert status["metric_summary"]["directional_accuracy"] == pytest.approx(2 / 3)
    assert status["metric_summary"]["after_cost_expectancy_bps"] == pytest.approx(10 / 3)
    assert {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "strategy": "trend",
        "regime": "bull",
        "confidence_bucket": "0.8-0.9",
    }.items() <= buckets[0].items()

    readiness = paper_loop._paper_b_grade_bucket_promotion_readiness_status(status)  # noqa: SLF001
    assert readiness["status"] == "BLOCKED_B_GRADE_BUCKETS_NOT_A_GRADE_READY"
    assert readiness["counts_as_a_grade_evidence"] is False
    assert readiness["a_grade_promotion_allowed"] is False
    assert readiness["metric_ready_bucket_count"] == 0
    assert readiness["a_grade_promotable_bucket_count"] == 0
    assert readiness["blocker_counts"]["INSUFFICIENT_BUCKET_SAMPLE_COUNT"] == 3
    assert readiness["blocker_counts"]["WIN_RATE_95PCT_LCB_BELOW_90P"] == 3
    fragmentation = readiness["evidence_fragmentation_status"]
    assert fragmentation["status"] == "BLOCKED_FRAGMENTED_B_GRADE_EVIDENCE"
    assert fragmentation["bucket_count"] == 3
    assert fragmentation["insufficient_sample_bucket_count"] == 3
    assert fragmentation["buckets_at_or_above_minimum_count"] == 0
    assert fragmentation["sample_count_deficit_to_minimum_total"] == 87
    assert fragmentation["sample_count_distribution"]["1"] == 3
    assert fragmentation["paper_only_label_collection_priority_bucket_count"] == 2
    priority = readiness["paper_only_label_collection_priority_buckets"]
    assert len(priority) == 2
    assert all(bucket["paper_only"] is True for bucket in priority)
    assert all(bucket["places_real_order"] is False for bucket in priority)
    assert all(bucket["counts_as_a_grade_evidence"] is False for bucket in priority)
    assert all(bucket["a_grade_promotion_allowed"] is False for bucket in priority)
    assert all(
        bucket["priority_reason"]
        == "PAPER_ONLY_COLLECT_MORE_B_GRADE_LABELS_FOR_PROMISING_UNDERPOWERED_BUCKET"
        for bucket in priority
    )
    assert all(
        bucket["a_grade_execution_tier_if_candidate_now"] == "SHADOW_ONLY"
        for bucket in readiness["buckets"]
    )
    assert all(bucket["counts_as_a_grade_evidence"] is False for bucket in readiness["buckets"])


def test_b_grade_bucket_promotion_readiness_never_promotes_learning_only_bucket(
    monkeypatch,
) -> None:
    monkeypatch.setattr(paper_loop, "_utc_iso", lambda: "2026-06-22T14:30:00Z")
    rows = [
        {
            "paper_only": True,
            "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
            "calibration_label_purpose": "B_GRADE_EXPLORATION_OUTCOME_LABEL",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "selected_action": "long",
            "strategy_id": "trend",
            "market_regime_at_entry": "bull",
            "confidence_calibrated": 0.97,
            "expected_move_after_cost_bps": 11.0,
            "realized_net_pnl_bps": 12.0,
            "directional_outcome": "UP",
            "action_was_profitable": True,
        }
        for _ in range(120)
    ]

    quality = paper_loop._paper_b_grade_model_quality_status(rows)  # noqa: SLF001
    readiness = paper_loop._paper_b_grade_bucket_promotion_readiness_status(quality)  # noqa: SLF001

    assert quality["profit_factor"] == "inf"
    assert readiness["source_bucket_count"] == 1
    assert readiness["metric_ready_bucket_count"] == 1
    assert readiness["a_grade_promotable_bucket_count"] == 0
    assert readiness["evidence_fragmentation_status"]["status"] == (
        "READY_B_GRADE_BUCKET_SAMPLE_COVERAGE"
    )
    assert readiness["evidence_fragmentation_status"]["insufficient_sample_bucket_count"] == 0
    assert readiness["paper_only_label_collection_priority_buckets"] == []
    bucket = readiness["buckets"][0]
    assert bucket["bucket_metric_conditions_pass"] is True
    assert bucket["metric_blocker_reasons"] == []
    assert bucket["profit_factor_is_infinite"] is True
    assert bucket["counts_as_a_grade_evidence"] is False
    assert bucket["a_grade_promotion_allowed"] is False
    assert bucket["a_grade_execution_tier_if_candidate_now"] == "SHADOW_ONLY"
    assert "B_GRADE_OUTCOMES_ARE_LEARNING_ONLY_NOT_A_GRADE_EVIDENCE" in bucket[
        "promotion_blocker_reasons"
    ]
    assert "UNTOUCHED_HOLDOUT_AND_FROZEN_POLICY_NOT_VERIFIED_FOR_BUCKET" in bucket[
        "promotion_blocker_reasons"
    ]


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


def test_continuous_edge_guardian_halt_downgrades_new_a_grade_to_shadow_only() -> None:
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={
            "selected_action": "long",
            "confidence_calibrated": 0.80,
            "expected_move_after_cost_bps": 12.0,
        },
        intent={
            "side": "long",
            "confidence_calibrated": 0.80,
            "expected_move_after_cost_bps": 12.0,
        },
        allocation=_allowed_allocation(expected_move_after_cost_bps=12.0),
        integrity_gate={"allowed": True},
        local_trade_gates_pass=True,
        paper_fill_allowed_upstream=True,
        portfolio_drawdown_bps=0.0,
        continuous_edge_guardian_gate={
            "status": "A_GRADE_HALTED_PERFORMANCE",
            "a_grade_new_entries_allowed": False,
            "failure_reasons": [{"reason": "ROLLING_100_WIN_RATE_BELOW_90P"}],
            "allowed_runtime_actions": ["reduce", "close"],
        },
    )

    assert classification["paper_opportunity_tier"] == "SHADOW_ONLY"
    assert classification["paper_opportunity_tier_reason"] == "CONTINUOUS_EDGE_GUARDIAN_A_GRADE_HALTED"
    assert classification["pre_guardian_paper_opportunity_tier"] == "A_GRADE_EXECUTION_PAPER"
    assert classification["pre_guardian_paper_opportunity_tier_reason"] == (
        "STRICT_UPSTREAM_PAPER_FILL_GATE_ALLOWED"
    )
    assert classification["pre_guardian_paper_fill_allowed_source"] == (
        "STRICT_UPSTREAM_PAPER_FILL_GATE"
    )
    assert classification["continuous_edge_guardian_forced_shadow_only"] is True
    assert classification["counts_as_a_grade_evidence"] is False
    assert classification["continuous_edge_guardian_status"] == "A_GRADE_HALTED_PERFORMANCE"
    assert classification["paper_only"] is True
    assert classification["places_real_order"] is False


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


def test_priority_bucket_context_matches_strategy_regime_labels_for_paper_only_collection() -> None:
    readiness = {
        "generated_utc": "2026-06-23T20:55:00Z",
        "paper_only_label_collection_priority_buckets": [
            {
                "symbol": "HUSDT",
                "timeframe": "4h",
                "side": "long",
                "strategy": "trend_mode",
                "regime": "TREND",
                "confidence_bucket": "0.6-0.7",
                "closed_economic_outcome_count": 3,
                "sample_count_deficit_to_minimum": 27,
                "priority_reason": (
                    "PAPER_ONLY_COLLECT_MORE_B_GRADE_LABELS_FOR_PROMISING_UNDERPOWERED_BUCKET"
                ),
            }
        ],
    }
    priority_index = paper_loop._paper_only_label_collection_priority_index(readiness)  # noqa: SLF001
    intent = {
        "symbol": "HUSDT",
        "timeframe": "4h",
        "side": "long",
        "strategy_id": "trend_mode",
        "strategy_regime_labels": ["TREND"],
        "confidence_calibrated": 0.64,
    }
    allocation = {"model_inputs": {}}

    payload = paper_loop._attach_paper_only_label_collection_priority(  # noqa: SLF001
        intent=intent,
        allocation=allocation,
        priority_index=priority_index,
    )

    assert payload is not None
    assert intent["paper_only_label_collection_priority"] is True
    assert intent["paper_only_label_collection_priority_rank"] == 1
    assert intent["paper_only_label_collection_priority_bucket_key"] == (
        "HUSDT|4h|long|trend_mode|TREND|0.6-0.7"
    )
    assert intent["paper_only_label_collection_priority_sample_count_deficit_to_minimum"] == 27
    assert intent["counts_as_a_grade_evidence"] is False
    assert intent["a_grade_promotion_allowed"] is False
    assert intent["live_ready_implication"] is False
    assert allocation["model_inputs"]["paper_only_label_collection_priority"] is True


def test_priority_bucket_candidate_becomes_paper_only_b_grade_label_collection() -> None:
    intent = {
        "symbol": "HUSDT",
        "timeframe": "4h",
        "side": "long",
        "strategy_id": "trend_mode",
        "strategy_regime_labels": ["TREND"],
        "confidence_calibrated": 0.64,
        "expected_move_after_cost_bps": 8.0,
    }
    allocation = _allowed_allocation(
        confidence_calibrated=0.64,
        expected_move_after_cost_bps=8.0,
    )
    priority_index = paper_loop._paper_only_label_collection_priority_index(  # noqa: SLF001
        {
            "generated_utc": "2026-06-23T20:55:00Z",
            "paper_only_label_collection_priority_buckets": [
                {
                    "symbol": "HUSDT",
                    "timeframe": "4h",
                    "side": "long",
                    "strategy": "trend_mode",
                    "regime": "TREND",
                    "confidence_bucket": "0.6-0.7",
                    "closed_economic_outcome_count": 3,
                    "sample_count_deficit_to_minimum": 27,
                    "priority_reason": "PRIORITY_UNDERPOWERED_BUCKET",
                }
            ],
        }
    )
    paper_loop._attach_paper_only_label_collection_priority(  # noqa: SLF001
        intent=intent,
        allocation=allocation,
        priority_index=priority_index,
    )

    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={
            "selected_action": "long",
            "confidence_calibrated": 0.64,
            "expected_move_after_cost_bps": 8.0,
        },
        intent=intent,
        allocation=allocation,
        integrity_gate={"allowed": True},
        local_trade_gates_pass=False,
        exploration_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=100.0,
    )

    assert classification["paper_opportunity_tier"] == "B_GRADE_EXPLORATION_PAPER"
    assert classification["paper_opportunity_tier_reason"] == (
        "PAPER_ONLY_PRIORITY_BUCKET_LABEL_COLLECTION"
    )
    assert classification["calibration_label_purpose"] == "B_GRADE_EXPLORATION_OUTCOME_LABEL"
    assert classification["paper_only_label_collection_priority"] is True
    assert classification["paper_only_label_collection_priority_reason"] == "PRIORITY_UNDERPOWERED_BUCKET"
    assert classification["counts_as_a_grade_evidence"] is False
    assert classification["a_grade_promotion_allowed"] is False
    assert classification["live_ready_implication"] is False
    assert classification["risk_budget_fraction_of_normal_adaptive"] > 0.0

    paper_loop._apply_paper_tier_classification(  # noqa: SLF001
        intent=intent,
        allocation=allocation,
        classification=classification,
    )

    assert allocation["paper_opportunity_tier_reason"] == (
        "PAPER_ONLY_PRIORITY_BUCKET_LABEL_COLLECTION"
    )
    assert allocation["model_inputs"]["paper_only_label_collection_priority"] is True
    assert allocation["model_inputs"]["a_grade_promotion_allowed"] is False
    assert allocation["model_inputs"]["live_ready_implication"] is False


def test_size_adjusted_trend_entry_is_not_lifecycle_no_trade() -> None:
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={
            "selected_action": "short",
            "confidence_calibrated": 0.66,
            "expected_move_after_cost_bps": -14.0,
            "strategy_selected_mode": "trend_mode",
            "strategy_router_selected_mode": "reduce_size_mode",
            "strategy_size_adjustment_mode": "reduce_size_mode",
            "strategy_regime_labels": ["TREND"],
        },
        intent={
            "side": "short",
            "confidence_calibrated": 0.66,
            "expected_move_after_cost_bps": -14.0,
            "strategy_selected_mode": "trend_mode",
            "strategy_id": "trend_mode",
            "strategy_family": "trend_mode",
            "strategy_subtype": "trend_mode",
            "strategy_router_selected_mode": "reduce_size_mode",
            "strategy_size_adjustment_mode": "reduce_size_mode",
            "entry_reason": "reduce_size_mode",
            "paper_only": True,
            "places_real_order": False,
        },
        allocation=_allowed_allocation(confidence_calibrated=0.66, expected_move_after_cost_bps=-14.0),
        integrity_gate={"allowed": True},
        local_trade_gates_pass=False,
        exploration_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=0.0,
    )

    assert classification["paper_opportunity_tier"] == "B_GRADE_EXPLORATION_PAPER"
    assert classification["paper_opportunity_tier_reason"] == "DYNAMIC_POSITIVE_EDGE_BELOW_A_GRADE_EXPLORATION"
    assert "lifecycle_or_no_trade_strategy_reasons" not in classification


def test_no_trade_strategy_mode_cannot_be_b_grade_executable() -> None:
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={
            "selected_action": "long",
            "confidence_calibrated": 0.72,
            "expected_move_after_cost_bps": 10.0,
            "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
            "strategy_router_selected_mode": "no_trade_mode",
            "strategy_regime_labels": ["MODEL_DISAGREEMENT", "NO_TRADE"],
        },
        intent={
            "side": "long",
            "confidence_calibrated": 0.72,
            "expected_move_after_cost_bps": 10.0,
            "strategy_selected_mode": "no_trade_mode",
        },
        allocation=_allowed_allocation(confidence_calibrated=0.72, expected_move_after_cost_bps=10.0),
        integrity_gate={"allowed": True},
        local_trade_gates_pass=False,
        exploration_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=0.0,
    )

    assert classification["paper_opportunity_tier"] == "NO_TRADE"
    assert classification["paper_opportunity_tier_reason"] == (
        "LIFECYCLE_OR_NO_TRADE_STRATEGY_NOT_ENTRY_EVIDENCE"
    )
    assert classification["paper_only"] is True
    assert classification["places_real_order"] is False
    assert "intent.strategy_selected_mode=NO_TRADE" in classification["no_trade_strategy_reasons"]
    assert "strategy_regime_labels_include_NO_TRADE" in classification["no_trade_strategy_reasons"]


def test_no_trade_regime_label_blocks_dynamic_b_grade_exploration() -> None:
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={
            "selected_action": "short",
            "confidence_calibrated": 0.68,
            "expected_move_after_cost_bps": -9.0,
            "market_regime": "MODEL_DISAGREEMENT,NO_TRADE",
        },
        intent={
            "side": "short",
            "confidence_calibrated": 0.68,
            "expected_move_after_cost_bps": -9.0,
            "market_regime_at_entry": "MODEL_DISAGREEMENT,NO_TRADE",
        },
        allocation=_allowed_allocation(confidence_calibrated=0.68, expected_move_after_cost_bps=-9.0),
        integrity_gate={"allowed": True},
        local_trade_gates_pass=False,
        exploration_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=0.0,
    )

    assert classification["paper_opportunity_tier"] == "NO_TRADE"
    assert classification["paper_opportunity_tier_reason"] == (
        "LIFECYCLE_OR_NO_TRADE_STRATEGY_NOT_ENTRY_EVIDENCE"
    )
    assert classification["no_trade_strategy_reasons"] == [
        "strategy_regime_labels_include_NO_TRADE"
    ]


def test_lifecycle_strategy_mode_cannot_be_b_grade_entry_evidence() -> None:
    classification = paper_loop._classify_paper_opportunity_tier(  # noqa: SLF001
        signal={
            "selected_action": "short",
            "confidence_calibrated": 0.68,
            "expected_move_after_cost_bps": -9.0,
            "strategy_router_selected_mode": "reduce_size_mode",
        },
        intent={
            "side": "short",
            "confidence_calibrated": 0.68,
            "expected_move_after_cost_bps": -9.0,
            "strategy_selected_mode": "trend_mode",
            "strategy_router_selected_mode": "reduce_size_mode",
            "entry_reason": "reduce_size_mode",
        },
        allocation=_allowed_allocation(confidence_calibrated=0.68, expected_move_after_cost_bps=-9.0),
        integrity_gate={"allowed": True},
        local_trade_gates_pass=False,
        exploration_trade_gates_pass=True,
        paper_fill_allowed_upstream=False,
        portfolio_drawdown_bps=0.0,
    )

    assert classification["paper_opportunity_tier"] == "NO_TRADE"
    assert classification["paper_opportunity_tier_reason"] == (
        "LIFECYCLE_OR_NO_TRADE_STRATEGY_NOT_ENTRY_EVIDENCE"
    )
    assert "intent.strategy_router_selected_mode=LIFECYCLE_ACTION" in classification[
        "lifecycle_or_no_trade_strategy_reasons"
    ]
    assert "intent.entry_reason=LIFECYCLE_ACTION" in classification[
        "lifecycle_or_no_trade_strategy_reasons"
    ]


def test_feedback_entry_context_uses_audited_strategy_as_entry_reason() -> None:
    intent = {
        "strategy_selected_mode": "trend_mode",
        "strategy_id": "trend_mode",
        "strategy_family": "trend_mode",
        "strategy_subtype": "trend_mode",
        "strategy_size_adjustment_mode": "reduce_size_mode",
    }

    paper_loop._attach_trainer_feedback_entry_context(  # noqa: SLF001
        intent=intent,
        prediction={},
        strategy_router={
            "selected_mode": "reduce_size_mode",
            "regime_labels": ["TREND"],
            "explanation": {},
        },
        allocation={"model_inputs": {}},
        portfolio_context={"drawdown_bps": 0.0},
    )

    assert intent["strategy_selected_mode"] == "trend_mode"
    assert intent["strategy_size_adjustment_mode"] == "reduce_size_mode"
    assert intent["entry_reason"] == "trend_mode"


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


def test_no_trade_tier_blocks_executable_allocator_decision() -> None:
    intent = {
        "paper_opportunity_tier": "NO_TRADE",
        "paper_opportunity_tier_reason": "EXPECTED_EDGE_NOT_FAVORABLE_AFTER_COST",
        "paper_only": True,
        "places_real_order": False,
        "gross_notional_usd": 1000.0,
        "allocated_margin_usd": 500.0,
        "paper_fill_allowed": True,
        "paper_sizing_complete": True,
    }
    allocation = _allowed_allocation(paper_opportunity_tier="NO_TRADE")

    blocked = paper_loop._block_non_executable_paper_tier(  # noqa: SLF001
        intent=intent,
        allocation=allocation,
    )

    assert blocked is True
    assert intent["allocator_decision"] == "BLOCK_NON_EXECUTABLE_PAPER_TIER"
    assert allocation["allocator_decision"] == "BLOCK_NON_EXECUTABLE_PAPER_TIER"
    assert intent["pre_non_executable_paper_tier"] == "NO_TRADE"
    assert intent["pre_non_executable_paper_tier_reason"] == "EXPECTED_EDGE_NOT_FAVORABLE_AFTER_COST"
    assert intent["non_executable_paper_tier_block_reason"] == "NON_EXECUTABLE_PAPER_TIER:NO_TRADE"
    assert allocation["pre_non_executable_paper_tier_reason"] == "EXPECTED_EDGE_NOT_FAVORABLE_AFTER_COST"
    assert intent["paper_fill_allowed"] is False
    assert intent["paper_sizing_complete"] is False
    assert intent["gross_notional_usd"] == 0.0
    assert allocation["gross_notional_usd"] == 0.0
    assert intent["pre_paper_tier_block_gross_notional_usd"] == 1000.0
    assert allocation["pre_paper_tier_block_gross_notional_usd"] == 1000.0
    assert intent["places_real_order"] is False
    assert allocation["places_real_order"] is False


def test_blocked_directional_candidate_can_emit_shadow_observation_without_fill_implication() -> None:
    intent = {
        "intent_id": "intent-shadow-1",
        "symbol": "BTCUSDT",
        "side": "long",
        "selected_action": "long",
        "timeframe": "1m",
        "strategy_selected_mode": "trend_mode",
        "strategy_router_selected_mode": "trend_mode",
        "paper_opportunity_tier": "NO_TRADE",
        "paper_opportunity_tier_reason": "EXPECTED_EDGE_NOT_FAVORABLE_AFTER_COST",
        "paper_only": True,
        "places_real_order": False,
        "paper_fill_allowed": True,
        "strict_paper_fill_allowed_upstream": True,
        "entry_price": 100.0,
        "entry_price_source": "V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE",
        "entry_price_utc": "2026-06-23T17:00:00Z",
        "entry_price_provenance_present": True,
        "paper_signal_temporal_rejection_reasons": [],
        "paper_pre_fill_market_evidence_rejection_reasons": [],
        "valid_for_paper": True,
    }

    shadow = paper_loop._shadow_observation_from_blocked_directional_candidate(  # noqa: SLF001
        intent=intent,
        signal={"selected_action": "long"},
        integrity_gate={"allowed": True},
        observation_source="NON_EXECUTABLE_PAPER_TIER_PRE_BLOCK",
        observation_reason="EXPECTED_EDGE_NOT_FAVORABLE_AFTER_COST",
    )

    assert shadow is not None
    assert shadow["decision"] == "SHADOW_OBSERVATION_ONLY"
    assert shadow["side"] == "long"
    assert shadow["paper_opportunity_tier"] == "NO_TRADE"
    assert shadow["shadow_observation_source"] == "NON_EXECUTABLE_PAPER_TIER_PRE_BLOCK"
    assert shadow["shadow_observation_selected_before_outcome"] is True
    assert shadow["paper_fill_allowed"] is False
    assert shadow["strict_paper_fill_allowed_upstream"] is False
    assert shadow["places_real_order"] is False
    assert shadow["counted_as_fill"] is False
    assert shadow["affects_pnl_ledger"] is False
    assert shadow["counts_as_a_grade_evidence"] is False
    assert shadow["a_grade_promotion_allowed"] is False
    assert shadow["live_ready_implication"] is False
    assert shadow["candidate_selected_after_outcome"] is False
    assert shadow["future_labels_used_as_features"] is False


def test_shadow_observation_rejects_dirty_or_no_trade_strategy_candidates() -> None:
    base_intent = {
        "intent_id": "intent-shadow-dirty",
        "symbol": "ETHUSDT",
        "side": "short",
        "selected_action": "short",
        "strategy_selected_mode": "trend_mode",
        "strategy_router_selected_mode": "trend_mode",
        "paper_opportunity_tier": "NO_TRADE",
        "paper_only": True,
        "places_real_order": False,
        "entry_price": 2000.0,
        "entry_price_source": "V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE",
        "entry_price_utc": "2026-06-23T17:00:00Z",
        "entry_price_provenance_present": True,
        "paper_signal_temporal_rejection_reasons": [],
        "paper_pre_fill_market_evidence_rejection_reasons": [],
        "valid_for_paper": True,
    }

    dirty = dict(base_intent)
    dirty["paper_signal_temporal_rejection_reasons"] = ["AVAILABLE_AT_AFTER_DECISION_TIME"]
    assert (
        paper_loop._shadow_observation_from_blocked_directional_candidate(  # noqa: SLF001
            intent=dirty,
            signal={"selected_action": "short"},
            integrity_gate={"allowed": True},
            observation_source="LOCAL_PAPER_TRADE_GATES_FAILED",
            observation_reason="temporal",
        )
        is None
    )

    no_trade_strategy = dict(base_intent)
    no_trade_strategy["strategy_selected_mode"] = "no_trade_mode"
    assert (
        paper_loop._shadow_observation_from_blocked_directional_candidate(  # noqa: SLF001
            intent=no_trade_strategy,
            signal={"selected_action": "short", "strategy_regime_labels": ["NO_TRADE"]},
            integrity_gate={"allowed": True},
            observation_source="NON_EXECUTABLE_PAPER_TIER_PRE_BLOCK",
            observation_reason="NO_TRADE_STRATEGY",
        )
        is None
    )


def test_shadow_observation_history_preserves_original_entry_time_for_duplicate() -> None:
    existing = {
        "decision": "SHADOW_OBSERVATION_ONLY",
        "intent_id": "intent-shadow-1",
        "prediction_id": "prediction-shadow-1",
        "symbol": "BTCUSDT",
        "side": "long",
        "timeframe": "1m",
        "shadow_observation_source": "NON_EXECUTABLE_PAPER_TIER_PRE_BLOCK",
        "shadow_observation_reason": "BLOCK_NO_EDGE",
        "entry_price": 100.0,
        "entry_price_source": "V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE",
        "entry_price_utc": "2026-06-23T17:00:00Z",
        "paper_only": True,
        "places_real_order": False,
        "paper_fill_allowed": False,
        "counted_as_fill": False,
    }
    current = {
        **existing,
        "entry_price": 101.0,
        "entry_price_utc": "2026-06-23T17:04:30Z",
        "generated_utc": "2026-06-23T17:04:30Z",
    }

    merged = paper_loop._merge_shadow_observation_history(  # noqa: SLF001
        [existing],
        [current],
        now_utc="2026-06-23T17:05:00Z",
    )

    assert len(merged) == 1
    row = merged[0]
    assert row["entry_price"] == 100.0
    assert row["entry_price_utc"] == "2026-06-23T17:00:00Z"
    assert row["shadow_observation_first_seen_utc"] == "2026-06-23T17:00:00Z"
    assert row["shadow_observation_last_seen_utc"] == "2026-06-23T17:05:00Z"
    assert row["shadow_observation_seen_count"] == 2
    assert row["shadow_observation_history_persisted"] is True
    assert row["paper_fill_allowed"] is False
    assert row["counted_as_fill"] is False
    assert row["affects_pnl_ledger"] is False
    assert row["counts_as_a_grade_evidence"] is False
    assert row["live_ready_implication"] is False


def test_shadow_observation_history_is_bounded_to_newest_rows() -> None:
    rows = [
        {
            "decision": "SHADOW_OBSERVATION_ONLY",
            "intent_id": f"intent-{idx}",
            "prediction_id": f"prediction-{idx}",
            "symbol": "BTCUSDT",
            "side": "long",
            "timeframe": "1m",
            "shadow_observation_source": "NON_EXECUTABLE_PAPER_TIER_PRE_BLOCK",
            "shadow_observation_reason": "BLOCK_NO_EDGE",
            "entry_price": 100.0 + idx,
            "entry_price_source": "V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE",
            "entry_price_utc": f"2026-06-23T17:0{idx}:00Z",
            "paper_only": True,
            "places_real_order": False,
        }
        for idx in range(5)
    ]

    merged = paper_loop._merge_shadow_observation_history(  # noqa: SLF001
        rows,
        [],
        now_utc="2026-06-23T17:10:00Z",
        max_rows=3,
    )

    assert [row["prediction_id"] for row in merged] == [
        "prediction-2",
        "prediction-3",
        "prediction-4",
    ]
    assert all(row["paper_fill_allowed"] is False for row in merged)
    assert all(row["places_real_order"] is False for row in merged)


def test_b_grade_tier_remains_paper_only_executable_lane() -> None:
    intent = {
        "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
        "paper_only": True,
        "places_real_order": False,
    }
    allocation = _allowed_allocation(paper_opportunity_tier="B_GRADE_EXPLORATION_PAPER")

    blocked = paper_loop._block_non_executable_paper_tier(  # noqa: SLF001
        intent=intent,
        allocation=allocation,
    )

    assert blocked is False
    assert allocation["allocator_decision"] == "ALLOW_WITH_SIZE"
    assert allocation["gross_notional_usd"] == 1000.0


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
                "counts_as_a_grade_evidence": False,
                "paper_only_label_collection_priority": True,
                "paper_only_label_collection_priority_reason": (
                    "PAPER_ONLY_COLLECT_MORE_B_GRADE_LABELS_FOR_PROMISING_UNDERPOWERED_BUCKET"
                ),
            },
        ],
        blocked_rows=[
            {
                "intent_id": "blocked-1",
                "paper_opportunity_tier": "NO_TRADE",
                "paper_opportunity_tier_reason": "NON_EXECUTABLE_PAPER_TIER:NO_TRADE",
                "pre_non_executable_paper_tier_reason": "EXPECTED_EDGE_NOT_FAVORABLE_AFTER_COST",
                "non_executable_paper_tier_block_reason": "NON_EXECUTABLE_PAPER_TIER:NO_TRADE",
                "local_block_reasons": ["paper_tier:NON_EXECUTABLE_PAPER_TIER:NO_TRADE"],
                "paper_fill_gate_block_reasons": ["NON_EXECUTABLE_PAPER_TIER:NO_TRADE"],
                "paper_runtime_market_evidence_rejection_reasons": [
                    "MISSING_PARTIAL_FILL_LEDGER_EVIDENCE"
                ],
                "lifecycle_or_no_trade_strategy_reasons": [
                    "intent.strategy_selected_mode=NO_TRADE"
                ],
            }
        ],
        shadow_rows=[{"paper_opportunity_tier": "SHADOW_ONLY"}],
        held_rows=[],
    )

    assert "missing" not in status["tier_counts"]
    assert status["accepted_tier_counts"] == {"B_GRADE_EXPLORATION_PAPER": 1}
    assert status["legacy_accepted_without_tier_count"] == 1
    assert status["b_grade_exploration_accepted_count"] == 1
    assert status["paper_only_label_collection_priority_candidate_count"] == 1
    assert status["paper_only_label_collection_priority_b_grade_accepted_count"] == 1
    assert status["persistent_paper_only_label_collection_priority_b_grade_accepted_count"] == 1
    assert status["paper_only_label_collection_priority_live_routing_blocked"] is True
    assert status["paper_only_label_collection_priority_reason_counts"] == {
        "PAPER_ONLY_COLLECT_MORE_B_GRADE_LABELS_FOR_PROMISING_UNDERPOWERED_BUCKET": 1
    }
    assert status["b_grade_exploration_live_routing_blocked"] is True
    assert status["blocked_final_reason_counts"] == {
        "NON_EXECUTABLE_PAPER_TIER:NO_TRADE": 1
    }
    assert status["blocked_upstream_tier_reason_counts"] == {
        "EXPECTED_EDGE_NOT_FAVORABLE_AFTER_COST": 1
    }
    assert status["blocked_runtime_market_evidence_rejection_counts"] == {
        "MISSING_PARTIAL_FILL_LEDGER_EVIDENCE": 1
    }
    assert status["blocked_lifecycle_or_no_trade_strategy_reason_counts"] == {
        "intent.strategy_selected_mode=NO_TRADE": 1
    }
    assert status["sample_blocked_fills"][0]["accepted_fill_state_compacted"] is True


def test_exploration_tier_status_uses_current_accepted_rows_for_primary_counts() -> None:
    status = paper_loop._paper_exploration_tier_status(  # noqa: SLF001
        accepted_rows=[
            {
                "fill_id": "historical-a",
                "paper_opportunity_tier": "A_GRADE_EXECUTION_PAPER",
                "paper_only": True,
                "places_real_order": False,
            },
            {
                "fill_id": "historical-b",
                "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
                "paper_only": True,
                "places_real_order": False,
            },
        ],
        current_accepted_rows=[
            {
                "fill_id": "current-b",
                "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
                "risk_budget_fraction_of_normal_adaptive": 0.12,
                "paper_only": True,
                "places_real_order": False,
            }
        ],
        blocked_rows=[],
        shadow_rows=[],
        held_rows=[],
    )

    assert status["accepted_tier_counts_scope"] == "current_cycle_accepted_fills_only"
    assert status["accepted_tier_counts"] == {"B_GRADE_EXPLORATION_PAPER": 1}
    assert status["persistent_accepted_tier_counts"] == {
        "A_GRADE_EXECUTION_PAPER": 1,
        "B_GRADE_EXPLORATION_PAPER": 1,
    }
    assert status["b_grade_exploration_accepted_count"] == 1
    assert status["persistent_b_grade_exploration_accepted_count"] == 1


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
