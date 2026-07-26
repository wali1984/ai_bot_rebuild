from __future__ import annotations

import pytest

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    V2HybridTrainerDataLoader,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FeatureTensorRecord,
)
from v2.backend.app.services.native_trainer.feedback_enrichment import (
    build_strategy_hedge_exit_feedback,
)
from v2.backend.app.services.paper_trade_management import lifecycle as lifecycle_module
from v2.backend.app.services.paper_trade_management.caps import PaperExposureCaps
from v2.backend.app.services.paper_trade_management.exits import (
    PAPER_EXIT_POLICY_VERSION,
    PaperExitConfig,
    evaluate_exit,
)
from v2.backend.app.services.paper_trade_management.lifecycle import (
    PaperLifecycleConfig,
    reconcile_paper_lifecycle,
)
from v2.backend.app.services.paper_trade_management.outcomes import (
    FUNDING_PNL_ACCOUNTING_FORMULA,
    FUNDING_PNL_ACCOUNTING_VERSION,
    OUTCOME_AVAILABILITY_SCHEMA_VERSION,
    OUTCOME_AVAILABILITY_SOURCE,
    build_close_event,
    capture_close_outcome_availability,
)
from v2.backend.app.services.paper_trade_management.position_state import (
    ADAPTIVE_CAPITAL_POLICY_VERSION,
    maintenance_bracket_evidence_from_payload,
    parse_aware_utc,
    position_from_fill,
)
from v2.backend.app.services.trade_lifecycle_guard import (
    TradeLifecycleGuardInput,
    evaluate_trade_lifecycle_guard,
)


def _fill(
    *,
    fill_id: str,
    symbol: str = "BTCUSDT",
    side: str = "long",
    qty: float = 1.0,
    price: float = 100.0,
    timeframe: str = "1m",
) -> dict:
    return {
        "fill_id": fill_id,
        "ledger_row_id": fill_id,
        "intent_id": fill_id,
        "symbol": symbol,
        "side": side,
        "quantity": qty,
        "notional": qty * price,
        "notional_usdt": qty * price,
        "entry_price": price,
        "fill_price": price,
        "fill_price_utc": "2026-06-11T10:00:00Z",
        "generated_utc": "2026-06-11T10:00:00Z",
        "signal_id": f"sig_{fill_id}",
        "prediction_id": f"pred_{fill_id}",
        "risk_decision_id": f"risk_{fill_id}",
        "orchestrator_decision_id": f"orch_{fill_id}",
        "decision_id": f"orch_{fill_id}",
        "market_state_id": f"ms_{fill_id}",
        "feature_snapshot_id": f"feat_{fill_id}",
        "mtf_snapshot_id": f"mtf_{fill_id}",
        "feature_cutoff": "2026-06-11T09:59:00Z",
        "decision_time": "2026-06-11T10:00:00Z",
        "available_at": "2026-06-11T09:59:30Z",
        "selected_action": side,
        "model_version": "unit_model_v1",
        "checkpoint_id": f"ckpt_{fill_id}",
        "source_hashes": {"feature_vector_hash": f"hash_{fill_id}"},
        "trainer_source": "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW",
        "timeframe": timeframe,
        "paper_fill_allowed": True,
        "maintenance_margin_rate": 0.005,
    }


_TEST_BRACKET_CHECKSUM = "a" * 64
_TEST_BRACKET_HMAC = "b" * 64
_TEST_BRACKET_BINDING = "mainnet:paper-test-trader:PAPER_TEST_READONLY"


def _maintenance_bracket_evidence(
    *,
    bracket_id: int = 1,
    ratio: float = 0.005,
    cum: float = 0.0,
    max_initial_leverage: float = 20.0,
    available_at: str = "2026-06-11T09:59:30Z",
    expires_at: str = "2026-06-11T10:10:00Z",
    consumer_observed_at: str = "2026-06-11T10:00:00Z",
) -> dict:
    return {
        "prevalidated": True,
        "bracket_id": bracket_id,
        "maint_margin_ratio": ratio,
        "cum": cum,
        "max_initial_leverage": max_initial_leverage,
        "evidence_hash": _TEST_BRACKET_CHECKSUM,
        "evidence_checksum_sha256": _TEST_BRACKET_CHECKSUM,
        "evidence_hmac_sha256": _TEST_BRACKET_HMAC,
        "binding": _TEST_BRACKET_BINDING,
        "environment_id": "mainnet",
        "key_id": "unit-key",
        "source": "BINANCE_USDM_USER_DATA_GET_FAPI_V1_LEVERAGE_BRACKET",
        "available_at": available_at,
        "expires_at": expires_at,
        "consumer_observed_at": consumer_observed_at,
    }


def _audit_quality_fields() -> dict:
    return {
        "actual_observed_spread_entry_bps": 1.4,
        "actual_observed_spread_exit_bps": 1.6,
        "observed_bid": 99.99,
        "observed_ask": 100.01,
        "observed_spread_bps": 1.4,
        "order_size": 100.0,
        "order_size_usd": 100.0,
        "entry_spread_source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test",
        "exit_spread_source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test",
        "expected_slippage_bps": 0.9,
        "expected_slippage_usd": 0.01,
        "expected_slippage_source": "MODELED_FROM_OBSERVED_SPREAD_VOLATILITY_LIQUIDITY",
        "expected_slippage_modeled": True,
        "selector_policy_fingerprint": "selector-fp-audit",
        "frozen_selector_fingerprint": "selector-fp-audit",
        "candidate_selected_before_outcome": True,
        "candidate_selected_after_outcome": False,
        "post_outcome_candidate_selection": False,
        "future_labels_used_as_features": False,
        "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
        "paper_opportunity_tier_reason": "UNIT_PRE_OUTCOME_EXPLORATION",
        "explicit_paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
        "paper_fill_allowed_source": "B_GRADE_EXPLORATION_PAPER_LOCAL_GATE",
        "strict_paper_fill_allowed_upstream": False,
        "calibration_label_purpose": "B_GRADE_EXPLORATION_FEEDBACK",
        "bid_depth_usd": 125000.0,
        "ask_depth_usd": 100000.0,
        "orderbook_depth_usd": 100000.0,
        "top_book_bid_depth_usd": 125000.0,
        "top_book_ask_depth_usd": 100000.0,
        "entry_orderbook_depth_usd": 100000.0,
        "entry_orderbook_depth_side": "ask",
        "top_of_book_depth_usd": 100000.0,
        "market_depth_usd": 100000.0,
        "orderbook_depth_source": "v2:market:orderbook:BTCUSDT:top5_notional_usd",
        "depth_utilization_pct": 0.001,
        "depth_derived_price_impact_bps": 0.25,
        "depth_price_impact_bps": 0.25,
        "depth_price_impact_source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test:ask_levels_top5:top5_vwap_vs_touch",
        "depth_price_impact_model": "ORDERBOOK_TOP5_VWAP_VS_TOUCH",
        "depth_price_impact_side": "ask",
        "depth_price_impact_quantity": 1.0,
        "depth_price_impact_filled_quantity": 1.0,
        "depth_price_impact_fill_complete": True,
        "depth_price_impact_vwap": 100.0025,
        "depth_price_impact_touch_price": 100.0,
        "maker_taker_assumption": "taker",
        "maker_taker_probability_detail": {"maker": 0.35, "taker": 0.65},
        "fee_schedule": {
            "fee_bps": 4.0,
            "source": "CONFIGURED_PAPER_FEE_SCHEDULE:unit",
            "maker_taker_assumption": "taker",
            "configured_schedule": True,
        },
        "fee_bps": 4.0,
        "fee_bps_source": "CONFIGURED_PAPER_FEE_SCHEDULE:unit",
        "fee_bps_configured_schedule": True,
        "funding_rate": 0.00002,
        "expected_funding_bps": 0.2,
        "holding_period_funding_bps": 0.2,
        "holding_period_funding_source": "expected_funding_bps",
        "latency_reserve_bps": 1.4,
        "latency_reserve_source": "ADAPTIVE_ALLOCATOR_EXECUTION_UNCERTAINTY_BPS",
        "partial_fill_estimate": {
            "model": "PAPER_SINGLE_IMMEDIATE_FILL",
            "expected_fill_count": 1,
            "expected_fill_probability": 1.0,
            "partial_fill_adjustment_bps": 0.0,
            "source": "PAPER_RUNTIME_FILL_LEDGER_ESTIMATE",
        },
        "partial_fill_probability": 1.0,
        "partial_fill_adjustment_bps": 0.0,
        "execution_probability": 1.0,
        "cost_source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test",
        "cost_source_timestamp": "2026-06-11T09:59:58Z",
        "source_timestamp": "2026-06-11T09:59:58Z",
        "cost_evidence_freshness_ms": 2000.0,
        "cost_evidence_source_fields": {
            "spread": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test",
            "fee": "CONFIGURED_PAPER_FEE_SCHEDULE:unit",
        },
        "runtime_cost_capture_source": "V2_PAPER_RUNTIME_DECISION_TIME_COST_CAPTURE",
        "runtime_cost_capture_status": "PRODUCTION_GRADE_COST_CAPTURE",
        "runtime_cost_capture_required_fields": [
            "observed_bid",
            "observed_ask",
            "observed_spread_bps",
            "order_size",
            "fee_schedule",
        ],
        "runtime_cost_capture_missing_fields": [],
        "runtime_cost_capture_explained_missing_fields": [],
        "runtime_cost_capture_unexplained_missing_fields": [],
        "runtime_cost_capture_order_cost_applicable": True,
        "runtime_cost_capture_no_order_reason": None,
        "runtime_cost_capture_temporal_reject_reasons": [],
        "fallback_cost_flag": False,
        "fallback": False,
        "production_grade_cost_flag": True,
        "production_grade_cost_evidence": True,
        "estimated_production_cost": 6.5,
        "estimated_production_cost_bps": 6.5,
        "counts_as_production_grade_training_evidence": True,
        "realized_slippage_bps": 1.0,
        "realized_slippage_usd": 0.01,
        "implementation_shortfall_usd": 0.0,
        "squeeze_evidence_score": 0.0,
        "squeeze_evidence_source": "DERIVED_FROM_LIQUIDATION_OI_FUNDING_ORDERBOOK_CONTEXT",
        "squeeze_evidence_components": {"spread_stress": 0.0},
        "mfe_bps": 20.0,
        "mfe_usd": 1.0,
        "mae_bps": 5.0,
        "mae_usd": 0.25,
        "intra_trade_high_price": 101.0,
        "intra_trade_low_price": 99.5,
        "trailing_stop_history": [],
        "microstructure_context": {
            "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test",
            "bid_ask_spread_bps": 1.4,
        },
    }


def _premium_ingestor_context_fields() -> dict:
    liquidity = {
        "source": "V2_ENTRY_FEATURE_SNAPSHOT_PREMIUM_INGESTORS",
        "orderbook_depth_usd": 100000.0,
        "bid_depth_usd": 125000.0,
        "ask_depth_usd": 100000.0,
        "depth_imbalance": 0.11,
        "nearest_bid_wall_distance_bps": 44.0,
        "nearest_ask_wall_distance_bps": 61.0,
    }
    liquidation = {
        "source": "V2_ENTRY_FEATURE_SNAPSHOT_PREMIUM_INGESTORS",
        "nearest_liquidation_level_above": 103.0,
        "nearest_liquidation_level_below": 97.0,
        "liquidation_sweep_target_short_distance_bps": 77.0,
        "liquidation_sweep_target_long_distance_bps": 118.0,
        "liquidation_pressure_direction": -0.2,
        "liquidation_levels_count_long": 4.0,
        "liquidation_levels_count_short": 3.0,
    }
    return {
        "liquidity_zone_context": liquidity,
        "liquidity_context": liquidity,
        "liquidation_distance_context": liquidation,
        "liquidation_context": liquidation,
        "microstructure_context": {
            "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test",
            "bid_ask_spread_bps": 1.4,
            "orderbook_depth_usd": 100000.0,
            "depth_imbalance": 0.11,
            "micro_price": 100.01,
        },
        "oi_funding_context": {
            "source": "V2_ENTRY_FEATURE_SNAPSHOT_PREMIUM_INGESTORS",
            "funding_rate": 0.0001,
            "expected_funding_bps": 1.0,
            "long_short_ratio": 1.2,
            "oi_change_pct": 0.01,
        },
        "public_intel_context": {
            "source": "V2_ENTRY_FEATURE_SNAPSHOT_PREMIUM_INGESTORS",
            "public_intel_score": 0.1,
            "news_sentiment_score": 0.05,
        },
    }


def _entry_feature_snapshot(fill_id: str) -> dict:
    return {
        "feature_snapshot_id": f"feat_{fill_id}",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "available_at": "2026-06-11T09:59:30Z",
        "generated_at": "2026-06-11T09:59:30Z",
        "feature_cutoff": "2026-06-11T09:59:00Z",
        "source_available_time": "2026-06-11T09:59:30Z",
        "candle_closed_confirmed": True,
        "latest_unclosed_kline_excluded": True,
        "source_hashes": {"feature_vector_hash": f"hash_{fill_id}"},
        "features": {"ret_pct": 1.0},
    }


def _active_runtime_dynamic_exit_config(**overrides) -> PaperExitConfig:
    return PaperExitConfig(
        static_stop_loss_enabled=False,
        static_take_profit_enabled=False,
        static_profit_lock_enabled=False,
        static_profit_bank_enabled=False,
        static_max_hold_enabled=False,
        **overrides,
    )


def _position(fill_id: str, *, price: float = 100.0):
    fill = _fill(fill_id=fill_id, price=price)
    return position_from_fill(
        fill,
        fill_id=fill_id,
        side=str(fill["side"]),
        quantity=float(fill["quantity"]),
        price=price,
    )


def test_close_builder_keeps_entry_and_pending_outcome_availability_distinct() -> None:
    close_event, outcome = build_close_event(
        position=_position("outcome-time-builder"),
        close_quantity=1.0,
        exit_price=101.0,
        exit_time="2026-06-11T10:05:00Z",
        close_reason="TEST_CLOSE",
    )

    for row in (close_event, outcome):
        assert row["close_event_time"] == "2026-06-11T10:05:00Z"
        assert parse_aware_utc(row["outcome_generated_at"]) is not None
        assert row["outcome_availability_schema_version"] == (
            OUTCOME_AVAILABILITY_SCHEMA_VERSION
        )
        assert row["outcome_availability_status"] == (
            "PENDING_LIFECYCLE_PUBLICATION"
        )
        assert "outcome_available_at" not in row
        # This remains the entry feature's availability clock.  It must never
        # be relabelled as post-close outcome availability.
        assert row["available_at"] == "2026-06-11T09:59:30Z"


def test_lifecycle_seals_new_close_outcome_availability_after_generation() -> None:
    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[_fill(fill_id="outcome-time-publish")],
        mark_prices={"BTCUSDT": 102.0},
        generated_utc="2026-06-11T10:05:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(
                take_profit_bps=100.0,
                stop_loss_bps=99999.0,
            ),
        ),
    )

    close_event = result["new_close_events"][0]
    outcome = result["new_outcome_labels"][0]
    for row in (close_event, outcome):
        close_time = parse_aware_utc(row["close_event_time"])
        generated_at = parse_aware_utc(row["outcome_generated_at"])
        available_at = parse_aware_utc(row["outcome_available_at"])
        assert close_time is not None
        assert generated_at is not None
        assert available_at is not None
        assert close_time <= generated_at <= available_at
        assert row["outcome_available_at_source"] == OUTCOME_AVAILABILITY_SOURCE
        assert row["outcome_availability_status"] == "READY"
        assert row["available_at"] == "2026-06-11T09:59:30Z"
    assert close_event["outcome_generated_at"] == outcome["outcome_generated_at"]
    assert close_event["outcome_available_at"] == outcome["outcome_available_at"]


def test_outcome_availability_seal_fails_closed_on_invalid_pit_order() -> None:
    close_event, outcome = build_close_event(
        position=_position("outcome-time-order"),
        close_quantity=1.0,
        exit_price=101.0,
        exit_time="2026-06-11T10:05:00Z",
        close_reason="TEST_CLOSE",
    )
    for row in (close_event, outcome):
        row["outcome_generated_at"] = "2026-06-11T10:05:02Z"

    sealed_close, sealed_outcome, reasons = capture_close_outcome_availability(
        close_event,
        outcome,
        outcome_available_at="2026-06-11T10:05:01Z",
    )

    assert reasons == ["OUTCOME_AVAILABLE_AT_BEFORE_OUTCOME_GENERATED_AT"]
    assert "outcome_available_at" not in sealed_close
    assert "outcome_available_at" not in sealed_outcome


def test_lifecycle_blocks_close_when_outcome_clock_precedes_close_event(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "v2.backend.app.services.paper_trade_management.outcomes._utc_now_iso_microseconds",
        lambda: "2026-06-11T10:04:59Z",
    )

    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[_fill(fill_id="outcome-time-fail-closed")],
        mark_prices={"BTCUSDT": 102.0},
        generated_utc="2026-06-11T10:05:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(
                take_profit_bps=100.0,
                stop_loss_bps=99999.0,
            ),
        ),
    )

    assert result["new_close_events"] == []
    assert result["new_outcome_labels"] == []
    assert result["open_positions"][0]["symbol"] == "BTCUSDT"
    block = result["paper_closed_trade_outcome_label_status"]["dirty_close_blocks"][0]
    assert block["paper_outcome_availability_status"] == "BLOCKED"
    assert block["paper_close_block_reasons"] == [
        "OUTCOME_AVAILABLE_AT_BEFORE_CLOSE_EVENT_TIME",
        "OUTCOME_GENERATED_AT_BEFORE_CLOSE_EVENT_TIME",
    ]


def test_lifecycle_does_not_backfill_outcome_availability_on_historical_rows() -> None:
    historical_close = {
        "close_id": "legacy-close-without-availability",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "exit_price_utc": "2026-06-10T10:05:00Z",
        "realized_pnl_usd": 1.0,
        "realized_net_pnl_usd": 0.9,
    }
    historical_outcome = {
        "outcome_label_id": "legacy-outcome-without-availability",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "exit_time": "2026-06-10T10:05:00Z",
        "realized_pnl_usd": 1.0,
        "realized_net_pnl_usd": 0.9,
    }

    result = reconcile_paper_lifecycle(
        existing_ledger={
            "closed_trades": [historical_close],
            "outcome_labels": [historical_outcome],
        },
        accepted_fills=[],
        generated_utc="2026-06-11T10:05:00Z",
    )

    assert "outcome_available_at" not in result["closed_trades"][0]
    assert "outcome_generated_at" not in result["closed_trades"][0]
    assert "outcome_available_at" not in result["outcome_labels"][0]
    assert "outcome_generated_at" not in result["outcome_labels"][0]


def test_active_runtime_exit_config_suppresses_static_stop_loss() -> None:
    position = _position("static_stop_disabled")

    result = evaluate_exit(
        position=position,
        # -20bps: static 80bps stop suppressed; above the 35bps missing-ATR
        # floor fallback added by the A+ goal (Phase 8).
        mark_price=99.8,
        generated_utc="2026-06-11T10:30:00Z",
        config=_active_runtime_dynamic_exit_config(stop_loss_bps=80.0),
    )

    assert result["should_close"] is False
    assert result["close_reason"] is None

    # LITUSDT regression (A+ goal Phase 8): with static stops suppressed and no
    # ATR, the missing-ATR floor fallback still closes real losses instead of
    # leaving the position stopless.
    deep = evaluate_exit(
        position=_position("static_stop_disabled_deep"),
        mark_price=98.0,  # -200bps
        generated_utc="2026-06-11T10:30:00Z",
        config=_active_runtime_dynamic_exit_config(stop_loss_bps=80.0),
    )
    assert deep["should_close"] is True
    assert deep["close_reason"] == "TIER_1_ATR_VOLATILITY_STOP"
    assert deep["atr_missing_floor_fallback"] is True


def test_active_runtime_exit_config_suppresses_static_take_profit_and_max_hold() -> None:
    take_profit_position = _position("static_tp_disabled")
    take_profit = evaluate_exit(
        position=take_profit_position,
        mark_price=102.0,
        generated_utc="2026-06-11T10:30:00Z",
        config=_active_runtime_dynamic_exit_config(take_profit_bps=100.0),
    )
    assert take_profit["should_close"] is False
    assert take_profit["close_reason"] is None

    max_hold_position = _position("static_hold_disabled")
    max_hold = evaluate_exit(
        position=max_hold_position,
        mark_price=100.0,
        generated_utc="2026-06-11T12:00:00Z",
        config=_active_runtime_dynamic_exit_config(max_hold_seconds=10),
    )
    assert max_hold["should_close"] is False
    assert max_hold["close_reason"] is None


def test_active_runtime_exit_config_keeps_dynamic_atr_stop_enabled() -> None:
    position = _position("dynamic_atr_enabled")

    result = evaluate_exit(
        position=position,
        mark_price=98.0,
        generated_utc="2026-06-11T10:30:00Z",
        config=_active_runtime_dynamic_exit_config(),
        atr_bps=50.0,
    )

    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_1_ATR_VOLATILITY_STOP"
    assert result["atr_stop_bps"] == pytest.approx(100.0)


def test_position_from_fill_derives_entry_atr_from_percent_feature() -> None:
    fill = _fill(fill_id="atr_pct", price=100.0)
    fill["features"] = {"true_range_pct": 0.75, "ta_ATR": 2.0}

    pos = position_from_fill(fill, fill_id="atr_pct", side="long", quantity=1.0, price=100.0)

    assert pos.entry_atr_bps == pytest.approx(75.0)


def test_position_from_fill_derives_entry_atr_from_price_atr_feature() -> None:
    fill = _fill(fill_id="atr_price", price=100.0)
    fill["features"] = {"ta_ATR": 2.0}

    pos = position_from_fill(fill, fill_id="atr_price", side="long", quantity=1.0, price=100.0)

    assert pos.entry_atr_bps == pytest.approx(200.0)


def test_closed_feedback_preserves_paper_execution_evidence() -> None:
    fill = _fill(fill_id="exec_evidence", price=100.0)
    fill.update(_audit_quality_fields())
    fill.update(
        {
            "strategy_id": "trend_mode",
            "strategy_family": "trend_mode",
            "strategy_selected_mode": "trend_mode",
            "market_regime_at_entry": "TREND",
            "liquidity_zone_context": {"source": "unit"},
            "liquidation_distance_context": {"source": "unit"},
            "microstructure_context": {
                "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test",
                "bid_ask_spread_bps": 1.4,
            },
            "oi_funding_context": {"source": "unit"},
            "public_intel_context": {"source": "unit"},
            "major_move_signal_id": "major-1",
            "maker_probability": 0.35,
            "taker_probability": 0.65,
            "maker_taker_probability_source": "PAPER_FILL_MODEL_FROM_OBSERVED_DEPTH",
            "selector_policy_fingerprint": "selector-fp-exec",
            "frozen_selector_fingerprint": "selector-fp-exec",
            "candidate_selected_before_outcome": True,
            "candidate_selected_after_outcome": False,
            "post_outcome_candidate_selection": False,
            "future_labels_used_as_features": False,
            "latency_ms": 42.0,
            "latency_source": "PAPER_DECISION_TO_FILL_RUNTIME_TIMESTAMPS",
            "partial_fill_count": 2,
            "partial_fills": [
                {"quantity": 0.4, "price": 100.0},
                {"quantity": 0.6, "price": 100.1},
            ],
            "mark_index_divergence_bps": 0.8,
            "mark_index_source": "V2_MARKET_FUNDING_PREMIUM_INDEX:v2:market:funding:BTCUSDT",
            "mark_index_available_at": "2026-06-11T10:00:00Z",
            "mark_price": 100.08,
            "index_price": 100.0,
        }
    )
    position = position_from_fill(
        fill,
        fill_id="exec_evidence",
        side="long",
        quantity=1.0,
        price=100.0,
    )

    close_event, outcome = build_close_event(
        position=position,
        close_quantity=1.0,
        exit_price=101.0,
        exit_time="2026-06-11T10:10:00Z",
        close_reason="TIER_2_TAKE_PROFIT",
        exit_spread_bps=1.6,
        exit_spread_source="V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test",
    )
    feedback = build_strategy_hedge_exit_feedback(
        close_event=close_event,
        outcome_label=outcome,
    )

    assert position.production_grade_cost_flag is True
    assert position.runtime_cost_capture_status == "PRODUCTION_GRADE_COST_CAPTURE"
    assert position.cost_source == "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test"
    assert position.maker_probability == pytest.approx(0.35)
    assert close_event["maker_probability"] == pytest.approx(0.35)
    assert outcome["latency_ms"] == pytest.approx(42.0)
    assert outcome["execution_latency_ms"] == pytest.approx(42.0)
    assert feedback["maker_probability"] == pytest.approx(0.35)
    assert feedback["taker_probability"] == pytest.approx(0.65)
    assert feedback["maker_taker_probability_source"] == "PAPER_FILL_MODEL_FROM_OBSERVED_DEPTH"
    assert feedback["selector_policy_fingerprint"] == "selector-fp-exec"
    assert feedback["frozen_selector_fingerprint"] == "selector-fp-exec"
    assert feedback["candidate_selected_before_outcome"] is True
    assert feedback["candidate_selected_after_outcome"] is False
    assert feedback["post_outcome_candidate_selection"] is False
    assert feedback["future_labels_used_as_features"] is False
    assert feedback["paper_opportunity_tier"] == "B_GRADE_EXPLORATION_PAPER"
    assert feedback["paper_opportunity_tier_reason"] == "UNIT_PRE_OUTCOME_EXPLORATION"
    assert feedback["explicit_paper_opportunity_tier"] == "B_GRADE_EXPLORATION_PAPER"
    assert feedback["paper_fill_allowed_source"] == "B_GRADE_EXPLORATION_PAPER_LOCAL_GATE"
    assert feedback["strict_paper_fill_allowed_upstream"] is False
    assert feedback["calibration_label_purpose"] == "B_GRADE_EXPLORATION_FEEDBACK"
    assert feedback["latency_ms"] == pytest.approx(42.0)
    assert feedback["paper_fill_latency_ms"] == pytest.approx(42.0)
    assert feedback["fill_latency_ms"] == pytest.approx(42.0)
    assert feedback["execution_latency_ms"] == pytest.approx(42.0)
    assert feedback["simulated_latency_ms"] == pytest.approx(42.0)
    assert feedback["latency_source"] == "PAPER_DECISION_TO_FILL_RUNTIME_TIMESTAMPS"
    assert feedback["partial_fill_count"] == 2
    assert feedback["partial_fills"] == fill["partial_fills"]
    assert feedback["mark_index_divergence_bps"] == pytest.approx(0.8)
    assert feedback["mark_index_source"] == "V2_MARKET_FUNDING_PREMIUM_INDEX:v2:market:funding:BTCUSDT"
    assert feedback["mark_index_available_at"] == "2026-06-11T10:00:00Z"
    assert feedback["mark_price"] == pytest.approx(100.08)
    assert feedback["index_price"] == pytest.approx(100.0)
    for row in (close_event, outcome, feedback):
        assert row["closed_entry_notional_usd"] == pytest.approx(100.0)
        assert row["realized_gross_pnl_usd"] == pytest.approx(1.0)
        assert row["fees_usd"] == pytest.approx(row["fees"])
        assert row["slippage_usd"] == pytest.approx(row["slippage"])
        assert row["funding_pnl_usd"] == pytest.approx(row["funding"])
        assert row["realized_net_pnl_usd"] == pytest.approx(
            row["realized_gross_pnl_usd"]
            - row["fees_usd"]
            - row["slippage_usd"]
            + row["funding_pnl_usd"]
        )
        assert row["production_grade_cost_flag"] is True
        assert row["production_grade_cost_evidence"] is True
        assert row["counts_as_production_grade_training_evidence"] is True
        assert row["runtime_cost_capture_status"] == "PRODUCTION_GRADE_COST_CAPTURE"
        assert row["runtime_cost_capture_missing_fields"] == []
        assert row["runtime_cost_capture_temporal_reject_reasons"] == []
        assert row["cost_source"] == "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test"
        assert row["cost_source_timestamp"] == "2026-06-11T09:59:58Z"
        assert row["cost_evidence_freshness_ms"] == pytest.approx(2000.0)
        assert row["order_size_usd"] == pytest.approx(100.0)
        assert row["fee_bps"] == pytest.approx(4.0)
        assert row["fee_schedule"]["source"] == "CONFIGURED_PAPER_FEE_SCHEDULE:unit"
        assert row["latency_reserve_bps"] == pytest.approx(1.4)
        assert row["partial_fill_estimate"]["source"] == "PAPER_RUNTIME_FILL_LEDGER_ESTIMATE"
        assert row["estimated_production_cost_bps"] == pytest.approx(6.5)


def test_same_symbol_repeated_long_nets_into_one_position() -> None:
    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[_fill(fill_id="a", qty=1), _fill(fill_id="b", qty=0.5, price=110)],
        mark_prices={"BTCUSDT": 110.0},
        generated_utc="2026-06-11T10:05:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(
                take_profit_bps=99999.0,
                stop_loss_bps=99999.0,
                profit_bank_bps=99999.0,
                profit_lock_bps=99999.0,
            ),
        ),
    )

    assert len(result["open_positions"]) == 1
    assert result["open_positions"][0]["net_quantity"] == 1.5
    assert result["paper_hedge_netting_status"]["same_side_netting_count"] == 1


def test_position_from_fill_reconciles_notional_margin_and_leverage() -> None:
    fill = _fill(fill_id="capital-reconcile", qty=2.0, price=50.0)
    fill.update(
        {
            "gross_notional_usd": 250.0,
            "allocated_margin_usd": 50.0,
            "effective_leverage": 4.0,
            "maintenance_margin_rate": 0.01,
            "maintenance_margin_estimate": 99.0,
            "liquidation_price_estimate": 1.0,
            "liquidation_buffer_bps": 9999.0,
            "maintenance_bracket_evidence": _maintenance_bracket_evidence(
                ratio=0.01,
            ),
        }
    )

    position = position_from_fill(
        fill,
        fill_id="capital-reconcile",
        side="long",
        quantity=2.0,
        price=50.0,
    )
    payload = position.to_payload(generated_utc="2026-06-11T10:01:00Z")

    assert payload["gross_notional_usd"] == pytest.approx(100.0)
    assert payload["allocated_margin_usd"] == pytest.approx(25.0)
    assert payload["effective_leverage"] == pytest.approx(4.0)
    assert payload["allocated_margin_usd"] * payload["effective_leverage"] == pytest.approx(
        payload["gross_notional_usd"]
    )
    assert payload["maintenance_margin_estimate"] == pytest.approx(1.0)
    assert payload["allocated_margin_usd_upstream"] == pytest.approx(50.0)
    assert payload["capital_accounting_reconciled"] is True
    assert "ALLOCATED_MARGIN_RECOMPUTED_FROM_NOTIONAL_LEVERAGE" in payload[
        "capital_accounting_reconciliation_reasons"
    ]


def test_position_from_fill_never_promotes_recommended_to_executed_leverage() -> None:
    fill = _fill(fill_id="recommendation-is-advisory", qty=2.0, price=50.0)
    fill["recommended_leverage"] = 8.0

    position = position_from_fill(
        fill,
        fill_id="recommendation-is-advisory",
        side="long",
        quantity=2.0,
        price=50.0,
    )

    assert position.recommended_leverage == pytest.approx(8.0)
    assert position.effective_leverage == pytest.approx(1.0)
    assert position.allocated_margin_usd == pytest.approx(100.0)
    assert position.leverage_source == "FAIL_CLOSED_1X_EXECUTED_LEVERAGE_MISSING"


def test_position_from_fill_never_labels_isolated_liquidation_math_as_cross() -> None:
    fill = _fill(fill_id="cross-margin-model-unavailable", qty=2.0, price=50.0)
    fill.update(
        {
            "effective_leverage": 2.0,
            "recommended_margin_mode": "cross_paper_simulated",
            "margin_mode_simulated": "cross_paper_simulated",
            "maintenance_bracket_evidence": _maintenance_bracket_evidence(),
        }
    )

    position = position_from_fill(
        fill,
        fill_id="cross-margin-model-unavailable",
        side="long",
        quantity=2.0,
        price=50.0,
    )

    assert position.recommended_margin_mode == "cross_paper_simulated"
    assert position.margin_mode_simulated == "isolated_paper_simulated"
    assert (
        "CROSS_MARGIN_SIMULATION_DOWNGRADED_NO_ACCOUNT_WIDE_LIQUIDATION_MODEL"
        in position.capital_accounting_reconciliation_reasons
    )
    assert position.liquidation_price_estimate is not None


def test_position_from_fill_missing_maintenance_has_no_liquidation_estimate() -> None:
    fill = _fill(fill_id="maintenance-missing", qty=1.0, price=100.0)
    fill.pop("maintenance_margin_rate")

    position = position_from_fill(
        fill,
        fill_id="maintenance-missing",
        side="long",
        quantity=1.0,
        price=100.0,
    )
    position.recompute_capital_accounting()

    assert position.maintenance_margin_rate is None
    assert position.maintenance_margin_estimate is None
    assert position.liquidation_price_estimate is None
    assert position.liquidation_buffer_bps is None
    assert "MAINTENANCE_BRACKET_EVIDENCE_MISSING_FAIL_CLOSED" in (
        position.capital_accounting_reconciliation_reasons
    )

    payload = position.to_payload(generated_utc="2026-06-11T10:01:00Z")
    assert payload["maintenance_margin_estimate"] is None
    assert payload["current_capital_accounting"]["maintenance_margin_estimate"] is None


def test_missing_maintenance_cannot_be_reconstructed_from_legacy_zero_estimate() -> None:
    fill = _fill(fill_id="maintenance-legacy-zero", qty=1.0, price=100.0)
    fill.pop("maintenance_margin_rate")
    fill["maintenance_margin_estimate"] = 0.0

    position = position_from_fill(
        fill,
        fill_id="maintenance-legacy-zero",
        side="long",
        quantity=1.0,
        price=100.0,
    )
    position.recompute_capital_accounting()
    payload = position.to_payload(generated_utc="2026-06-11T10:01:00Z")

    assert position.maintenance_margin_rate is None
    assert position.maintenance_margin_estimate is None
    assert position.liquidation_price_estimate is None
    assert position.liquidation_buffer_bps is None
    assert payload["maintenance_margin_estimate"] is None
    assert payload["current_capital_accounting"]["maintenance_margin_estimate"] is None


def test_same_side_netting_recomputes_aggregate_capital_state() -> None:
    first = _fill(fill_id="aggregate-a", qty=1.0, price=100.0)
    first.update(
        {
            "effective_leverage": 2.0,
            "allocated_margin_usd": 500.0,
            "maintenance_margin_rate": 0.005,
            "maintenance_bracket_evidence": _maintenance_bracket_evidence(
                bracket_id=1,
                ratio=0.005,
            ),
        }
    )
    second = _fill(fill_id="aggregate-b", qty=1.0, price=100.0)
    second.update(
        {
            "effective_leverage": 4.0,
            "allocated_margin_usd": 500.0,
            "maintenance_margin_rate": 0.01,
            "maintenance_bracket_evidence": _maintenance_bracket_evidence(
                bracket_id=2,
                ratio=0.01,
                max_initial_leverage=4.0,
            ),
        }
    )

    whole_position_bracket = _maintenance_bracket_evidence(
        bracket_id=3,
        ratio=0.006,
        cum=0.2,
        max_initial_leverage=3.0,
        consumer_observed_at="2026-06-11T10:01:00Z",
    )

    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[first, second],
        mark_prices={
            "BTCUSDT": {
                "price": 100.0,
                "maintenance_bracket_evidence": whole_position_bracket,
            }
        },
        generated_utc="2026-06-11T10:01:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exit_config=PaperExitConfig(
                take_profit_bps=99999.0,
                stop_loss_bps=99999.0,
                profit_bank_bps=99999.0,
                profit_lock_bps=99999.0,
            ),
        ),
    )

    position = result["open_positions"][0]
    assert position["net_quantity"] == pytest.approx(2.0)
    assert position["avg_entry_price"] == pytest.approx(100.0)
    assert position["gross_notional_usd"] == pytest.approx(200.0)
    assert position["allocated_margin_usd"] == pytest.approx(75.0)
    assert position["effective_leverage"] == pytest.approx(200.0 / 75.0)
    assert position["allocated_margin_usd"] * position["effective_leverage"] == pytest.approx(
        position["gross_notional_usd"]
    )
    assert position["maintenance_bracket_id"] == 3
    assert position["maintenance_margin_rate"] == pytest.approx(0.006)
    assert position["maintenance_margin_cum"] == pytest.approx(0.2)
    assert position["maintenance_margin_notional_usd"] == pytest.approx(200.0)
    assert position["maintenance_margin_estimate"] == pytest.approx(1.0)
    assert position["liquidation_price_estimate"] is not None
    assert position["liquidation_buffer_bps"] is not None
    assert result["paper_hedge_netting_status"]["same_side_netting_count"] == 1


def test_same_side_fill_uses_conservative_bracket_without_weighting_rates() -> None:
    first_fill = _fill(fill_id="tier-fill-a", qty=1.0, price=100.0)
    first_fill.update(
        {
            "effective_leverage": 2.0,
            "maintenance_bracket_evidence": _maintenance_bracket_evidence(
                bracket_id=1,
                ratio=0.005,
            ),
        }
    )
    second_fill = _fill(fill_id="tier-fill-b", qty=1.0, price=100.0)
    second_fill.update(
        {
            "effective_leverage": 4.0,
            "maintenance_bracket_evidence": _maintenance_bracket_evidence(
                bracket_id=2,
                ratio=0.01,
                max_initial_leverage=4.0,
            ),
        }
    )
    position = position_from_fill(
        first_fill,
        fill_id="tier-fill-a",
        side="long",
        quantity=1.0,
        price=100.0,
    )
    incoming = position_from_fill(
        second_fill,
        fill_id="tier-fill-b",
        side="long",
        quantity=1.0,
        price=100.0,
    )

    position.apply_same_side_fill(
        fill_id="tier-fill-b",
        quantity=1.0,
        price=100.0,
        incoming_position=incoming,
    )

    assert position.maintenance_bracket_id == 2
    assert position.maintenance_margin_rate == pytest.approx(0.01)
    assert position.maintenance_margin_rate != pytest.approx(0.0075)
    assert position.maintenance_margin_estimate == pytest.approx(2.0)
    assert position.maintenance_bracket_evidence_status == (
        "READY_CONSERVATIVE_SAME_SIDE_FILL"
    )
    assert position.allocated_margin_usd * position.effective_leverage == pytest.approx(
        position.gross_notional_usd
    )


def test_mark_tier_boundary_reselects_whole_position_bracket_and_uses_cum() -> None:
    fill = _fill(fill_id="tier-boundary", qty=5.0, price=99.0)
    fill.update(
        {
            "effective_leverage": 2.0,
            "maintenance_bracket_evidence": _maintenance_bracket_evidence(
                bracket_id=1,
                ratio=0.004,
            ),
        }
    )
    position = position_from_fill(
        fill,
        fill_id="tier-boundary",
        side="long",
        quantity=5.0,
        price=99.0,
    )

    position.update_mark(
        mark_price=99.99,
        mark_time="2026-06-11T10:01:00Z",
        maintenance_bracket_evidence=_maintenance_bracket_evidence(
            bracket_id=1,
            ratio=0.004,
            consumer_observed_at="2026-06-11T10:01:00Z",
        ),
    )
    assert position.maintenance_margin_notional_usd == pytest.approx(499.95)
    assert position.maintenance_margin_estimate == pytest.approx(1.9998)

    position.update_mark(
        mark_price=100.0,
        mark_time="2026-06-11T10:02:00Z",
        maintenance_bracket_evidence=_maintenance_bracket_evidence(
            bracket_id=2,
            ratio=0.01,
            cum=3.0,
            max_initial_leverage=3.0,
            consumer_observed_at="2026-06-11T10:02:00Z",
        ),
    )
    assert position.maintenance_bracket_id == 2
    assert position.maintenance_margin_notional_usd == pytest.approx(500.0)
    assert position.maintenance_margin_estimate == pytest.approx(2.0)
    # Entry-basis capital does not drift with the mark-basis maintenance tier.
    assert position.gross_notional_usd == pytest.approx(495.0)
    assert position.allocated_margin_usd == pytest.approx(247.5)
    assert position.allocated_margin_usd * position.effective_leverage == pytest.approx(
        position.gross_notional_usd
    )


def test_maintenance_bracket_roundtrip_and_lifecycle_restart() -> None:
    fill = _fill(fill_id="bracket-restart", qty=2.0, price=100.0)
    fill.update(
        {
            "effective_leverage": 2.0,
            "maintenance_bracket_evidence": _maintenance_bracket_evidence(
                ratio=0.006,
                cum=0.25,
            ),
        }
    )
    mark_evidence = _maintenance_bracket_evidence(
        ratio=0.006,
        cum=0.25,
        consumer_observed_at="2026-06-11T10:01:00Z",
    )
    first = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[fill],
        mark_prices={
            "BTCUSDT": {
                "price": 101.0,
                "maintenance_bracket_evidence": mark_evidence,
            }
        },
        generated_utc="2026-06-11T10:01:00Z",
        config=PaperLifecycleConfig(portfolio_equity_usdt=10000.0),
    )
    persisted = first["open_positions"][0]
    assert persisted["maintenance_bracket_evidence"]["binding"] == (
        _TEST_BRACKET_BINDING
    )
    assert persisted["maintenance_bracket_evidence_hash"] == (
        _TEST_BRACKET_CHECKSUM
    )

    restarted = reconcile_paper_lifecycle(
        existing_ledger=first,
        accepted_fills=[fill],
        mark_prices={
            "BTCUSDT": {
                "price": 102.0,
                "maintenance_bracket_evidence": _maintenance_bracket_evidence(
                    ratio=0.006,
                    cum=0.25,
                    consumer_observed_at="2026-06-11T10:02:00Z",
                ),
            }
        },
        generated_utc="2026-06-11T10:02:00Z",
        config=PaperLifecycleConfig(portfolio_equity_usdt=10000.0),
    )
    restored = restarted["open_positions"][0]
    assert restored["maintenance_bracket_id"] == 1
    assert restored["maintenance_bracket_maint_margin_ratio"] == pytest.approx(0.006)
    assert restored["maintenance_bracket_cum"] == pytest.approx(0.25)
    assert restored["maintenance_bracket_max_initial_leverage"] == pytest.approx(20.0)
    assert restored["maintenance_bracket_source"].startswith("BINANCE_USDM")
    assert restored["maintenance_bracket_available_at"] == "2026-06-11T09:59:30Z"
    assert restored["maintenance_bracket_expires_at"] == "2026-06-11T10:10:00Z"
    assert restored["maintenance_margin_notional_usd"] == pytest.approx(204.0)
    assert restored["maintenance_margin_estimate"] == pytest.approx(0.974)

    position = position_from_fill(
        fill,
        fill_id="bracket-close-lineage",
        side="long",
        quantity=2.0,
        price=100.0,
    )
    position.update_mark(
        mark_price=102.0,
        mark_time="2026-06-11T10:02:00Z",
        maintenance_bracket_evidence=_maintenance_bracket_evidence(
            ratio=0.006,
            cum=0.25,
            consumer_observed_at="2026-06-11T10:02:00Z",
        ),
    )
    close_event, outcome = build_close_event(
        position=position,
        close_quantity=2.0,
        exit_price=102.0,
        exit_time="2026-06-11T10:03:00Z",
        close_reason="UNIT_BRACKET_LINEAGE_CLOSE",
    )
    for payload in (close_event, outcome):
        assert payload["maintenance_margin_rate"] == pytest.approx(0.006)
        assert payload["maintenance_margin_cum"] == pytest.approx(0.25)
        assert payload["maintenance_bracket_id"] == 1
        assert payload["maintenance_bracket_evidence_hash"] == (
            _TEST_BRACKET_CHECKSUM
        )
        assert payload["maintenance_bracket_binding"] == (
            _TEST_BRACKET_BINDING
        )
        assert payload["maintenance_bracket_environment_id"] == "mainnet"
        assert payload["maintenance_bracket_evidence_status"] == "READY"


def test_authenticated_bracket_drives_tier_zero_near_liquidation_exit() -> None:
    fill = _fill(fill_id="bracket-tier-zero", qty=10.0, price=100.0)
    fill.update(
        {
            "effective_leverage": 10.0,
            "allocated_margin_usd": 100.0,
            "gross_notional_usd": 1000.0,
            "maintenance_bracket_evidence": _maintenance_bracket_evidence(
                ratio=0.005,
                cum=0.0,
            ),
        }
    )
    mark_evidence = _maintenance_bracket_evidence(
        ratio=0.005,
        cum=0.0,
        consumer_observed_at="2026-06-11T10:01:00Z",
    )
    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[fill],
        mark_prices={
            "BTCUSDT": {
                "price": 91.0,
                "maintenance_bracket_evidence": mark_evidence,
            }
        },
        generated_utc="2026-06-11T10:01:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=100000.0,
            exit_config=PaperExitConfig(
                emergency_liquidation_distance_bps=250.0,
                min_hold_seconds=0,
                static_stop_loss_enabled=False,
                static_take_profit_enabled=False,
            ),
        ),
    )

    evaluations = result["paper_exit_coordinator_status"]["evaluations"]
    assert len(evaluations) == 1
    assert evaluations[0]["should_close"] is True
    assert evaluations[0]["close_reason"] == (
        "TIER_0_EMERGENCY_LIQUIDATION_DISTANCE"
    )
    assert evaluations[0]["current_liquidation_distance_bps"] <= 250.0
    assert result["new_close_events"][0]["close_reason"] == (
        "TIER_0_EMERGENCY_LIQUIDATION_DISTANCE"
    )


def test_missing_or_stale_mark_bracket_makes_maintenance_and_liquidation_unknown() -> None:
    fill = _fill(fill_id="bracket-missing-at-mark", qty=1.0, price=100.0)
    fill["maintenance_bracket_evidence"] = _maintenance_bracket_evidence()
    position = position_from_fill(
        fill,
        fill_id="bracket-missing-at-mark",
        side="long",
        quantity=1.0,
        price=100.0,
    )

    position.update_mark(
        mark_price=101.0,
        mark_time="2026-06-11T10:01:00Z",
        maintenance_bracket_evidence=None,
    )
    assert position.maintenance_margin_rate is None
    assert position.maintenance_margin_estimate is None
    assert position.liquidation_price_estimate is None
    assert position.liquidation_buffer_bps is None
    assert position.maintenance_bracket_id == 1
    assert position.maintenance_bracket_evidence_status == "MISSING_FOR_CURRENT_MARK"

    position.update_mark(
        mark_price=102.0,
        mark_time="2026-06-11T10:02:00Z",
        maintenance_bracket_evidence=_maintenance_bracket_evidence(
            bracket_id=2,
            ratio=0.01,
            cum=3.0,
            expires_at="2026-06-11T10:01:59Z",
            consumer_observed_at="2026-06-11T10:01:00Z",
        ),
    )
    assert position.maintenance_margin_estimate is None
    assert position.liquidation_price_estimate is None
    assert position.maintenance_bracket_id == 2
    assert position.maintenance_bracket_evidence_status == "STALE_AT_MARK"


@pytest.mark.parametrize(
    ("remove_field", "overrides"),
    (
        ("evidence_hmac_sha256", {}),
        (None, {"evidence_hmac_sha256": "B" * 64}),
        (None, {"evidence_hash": "c" * 64}),
        (None, {"binding": "testnet:paper-test-trader:PAPER_TEST_READONLY"}),
        (None, {"source": "UNTRUSTED_BRACKET_SOURCE"}),
    ),
    ids=(
        "missing-hmac",
        "noncanonical-hmac",
        "checksum-hash-mismatch",
        "environment-binding-mismatch",
        "wrong-source",
    ),
)
def test_mark_bracket_rejects_missing_or_tampered_provenance(
    remove_field: str | None,
    overrides: dict[str, object],
) -> None:
    fill = _fill(fill_id="bracket-provenance-adversarial")
    fill["maintenance_bracket_evidence"] = _maintenance_bracket_evidence()
    position = position_from_fill(
        fill,
        fill_id="bracket-provenance-adversarial",
        side="long",
        quantity=1.0,
        price=100.0,
    )
    evidence = _maintenance_bracket_evidence(
        consumer_observed_at="2026-06-11T10:01:00Z"
    )
    if remove_field is not None:
        evidence.pop(remove_field)
    evidence.update(overrides)

    position.update_mark(
        mark_price=101.0,
        mark_time="2026-06-11T10:01:00Z",
        maintenance_bracket_evidence=evidence,
    )

    assert position.maintenance_bracket_evidence_status == "INVALID"
    assert position.maintenance_margin_rate is None
    assert position.maintenance_margin_estimate is None
    assert position.liquidation_price_estimate is None
    assert position.liquidation_buffer_bps is None


def test_flattened_bracket_aliases_roundtrip_into_lifecycle_evidence() -> None:
    flattened = {
        "maintenance_bracket_id": 2,
        "maintenance_bracket_prevalidated": True,
        "maintenance_margin_rate": 0.01,
        "maintenance_margin_cum": 3.0,
        "maintenance_bracket_max_initial_leverage": 3.0,
        "maintenance_bracket_evidence_checksum_sha256": _TEST_BRACKET_CHECKSUM,
        "maintenance_bracket_evidence_hmac_sha256": _TEST_BRACKET_HMAC,
        "maintenance_bracket_account_binding_id": _TEST_BRACKET_BINDING,
        "maintenance_bracket_environment_id": "mainnet",
        "maintenance_bracket_key_id": "unit-key",
        "maintenance_bracket_source": (
            "BINANCE_USDM_USER_DATA_GET_FAPI_V1_LEVERAGE_BRACKET"
        ),
        "maintenance_margin_evidence_available_at": "2026-06-11T09:59:30Z",
        "maintenance_bracket_expires_at": "2026-06-11T10:10:00Z",
        "maintenance_bracket_consumer_observed_at": "2026-06-11T10:00:00Z",
    }

    evidence = maintenance_bracket_evidence_from_payload(flattened)

    assert evidence is not None
    assert evidence["binding"] == _TEST_BRACKET_BINDING
    assert evidence["available_at"] == "2026-06-11T09:59:30Z"
    assert evidence["evidence_checksum_sha256"] == _TEST_BRACKET_CHECKSUM
    assert evidence["evidence_hmac_sha256"] == _TEST_BRACKET_HMAC

    fill = _fill(fill_id="flattened-bracket-restart")
    fill.update(flattened)
    position = position_from_fill(
        fill,
        fill_id="flattened-bracket-restart",
        side="long",
        quantity=1.0,
        price=100.0,
    )
    assert position.maintenance_bracket_evidence_status == "READY"
    assert position.maintenance_margin_rate == pytest.approx(0.01)
    assert position.liquidation_price_estimate is not None


def test_selector_shaped_bracket_audit_record_normalizes_only_with_explicit_trust() -> None:
    raw_selector = {
        "prevalidated": True,
        "selected_bracket": 2,
        "maintenance_margin_rate": 0.01,
        "maintenance_margin_cum": 3.0,
        "max_initial_leverage": 3.0,
        "content_checksum_sha256": _TEST_BRACKET_CHECKSUM,
        "evidence_hmac_sha256": _TEST_BRACKET_HMAC,
        "credential_binding_id": _TEST_BRACKET_BINDING,
        "exchange_environment": "mainnet",
        "evidence_auth_key_id": "unit-key",
        "source": "BINANCE_USDM_USER_DATA_GET_FAPI_V1_LEVERAGE_BRACKET",
        "available_at": "2026-06-11T09:59:30Z",
        "expires_at": "2026-06-11T10:10:00Z",
        "consumer_observed_at": "2026-06-11T10:00:00Z",
    }

    evidence = maintenance_bracket_evidence_from_payload(
        {"paper_maintenance_margin_bracket_evidence": raw_selector}
    )

    assert evidence == {
        "prevalidated": True,
        "bracket_id": 2,
        "maint_margin_ratio": 0.01,
        "cum": 3.0,
        "max_initial_leverage": 3.0,
        "evidence_hash": _TEST_BRACKET_CHECKSUM,
        "evidence_checksum_sha256": _TEST_BRACKET_CHECKSUM,
        "evidence_hmac_sha256": _TEST_BRACKET_HMAC,
        "binding": _TEST_BRACKET_BINDING,
        "environment_id": "mainnet",
        "key_id": "unit-key",
        "source": "BINANCE_USDM_USER_DATA_GET_FAPI_V1_LEVERAGE_BRACKET",
        "available_at": "2026-06-11T09:59:30Z",
        "expires_at": "2026-06-11T10:10:00Z",
        "consumer_observed_at": "2026-06-11T10:00:00Z",
    }

    untrusted = dict(raw_selector)
    untrusted.pop("prevalidated")
    untrusted_evidence = maintenance_bracket_evidence_from_payload(
        {"paper_maintenance_margin_bracket_evidence": untrusted}
    )
    assert untrusted_evidence is not None
    assert untrusted_evidence["prevalidated"] is False


def test_reopen_same_symbol_after_close_uses_new_position_generation() -> None:
    old_fill = _fill(fill_id="reused-generation", qty=1.0, price=100.0)
    old_position = position_from_fill(
        old_fill,
        fill_id="reused-generation",
        side="long",
        quantity=1.0,
        price=100.0,
    )
    new_fill = _fill(fill_id="reused-generation", qty=1.0, price=101.0)
    new_fill["fill_price_utc"] = "2026-06-11T10:06:00Z"
    new_fill["generated_utc"] = "2026-06-11T10:06:00Z"
    new_fill["decision_time"] = "2026-06-11T10:06:00Z"

    result = reconcile_paper_lifecycle(
        existing_ledger={
            "closed_trades": [
                {
                    "close_id": "old-generation-close",
                    "position_id": old_position.position_id,
                    "legacy_position_id": old_position.legacy_position_id,
                    "position_generation_id": old_position.position_generation_id,
                    "entry_fill_id": "reused-generation",
                    "source_fill_ids": ["reused-generation"],
                    "symbol": "BTCUSDT",
                    "side": "long",
                    "entry_time": "2026-06-11T10:00:00Z",
                    "exit_time": "2026-06-11T10:05:00Z",
                }
            ]
        },
        accepted_fills=[new_fill],
        mark_prices={"BTCUSDT": 101.0},
        generated_utc="2026-06-11T10:07:00Z",
        config=PaperLifecycleConfig(portfolio_equity_usdt=10000.0),
    )

    assert result["closed_previously_fills"] == []
    assert len(result["open_positions"]) == 1
    reopened = result["open_positions"][0]
    assert reopened["legacy_position_id"] == "paper_pos_BTCUSDT"
    assert reopened["position_id"] != old_position.position_id
    assert reopened["position_generation_id"] != old_position.position_generation_id
    repeated = position_from_fill(
        new_fill,
        fill_id="reused-generation",
        side="long",
        quantity=1.0,
        price=101.0,
    )
    assert repeated.position_id == reopened["position_id"]


def test_long_then_short_closes_before_reverse() -> None:
    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[
            _fill(fill_id="a", side="long", qty=1, price=100),
            _fill(fill_id="b", side="short", qty=1, price=105),
        ],
        mark_prices={"BTCUSDT": 105.0},
        generated_utc="2026-06-11T10:05:00Z",
        config=PaperLifecycleConfig(portfolio_equity_usdt=10000.0),
    )

    assert result["open_positions"] == []
    assert len(result["closed_trades"]) == 1
    assert result["closed_trades"][0]["close_reason"] == "TIER_3_MODEL_REVERSAL_NETTING"
    assert result["paper_hedge_netting_status"]["opposite_side_netting_count"] == 1


def test_symbol_exposure_cap_blocks_new_entry() -> None:
    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[_fill(fill_id="a", qty=3, price=100)],
        mark_prices={"BTCUSDT": 100.0},
        generated_utc="2026-06-11T10:05:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.02),
        ),
    )

    assert result["open_positions"] == []
    assert result["blocked_entries"][0]["paper_lifecycle_block_reasons"] == [
        "PAPER_SYMBOL_NOTIONAL_CAP_BLOCK"
    ]


def test_total_exposure_cap_blocks_new_entry() -> None:
    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[
            _fill(fill_id="a", symbol="BTCUSDT", qty=1, price=100),
            _fill(fill_id="b", symbol="ETHUSDT", qty=1, price=100),
        ],
        mark_prices={"BTCUSDT": 100.0, "ETHUSDT": 100.0},
        generated_utc="2026-06-11T10:05:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(
                max_single_symbol_exposure_pct=0.05,
                max_total_paper_exposure_pct=0.015,
            ),
        ),
    )

    assert len(result["open_positions"]) == 1
    assert result["blocked_entries"][0]["paper_lifecycle_block_reasons"] == [
        "PAPER_TOTAL_EXPOSURE_CAP_BLOCK"
    ]


def test_time_based_exit_closes_stale_position() -> None:
    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[_fill(fill_id="a", qty=1, price=100)],
        mark_prices={"BTCUSDT": 100.0},
        generated_utc="2026-06-11T10:10:01Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(max_hold_seconds=10, take_profit_bps=99999.0, stop_loss_bps=99999.0),
        ),
    )

    assert result["open_positions"] == []
    close = result["closed_trades"][0]
    assert close["close_reason"] == "TIER_4_MAX_HOLD_TIME"
    assert close["reduce_only"] is True
    assert close["close_position"] is True
    assert close["position_transition"] == "LONG_TO_FLAT"
    assert close["remaining_quantity_after_close"] == 0.0
    assert close["margin_release_required"] is True


def test_take_profit_closes_profitable_position_and_writes_outcome() -> None:
    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[_fill(fill_id="a", qty=1, price=100)],
        mark_prices={"BTCUSDT": 102.0},
        generated_utc="2026-06-11T10:05:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(
                take_profit_bps=100.0,
                stop_loss_bps=99999.0,
                profit_bank_bps=99999.0,
            ),
        ),
    )

    assert result["closed_trades"][0]["close_reason"] == "TIER_2_TAKE_PROFIT"
    assert result["closed_trades"][0]["realized_pnl_usd"] > 0
    assert result["outcome_labels"][0]["winner"] is True


def test_closed_trade_generates_consumable_trainer_feedback() -> None:
    fill = _fill(fill_id="feedback", qty=1, price=100)
    fill.update(
        {
            "strategy_id": "trend_following",
            "strategy_family": "trend_following",
            "strategy_subtype": "trend_following",
            "strategy_selected_mode": "trend_following",
            "market_regime_at_entry": "TREND",
            **_premium_ingestor_context_fields(),
            **_audit_quality_fields(),
        }
    )

    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 102.0},
        generated_utc="2026-06-11T10:05:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(take_profit_bps=100.0, stop_loss_bps=99999.0),
        ),
    )

    row = build_strategy_hedge_exit_feedback(
        close_event=result["closed_trades"][0],
        outcome_label=result["outcome_labels"][0],
    )

    assert row["trainer_consumable"] is True
    assert row["prediction_id"] == "pred_feedback"
    assert row["feature_snapshot_id"] == "feat_feedback"
    assert row["market_state_id"] == "ms_feedback"
    assert row["timeframe"] == "1m"
    assert row["missing_feedback_fields"] == []


def test_strategy_exit_pnl_fields_reach_trainer_feedback() -> None:
    fill = _fill(fill_id="exit-pnl", qty=1, price=100)
    fill.update(
        {
            "strategy_id": "mean_reversion",
            "strategy_family": "mean_reversion",
            "strategy_subtype": "mean_reversion",
            "strategy_selected_mode": "mean_reversion",
            "market_regime_at_entry": "RANGE",
            "liquidity_zone_context": {"source": "test"},
            "liquidity_context": {"source": "test"},
            "liquidation_distance_context": {"source": "test"},
            "microstructure_context": {"source": "test"},
            "oi_funding_context": {"source": "test"},
            "public_intel_context": {"source": "test"},
        }
    )
    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 98.0},
        generated_utc="2026-06-11T10:05:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(stop_loss_bps=100.0, take_profit_bps=99999.0),
        ),
    )

    row = build_strategy_hedge_exit_feedback(
        close_event=result["closed_trades"][0],
        outcome_label=result["outcome_labels"][0],
    )

    assert row["strategy_id"] == "mean_reversion"
    assert row["exit_reason"] == "TIER_1_STOP_LOSS"
    assert row["realized_pnl_bps"] < 0
    assert row["realized_pnl"] < 0


def test_paper_exploration_feedback_carries_phase6_economic_aliases() -> None:
    fill = _fill(fill_id="exploration-phase6", qty=1, price=100)
    fill.update(
        {
            "strategy_id": "microstructure_momentum",
            "strategy_family": "microstructure_momentum",
            "strategy_subtype": "microstructure_momentum",
            "strategy_selected_mode": "microstructure_momentum",
            "market_regime_at_entry": "MICROSTRUCTURE_MOMENTUM",
            **_premium_ingestor_context_fields(),
            **_audit_quality_fields(),
            "paper_opportunity_tier": "PAPER_RISK_CONTROLLER_EXPLORATION",
            "explicit_paper_opportunity_tier": "PAPER_RISK_CONTROLLER_EXPLORATION",
            "tier": "PAPER_RISK_CONTROLLER_EXPLORATION",
            "exploration_tier": "PAPER_RISK_CONTROLLER_EXPLORATION",
            "paper_exploration_tier": "PAPER_RISK_CONTROLLER_EXPLORATION",
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "counts_as_A_plus": False,
            "counts_as_live_ready": False,
        }
    )
    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 102.0},
        generated_utc="2026-06-11T10:05:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(take_profit_bps=100.0, stop_loss_bps=99999.0),
        ),
    )

    htf_snapshot = {
        "feature_snapshot_id": "snap_phase6_htf",
        "available_at": "2026-06-11T09:59:00Z",
        "feature_cutoff": "2026-06-11T09:55:00Z",
        "features": {
            "htf_4h_close": 101.0,
            "bid_ask_spread_bps": 1.2,
        },
    }
    row = build_strategy_hedge_exit_feedback(
        close_event={
            **result["closed_trades"][0],
            "entry_feature_snapshot": htf_snapshot,
            "entry_feature_snapshot_id": "snap_phase6_htf",
            "feature_snapshot_id": "snap_phase6_htf",
            "mtf_snapshot_id": None,
        },
        outcome_label={**result["outcome_labels"][0], "mtf_snapshot_id": None},
    )

    assert row["paper_opportunity_tier"] == "PAPER_RISK_CONTROLLER_EXPLORATION"
    assert row["paper_only"] is True
    assert row["routes_to_live"] is False
    assert row["places_real_order"] is False
    assert row["counts_as_A_plus"] is False
    assert row["counts_as_live_ready"] is False
    assert row["entry_time"] is not None
    assert row["exit_time"] in {"2026-06-11T10:05:00Z", "2026-06-11T10:05:00.000Z"}
    assert row["realized_gross_pnl_usd"] is not None
    assert row["fees_usd"] == row["fees"]
    assert row["slippage_usd"] == row["slippage"]
    assert row["funding_usd"] == row["funding"]
    assert row["max_adverse_usd"] == row["mae_usd"]
    assert row["max_favorable_usd"] == row["mfe_usd"]
    assert row["win_loss"] in {"win", "loss"}
    assert row["dirty_flag"] is False
    assert row["dirty_reasons"] == []
    assert row["mtf_snapshot_id"] == "snap_phase6_htf"
    assert row["mtf_snapshot_id_source"] == "ENTRY_FEATURE_SNAPSHOT_WITH_HTF_FEATURES"
    assert "MISSING_TRUST_MTF_SNAPSHOT_ID" not in row["trust_envelope_rejection_reasons"]


def test_major_move_fields_reach_trainer_feedback() -> None:
    fill = _fill(fill_id="major-move", qty=1, price=100)
    fill.update(
        {
            "strategy_id": "correlated_major_squeeze",
            "strategy_family": "breakout",
            "strategy_subtype": "correlated_major_squeeze",
            "strategy_selected_mode": "correlated_major_squeeze",
            "entry_reason": "paper_only_major_move_candidate",
            "market_regime_at_entry": "correlated_breakout_squeeze",
            **_premium_ingestor_context_fields(),
            "major_move_signal_id": "major_move_abc",
            "future_window_label_source": "closed_candle_replay_label",
            **_audit_quality_fields(),
            "squeeze_evidence_score": 0.74,
        }
    )
    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 102.0},
        generated_utc="2026-06-11T10:05:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(take_profit_bps=100.0, stop_loss_bps=99999.0),
        ),
    )

    row = build_strategy_hedge_exit_feedback(
        close_event=result["closed_trades"][0],
        outcome_label=result["outcome_labels"][0],
    )

    assert row["trainer_consumable"] is True
    assert row["major_move_signal_id"] == "major_move_abc"
    assert row["major_move_context"]["major_move_signal_id"] == "major_move_abc"
    assert row["squeeze_evidence_score"] == 0.74


def test_stop_loss_closes_losing_position() -> None:
    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[_fill(fill_id="a", qty=1, price=100)],
        mark_prices={"BTCUSDT": 98.0},
        generated_utc="2026-06-11T10:05:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(stop_loss_bps=100.0, take_profit_bps=99999.0),
        ),
    )

    assert result["closed_trades"][0]["close_reason"] == "TIER_1_STOP_LOSS"
    assert result["outcome_labels"][0]["winner"] is False


def test_trailing_stop_closes_after_best_price_reverses() -> None:
    existing_ledger = {
        "accepted": [_fill(fill_id="a", qty=1, price=100)],
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_id": "paper_pos_BTCUSDT",
                "side": "long",
                "opened_est": "2026-06-11T10:00:00Z",
                "best_favorable_price": 105.0,
            }
        ],
    }
    result = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=[_fill(fill_id="a", qty=1, price=100)],
        mark_prices={"BTCUSDT": 104.0},
        generated_utc="2026-06-11T10:10:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(
                trailing_stop_bps=50.0,
                take_profit_bps=99999.0,
                stop_loss_bps=99999.0,
                profit_bank_bps=99999.0,
            ),
        ),
    )
    assert result["closed_trades"][0]["close_reason"] == "TIER_2_TRAILING_STOP"


def test_trailing_stop_preempts_static_profit_tiers_after_long_reversal() -> None:
    existing_ledger = {
        "accepted": [_fill(fill_id="trail-profit-long", qty=1, price=100)],
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_id": "paper_pos_BTCUSDT",
                "side": "long",
                "opened_est": "2026-06-11T10:00:00Z",
                "best_favorable_price": 105.0,
            }
        ],
    }

    result = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=[_fill(fill_id="trail-profit-long", qty=1, price=100)],
        mark_prices={"BTCUSDT": 104.0},
        generated_utc="2026-06-11T10:10:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(
                trailing_stop_bps=50.0,
                take_profit_bps=100.0,
                profit_bank_bps=100.0,
                stop_loss_bps=99999.0,
            ),
        ),
    )

    close = result["closed_trades"][0]
    assert close["close_reason"] == "TIER_2_TRAILING_STOP"
    assert close["realized_pnl_usd"] > 0.0
    assert close["trailing_stop_history"]


def test_trailing_stop_preempts_static_profit_tiers_after_short_reversal() -> None:
    fill = _fill(fill_id="trail-profit-short", side="short", qty=1, price=100)
    existing_ledger = {
        "accepted": [fill],
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_id": "paper_pos_BTCUSDT",
                "side": "short",
                "opened_est": "2026-06-11T10:00:00Z",
                "best_favorable_price": 95.0,
            }
        ],
    }

    result = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 96.0},
        generated_utc="2026-06-11T10:10:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(
                trailing_stop_bps=50.0,
                take_profit_bps=100.0,
                profit_bank_bps=100.0,
                stop_loss_bps=99999.0,
            ),
        ),
    )

    close = result["closed_trades"][0]
    assert close["close_reason"] == "TIER_2_TRAILING_STOP"
    assert close["realized_pnl_usd"] > 0.0
    assert close["trailing_stop_history"]


def test_default_trailing_stop_can_fire_before_static_take_profit_after_floor() -> None:
    fill = _fill(fill_id="default-trailing-before-tp", qty=1, price=100)
    existing_ledger = {
        "accepted": [fill],
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_id": "paper_pos_BTCUSDT",
                "side": "long",
                "opened_est": "2026-06-11T10:00:00Z",
                "avg_entry_price": 100.0,
                "best_favorable_price": 101.0,
                "intra_trade_high_price": 101.0,
                "last_mark_price": 101.0,
            }
        ],
    }

    result = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 100.45},
        generated_utc="2026-06-11T10:10:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(
                take_profit_bps=120.0,
                profit_bank_bps=99999.0,
                stop_loss_bps=99999.0,
            ),
        ),
    )

    close = result["new_close_events"][0]
    assert close["close_reason"] == "TIER_2_TRAILING_STOP"
    assert close["exit_price"] == pytest.approx(100.495)
    assert close["exit_price_source"] == "PAPER_TRAILING_STOP_PRICE"
    assert close["realized_pnl_bps"] == pytest.approx(49.5)
    assert close["paper_exit_price"] == pytest.approx(100.495)
    assert close["paper_exit_pnl_bps"] == pytest.approx(49.5)
    assert close["trailing_stop_mark_price"] == pytest.approx(100.45)
    assert close["trailing_stop_gap_bps"] == pytest.approx(((100.495 - 100.45) / 100.495) * 10000.0)
    assert close["trailing_stop_bps_effective"] == pytest.approx(50.0)
    assert close["trailing_profit_floor_bps"] == pytest.approx(42.0)
    assert close["trailing_stop_history"]


def test_take_profit_defers_to_previously_armed_trailing_stop() -> None:
    fill = _fill(fill_id="tp-defers-to-trail", qty=1, price=100)
    existing_ledger = {
        "accepted": [fill],
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_id": "paper_pos_BTCUSDT",
                "side": "long",
                "opened_est": "2026-06-11T10:00:00Z",
                "avg_entry_price": 100.0,
                "best_favorable_price": 101.3,
                "intra_trade_high_price": 101.3,
                "last_mark_price": 101.3,
                "trailing_activation_price": 100.42,
                "trailing_activation_time": "2026-06-11T10:05:00Z",
                "trailing_stop_price": 100.7935,
                "trailing_stop_history": [
                    {
                        "generated_utc": "2026-06-11T10:05:00Z",
                        "activation_price": 100.42,
                        "trailing_stop_price": 100.7935,
                        "reason": "ADAPTIVE_TRAIL_ARMED_AFTER_NET_PROFIT_FLOOR",
                    }
                ],
            }
        ],
    }

    result = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 101.3},
        generated_utc="2026-06-11T10:10:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(
                take_profit_bps=120.0,
                profit_bank_bps=99999.0,
                stop_loss_bps=99999.0,
            ),
        ),
    )

    assert result["new_close_events"] == []
    evaluation = result["paper_exit_coordinator_status"]["evaluations"][0]
    assert evaluation["should_close"] is False
    assert evaluation["blocker"] == "TAKE_PROFIT_DEFERRED_TO_ACTIVE_TRAILING_STOP"
    assert evaluation["would_close_reason"] == "TIER_2_TAKE_PROFIT"
    assert result["open_positions"][0]["trailing_stop_history"]


def test_deferred_take_profit_closes_when_trailing_stop_is_breached() -> None:
    fill = _fill(fill_id="tp-defers-then-trails", qty=1, price=100)
    cfg = PaperLifecycleConfig(
        portfolio_equity_usdt=10000.0,
        exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
        exit_config=PaperExitConfig(
            take_profit_bps=120.0,
            profit_bank_bps=99999.0,
            stop_loss_bps=99999.0,
        ),
    )
    existing_ledger = {
        "accepted": [fill],
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_id": "paper_pos_BTCUSDT",
                "side": "long",
                "opened_est": "2026-06-11T10:00:00Z",
                "avg_entry_price": 100.0,
                "best_favorable_price": 101.3,
                "intra_trade_high_price": 101.3,
                "last_mark_price": 101.3,
                "trailing_activation_price": 100.42,
                "trailing_activation_time": "2026-06-11T10:05:00Z",
                "trailing_stop_price": 100.7935,
                "trailing_stop_history": [
                    {
                        "generated_utc": "2026-06-11T10:05:00Z",
                        "activation_price": 100.42,
                        "trailing_stop_price": 100.7935,
                        "reason": "ADAPTIVE_TRAIL_ARMED_AFTER_NET_PROFIT_FLOOR",
                    }
                ],
            }
        ],
    }
    deferred = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 101.3},
        generated_utc="2026-06-11T10:10:00Z",
        config=cfg,
    )

    closed = reconcile_paper_lifecycle(
        existing_ledger=deferred,
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 100.78},
        generated_utc="2026-06-11T10:11:00Z",
        config=cfg,
    )

    close = closed["new_close_events"][0]
    assert close["close_reason"] == "TIER_2_TRAILING_STOP"
    assert close["exit_price"] == pytest.approx(100.7935)
    assert close["exit_price_source"] == "PAPER_TRAILING_STOP_PRICE"
    assert close["realized_pnl_bps"] == pytest.approx(79.35)
    assert close["paper_exit_price"] == pytest.approx(100.7935)
    assert close["paper_exit_pnl_bps"] == pytest.approx(79.35)
    assert close["trailing_stop_mark_price"] == pytest.approx(100.78)
    assert close["trailing_stop_gap_bps"] == pytest.approx(((100.7935 - 100.78) / 100.7935) * 10000.0)
    assert close["trailing_stop_history"]


def test_prior_armed_trailing_stop_gap_close_records_profit_floor_gap() -> None:
    fill = _fill(fill_id="trail-gap-positive", qty=1, price=100)
    existing_ledger = {
        "accepted": [fill],
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_id": "paper_pos_BTCUSDT",
                "side": "long",
                "opened_est": "2026-06-11T10:00:00Z",
                "avg_entry_price": 100.0,
                "best_favorable_price": 101.0,
                "intra_trade_high_price": 101.0,
                "intra_trade_low_price": 100.0,
                "last_mark_price": 101.0,
                "trailing_activation_price": 100.55,
                "trailing_activation_time": "2026-06-11T10:05:00Z",
                "trailing_stop_price": 100.798,
                "trailing_stop_history": [
                    {
                        "generated_utc": "2026-06-11T10:05:00Z",
                        "activation_price": 100.55,
                        "trailing_stop_price": 100.798,
                        "reason": "ADAPTIVE_TRAIL_ARMED_AFTER_NET_PROFIT_FLOOR",
                    }
                ],
            }
        ],
    }

    result = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 100.4},
        generated_utc="2026-06-11T10:10:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(
                trailing_stop_bps=20.0,
                min_profit_before_trailing_bps=30.0,
                trailing_stop_min_after_cost_buffer_bps=25.0,
                take_profit_bps=99999.0,
                profit_bank_bps=99999.0,
                stop_loss_bps=99999.0,
                profit_lock_bps=99999.0,
            ),
        ),
    )

    close = result["new_close_events"][0]
    assert close["close_reason"] == "TIER_2_TRAILING_STOP"
    assert close["exit_price"] == pytest.approx(100.798)
    assert close["exit_price_source"] == "PAPER_TRAILING_STOP_PRICE"
    assert close["realized_pnl_bps"] == pytest.approx(79.8)
    assert close["paper_exit_price"] == pytest.approx(100.798)
    assert close["paper_exit_pnl_bps"] == pytest.approx(79.8)
    assert close["trailing_stop_mark_price"] == pytest.approx(100.4)
    assert close["trailing_stop_gap_bps"] == pytest.approx(((100.798 - 100.4) / 100.798) * 10000.0)
    assert close["trailing_profit_floor_bps"] == pytest.approx(55.0)
    assert close["trailing_profit_floor_gap_bps"] == pytest.approx(15.0)
    assert close["trailing_profit_floor_gap_exit"] is True
    assert (
        close["trailing_profit_floor_gap_exit_reason"]
        == "PRIOR_ARMED_TRAILING_STOP_BREACHED_WITH_POSITIVE_PNL"
    )


def test_prior_armed_trailing_stop_gap_to_unrealized_loss_uses_stop_price() -> None:
    fill = _fill(fill_id="trail-gap-loss-mark", qty=1, price=100)
    existing_ledger = {
        "accepted": [fill],
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_id": "paper_pos_BTCUSDT",
                "side": "long",
                "opened_est": "2026-06-11T10:00:00Z",
                "avg_entry_price": 100.0,
                "best_favorable_price": 101.0,
                "intra_trade_high_price": 101.0,
                "intra_trade_low_price": 100.0,
                "last_mark_price": 101.0,
                "trailing_activation_price": 100.55,
                "trailing_activation_time": "2026-06-11T10:05:00Z",
                "trailing_stop_price": 100.798,
                "trailing_stop_history": [
                    {
                        "generated_utc": "2026-06-11T10:05:00Z",
                        "activation_price": 100.55,
                        "trailing_stop_price": 100.798,
                        "reason": "ADAPTIVE_TRAIL_ARMED_AFTER_NET_PROFIT_FLOOR",
                    }
                ],
            }
        ],
    }

    result = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 99.8},
        generated_utc="2026-06-11T10:10:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(
                trailing_stop_bps=20.0,
                min_profit_before_trailing_bps=30.0,
                trailing_stop_min_after_cost_buffer_bps=25.0,
                take_profit_bps=99999.0,
                profit_bank_bps=99999.0,
                stop_loss_bps=99999.0,
                profit_lock_bps=99999.0,
            ),
        ),
    )

    close = result["new_close_events"][0]
    assert close["close_reason"] == "TIER_2_TRAILING_STOP"
    assert close["exit_price"] == pytest.approx(100.798)
    assert close["exit_price_source"] == "PAPER_TRAILING_STOP_PRICE"
    assert close["realized_pnl_bps"] == pytest.approx(79.8)
    assert close["paper_exit_price"] == pytest.approx(100.798)
    assert close["paper_exit_pnl_bps"] == pytest.approx(79.8)
    assert close["trailing_stop_mark_price"] == pytest.approx(99.8)
    assert close["trailing_stop_gap_bps"] == pytest.approx(((100.798 - 99.8) / 100.798) * 10000.0)
    assert close["trailing_profit_floor_bps"] == pytest.approx(55.0)
    assert close["trailing_profit_floor_gap_bps"] == pytest.approx(75.0)
    assert close["trailing_profit_floor_gap_exit"] is True


def test_prior_armed_trailing_stop_gap_blocks_stop_price_below_cost_floor() -> None:
    fill = _fill(fill_id="trail-gap-stop-below-cost-floor", qty=1, price=100)
    existing_ledger = {
        "accepted": [fill],
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_id": "paper_pos_BTCUSDT",
                "side": "long",
                "opened_est": "2026-06-11T10:00:00Z",
                "avg_entry_price": 100.0,
                "best_favorable_price": 100.7,
                "intra_trade_high_price": 100.7,
                "intra_trade_low_price": 100.0,
                "last_mark_price": 100.7,
                "trailing_activation_price": 100.42,
                "trailing_activation_time": "2026-06-11T10:05:00Z",
                "trailing_stop_price": 100.1965,
                "trailing_stop_history": [
                    {
                        "generated_utc": "2026-06-11T10:05:00Z",
                        "activation_price": 100.42,
                        "trailing_stop_price": 100.1965,
                        "reason": "ADAPTIVE_TRAIL_ARMED_AFTER_NET_PROFIT_FLOOR",
                    }
                ],
            }
        ],
    }

    result = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 99.8},
        generated_utc="2026-06-11T10:10:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(
                trailing_stop_bps=50.0,
                min_profit_before_trailing_bps=30.0,
                trailing_stop_min_after_cost_buffer_bps=12.0,
                take_profit_bps=99999.0,
                profit_bank_bps=99999.0,
                stop_loss_bps=99999.0,
                profit_lock_bps=99999.0,
            ),
        ),
    )

    # CG-F015: stop_price clamped to at-cost floor (100.42); trade now exits at floor instead of blocking
    assert len(result["new_close_events"]) == 1
    assert result["new_close_events"][0]["close_reason"] == "TIER_2_TRAILING_STOP"
    assert result["open_positions"] == []
    evaluation = result["paper_exit_coordinator_status"]["evaluations"][0]
    assert evaluation["should_close"] is True
    assert evaluation["close_reason"] == "TIER_2_TRAILING_STOP"
    assert evaluation["paper_exit_price"] == pytest.approx(100.42)
    assert evaluation["paper_exit_price_source"] == "PAPER_TRAILING_STOP_PRICE"
    assert evaluation["paper_exit_pnl_bps"] == pytest.approx(42.0)
    assert evaluation["trailing_profit_floor_bps"] == pytest.approx(42.0)
    assert evaluation["trailing_stop_exit_floor_bps"] == pytest.approx(30.0)
    assert evaluation["trailing_stop_exit_floor_gap_bps"] == pytest.approx(0.0)
    assert evaluation["trailing_stop_mark_price"] == pytest.approx(99.8)


def test_profit_bank_can_close_when_trailing_is_armed_same_cycle() -> None:
    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[_fill(fill_id="profit-bank-same-cycle", qty=1, price=100)],
        mark_prices={"BTCUSDT": 102.0},
        generated_utc="2026-06-11T10:10:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(
                profit_bank_bps=180.0,
                take_profit_bps=99999.0,
                stop_loss_bps=99999.0,
            ),
        ),
    )

    close = result["new_close_events"][0]
    assert close["close_reason"] == "TIER_2_PROFIT_BANK"
    assert close["trailing_stop_history"]


def test_profit_bank_defers_to_previously_armed_trailing_stop() -> None:
    fill = _fill(fill_id="profit-bank-defers-to-trail", qty=1, price=100)
    existing_ledger = {
        "accepted": [fill],
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_id": "paper_pos_BTCUSDT",
                "side": "long",
                "opened_est": "2026-06-11T10:00:00Z",
                "avg_entry_price": 100.0,
                "best_favorable_price": 102.0,
                "intra_trade_high_price": 102.0,
                "last_mark_price": 102.0,
                "trailing_activation_price": 100.42,
                "trailing_activation_time": "2026-06-11T10:05:00Z",
                "trailing_stop_price": 101.49,
                "trailing_stop_history": [
                    {
                        "generated_utc": "2026-06-11T10:05:00Z",
                        "activation_price": 100.42,
                        "trailing_stop_price": 101.49,
                        "reason": "ADAPTIVE_TRAIL_ARMED_AFTER_NET_PROFIT_FLOOR",
                    }
                ],
            }
        ],
    }

    result = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 101.9},
        generated_utc="2026-06-11T10:10:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(
                profit_bank_bps=180.0,
                take_profit_bps=99999.0,
                stop_loss_bps=99999.0,
            ),
        ),
    )

    assert result["new_close_events"] == []
    evaluation = result["paper_exit_coordinator_status"]["evaluations"][0]
    assert evaluation["should_close"] is False
    assert evaluation["blocker"] == "PROFIT_BANK_DEFERRED_TO_ACTIVE_TRAILING_STOP"
    assert evaluation["would_close_reason"] == "TIER_2_PROFIT_BANK"
    assert result["open_positions"][0]["trailing_stop_history"]


def test_deferred_profit_bank_closes_when_trailing_stop_is_breached() -> None:
    fill = _fill(fill_id="profit-bank-defers-then-trails", qty=1, price=100)
    cfg = PaperLifecycleConfig(
        portfolio_equity_usdt=10000.0,
        exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
        exit_config=PaperExitConfig(
            profit_bank_bps=180.0,
            take_profit_bps=99999.0,
            stop_loss_bps=99999.0,
        ),
    )
    existing_ledger = {
        "accepted": [fill],
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_id": "paper_pos_BTCUSDT",
                "side": "long",
                "opened_est": "2026-06-11T10:00:00Z",
                "avg_entry_price": 100.0,
                "best_favorable_price": 102.0,
                "intra_trade_high_price": 102.0,
                "last_mark_price": 102.0,
                "trailing_activation_price": 100.42,
                "trailing_activation_time": "2026-06-11T10:05:00Z",
                "trailing_stop_price": 101.49,
                "trailing_stop_history": [
                    {
                        "generated_utc": "2026-06-11T10:05:00Z",
                        "activation_price": 100.42,
                        "trailing_stop_price": 101.49,
                        "reason": "ADAPTIVE_TRAIL_ARMED_AFTER_NET_PROFIT_FLOOR",
                    }
                ],
            }
        ],
    }
    deferred = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 101.9},
        generated_utc="2026-06-11T10:10:00Z",
        config=cfg,
    )

    closed = reconcile_paper_lifecycle(
        existing_ledger=deferred,
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 101.45},
        generated_utc="2026-06-11T10:11:00Z",
        config=cfg,
    )

    close = closed["new_close_events"][0]
    assert close["close_reason"] == "TIER_2_TRAILING_STOP"
    assert close["exit_price"] == pytest.approx(101.49)
    assert close["exit_price_source"] == "PAPER_TRAILING_STOP_PRICE"
    assert close["realized_pnl_bps"] == pytest.approx(149.0)
    assert close["paper_exit_price"] == pytest.approx(101.49)
    assert close["paper_exit_pnl_bps"] == pytest.approx(149.0)
    assert close["trailing_stop_mark_price"] == pytest.approx(101.45)
    assert close["trailing_stop_gap_bps"] == pytest.approx(((101.49 - 101.45) / 101.49) * 10000.0)
    assert close["trailing_stop_history"]


def test_profit_lock_defers_to_armed_trailing_stop_before_trail_breach() -> None:
    fill = _fill(fill_id="profit-lock-defers", qty=1, price=100)
    existing_ledger = {
        "accepted": [fill],
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_id": "paper_pos_BTCUSDT",
                "side": "long",
                "opened_est": "2026-06-11T10:00:00Z",
                "avg_entry_price": 100.0,
                "best_favorable_price": 103.0,
                "intra_trade_high_price": 103.0,
                "last_mark_price": 103.0,
            }
        ],
    }

    result = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 102.2},
        generated_utc="2026-06-11T10:10:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(
                trailing_stop_bps=120.0,
                profit_lock_bps=70.0,
                take_profit_bps=99999.0,
                profit_bank_bps=99999.0,
                stop_loss_bps=99999.0,
            ),
        ),
    )

    assert result["new_close_events"] == []
    assert result["open_positions"][0]["trailing_stop_history"]
    evaluation = result["paper_exit_coordinator_status"]["evaluations"][0]
    assert evaluation["should_close"] is False
    assert evaluation["blocker"] == "PROFIT_LOCK_DEFERRED_TO_ACTIVE_TRAILING_STOP"
    assert evaluation["would_close_reason"] == "TIER_2_PROFIT_LOCK"


def test_deferred_profit_lock_closes_when_trailing_stop_is_breached() -> None:
    fill = _fill(fill_id="profit-lock-to-trail", qty=1, price=100)
    cfg = PaperLifecycleConfig(
        portfolio_equity_usdt=10000.0,
        exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
        exit_config=PaperExitConfig(
            trailing_stop_bps=120.0,
            profit_lock_bps=70.0,
            take_profit_bps=99999.0,
            profit_bank_bps=99999.0,
            stop_loss_bps=99999.0,
        ),
    )
    existing_ledger = {
        "accepted": [fill],
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_id": "paper_pos_BTCUSDT",
                "side": "long",
                "opened_est": "2026-06-11T10:00:00Z",
                "avg_entry_price": 100.0,
                "best_favorable_price": 103.0,
                "intra_trade_high_price": 103.0,
                "last_mark_price": 103.0,
            }
        ],
    }
    deferred = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 102.2},
        generated_utc="2026-06-11T10:10:00Z",
        config=cfg,
    )

    closed = reconcile_paper_lifecycle(
        existing_ledger=deferred,
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 101.7},
        generated_utc="2026-06-11T10:11:00Z",
        config=cfg,
    )

    close = closed["new_close_events"][0]
    assert close["close_reason"] == "TIER_2_TRAILING_STOP"
    assert close["realized_pnl_usd"] > 0.0
    assert close["trailing_stop_history"]


def test_profit_lock_can_close_when_trailing_deferral_is_disabled() -> None:
    fill = _fill(fill_id="profit-lock-legacy", qty=1, price=100)
    existing_ledger = {
        "accepted": [fill],
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_id": "paper_pos_BTCUSDT",
                "side": "long",
                "opened_est": "2026-06-11T10:00:00Z",
                "avg_entry_price": 100.0,
                "best_favorable_price": 103.0,
                "intra_trade_high_price": 103.0,
                "last_mark_price": 103.0,
            }
        ],
    }

    result = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 102.2},
        generated_utc="2026-06-11T10:10:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(
                trailing_stop_bps=120.0,
                profit_lock_bps=70.0,
                defer_profit_lock_to_active_trailing_stop=False,
                take_profit_bps=99999.0,
                profit_bank_bps=99999.0,
                stop_loss_bps=99999.0,
            ),
        ),
    )

    close = result["new_close_events"][0]
    assert close["close_reason"] == "TIER_2_PROFIT_LOCK"


def test_lifecycle_uses_entry_atr_to_widen_trailing_distance() -> None:
    fill = dict(_fill(fill_id="a", qty=1, price=100), entry_atr_bps=100.0)
    existing_ledger = {
        "accepted": [fill],
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_id": "paper_pos_BTCUSDT",
                "side": "long",
                "opened_est": "2026-06-11T10:00:00Z",
                "avg_entry_price": 100.0,
                "best_favorable_price": 110.0,
                "intra_trade_high_price": 110.0,
                "intra_trade_low_price": 100.0,
                "last_mark_price": 110.0,
                "entry_atr_bps": 100.0,
            }
        ],
    }
    result = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 110.0 * (1.0 - 80.0 / 10000.0)},
        generated_utc="2026-06-11T10:10:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(
                trailing_stop_bps=60.0,
                atr_trailing_stop_multiplier=1.5,
                take_profit_bps=99999.0,
                stop_loss_bps=99999.0,
                profit_bank_bps=99999.0,
                profit_lock_bps=99999.0,
            ),
        ),
    )

    assert result["new_close_events"] == []
    assert result["open_positions"]
    assert result["open_positions"][0]["entry_atr_bps"] == 100.0
    assert result["open_positions"][0]["trailing_stop_price"] == pytest.approx(
        110.0 * (1.0 - 150.0 / 10000.0)
    )
    exit_eval = result["paper_exit_coordinator_status"]["evaluations"][0]
    assert exit_eval["should_close"] is False


def test_negative_runtime_trailing_expectancy_disables_new_trailing_closes() -> None:
    historical_trailing_losses = [
        {
            "close_id": f"trail_loss_{i}",
            "close_reason": "TIER_2_TRAILING_STOP",
            "realized_pnl_usd": -1.0,
            "source_fill_ids": [f"old_{i}"],
        }
        for i in range(50)
    ]
    existing_ledger = {
        "closed_trades": historical_trailing_losses,
        "accepted": [_fill(fill_id="a", qty=1, price=100)],
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_id": "paper_pos_BTCUSDT",
                "side": "long",
                "opened_est": "2026-06-11T10:00:00Z",
                "best_favorable_price": 105.0,
            }
        ],
    }

    result = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=[_fill(fill_id="a", qty=1, price=100)],
        mark_prices={"BTCUSDT": 104.0},
        generated_utc="2026-06-11T10:10:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            disable_trailing_on_negative_runtime_expectancy=True,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(
                trailing_stop_bps=50.0,
                take_profit_bps=99999.0,
                stop_loss_bps=99999.0,
                profit_bank_bps=99999.0,
            ),
        ),
    )

    status = result["paper_stop_takeprofit_trailing_status"]["trailing_stop_runtime_circuit_breaker"]
    assert result["new_close_events"] == []
    assert result["open_positions"]
    assert result["paper_stop_takeprofit_trailing_status"]["trailing_stop_enabled"] is False
    assert status["disabled"] is True
    assert status["sample_count"] == 50
    assert status["pnl_usd"] == -50.0
    assert "TRAILING_RUNTIME_PNL_NOT_POSITIVE" in status["reasons"]
    assert "TRAILING_RUNTIME_WIN_RATE_BELOW_THRESHOLD" in status["reasons"]


def test_policy_scoped_trailing_expectancy_ignores_legacy_losses() -> None:
    legacy_trailing_losses = [
        {
            "close_id": f"legacy_trail_loss_{i}",
            "close_reason": "TIER_2_TRAILING_STOP",
            "realized_pnl_usd": -1.0,
            "source_fill_ids": [f"legacy_{i}"],
        }
        for i in range(50)
    ]
    existing_ledger = {
        "closed_trades": legacy_trailing_losses,
        "accepted": [_fill(fill_id="a", qty=1, price=100)],
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_id": "paper_pos_BTCUSDT",
                "side": "long",
                "opened_est": "2026-06-11T10:00:00Z",
                "best_favorable_price": 105.0,
            }
        ],
    }

    result = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=[_fill(fill_id="a", qty=1, price=100)],
        mark_prices={"BTCUSDT": 104.0},
        generated_utc="2026-06-11T10:10:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            disable_trailing_on_negative_runtime_expectancy=True,
            trailing_expectancy_evidence_policy_version=PAPER_EXIT_POLICY_VERSION,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(
                trailing_stop_bps=50.0,
                take_profit_bps=99999.0,
                stop_loss_bps=99999.0,
                profit_bank_bps=99999.0,
            ),
        ),
    )

    trailing_status = result["paper_stop_takeprofit_trailing_status"]
    breaker = trailing_status["trailing_stop_runtime_circuit_breaker"]
    context_policy = trailing_status["trailing_stop_context_policy"]
    assert breaker["disabled"] is False
    assert breaker["policy_version_filter_enabled"] is True
    assert breaker["policy_version"] == PAPER_EXIT_POLICY_VERSION
    assert breaker["unfiltered_sample_count"] == 50
    assert breaker["filtered_out_sample_count"] == 50
    assert breaker["sample_count"] == 0
    assert "TRAILING_RUNTIME_POLICY_SAMPLE_BELOW_MINIMUM" in breaker["reasons"]
    assert context_policy["policy_version_filter_enabled"] is True
    assert context_policy["unfiltered_sample_count"] == 50
    assert context_policy["filtered_out_sample_count"] == 50
    assert context_policy["trailing_sample_count"] == 0
    assert trailing_status["trailing_stop_enabled"] is True
    assert result["new_close_events"][0]["close_reason"] == "TIER_2_TRAILING_STOP"
    assert result["new_close_events"][0]["paper_exit_policy_version"] == PAPER_EXIT_POLICY_VERSION


def test_trailing_status_reports_policy_scoped_counts_separately_from_new_closes() -> None:
    result = reconcile_paper_lifecycle(
        existing_ledger={
            "closed_trades": [
                {
                    "close_id": "legacy_trailing",
                    "close_reason": "TIER_2_TRAILING_STOP",
                    "realized_pnl_usd": -1.0,
                    "source_fill_ids": ["legacy"],
                },
                {
                    "close_id": "active_trailing",
                    "paper_exit_policy_version": PAPER_EXIT_POLICY_VERSION,
                    "close_reason": "TIER_2_TRAILING_STOP",
                    "realized_pnl_usd": 1.0,
                    "source_fill_ids": ["active_trailing_fill"],
                },
                {
                    "close_id": "active_profit_bank",
                    "paper_exit_policy_version": PAPER_EXIT_POLICY_VERSION,
                    "close_reason": "TIER_2_PROFIT_BANK",
                    "realized_pnl_usd": 2.0,
                    "source_fill_ids": ["active_profit_fill"],
                },
            ]
        },
        accepted_fills=[],
        mark_prices={},
        generated_utc="2026-06-11T10:10:00Z",
        config=PaperLifecycleConfig(),
    )

    trailing_status = result["paper_stop_takeprofit_trailing_status"]
    coordinator_status = result["paper_exit_coordinator_status"]
    assert result["new_close_events"] == []
    assert trailing_status["triggered_count"] == 0
    assert trailing_status["triggered_count_semantics"] == "LEGACY_ALIAS_FOR_NEW_CLOSE_EVENT_COUNT"
    assert trailing_status["new_close_event_count"] == 0
    assert trailing_status["historical_trailing_stop_triggered_count"] == 2
    assert trailing_status["active_policy_version"] == PAPER_EXIT_POLICY_VERSION
    assert trailing_status["active_policy_closed_trade_count"] == 2
    assert trailing_status["active_policy_trailing_stop_triggered_count"] == 1
    assert trailing_status["active_policy_close_reasons"] == {
        "TIER_2_PROFIT_BANK": 1,
        "TIER_2_TRAILING_STOP": 1,
    }
    assert coordinator_status["active_policy_closed_trade_count"] == 2
    assert coordinator_status["active_policy_trailing_stop_triggered_count"] == 1


def test_policy_scoped_trailing_expectancy_still_disables_current_policy_losses() -> None:
    current_policy_losses = [
        {
            "close_id": f"policy_trail_loss_{i}",
            "paper_exit_policy_version": PAPER_EXIT_POLICY_VERSION,
            "close_reason": "TIER_2_TRAILING_STOP",
            "realized_pnl_usd": -1.0,
            "source_fill_ids": [f"policy_{i}"],
        }
        for i in range(50)
    ]
    existing_ledger = {
        "closed_trades": current_policy_losses,
        "accepted": [_fill(fill_id="a", qty=1, price=100)],
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_id": "paper_pos_BTCUSDT",
                "side": "long",
                "opened_est": "2026-06-11T10:00:00Z",
                "best_favorable_price": 105.0,
            }
        ],
    }

    result = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=[_fill(fill_id="a", qty=1, price=100)],
        mark_prices={"BTCUSDT": 104.0},
        generated_utc="2026-06-11T10:10:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            disable_trailing_on_negative_runtime_expectancy=True,
            trailing_expectancy_evidence_policy_version=PAPER_EXIT_POLICY_VERSION,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(
                trailing_stop_bps=50.0,
                take_profit_bps=99999.0,
                stop_loss_bps=99999.0,
                profit_bank_bps=99999.0,
            ),
        ),
    )

    breaker = result["paper_stop_takeprofit_trailing_status"]["trailing_stop_runtime_circuit_breaker"]
    assert result["new_close_events"] == []
    assert result["open_positions"]
    assert result["paper_stop_takeprofit_trailing_status"]["trailing_stop_enabled"] is False
    assert breaker["disabled"] is True
    assert breaker["policy_version_filter_enabled"] is True
    assert breaker["policy_version"] == PAPER_EXIT_POLICY_VERSION
    assert breaker["unfiltered_sample_count"] == 50
    assert breaker["filtered_out_sample_count"] == 0
    assert breaker["sample_count"] == 50
    assert breaker["pnl_usd"] == -50.0
    assert "TRAILING_RUNTIME_PNL_NOT_POSITIVE" in breaker["reasons"]
    assert "TRAILING_RUNTIME_WIN_RATE_BELOW_THRESHOLD" in breaker["reasons"]


def test_positive_trailing_context_can_override_negative_global_trailing_expectancy() -> None:
    global_trailing_losses = [
        {
            "close_id": f"trail_loss_{i}",
            "symbol": "ETHUSDT",
            "timeframe": "1m",
            "strategy_selected_mode": "trend_mode",
            "market_regime_at_entry": "bear",
            "close_reason": "TIER_2_TRAILING_STOP",
            "realized_pnl_usd": -1.0,
            "source_fill_ids": [f"old_loss_{i}"],
        }
        for i in range(50)
    ]
    matching_context_wins = [
        {
            "close_id": f"trail_win_{i}",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "strategy_selected_mode": "mean_reversion_mode",
            "market_regime_at_entry": "bull",
            "close_reason": "TIER_2_TRAILING_STOP",
            "realized_pnl_usd": 2.0,
            "source_fill_ids": [f"old_win_{i}"],
        }
        for i in range(20)
    ]
    fill = _fill(fill_id="a", qty=1, price=100)
    fill.update({
        "strategy_selected_mode": "mean_reversion_mode",
        "market_regime_at_entry": "bull",
    })
    existing_ledger = {
        "closed_trades": global_trailing_losses + matching_context_wins,
        "accepted": [fill],
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_id": "paper_pos_BTCUSDT",
                "side": "long",
                "opened_est": "2026-06-11T10:00:00Z",
                "best_favorable_price": 105.0,
                "strategy_selected_mode": "mean_reversion_mode",
                "market_regime_at_entry": "bull",
            }
        ],
    }

    result = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 104.0},
        generated_utc="2026-06-11T10:10:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            disable_trailing_on_negative_runtime_expectancy=True,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(
                trailing_stop_bps=50.0,
                take_profit_bps=99999.0,
                stop_loss_bps=99999.0,
                profit_bank_bps=99999.0,
            ),
        ),
    )

    status = result["paper_stop_takeprofit_trailing_status"]
    context_decision = result["paper_exit_coordinator_status"]["evaluations"][0]["trailing_context_decision"]
    assert status["trailing_stop_runtime_circuit_breaker"]["disabled"] is True
    assert status["trailing_stop_enabled"] is True
    assert result["new_close_events"][0]["close_reason"] == "TIER_2_TRAILING_STOP"
    assert context_decision["decision_source"] == "CONTEXTUAL_TRAILING_EXPECTANCY_POLICY"
    assert context_decision["trailing_stop_enabled"] is True
    assert context_decision["selected_context"]["scope"] == "symbol_timeframe_strategy_regime"
    assert context_decision["selected_context"]["positive_expectancy"] is True


def test_negative_trailing_context_disables_matching_trailing_even_when_global_positive() -> None:
    global_trailing_wins = [
        {
            "close_id": f"trail_global_win_{i}",
            "symbol": "ETHUSDT",
            "timeframe": "1m",
            "strategy_selected_mode": "trend_mode",
            "market_regime_at_entry": "bear",
            "close_reason": "TIER_2_TRAILING_STOP",
            "realized_pnl_usd": 2.0,
            "source_fill_ids": [f"old_global_win_{i}"],
        }
        for i in range(50)
    ]
    matching_context_losses = [
        {
            "close_id": f"trail_context_loss_{i}",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "strategy_selected_mode": "mean_reversion_mode",
            "market_regime_at_entry": "bull",
            "close_reason": "TIER_2_TRAILING_STOP",
            "realized_pnl_usd": -1.0,
            "source_fill_ids": [f"old_context_loss_{i}"],
        }
        for i in range(20)
    ]
    fill = _fill(fill_id="a", qty=1, price=100)
    fill.update({
        "strategy_selected_mode": "mean_reversion_mode",
        "market_regime_at_entry": "bull",
    })
    existing_ledger = {
        "closed_trades": global_trailing_wins + matching_context_losses,
        "accepted": [fill],
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_id": "paper_pos_BTCUSDT",
                "side": "long",
                "opened_est": "2026-06-11T10:00:00Z",
                "best_favorable_price": 105.0,
                "strategy_selected_mode": "mean_reversion_mode",
                "market_regime_at_entry": "bull",
            }
        ],
    }

    result = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 104.0},
        generated_utc="2026-06-11T10:10:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            disable_trailing_on_negative_runtime_expectancy=True,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(
                trailing_stop_bps=50.0,
                take_profit_bps=99999.0,
                stop_loss_bps=99999.0,
                profit_bank_bps=99999.0,
            ),
        ),
    )

    status = result["paper_stop_takeprofit_trailing_status"]
    context_decision = result["paper_exit_coordinator_status"]["evaluations"][0]["trailing_context_decision"]
    assert status["trailing_stop_runtime_circuit_breaker"]["disabled"] is False
    assert status["trailing_stop_enabled"] is False
    assert result["new_close_events"] == []
    assert result["open_positions"]
    assert context_decision["decision_source"] == "CONTEXTUAL_TRAILING_EXPECTANCY_POLICY"
    assert context_decision["trailing_stop_enabled"] is False
    assert context_decision["selected_context"]["failed"] is True
    assert "TRAILING_CONTEXT_PNL_NOT_POSITIVE" in context_decision["reasons"]


def test_closed_trade_carries_accounting_and_path_telemetry() -> None:
    fill = _fill(fill_id="telemetry", qty=1, price=100)
    allocation = {
        **_complete_adaptive_capital_fields(),
        "allocation_id": "alloc_test",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "action": "long",
        "allocator_decision": "ALLOW_WITH_SIZE",
        "target_notional_usdt": 100.0,
        "target_quantity": 1.0,
        "model_inputs": {
            "raw_leverage_target": 3.0,
            "leverage_target": 2.0,
            "selected_leverage": 2.0,
            "leverage_selection_reason": "risk_pressure_caps_leverage_at_2x",
            "correlation_exposure_pct": 0.12,
            "correlation_pair_count": 5,
        },
    }
    allocation.update(
        {
            "risk_budget_usd": 100.0,
            "allocated_margin_usd": 50.0,
            "recommended_leverage": 2.0,
            "effective_leverage": 2.0,
            "recommended_margin_mode": "isolated",
            "liquidation_price_estimate": 50.5,
            "liquidation_buffer_bps": 4400.0,
        }
    )
    fill.update(
        {
            "microstructure_context": {
                "source": "TEST_ORDERBOOK",
                "bid_ask_spread_bps": 7.5,
            },
            "squeeze_evidence_score": 0.42,
            "squeeze_evidence_source": "DERIVED_FROM_LIQUIDATION_OI_FUNDING_ORDERBOOK_CONTEXT",
            "squeeze_evidence_components": {"liquidation_pressure": 0.7},
            "slippage_bps": 3.0,
            "expected_slippage_source": "OBSERVED_OR_UPSTREAM_MODELED_SLIPPAGE_BPS",
            "decision_latency_ms": 123.0,
            "entry_atr_bps": 42.0,
            "entry_feature_available_at": "2026-06-11T09:59:58Z",
            "entry_feature_generated_at": "2026-06-11T09:59:58Z",
            "entry_feature_cutoff": "2026-06-11T09:59:00Z",
            "entry_feature_decision_time": "2026-06-11T10:00:00Z",
            "entry_feature_source": "v2:features:latest:BTCUSDT:1m",
            "entry_feature_candle_closed_confirmed": True,
            "effective_leverage": 2.0,
            "leverage_source": "VALIDATED_PAPER_EXECUTION_ENVELOPE",
            "adaptive_allocation": allocation,
            "maintenance_bracket_evidence": _maintenance_bracket_evidence(
                expires_at="2026-06-11T10:20:00Z",
            ),
            "correlation_input_source": "ADAPTIVE_ALLOCATION_MODEL_INPUTS",
            "correlation_input_status": "READY",
            "correlation_diagnostics": {"pair_count": 5},
        }
    )
    cfg = PaperLifecycleConfig(
        portfolio_equity_usdt=10000.0,
        exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
        exit_config=PaperExitConfig(
            trailing_stop_bps=50.0,
            min_profit_before_trailing_bps=30.0,
            take_profit_bps=99999.0,
            stop_loss_bps=99999.0,
            profit_bank_bps=99999.0,
            atr_stop_multiplier=99999.0,
        ),
    )
    opened = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[fill],
        mark_prices={
            "BTCUSDT": {
                "price": 100.0,
                "maintenance_bracket_evidence": _maintenance_bracket_evidence(
                    expires_at="2026-06-11T10:20:00Z",
                ),
            }
        },
        generated_utc="2026-06-11T10:00:00Z",
        config=cfg,
    )
    adverse = reconcile_paper_lifecycle(
        existing_ledger=opened,
        accepted_fills=[fill],
        # -100bps adverse move: below stops under test, above the 150bps
        # catastrophic floor added by the A+ goal (Phase 8).
        mark_prices={
            "BTCUSDT": {
                "price": 99.0,
                "maintenance_bracket_evidence": _maintenance_bracket_evidence(
                    expires_at="2026-06-11T10:20:00Z",
                    consumer_observed_at="2026-06-11T10:05:00Z",
                ),
            }
        },
        generated_utc="2026-06-11T10:05:00Z",
        config=cfg,
    )
    favorable = reconcile_paper_lifecycle(
        existing_ledger=adverse,
        accepted_fills=[fill],
        mark_prices={
            "BTCUSDT": {
                "price": 105.0,
                "maintenance_bracket_evidence": _maintenance_bracket_evidence(
                    expires_at="2026-06-11T10:20:00Z",
                    consumer_observed_at="2026-06-11T10:10:00Z",
                ),
            }
        },
        generated_utc="2026-06-11T10:10:00Z",
        config=cfg,
    )
    closed = reconcile_paper_lifecycle(
        existing_ledger=favorable,
        accepted_fills=[fill],
        mark_prices={
            "BTCUSDT": {
                "price": 104.0,
                "maintenance_bracket_evidence": _maintenance_bracket_evidence(
                    expires_at="2026-06-11T10:20:00Z",
                    consumer_observed_at="2026-06-11T10:15:00Z",
                ),
            }
        },
        generated_utc="2026-06-11T10:15:00Z",
        config=cfg,
    )

    row = closed["closed_trades"][0]
    assert row["close_reason"] == "TIER_2_TRAILING_STOP"
    assert row["realized_pnl_usd"] > 0.0
    assert row["gross_notional_usd"] == 100.0
    assert row["effective_leverage"] == 2.0
    assert row["allocated_margin_usd"] == 50.0
    assert row["recommended_leverage"] == 2.0
    assert row["margin_mode_simulated"] == "isolated"
    assert row["adaptive_capital_policy_version"] == ADAPTIVE_CAPITAL_POLICY_VERSION
    assert row["adaptive_allocation"] == allocation
    assert row["adaptive_allocation"]["model_inputs"]["raw_leverage_target"] == 3.0
    assert row["adaptive_allocation"]["model_inputs"]["selected_leverage"] == 2.0
    assert row["correlation_exposure_pct"] == 0.12
    assert row["correlation_input_source"] == "ADAPTIVE_ALLOCATION_MODEL_INPUTS"
    assert row["correlation_input_status"] == "READY"
    assert row["correlation_pair_count"] == 5
    assert row["correlation_diagnostics"] == {"pair_count": 5}
    assert row["maintenance_margin_estimate"] > 0.0
    assert row["liquidation_price_estimate"] is not None
    assert row["risk_budget_usd"] == 100.0
    assert row["entry_atr_bps"] == 42.0
    assert row["atr_bps"] == 42.0
    assert row["entry_feature_available_at"] == "2026-06-11T09:59:58Z"
    assert row["entry_feature_generated_at"] == "2026-06-11T09:59:58Z"
    assert row["entry_feature_cutoff"] == "2026-06-11T09:59:00Z"
    assert row["entry_feature_decision_time"] == "2026-06-11T10:00:00Z"
    assert row["entry_feature_source"] == "v2:features:latest:BTCUSDT:1m"
    assert row["entry_feature_candle_closed_confirmed"] is True
    assert row["mfe_bps"] == 500.0
    assert row["mae_bps"] == 100.0
    assert row["intra_trade_high_price"] == 105.0
    assert row["intra_trade_low_price"] == 99.0
    assert row["trailing_activation_price"] == pytest.approx(100.42)
    assert row["paper_exit_policy_version"] == PAPER_EXIT_POLICY_VERSION
    assert row["trailing_after_cost_floor_enabled"] is True
    assert row["min_profit_before_trailing_bps"] == pytest.approx(30.0)
    assert row["trailing_stop_min_after_cost_buffer_bps"] == pytest.approx(12.0)
    assert row["trailing_after_cost_buffer_bps"] == pytest.approx(12.0)
    assert row["trailing_profit_floor_bps"] == pytest.approx(42.0)
    assert row["trailing_stop_price"] is not None
    assert row["trailing_stop_history"]
    assert row["actual_observed_spread_entry_bps"] == 7.5
    assert row["actual_observed_spread_exit_bps"] == 7.5
    assert row["expected_slippage_bps"] == 3.0
    assert row["expected_slippage_source"] == "OBSERVED_OR_UPSTREAM_MODELED_SLIPPAGE_BPS"
    assert row["realized_slippage_bps"] == pytest.approx(3.75)  # CG-F010: max(0.25, 7.5*0.50)
    assert row["decision_latency_ms"] == 123.0
    assert row["squeeze_evidence_score"] == 0.42
    outcome = closed["outcome_labels"][0]
    assert outcome["adaptive_allocation"] == allocation
    assert outcome["adaptive_allocation"]["model_inputs"]["leverage_selection_reason"] == "risk_pressure_caps_leverage_at_2x"
    assert outcome["correlation_exposure_pct"] == 0.12
    assert row["squeeze_evidence_source"] == "DERIVED_FROM_LIQUIDATION_OI_FUNDING_ORDERBOOK_CONTEXT"
    assert row["squeeze_evidence_components"] == {"liquidation_pressure": 0.7}
    outcome = closed["outcome_labels"][0]
    assert outcome["paper_exit_policy_version"] == PAPER_EXIT_POLICY_VERSION
    assert outcome["trailing_profit_floor_bps"] == pytest.approx(42.0)
    assert outcome["trailing_after_cost_buffer_bps"] == pytest.approx(12.0)
    assert outcome["entry_atr_bps"] == 42.0
    assert outcome["entry_feature_available_at"] == "2026-06-11T09:59:58Z"
    assert outcome["entry_feature_cutoff"] == "2026-06-11T09:59:00Z"


def test_opposite_side_netting_close_records_exit_path_and_spread_evidence() -> None:
    entry = _fill(fill_id="entry", qty=1, price=100)
    exit_fill = _fill(fill_id="exit", qty=1, price=98)
    exit_fill["side"] = "short"
    exit_fill["actual_observed_spread_entry_bps"] = 4.5
    exit_fill["entry_spread_source"] = "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test"
    exit_fill["entry_spread_available_at"] = "2026-06-11T10:02:00Z"

    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[entry, exit_fill],
        mark_prices={},
        generated_utc="2026-06-11T10:05:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(take_profit_bps=99999.0, stop_loss_bps=99999.0),
        ),
    )

    close = result["closed_trades"][0]
    assert close["close_reason"] == "TIER_3_MODEL_REVERSAL_NETTING"
    assert close["mfe_bps"] == 0.0
    assert close["mae_bps"] == 200.0
    assert close["intra_trade_high_price"] == 100
    assert close["intra_trade_low_price"] == 98
    assert close["actual_observed_spread_exit_bps"] == 4.5
    assert close["exit_spread_source"] == "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test"
    assert close["exit_spread_available_at"] == "2026-06-11T10:02:00Z"
    assert close["expected_slippage_source"] == "MODELED_FROM_OBSERVED_EXIT_SPREAD"
    assert close["expected_slippage_modeled"] is True
    assert close["squeeze_evidence_score"] == 0.0
    assert close["squeeze_evidence_source"] == "DERIVED_FROM_LIQUIDATION_OI_FUNDING_ORDERBOOK_CONTEXT"


def test_mark_triggered_close_records_current_exit_spread_evidence() -> None:
    fill = _fill(fill_id="mark-exit", qty=1, price=100)

    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[fill],
        mark_prices={
            "BTCUSDT": {
                "price": 102.0,
                "source": "V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE",
                "actual_observed_spread_exit_bps": 6.0,
                "exit_spread_source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BTCUSDT",
                "exit_spread_available_at": "2026-06-11T10:04:59Z",
            }
        },
        generated_utc="2026-06-11T10:05:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(take_profit_bps=100.0, stop_loss_bps=99999.0),
        ),
    )

    close = result["closed_trades"][0]
    assert close["close_reason"] == "TIER_2_PROFIT_BANK"
    assert close["mfe_bps"] == 200.0
    assert close["mae_bps"] == 0.0
    assert close["intra_trade_high_price"] == 102.0
    assert close["intra_trade_low_price"] == 100
    assert close["actual_observed_spread_exit_bps"] == 6.0
    assert close["exit_spread_source"] == "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BTCUSDT"
    assert close["exit_spread_available_at"] == "2026-06-11T10:04:59Z"
    assert close["expected_slippage_source"] == "MODELED_FROM_OBSERVED_EXIT_SPREAD"
    assert close["expected_slippage_bps"] == 3.0
    assert close["squeeze_evidence_score"] > 0.0


def test_dirty_close_event_missing_path_is_blocked_before_closed_ledger(monkeypatch) -> None:
    real_build_close_event = lifecycle_module.build_close_event

    def dirty_build_close_event(**kwargs):
        close_event, outcome = real_build_close_event(**kwargs)
        for row in (close_event, outcome):
            for field in (
                "mfe_bps",
                "mae_bps",
                "intra_trade_high_price",
                "intra_trade_low_price",
            ):
                row.pop(field, None)
        return close_event, outcome

    monkeypatch.setattr(lifecycle_module, "build_close_event", dirty_build_close_event)

    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[_fill(fill_id="dirty-path", qty=1, price=100)],
        mark_prices={"BTCUSDT": 102.0},
        generated_utc="2026-06-11T10:05:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(take_profit_bps=100.0, stop_loss_bps=99999.0),
        ),
    )

    block = result["paper_closed_trade_outcome_label_status"]["dirty_close_blocks"][0]
    assert result["closed_trades"] == []
    assert result["outcome_labels"] == []
    assert result["new_close_events"] == []
    assert result["open_positions"][0]["symbol"] == "BTCUSDT"
    assert result["paper_position_lifecycle_status"]["dirty_close_block_count"] == 1
    assert block["paper_close_blocked"] is True
    assert block["close_reason"] == "TIER_2_PROFIT_BANK"
    assert block["paper_close_block_reasons"] == [
        "MISSING_MFE_BPS",
        "MISSING_MAE_BPS",
        "MISSING_INTRA_TRADE_HIGH_PRICE",
        "MISSING_INTRA_TRADE_LOW_PRICE",
    ]


def test_trailing_close_missing_history_is_blocked_before_closed_ledger(monkeypatch) -> None:
    real_build_close_event = lifecycle_module.build_close_event

    def dirty_build_close_event(**kwargs):
        close_event, outcome = real_build_close_event(**kwargs)
        for row in (close_event, outcome):
            row["trailing_stop_history"] = []
            row["trailing_activation_price"] = None
            row["trailing_activation_time"] = None
            row["trailing_stop_price"] = None
        return close_event, outcome

    monkeypatch.setattr(lifecycle_module, "build_close_event", dirty_build_close_event)
    existing_ledger = {
        "accepted": [_fill(fill_id="trail-dirty", qty=1, price=100)],
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_id": "paper_pos_BTCUSDT",
                "side": "long",
                "opened_est": "2026-06-11T10:00:00Z",
                "best_favorable_price": 105.0,
            }
        ],
    }

    result = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=[_fill(fill_id="trail-dirty", qty=1, price=100)],
        mark_prices={"BTCUSDT": 104.0},
        generated_utc="2026-06-11T10:10:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(
                trailing_stop_bps=50.0,
                take_profit_bps=99999.0,
                stop_loss_bps=99999.0,
                profit_bank_bps=99999.0,
            ),
        ),
    )

    block = result["paper_exit_coordinator_status"]["dirty_close_blocks"][0]
    assert result["closed_trades"] == []
    assert result["new_close_events"] == []
    assert result["open_positions"][0]["symbol"] == "BTCUSDT"
    assert block["close_reason"] == "TIER_2_TRAILING_STOP"
    assert block["paper_close_block_reasons"] == [
        "MISSING_TRAILING_STOP_HISTORY_FOR_TRAILING_EXIT",
        "MISSING_TRAILING_ACTIVATION_PRICE_FOR_TRAILING_EXIT",
        "MISSING_TRAILING_ACTIVATION_TIME_FOR_TRAILING_EXIT",
        "MISSING_TRAILING_STOP_PRICE_FOR_TRAILING_EXIT",
    ]


def test_prior_open_position_context_carries_into_closed_trade_feedback() -> None:
    existing_ledger = {
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_id": "paper_pos_BTCUSDT",
                "side": "long",
                "opened_est": "2026-06-11T10:00:00Z",
                "strategy_id": "trend_following",
                "strategy_family": "trend_following",
                "strategy_selected_mode": "trend_following",
                "hedge_state": "NO_HEDGE",
                "hedge_reason": "NO_HEDGE_CONTEXT",
                "drawdown_at_entry": 0.0,
                "market_regime_at_entry": "TREND",
                "liquidity_zone_context": {"source": "test_liquidity"},
                "liquidation_distance_context": {"source": "test_liquidations"},
                "microstructure_context": {"source": "test_microstructure"},
            }
        ],
    }

    result = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=[_fill(fill_id="a", qty=1, price=100)],
        mark_prices={"BTCUSDT": 102.0},
        generated_utc="2026-06-11T10:05:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(take_profit_bps=100.0, stop_loss_bps=99999.0),
        ),
    )

    close = result["closed_trades"][0]
    outcome = result["outcome_labels"][0]
    assert close["strategy_id"] == "trend_following"
    assert close["strategy_family"] == "trend_following"
    assert close["hedge_state"] == "NO_HEDGE"
    assert close["hedge_reason"] == "NO_HEDGE_CONTEXT"
    assert close["market_regime_at_entry"] == "TREND"
    assert close["liquidity_zone_context"] == {"source": "test_liquidity"}
    assert close["liquidation_distance_context"] == {"source": "test_liquidations"}
    assert close["microstructure_context"] == {"source": "test_microstructure"}
    assert close["source_fill_ids"] == ["a"]
    assert outcome["strategy_id"] == "trend_following"
    assert outcome["hedge_state"] == "NO_HEDGE"
    assert outcome["hedge_reason"] == "NO_HEDGE_CONTEXT"
    assert outcome["liquidity_zone_context"] == {"source": "test_liquidity"}


def test_prior_open_position_mark_state_restores_path_telemetry_before_close() -> None:
    existing_ledger = {
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_id": "paper_pos_BTCUSDT",
                "side": "short",
                "opened_est": "2026-06-11T10:00:00Z",
                "last_mark_price": 95.0,
                "last_mark_est": "2026-06-11T10:03:00Z",
                "best_favorable_price": 95.0,
            }
        ],
    }

    result = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=[_fill(fill_id="a", side="short", qty=1, price=100)],
        mark_prices={"BTCUSDT": 96.0},
        generated_utc="2026-06-11T10:05:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(
                take_profit_bps=300.0,
                trailing_stop_bps=99999.0,
                stop_loss_bps=99999.0,
            ),
        ),
    )

    close = result["closed_trades"][0]
    assert close["close_reason"] == "TIER_2_PROFIT_BANK"
    assert close["mfe_bps"] == 500.0
    assert close["mae_bps"] == 0.0
    assert close["intra_trade_high_price"] == 100.0
    assert close["intra_trade_low_price"] == 95.0


def test_same_side_netting_can_fill_missing_position_context_before_close() -> None:
    enriched_fill = _fill(fill_id="b", qty=0.5, price=100)
    enriched_fill.update(
        {
            "strategy_id": "momentum",
            "strategy_family": "momentum",
            "strategy_selected_mode": "momentum",
            "drawdown_at_entry": 0.0,
            "market_regime_at_entry": "MOMENTUM",
            "liquidity_zone_context": {"source": "test_liquidity"},
            "liquidation_distance_context": {"source": "test_liquidations"},
            "microstructure_context": {"source": "test_microstructure"},
        }
    )

    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[_fill(fill_id="a", qty=1, price=100), enriched_fill],
        mark_prices={"BTCUSDT": 102.0},
        generated_utc="2026-06-11T10:05:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(take_profit_bps=100.0, stop_loss_bps=99999.0),
        ),
    )

    close = result["closed_trades"][0]
    assert close["strategy_id"] == "momentum"
    assert close["strategy_family"] == "momentum"
    assert close["market_regime_at_entry"] == "MOMENTUM"
    assert close["microstructure_context"] == {"source": "test_microstructure"}


def test_trainer_feedback_loader_requires_enriched_outcome_label() -> None:
    tensor = FeatureTensorRecord(
        tensor_id="tensor",
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot_id="feat",
        values=(0.0,),
        missing_mask=(0,),
        stale_mask=(0,),
        source_availability=(1,),
        feature_names=("ema_12",),
        source_labels=("test",),
        missing_feature_names=(),
        stale_feature_names=(),
        data_coverage_percent=100.0,
        source_availability_vector=(1,),
    )
    loader = V2HybridTrainerDataLoader()

    bare_label = loader._label_from_closed_trade_outcome(  # noqa: SLF001
        payloads={
            "paper_outcome_labels": [
                {
                    "symbol": "BTCUSDT",
                    "timeframe": "1m",
                    "entry_prediction_id": "pred",
                    "exit_time": "2026-06-11T10:00:00Z",
                    "realized_pnl_bps": 12.5,
                }
            ]
        },
        tensor=tensor,
    )

    assert bare_label is None

    label = loader._label_from_closed_trade_outcome(  # noqa: SLF001
        payloads={
            "paper_outcome_labels": [
                {
                    "symbol": "BTCUSDT",
                    "timeframe": "1m",
                    "prediction_id": "pred",
                    "entry_prediction_id": "pred",
                    "signal_id": "sig",
                    "entry_signal_id": "sig",
                        "feature_snapshot_id": "feat",
                        "entry_feature_snapshot_id": "feat",
                        "market_state_id": "ms",
                        "entry_market_state_id": "ms",
                        "decision_id": "decision",
                        "mtf_snapshot_id": "mtf",
                        "feature_cutoff": "2026-06-11T09:59:00Z",
                        "decision_time": "2026-06-11T10:00:00Z",
                        "available_at": "2026-06-11T09:59:30Z",
                        "selected_action": "long",
                        "model_version": "unit_model_v1",
                        "checkpoint_id": "ckpt",
                        "source_hashes": {"feature_vector_hash": "hash_feat"},
                        "exit_time": "2026-06-11T10:00:00Z",
                        "action": "long",
                    "entry_price": 100.0,
                    "exit_price": 101.0,
                    "realized_pnl": 1.0,
                    "realized_pnl_bps": 12.5,
                    "trainer_feedback_source": "V2_PAPER_TRADE_MANAGEMENT_CLOSED_TRADE",
                    "strategy_id": "trend_following",
                    "strategy_family": "trend_following",
                    "strategy_subtype": "trend_following",
                    "entry_reason": "trend_following",
                    "hedge_state": "NO_HEDGE",
                    "hedge_reason": "NO_HEDGE_CONTEXT",
                    "exit_reason": "TIER_2_TAKE_PROFIT",
                    "hold_time_seconds": 300,
                    "market_regime": "TREND",
                    "market_regime_at_entry": "TREND",
                    "market_regime_at_exit": "TREND",
                    **_premium_ingestor_context_fields(),
                    "major_move_context": {"source": "test", "status": "not_major_move_trade"},
                    "future_window_label_source": "closed_trade_outcome",
                    "drawdown_at_entry": 0.0,
                    **_audit_quality_fields(),
                }
            ]
        },
        tensor=tensor,
    )

    assert label == 12.5


def test_position_from_fill_preserves_trainer_feedback_entry_context() -> None:
    position = position_from_fill(
        {
            "symbol": "BTCUSDT",
            "signal_id": "sig",
            "prediction_id": "pred",
            "strategy_id": "trend_following",
            "strategy_family": "trend_following",
            "strategy_selected_mode": "trend_following",
            "strategy_regime_labels": ["TREND"],
            "drawdown_at_entry": 0.0,
            "liquidity_zone_context": {"source": "test"},
            "liquidation_distance_context": {"source": "test"},
            "microstructure_context": {"source": "test"},
            "generated_utc": "2026-06-11T10:00:00Z",
        },
        fill_id="fill",
        side="long",
        quantity=1.0,
        price=100.0,
    )

    assert position.strategy_id == "trend_following"
    assert position.strategy_family == "trend_following"
    assert position.drawdown_at_entry == 0.0
    assert position.market_regime_at_entry == "TREND"
    assert position.liquidity_zone_context == {"source": "test"}
    assert position.liquidation_distance_context == {"source": "test"}
    assert position.microstructure_context == {"source": "test"}


def test_position_from_fill_preserves_exploration_tier_and_preemptive_lineage() -> None:
    position = position_from_fill(
        {
            "symbol": "KITEUSDT",
            "signal_id": "hyp_fill",
            "prediction_id": "hyp_fill",
            "candidate_id": "hyp_fill",
            "preemptive_decision_id": "pec_hyp_fill",
            "risk_decision_id": "rd_hyp_fill",
            "orchestrator_decision_id": "dec_hyp_fill",
            "allocator_decision_id": "alloc_hyp_fill",
            "paper_opportunity_tier": "PAPER_RISK_CONTROLLER_EXPLORATION",
            "paper_opportunity_tier_reason": (
                "DYNAMIC_EVIDENCE_AWARE_PAPER_RISK_CONTROLLER_EXPLORATION"
            ),
            "confidence_executable_trade": 0.81,
            "dynamic_exploration_floor": 0.66,
            "dynamic_exploration_floor_formula": "formula-test",
            "exploration_floor_inputs": {"microstructure_trust": 0.91},
            "paper_risk_controller_exploration_above_floor": True,
            "paper_risk_controller_exploration_eligible": True,
            "bootstrap_exploration": False,
            "feature_vector_hash": "strategy_supply_hyp_fill",
            "provider_hashes": {"latest": "provider_hash"},
            "generated_utc": "2026-06-11T10:00:00Z",
        },
        fill_id="fill",
        side="long",
        quantity=1.0,
        price=0.12,
    )

    payload = position.to_payload(generated_utc="2026-06-11T10:01:00Z")

    assert position.preemptive_decision_id == "pec_hyp_fill"
    assert payload["preemptive_decision_id"] == "pec_hyp_fill"
    assert payload["tier"] == "PAPER_RISK_CONTROLLER_EXPLORATION"
    assert payload["exploration_tier"] == "PAPER_RISK_CONTROLLER_EXPLORATION"
    assert payload["paper_exploration_tier"] == "PAPER_RISK_CONTROLLER_EXPLORATION"
    assert payload["paper_opportunity_tier"] == "PAPER_RISK_CONTROLLER_EXPLORATION"
    assert payload["confidence_executable_trade"] == 0.81
    assert payload["dynamic_exploration_floor"] == 0.66
    assert payload["dynamic_exploration_floor_formula"] == "formula-test"
    assert payload["exploration_floor_inputs"] == {"microstructure_trust": 0.91}
    assert payload["paper_risk_controller_exploration_above_floor"] is True
    assert payload["paper_risk_controller_exploration_eligible"] is True
    assert payload["bootstrap_exploration"] is False
    assert payload["paper_only"] is True
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False
    assert payload["counts_as_A_plus"] is False
    assert payload["counts_as_live_ready"] is False


def test_position_from_fill_preserves_adaptive_capital_policy_version() -> None:
    position = position_from_fill(
        {
            "symbol": "BTCUSDT",
            "generated_utc": "2026-06-11T10:00:00Z",
            "adaptive_allocation": {
                "adaptive_capital_policy_version": ADAPTIVE_CAPITAL_POLICY_VERSION,
            },
        },
        fill_id="fill",
        side="long",
        quantity=1.0,
        price=100.0,
    )

    payload = position.to_payload(generated_utc="2026-06-11T10:01:00Z")

    assert position.adaptive_capital_policy_version == ADAPTIVE_CAPITAL_POLICY_VERSION
    assert payload["adaptive_capital_policy_version"] == ADAPTIVE_CAPITAL_POLICY_VERSION


def test_position_from_fill_sets_policy_activated_at_for_adaptive_policy() -> None:
    position = position_from_fill(
        {
            "symbol": "BTCUSDT",
            "generated_utc": "2026-06-11T10:00:00Z",
            "fill_price_utc": "2026-06-11T10:00:05Z",
            "adaptive_allocation": {
                "adaptive_capital_policy_version": ADAPTIVE_CAPITAL_POLICY_VERSION,
            },
        },
        fill_id="fill",
        side="long",
        quantity=1.0,
        price=100.0,
    )

    payload = position.to_payload(generated_utc="2026-06-11T10:01:00Z")

    assert position.policy_activated_at == "2026-06-11T10:00:05Z"
    assert payload["policy_activated_at"] == "2026-06-11T10:00:05Z"


def test_position_from_fill_uses_entry_creation_time_when_policy_timestamp_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "v2.backend.app.services.paper_trade_management.position_state.utc_now_iso",
        lambda: "2026-06-11T10:00:09Z",
    )

    position = position_from_fill(
        {
            "symbol": "BTCUSDT",
            "adaptive_allocation": {
                "adaptive_capital_policy_version": ADAPTIVE_CAPITAL_POLICY_VERSION,
            },
        },
        fill_id="fill",
        side="long",
        quantity=1.0,
        price=100.0,
    )

    payload = position.to_payload(generated_utc="2026-06-11T10:01:00Z")

    assert position.policy_activated_at == "2026-06-11T10:00:09Z"
    assert payload["policy_activated_at"] == "2026-06-11T10:00:09Z"


def test_lifecycle_writes_policy_activation_and_funding_terms_to_accepted_open_fill() -> None:
    fill = _fill(fill_id="policy-activated", qty=1.0, price=100.0)
    fill.update({
        "adaptive_allocation": {
            "adaptive_capital_policy_version": ADAPTIVE_CAPITAL_POLICY_VERSION,
            "expected_funding_bps": 1.0,
            "model_inputs": {
                "funding_rate": 0.0001,
                "funding_interval_seconds": 3600.0,
            },
        },
    })

    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 100.0},
        generated_utc="2026-06-11T10:01:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exit_config=PaperExitConfig(
                take_profit_bps=99999.0,
                stop_loss_bps=99999.0,
                profit_bank_bps=99999.0,
                profit_lock_bps=99999.0,
            ),
        ),
    )

    accepted = result["accepted_open_fills"][0]
    assert accepted["paper_lifecycle_status"] == "OPEN_POSITION"
    assert accepted["adaptive_capital_policy_version"] == ADAPTIVE_CAPITAL_POLICY_VERSION
    assert accepted["policy_activated_at"] == "2026-06-11T10:00:00Z"
    assert accepted["expected_funding_bps"] == 1.0
    assert accepted["funding_rate"] == 0.0001
    assert accepted["funding_interval_seconds"] == 3600.0


def test_lifecycle_preserves_paper_exploration_materialization_lineage() -> None:
    fill = _fill(
        fill_id="exploration-open",
        symbol="ORDIUSDT",
        side="long",
        qty=2.0,
        price=3.5,
        timeframe="4h",
    )
    fill.update({
        "candidate_id": "hyp_exploration_open",
        "paper_opportunity_tier": "PAPER_RISK_CONTROLLER_EXPLORATION",
        "materialization_queue_id": "paper_exploration_materialize_hyp_exploration_open",
        "materialization_queue_accepted_at": "2026-07-10T10:00:00Z",
        "materialization_queue_expires_at": "2026-07-10T10:15:00Z",
        "allocator_decision_id": "allocsim_hyp_exploration_open",
        "confidence_executable_trade": 0.83,
        "dynamic_exploration_floor": 0.64,
        "dynamic_exploration_floor_formula": "formula-test",
        "exploration_floor_inputs": {"provider_confluence": 0.8},
        "paper_risk_controller_exploration_above_floor": True,
        "paper_risk_controller_exploration_eligible": True,
        "bootstrap_exploration": False,
        "provider_hashes": {"latest": "provider-hash"},
        "feature_vector_hash": "feature-hash",
        "checkpoint_id": "ckpt_exploration_open",
        "checkpoint_id_source": "redis:v2:trainer:checkpoint:evidence.active_checkpoint_id",
        "entry_prediction_snapshot": {
            "prediction_id": "pred_exploration_open",
            "signal_id": "sig_exploration_open",
            "symbol": "ORDIUSDT",
            "timeframe": "4h",
            "selected_action": "long",
            "feature_snapshot_id": "feat_exploration_open",
            "checkpoint_id": "ckpt_exploration_open",
        },
        "risk_decision_record_key": "v2:decision:risk:rd_exploration_open",
        "risk_decision_record_hash": "risk-record-hash",
        "risk_decision_record_resolved": True,
        "risk_decision_source": "PER_ID_DECISION_RECORD",
        "orchestrator_decision_record_key": (
            "v2:decision:orchestrator:orch_exploration_open"
        ),
        "orchestrator_decision_record_hash": "orch-record-hash",
        "orchestrator_decision_record_resolved": True,
        "orchestrator_decision_source": "PER_ID_DECISION_RECORD",
        "decision_record_missing_reasons": [],
        "expected_net_pnl_usd": 0.42,
        "expected_max_loss_usd": 0.21,
        "fill_price_utc": "2026-07-10T10:00:00Z",
        "generated_utc": "2026-07-10T10:00:00Z",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "live_order": False,
        "test_order": False,
        "counts_as_A_plus": False,
        "counts_as_final_A_plus": False,
        "counts_as_live_ready": False,
    })

    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[fill],
        mark_prices={"ORDIUSDT": 3.5},
        generated_utc="2026-07-10T10:01:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exit_config=PaperExitConfig(
                take_profit_bps=99999.0,
                stop_loss_bps=99999.0,
                profit_bank_bps=99999.0,
                profit_lock_bps=99999.0,
            ),
        ),
    )

    accepted = result["accepted_open_fills"][0]
    position = result["open_positions"][0]
    for row in (accepted, position):
        assert row["paper_opportunity_tier"] == "PAPER_RISK_CONTROLLER_EXPLORATION"
        assert (
            row["materialization_queue_id"]
            == "paper_exploration_materialize_hyp_exploration_open"
        )
        assert row["allocator_decision_id"] == "allocsim_hyp_exploration_open"
        assert row["confidence_executable_trade"] == 0.83
        assert row["dynamic_exploration_floor"] == 0.64
        assert row["dynamic_exploration_floor_formula"] == "formula-test"
        assert row["exploration_floor_inputs"] == {"provider_confluence": 0.8}
        assert row["paper_risk_controller_exploration_above_floor"] is True
        assert row["paper_risk_controller_exploration_eligible"] is True
        assert row["bootstrap_exploration"] is False
        assert row["provider_hashes"] == {"latest": "provider-hash"}
        assert row["feature_vector_hash"] == "feature-hash"
        assert row["checkpoint_id"] == "ckpt_exploration_open"
        assert (
            row["checkpoint_id_source"]
            == "redis:v2:trainer:checkpoint:evidence.active_checkpoint_id"
        )
        assert row["entry_prediction_snapshot"]["prediction_id"] == "pred_exploration_open"
        assert row["risk_decision_record_key"] == "v2:decision:risk:rd_exploration_open"
        assert row["risk_decision_record_hash"] == "risk-record-hash"
        assert row["risk_decision_record_resolved"] is True
        assert row["risk_decision_source"] == "PER_ID_DECISION_RECORD"
        assert (
            row["orchestrator_decision_record_key"]
            == "v2:decision:orchestrator:orch_exploration_open"
        )
        assert row["orchestrator_decision_record_hash"] == "orch-record-hash"
        assert row["orchestrator_decision_record_resolved"] is True
        assert row["orchestrator_decision_source"] == "PER_ID_DECISION_RECORD"
        assert row["decision_record_missing_reasons"] == []
        assert row["expected_net_pnl_usd"] == 0.42
        assert row["expected_max_loss_usd"] == 0.21
        assert row["paper_only"] is True
        assert row["routes_to_live"] is False
        assert row["places_real_order"] is False
        assert row["raw_safety_fields"]["routes_to_live"] is False
        assert row["invariant_checks"]["routes_to_live_is_false"] is True


def test_lifecycle_rehydrates_exploration_lineage_from_replayed_open_position() -> None:
    fill = _fill(
        fill_id="paper_pos_ORDIUSDT",
        symbol="ORDIUSDT",
        side="long",
        qty=2.0,
        price=3.5,
        timeframe="4h",
    )
    fill.update({
        "candidate_id": "hyp_replayed_exploration",
        "prediction_id": "hyp_replayed_exploration",
        "signal_id": "hyp_replayed_exploration",
        "paper_opportunity_tier": "PAPER_RISK_CONTROLLER_EXPLORATION",
        "risk_decision_id": "rd_dec_hyp_replayed_exploration",
        "orchestrator_decision_id": "dec_hyp_replayed_exploration",
        "confidence_executable_trade": 0.82,
        "dynamic_exploration_floor": 0.65,
        "dynamic_exploration_floor_formula": "formula-test",
        "exploration_floor_inputs": {"symbol_timeframe_evidence_count": 25},
        "paper_risk_controller_exploration_above_floor": True,
        "paper_risk_controller_exploration_eligible": True,
        "bootstrap_exploration": False,
        "adaptive_allocation": {
            "allocation_id": "alloc_real_replayed_exploration",
            "allocated_margin_usd": 3.0,
            "gross_notional_usd": 7.0,
        },
        "source_hashes": {
            "feature_vector_hash": "strategy_supply_replayed",
            "latest": "latest-provider-hash",
            "orderbook": "orderbook-provider-hash",
        },
        "expected_net_pnl_usd": 0.42,
        "expected_max_loss_usd": 0.21,
        "fill_price_utc": "2026-07-10T10:00:00Z",
        "generated_utc": "2026-07-10T10:00:00Z",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    })

    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[fill],
        mark_prices={"ORDIUSDT": 3.5},
        generated_utc="2026-07-10T10:01:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exit_config=PaperExitConfig(
                take_profit_bps=99999.0,
                stop_loss_bps=99999.0,
                profit_bank_bps=99999.0,
                profit_lock_bps=99999.0,
            ),
        ),
    )

    accepted = result["accepted_open_fills"][0]
    position = result["open_positions"][0]
    for row in (accepted, position):
        assert (
            row["materialization_queue_id"]
            == "paper_exploration_materialize_hyp_replayed_exploration"
        )
        assert row["allocation_id"] == "alloc_real_replayed_exploration"
        assert row["allocator_decision_id"] == "alloc_real_replayed_exploration"
        assert row["allocator_decision_id_source"] == "adaptive_allocation.allocation_id"
        assert row["confidence_executable_trade"] == 0.82
        assert row["dynamic_exploration_floor"] == 0.65
        assert row["dynamic_exploration_floor_formula"] == "formula-test"
        assert row["exploration_floor_inputs"] == {
            "symbol_timeframe_evidence_count": 25
        }
        assert row["paper_risk_controller_exploration_above_floor"] is True
        assert row["paper_risk_controller_exploration_eligible"] is True
        assert row["bootstrap_exploration"] is False
        assert row["feature_vector_hash"] == "strategy_supply_replayed"
        assert row["provider_hashes"] == {
            "latest": "latest-provider-hash",
            "orderbook": "orderbook-provider-hash",
        }
        assert row["paper_only"] is True
        assert row["routes_to_live"] is False
        assert row["places_real_order"] is False
        assert row["counts_as_A_plus"] is False
        assert row["counts_as_live_ready"] is False
        assert row["raw_safety_fields"]["places_real_order"] is False
        assert row["invariant_checks"]["places_real_order_is_false"] is True
        assert row["paper_only"] is True
        assert row["routes_to_live"] is False
        assert row["places_real_order"] is False
        assert row["live_order"] is False
        assert row["test_order"] is False
        assert row["counts_as_A_plus"] is False
        assert row["counts_as_live_ready"] is False


def test_lifecycle_enriches_previously_closed_accepted_fill_with_policy_and_funding_terms() -> None:
    fill = _fill(fill_id="policy-closed", qty=1.0, price=100.0)
    fill.update({
        "adaptive_allocation": {
            "adaptive_capital_policy_version": ADAPTIVE_CAPITAL_POLICY_VERSION,
            "model_inputs": {
                "expected_funding_bps": 1.5,
                "funding_interval_seconds": 3600.0,
            },
        },
    })

    result = reconcile_paper_lifecycle(
        existing_ledger={
            "closed_trades": [
                    {
                        "close_id": "already_closed",
                        "source_fill_ids": ["policy-closed"],
                        "entry_cost_is_final_close": True,
                        "entry_cost_pre_close_quantity": 1.0,
                        "entry_cost_closed_quantity": 1.0,
                    }
            ],
        },
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 100.0},
        generated_utc="2026-06-11T10:01:00Z",
        config=PaperLifecycleConfig(portfolio_equity_usdt=10000.0),
    )

    assert result["accepted_open_fills"] == []
    accepted = result["closed_previously_fills"][0]
    assert accepted["paper_lifecycle_status"] == "CLOSED_PREVIOUSLY"
    assert accepted["adaptive_capital_policy_version"] == ADAPTIVE_CAPITAL_POLICY_VERSION
    assert accepted["policy_activated_at"] == "2026-06-11T10:00:00Z"
    assert accepted["expected_funding_bps"] == 1.5
    assert accepted["funding_rate"] == 0.00015
    assert accepted["funding_interval_seconds"] == 3600.0
    assert accepted["adaptive_allocation"]["policy_activated_at"] == "2026-06-11T10:00:00Z"
    assert accepted["adaptive_allocation"]["expected_funding_bps"] == 1.5
    assert accepted["adaptive_allocation"]["model_inputs"]["funding_rate"] == 0.00015


def test_lifecycle_repairs_existing_closed_trade_funding_before_emitting_ledger() -> None:
    fill = _fill(fill_id="closed-zero-funding", side="short", qty=1.0, price=100.0)
    fill.update({
        "adaptive_capital_policy_version": ADAPTIVE_CAPITAL_POLICY_VERSION,
        "expected_funding_bps": 2.5,
        "funding_rate": 0.00025,
        "adaptive_allocation": {
            "adaptive_capital_policy_version": ADAPTIVE_CAPITAL_POLICY_VERSION,
            "expected_funding_bps": 2.5,
            "model_inputs": {
                "funding_rate": 0.00025,
                "funding_interval_seconds": 3600.0,
            },
        },
    })
    closed = {
        "close_id": "closed-zero-funding-close",
        "outcome_label_id": "closed-zero-funding-outcome",
        "trainer_feedback_id": "closed-zero-funding-feedback",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "short",
        "source_fill_ids": ["closed-zero-funding"],
        "entry_signal_id": "sig_closed-zero-funding",
        "entry_prediction_id": "pred_closed-zero-funding",
        "entry_price": 100.0,
        "closed_quantity": 1.0,
        "exit_price": 99.0,
        "exit_time": "2026-06-11T11:00:00Z",
        "hold_time_seconds": 3600.0,
        "realized_pnl_usd": 1.0,
        "realized_pnl_usdt": 1.0,
        "realized_pnl": 1.0,
        "winner": True,
        "paper_only": True,
        "places_real_order": False,
        "paper_exit_policy_version": PAPER_EXIT_POLICY_VERSION,
        "adaptive_capital_policy_version": ADAPTIVE_CAPITAL_POLICY_VERSION,
        "policy_activated_at": "2026-06-11T10:00:00Z",
        "funding_pnl_usd": None,
        "funding_pnl_source": None,
        "adaptive_allocation": {
            "adaptive_capital_policy_version": ADAPTIVE_CAPITAL_POLICY_VERSION,
            "policy_activated_at": "2026-06-11T10:00:00Z",
            "expected_funding_bps": 0.0,
            "model_inputs": {
                "funding_rate": 0.0,
                "expected_funding_bps": 0.0,
                "funding_interval_seconds": 3600.0,
            },
        },
    }
    outcome = dict(closed)
    outcome.pop("close_id")

    result = reconcile_paper_lifecycle(
        existing_ledger={
            "closed_trades": [closed],
            "outcome_labels": [outcome],
        },
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 100.0},
        generated_utc="2026-06-11T12:00:00Z",
        config=PaperLifecycleConfig(portfolio_equity_usdt=10000.0),
    )

    repaired_close = result["closed_trades"][0]
    repaired_outcome = result["outcome_labels"][0]
    assert repaired_close["funding_pnl_accounting_status"] == "READY_FUNDING_PNL_ACCRUED"
    assert repaired_close["funding_pnl_source"] == "FUNDING_RATE"
    assert repaired_close["funding_rate"] == 0.0
    assert repaired_close["funding_bps"] == 0.0
    assert repaired_close["funding_pnl_usd"] == 0.0
    assert repaired_outcome["funding_pnl_accounting_status"] == "READY_FUNDING_PNL_ACCRUED"
    assert repaired_outcome["funding_pnl_usd"] == 0.0
    status = result["paper_closed_trade_outcome_label_status"]
    assert status["policy_funding_repair"]["status_counts"]["repaired"] == 1
    assert status["outcome_label_policy_funding_repair"]["status_counts"]["repaired"] == 1


def test_lifecycle_does_not_synthesize_policy_activation_for_timestampless_closed_fill() -> None:
    fill = _fill(fill_id="timestampless-policy-closed", qty=1.0, price=100.0)
    for key in ("fill_price_utc", "generated_utc", "entry_price_utc", "fill_time_est"):
        fill.pop(key, None)
    fill.update({
        "adaptive_allocation": {
            "adaptive_capital_policy_version": ADAPTIVE_CAPITAL_POLICY_VERSION,
        },
    })

    result = reconcile_paper_lifecycle(
        existing_ledger={
            "closed_trades": [
                    {
                        "close_id": "already_closed",
                        "source_fill_ids": ["timestampless-policy-closed"],
                        "entry_cost_is_final_close": True,
                        "entry_cost_pre_close_quantity": 1.0,
                        "entry_cost_closed_quantity": 1.0,
                    }
            ],
        },
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 100.0},
        generated_utc="2026-06-11T10:01:00Z",
        config=PaperLifecycleConfig(portfolio_equity_usdt=10000.0),
    )

    assert result["accepted_open_fills"] == []
    accepted = result["closed_previously_fills"][0]
    assert accepted["paper_lifecycle_status"] == "CLOSED_PREVIOUSLY"
    assert accepted["adaptive_capital_policy_version"] == ADAPTIVE_CAPITAL_POLICY_VERSION
    assert "policy_activated_at" not in accepted
    assert "policy_activated_at" not in accepted["adaptive_allocation"]


def test_close_event_accounts_signed_funding_pnl_for_long_and_short() -> None:
    base_fill = {
        "symbol": "BTCUSDT",
        "fill_price_utc": "2026-06-11T10:00:00Z",
        "adaptive_allocation": {
            "adaptive_capital_policy_version": ADAPTIVE_CAPITAL_POLICY_VERSION,
            "model_inputs": {
                "funding_rate": 0.0001,
                "funding_interval_seconds": 3600.0,
            },
        },
    }
    long_position = position_from_fill(
        base_fill,
        fill_id="long",
        side="long",
        quantity=1.0,
        price=100.0,
    )
    short_position = position_from_fill(
        base_fill,
        fill_id="short",
        side="short",
        quantity=1.0,
        price=100.0,
    )

    long_close, long_outcome = build_close_event(
        position=long_position,
        close_quantity=1.0,
        exit_price=100.0,
        exit_time="2026-06-11T11:00:00Z",
        close_reason="TEST_CLOSE",
        fee_bps=0.0,
        slippage_bps=0.0,
    )
    short_close, short_outcome = build_close_event(
        position=short_position,
        close_quantity=1.0,
        exit_price=100.0,
        exit_time="2026-06-11T11:00:00Z",
        close_reason="TEST_CLOSE",
        fee_bps=0.0,
        slippage_bps=0.0,
    )

    assert long_close["funding_pnl_usd"] == pytest.approx(-0.01)
    assert long_close["funding_pnl_accounting_version"] == FUNDING_PNL_ACCOUNTING_VERSION
    assert long_close["funding_pnl_accounting_status"] == "READY_FUNDING_PNL_ACCRUED"
    assert long_close["funding_pnl_formula"] == FUNDING_PNL_ACCOUNTING_FORMULA
    assert long_close["funding_pnl_side_sign"] == -1.0
    assert long_close["funding_pnl_source"] == "FUNDING_RATE"
    assert long_close["realized_pnl_usd"] == pytest.approx(0.0)
    assert long_close["realized_pnl"] == pytest.approx(0.0)
    assert long_close["realized_net_pnl_usd"] == pytest.approx(-0.01)
    assert long_outcome["funding_pnl_usd"] == pytest.approx(-0.01)
    assert long_outcome["funding_pnl_accounting_version"] == FUNDING_PNL_ACCOUNTING_VERSION
    assert long_outcome["funding_pnl_accounting_status"] == "READY_FUNDING_PNL_ACCRUED"
    assert short_close["funding_pnl_usd"] == pytest.approx(0.01)
    assert short_close["funding_pnl_accounting_version"] == FUNDING_PNL_ACCOUNTING_VERSION
    assert short_close["funding_pnl_accounting_status"] == "READY_FUNDING_PNL_ACCRUED"
    assert short_close["funding_pnl_formula"] == FUNDING_PNL_ACCOUNTING_FORMULA
    assert short_close["funding_pnl_side_sign"] == 1.0
    assert short_close["funding_pnl_source"] == "FUNDING_RATE"
    assert short_close["realized_pnl_usd"] == pytest.approx(0.0)
    assert short_close["realized_pnl"] == pytest.approx(0.0)
    assert short_close["realized_net_pnl_usd"] == pytest.approx(0.01)
    assert short_outcome["funding_pnl_usd"] == pytest.approx(0.01)
    assert short_outcome["funding_pnl_accounting_version"] == FUNDING_PNL_ACCOUNTING_VERSION
    assert short_outcome["funding_pnl_accounting_status"] == "READY_FUNDING_PNL_ACCRUED"


def test_p0019_close_event_populates_gross_and_net_realized_pnl_usd() -> None:
    position = position_from_fill(
        _fill(fill_id="p0019-close", qty=2.0, price=100.0),
        fill_id="p0019-close",
        side="long",
        quantity=2.0,
        price=100.0,
    )

    close, outcome = build_close_event(
        position=position,
        close_quantity=2.0,
        exit_price=101.0,
        exit_time="2026-06-11T11:00:00Z",
        close_reason="TEST_CLOSE",
        fee_bps=4.0,
        slippage_bps=2.0,
    )

    assert close["realized_pnl_bps"] == pytest.approx(100.0)
    assert close["gross_notional_usd"] == pytest.approx(200.0)
    assert close["realized_pnl_usd"] == pytest.approx(2.0)
    assert close["realized_pnl"] == pytest.approx(2.0)
    assert close["realized_net_pnl_usd"] == pytest.approx(2.0 - close["fees"] - close["slippage"])
    assert outcome["realized_pnl_usd"] == close["realized_pnl_usd"]
    assert outcome["realized_net_pnl_usd"] == close["realized_net_pnl_usd"]


def test_p0019_carried_closed_rows_populate_missing_realized_pnl_usd_aliases() -> None:
    closed = {
        "close_id": "p0019-carried-close",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "source_fill_ids": ["p0019-carried"],
        "entry_price": 100.0,
        "exit_price": 101.0,
        "closed_quantity": 2.0,
        "gross_notional_usd": 200.0,
        "realized_pnl_bps": 100.0,
        "fees": 0.08,
        "slippage": 0.04,
        "funding_pnl_usd": -0.01,
        "paper_only": True,
        "places_real_order": False,
    }
    outcome = {
        **closed,
        "outcome_label_id": "p0019-carried-outcome",
        "trainer_feedback_id": "p0019-carried-feedback",
    }

    result = reconcile_paper_lifecycle(
        existing_ledger={"closed_trades": [closed], "outcome_labels": [outcome]},
        accepted_fills=[_fill(fill_id="p0019-carried", qty=2.0, price=100.0)],
        mark_prices={"BTCUSDT": 101.0},
        generated_utc="2026-06-11T12:00:00Z",
        config=PaperLifecycleConfig(portfolio_equity_usdt=10000.0),
    )

    repaired_close = result["closed_trades"][0]
    repaired_outcome = result["outcome_labels"][0]
    assert repaired_close["realized_pnl_usd"] == pytest.approx(2.0)
    assert repaired_close["realized_pnl"] == pytest.approx(2.0)
    assert repaired_close["realized_net_pnl_usd"] == pytest.approx(1.87)
    assert repaired_outcome["realized_pnl_usd"] == pytest.approx(2.0)
    assert repaired_outcome["realized_net_pnl_usd"] == pytest.approx(1.87)
    assert result["realized_pnl_usd"] == pytest.approx(1.87)


def test_position_from_fill_preserves_adaptive_allocation_and_correlation_evidence() -> None:
    allocation = {
        "adaptive_capital_policy_version": ADAPTIVE_CAPITAL_POLICY_VERSION,
        "allocator_decision": "ALLOW_WITH_SIZE",
        "gross_notional_usd": 100.0,
        "allocated_margin_usd": 100.0,
        "recommended_leverage": 1.0,
        "effective_leverage": 1.0,
        "model_inputs": {
            "correlation_exposure_pct": 0.11,
            "correlation_pair_count": 4,
        },
    }
    position = position_from_fill(
        {
            "symbol": "BTCUSDT",
            "generated_utc": "2026-06-11T10:00:00Z",
            "adaptive_allocation": allocation,
            "correlation_input_source": "MARKET_OHLCV_RETURN_CORRELATION",
            "correlation_input_status": "READY",
            "correlation_diagnostics": {"return_count": 99},
        },
        fill_id="fill",
        side="long",
        quantity=1.0,
        price=100.0,
    )

    payload = position.to_payload(generated_utc="2026-06-11T10:01:00Z")

    assert payload["adaptive_allocation"] == allocation
    assert payload["correlation_exposure_pct"] == 0.11
    assert payload["correlation_input_source"] == "MARKET_OHLCV_RETURN_CORRELATION"
    assert payload["correlation_input_status"] == "READY"
    assert payload["correlation_pair_count"] == 4
    assert payload["correlation_diagnostics"] == {"return_count": 99}


def test_lifecycle_does_not_overwrite_fresh_adaptive_accounting_with_stale_prior() -> None:
    allocation = {
        **_complete_adaptive_capital_fields(),
        "allocation_id": "alloc_fresh",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "action": "long",
        "allocator_decision": "ALLOW_WITH_SIZE",
        "target_notional_usdt": 100.0,
        "target_quantity": 1.0,
        "allocated_margin_usd": 50.0,
        "recommended_leverage": 2.0,
        "effective_leverage": 2.0,
        "recommended_margin_mode": "isolated_paper_simulated",
        "model_inputs": {
            "selected_leverage": 2.0,
            "leverage_selection_reason": "test",
            "selected_margin_mode": "isolated_paper_simulated",
            "margin_mode_selection_reason": "test",
            "selected_hedge_budget_pct_of_risk": 0.0,
            "hedge_budget_selection_reason": "test",
        },
    }
    fill = _fill(fill_id="fresh-accounting", qty=1.0, price=100.0)
    fill.update({
        "adaptive_capital_policy_version": ADAPTIVE_CAPITAL_POLICY_VERSION,
        "adaptive_allocation": allocation,
        "gross_notional_usd": 100.0,
        "allocated_margin_usd": 50.0,
        "recommended_leverage": 2.0,
        "effective_leverage": 2.0,
        "recommended_margin_mode": "isolated_paper_simulated",
        "stop_distance_bps": 50.0,
        "liquidation_price_estimate": 1.0,
        "liquidation_buffer_bps": 9000.0,
        "expected_fees_usd": 0.04,
        "expected_slippage_usd": 0.02,
        "expected_funding_usd": 0.0,
        "expected_net_pnl_usd": 1.0,
        "expected_shortfall_usd": 15.0,
        "hedge_budget_usd": 0.0,
        "capital_allocation_reason": "adaptive_allocation_from_confidence_edge_market_quality_and_risk_budget",
    })
    existing_ledger = {
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_id": "paper_pos_BTCUSDT",
                "side": "long",
                "opened_est": "2026-06-11T10:00:00Z",
                "best_favorable_price": 105.0,
                "adaptive_capital_policy_version": ADAPTIVE_CAPITAL_POLICY_VERSION,
                "adaptive_allocation": allocation,
                "gross_notional_usd": 100.0,
                "allocated_margin_usd": 200.0,
                "recommended_leverage": 1.0,
                "effective_leverage": 1.0,
                "recommended_margin_mode": "isolated_paper_simulated",
                "stop_distance_bps": 50.0,
                "liquidation_price_estimate": 1.0,
                "liquidation_buffer_bps": 9000.0,
                "expected_fees_usd": 0.04,
                "expected_slippage_usd": 0.02,
                "expected_funding_usd": 0.0,
                "expected_net_pnl_usd": 1.0,
                "expected_shortfall_usd": 15.0,
                "hedge_budget_usd": 0.0,
                "capital_allocation_reason": "stale_prior_accounting",
            }
        ],
    }

    result = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 104.0},
        generated_utc="2026-06-11T10:10:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(
                trailing_stop_bps=99999.0,
                take_profit_bps=99999.0,
                stop_loss_bps=99999.0,
                profit_bank_bps=99999.0,
                atr_stop_multiplier=99999.0,
            ),
        ),
    )

    row = result["open_positions"][0]
    assert row["allocated_margin_usd"] == 50.0
    assert row["recommended_leverage"] == 2.0
    assert row["effective_leverage"] == 2.0
    assert row["capital_allocation_reason"] == "adaptive_allocation_from_confidence_edge_market_quality_and_risk_budget"
    assert row["best_favorable_price"] == 105.0


def test_position_from_fill_does_not_version_legacy_incomplete_allocation() -> None:
    position = position_from_fill(
        {
            "symbol": "BTCUSDT",
            "generated_utc": "2026-06-11T10:00:00Z",
            "adaptive_allocation": {
                "risk_budget_pct_of_equity": 0.01,
                "model_inputs": {"equity": 10000.0},
            },
        },
        fill_id="fill",
        side="long",
        quantity=1.0,
        price=100.0,
    )

    payload = position.to_payload(generated_utc="2026-06-11T10:01:00Z")

    assert position.adaptive_capital_policy_version is None
    assert position.policy_activated_at is None
    assert payload["adaptive_capital_policy_version"] is None
    assert payload["policy_activated_at"] is None


def _complete_adaptive_capital_fields() -> dict:
    return {
        "adaptive_capital_policy_version": ADAPTIVE_CAPITAL_POLICY_VERSION,
        "risk_budget_usd": 10.0,
        "gross_notional_usd": 100.0,
        "allocated_margin_usd": 100.0,
        "recommended_leverage": 1.0,
        "effective_leverage": 1.0,
        "recommended_margin_mode": "isolated_paper_simulated",
        "stop_distance_bps": 50.0,
        "liquidation_price_estimate": 1.0,
        "liquidation_buffer_bps": 9000.0,
        "expected_fees_usd": 0.04,
        "expected_slippage_usd": 0.02,
        "expected_funding_usd": 0.0,
        "expected_net_pnl_usd": 1.0,
        "expected_shortfall_usd": 15.0,
        "hedge_budget_usd": 0.0,
        "capital_allocation_reason": "adaptive_allocation_from_confidence_edge_market_quality_and_risk_budget",
    }


def test_lifecycle_does_not_carry_incomplete_prior_adaptive_capital_version() -> None:
    fill = _fill(fill_id="legacy-incomplete-capital", qty=1.0, price=100.0)
    existing_ledger = {
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_id": "paper_pos_BTCUSDT",
                "side": "long",
                "opened_est": "2026-06-11T10:00:00Z",
                "avg_entry_price": 100.0,
                "net_quantity": 1.0,
                "adaptive_capital_policy_version": ADAPTIVE_CAPITAL_POLICY_VERSION,
                "risk_budget_usd": 10.0,
            }
        ],
    }

    result = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 100.0},
        generated_utc="2026-06-11T10:01:00Z",
        config=PaperLifecycleConfig(portfolio_equity_usdt=10000.0),
    )

    assert result["open_positions"][0]["adaptive_capital_policy_version"] is None
    assert result["open_positions"][0]["risk_budget_usd"] == 10.0


def test_lifecycle_carries_complete_prior_adaptive_capital_version() -> None:
    allocation = {
        **_complete_adaptive_capital_fields(),
        "model_inputs": {
            "raw_leverage_target": 3.0,
            "leverage_target": 1.0,
            "selected_leverage": 1.0,
            "leverage_selection_reason": "drawdown_pressure_caps_leverage_at_1x",
        },
    }
    fill = _fill(fill_id="complete-capital", qty=1.0, price=100.0)
    existing_ledger = {
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_id": "paper_pos_BTCUSDT",
                "side": "long",
                "opened_est": "2026-06-11T10:00:00Z",
                "avg_entry_price": 100.0,
                "net_quantity": 1.0,
                **_complete_adaptive_capital_fields(),
                "adaptive_allocation": allocation,
                "correlation_exposure_pct": 0.08,
                "correlation_input_source": "ADAPTIVE_ALLOCATION_MODEL_INPUTS",
                "correlation_input_status": "READY",
                "correlation_pair_count": 3,
            }
        ],
    }

    result = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=[fill],
        mark_prices={"BTCUSDT": 100.0},
        generated_utc="2026-06-11T10:01:00Z",
        config=PaperLifecycleConfig(portfolio_equity_usdt=10000.0),
    )

    assert result["open_positions"][0]["adaptive_capital_policy_version"] == ADAPTIVE_CAPITAL_POLICY_VERSION
    assert result["open_positions"][0]["stop_distance_bps"] == 50.0
    assert result["open_positions"][0]["adaptive_allocation"] == allocation
    assert result["open_positions"][0]["adaptive_allocation"]["model_inputs"]["raw_leverage_target"] == 3.0
    assert result["open_positions"][0]["correlation_exposure_pct"] == 0.08
    assert result["open_positions"][0]["correlation_input_status"] == "READY"
    assert result["open_positions"][0]["correlation_pair_count"] == 3


def test_lifecycle_promotes_nested_adaptive_policy_version_to_open_and_closed_payloads() -> None:
    allocation = {
        **_complete_adaptive_capital_fields(),
        "policy_activated_at": "2026-06-11T10:00:00Z",
        "model_inputs": {
            "raw_leverage_target": 2.0,
            "leverage_target": 1.0,
            "selected_leverage": 1.0,
            "leverage_selection_reason": "after_cost_edge_too_small_for_dynamic_leverage",
        },
    }
    existing_ledger = {
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_id": "paper_pos_BTCUSDT",
                "side": "long",
                "opened_est": "2026-06-11T10:00:00Z",
                "avg_entry_price": 100.0,
                "net_quantity": 1.0,
                **{
                    key: value
                    for key, value in _complete_adaptive_capital_fields().items()
                    if key != "adaptive_capital_policy_version"
                },
                "adaptive_allocation": allocation,
            }
        ],
    }

    open_result = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=[_fill(fill_id="nested-version", qty=1.0, price=100.0)],
        mark_prices={"BTCUSDT": 100.0},
        generated_utc="2026-06-11T10:01:00Z",
        config=PaperLifecycleConfig(portfolio_equity_usdt=10000.0),
    )
    closed_result = reconcile_paper_lifecycle(
        existing_ledger=open_result,
        accepted_fills=[_fill(fill_id="nested-version", qty=1.0, price=100.0)],
        mark_prices={"BTCUSDT": 102.0},
        generated_utc="2026-06-11T10:05:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exit_config=PaperExitConfig(take_profit_bps=100.0, stop_loss_bps=99999.0),
        ),
    )

    assert open_result["open_positions"][0]["adaptive_capital_policy_version"] == ADAPTIVE_CAPITAL_POLICY_VERSION
    assert open_result["open_positions"][0]["policy_activated_at"] == "2026-06-11T10:00:00Z"
    assert closed_result["closed_trades"][0]["adaptive_capital_policy_version"] == ADAPTIVE_CAPITAL_POLICY_VERSION
    assert closed_result["closed_trades"][0]["policy_activated_at"] == "2026-06-11T10:00:00Z"
    assert closed_result["outcome_labels"][0]["adaptive_capital_policy_version"] == ADAPTIVE_CAPITAL_POLICY_VERSION
    assert closed_result["outcome_labels"][0]["policy_activated_at"] == "2026-06-11T10:00:00Z"
    assert closed_result["closed_trades"][0]["adaptive_allocation"] == allocation
    assert closed_result["outcome_labels"][0]["adaptive_allocation"] == allocation


def test_lifecycle_carries_trust_envelope_from_prior_position_into_close() -> None:
    original_fill = _fill(fill_id="trust-carry", qty=1.0, price=100.0)
    original_fill.update(_audit_quality_fields())
    original_fill.update(
        {
            "candidate_id": "challenger_v2_unit",
            "paper_policy_owner": "challenger_v2",
            "policy_fingerprint": "policy-fp-trust-carry",
            "model_source": "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA",
        }
    )
    original_fill["entry_feature_snapshot"] = _entry_feature_snapshot("trust-carry")
    open_result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[original_fill],
        mark_prices={"BTCUSDT": 100.0},
        generated_utc="2026-06-11T10:01:00Z",
        config=PaperLifecycleConfig(portfolio_equity_usdt=10000.0),
    )
    stale_carried_fill = _fill(fill_id="trust-carry", qty=1.0, price=100.0)
    stale_carried_fill.update(_audit_quality_fields())
    for field in (
        "decision_id",
        "market_state_id",
        "feature_snapshot_id",
        "mtf_snapshot_id",
        "feature_cutoff",
        "decision_time",
        "available_at",
        "selected_action",
        "model_version",
        "model_source",
        "candidate_id",
        "paper_policy_owner",
        "policy_fingerprint",
        "checkpoint_id",
        "source_hashes",
        "entry_feature_snapshot",
    ):
        stale_carried_fill.pop(field, None)

    carried_result = reconcile_paper_lifecycle(
        existing_ledger=open_result,
        accepted_fills=[stale_carried_fill],
        mark_prices={"BTCUSDT": 100.0},
        generated_utc="2026-06-11T10:03:00Z",
        config=PaperLifecycleConfig(portfolio_equity_usdt=10000.0),
    )
    carried_position = carried_result["open_positions"][0]
    carried_fill = carried_result["accepted_open_fills"][0]
    for row in (carried_position, carried_fill):
        assert row["prediction_id"] == "pred_trust-carry"
        assert row["signal_id"] == "sig_trust-carry"
        assert row["feature_snapshot_id"] == "feat_trust-carry"
        assert row["entry_feature_snapshot_id"] == "feat_trust-carry"
        assert row["decision_id"] == "orch_trust-carry"
        assert row["candidate_id"] == "challenger_v2_unit"
        assert row["paper_policy_owner"] == "challenger_v2"
        assert row["policy_fingerprint"] == "policy-fp-trust-carry"
        assert row["model_source"] == "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA"
        assert row["entry_feature_snapshot"] == _entry_feature_snapshot("trust-carry")
        assert row["entry_orderbook_depth_usd"] == 100000.0
        assert row["depth_price_impact_bps"] == 0.25
        assert row["depth_price_impact_source"] == (
            "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test:ask_levels_top5:top5_vwap_vs_touch"
        )

    closed_result = reconcile_paper_lifecycle(
        existing_ledger=carried_result,
        accepted_fills=[stale_carried_fill],
        mark_prices={
            "BTCUSDT": {
                "price": 102.0,
                "actual_observed_spread_exit_bps": 1.6,
                "exit_spread_source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test",
            }
        },
        generated_utc="2026-06-11T10:05:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exit_config=PaperExitConfig(take_profit_bps=100.0, stop_loss_bps=99999.0),
        ),
    )

    close_event = closed_result["closed_trades"][0]
    outcome = closed_result["outcome_labels"][0]
    for row in (close_event, outcome):
        assert row["entry_prediction_id"] == "pred_trust-carry"
        assert row["prediction_id"] == "pred_trust-carry"
        assert row["entry_feature_snapshot_id"] == "feat_trust-carry"
        assert row["feature_snapshot_id"] == "feat_trust-carry"
        assert row["decision_id"] == "orch_trust-carry"
        assert row["mtf_snapshot_id"] == "mtf_trust-carry"
        assert row["feature_cutoff"] == "2026-06-11T09:59:00Z"
        assert row["decision_time"] == "2026-06-11T10:00:00Z"
        assert row["available_at"] == "2026-06-11T09:59:30Z"
        assert row["selected_action"] == "long"
        assert row["model_version"] == "unit_model_v1"
        assert row["model_source"] == "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA"
        assert row["candidate_id"] == "challenger_v2_unit"
        assert row["paper_policy_owner"] == "challenger_v2"
        assert row["policy_fingerprint"] == "policy-fp-trust-carry"
        assert row["checkpoint_id"] == "ckpt_trust-carry"
        assert row["source_hashes"] == {"feature_vector_hash": "hash_trust-carry"}
        assert row["entry_feature_snapshot"] == _entry_feature_snapshot("trust-carry")
        assert row["candidate_selected_before_outcome"] is True
        assert row["candidate_selected_after_outcome"] is False
        assert row["future_labels_used_as_features"] is False
        assert row["entry_orderbook_depth_usd"] == 100000.0
        assert row["depth_price_impact_bps"] == 0.25
        assert row["depth_price_impact_model"] == "ORDERBOOK_TOP5_VWAP_VS_TOUCH"


def test_lifecycle_guard_kill_switch_blocks_paper_entry() -> None:
    result = evaluate_trade_lifecycle_guard(
        TradeLifecycleGuardInput(
            symbol="BTCUSDT",
            side="long",
            kill_switch_active=True,
        )
    )

    assert result.allowed is False
    assert "TRADE_LIFECYCLE_KILL_SWITCH_ACTIVE" in result.blockers


def test_lifecycle_guard_reduce_only_blocks_entry_but_allows_close() -> None:
    entry_result = evaluate_trade_lifecycle_guard(
        TradeLifecycleGuardInput(
            symbol="BTCUSDT",
            side="long",
            reduce_only_latch_active=True,
            close_or_reduce=False,
        )
    )
    close_result = evaluate_trade_lifecycle_guard(
        TradeLifecycleGuardInput(
            symbol="BTCUSDT",
            side="long",
            action="close",
            reduce_only_latch_active=True,
            close_or_reduce=True,
        )
    )

    assert entry_result.allowed is False
    assert "TRADE_LIFECYCLE_REDUCE_ONLY_LATCH_BLOCKS_NEW_ENTRY" in entry_result.blockers
    assert close_result.allowed is True
    assert close_result.blockers == ()


def test_reduce_only_latch_blocks_new_entry_but_allows_close() -> None:
    blocked = evaluate_trade_lifecycle_guard(
        TradeLifecycleGuardInput(
            symbol="BTCUSDT",
            side="long",
            reduce_only_latch_active=True,
            close_or_reduce=False,
        )
    )
    allowed = evaluate_trade_lifecycle_guard(
        TradeLifecycleGuardInput(
            symbol="BTCUSDT",
            side="long",
            action="close",
            reduce_only_latch_active=True,
            close_or_reduce=True,
        )
    )

    assert blocked.allowed is False
    assert allowed.allowed is True


def test_admission_invalidated_position_still_stop_closes_within_one_cycle() -> None:
    """P-0018 regression (F-0015): a position flagged admission-invalidated
    must remain under lifecycle management — a mark beyond its stop closes it
    in the SAME reconcile cycle. The BASUSDT incident realized -1397bps against
    a 63bps designed stop because the limbo position was dropped from the open
    set and its stop was never evaluated."""
    existing_ledger = {
        "accepted": [_fill(fill_id="a", qty=1, price=100)],
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_id": "paper_pos_BTCUSDT",
                "side": "long",
                "opened_est": "2026-06-11T10:00:00Z",
                "admission_invalidated": True,
                "new_entry_admission_eligible": False,
                "admission_drop_reason": "OPEN_POSITION_FILL_NO_LONGER_ADMISSION_VALID",
            }
        ],
    }
    result = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=[_fill(fill_id="a", qty=1, price=100)],
        mark_prices={"BTCUSDT": 98.0},  # -200bps, beyond the 100bps stop
        generated_utc="2026-06-11T10:05:00Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(stop_loss_bps=100.0, take_profit_bps=99999.0),
        ),
    )
    closed = result["closed_trades"]
    assert closed, "admission-invalidated position must be closeable"
    assert closed[0]["close_reason"] == "TIER_1_STOP_LOSS"
    assert result["open_positions"] == []


def test_lifecycle_honors_portfolio_cascade_guard_close() -> None:
    # The portfolio cascade guard's CLOSE directive forces a TIER_0 protective
    # exit (one coin's MM move must never cascade the book).
    fill = _fill(fill_id="guard1", symbol="ALTAUSDT", price=1.0, qty=10.0)
    guard = {
        "directives": [
            {
                "symbol": "ALTAUSDT",
                "action": "CLOSE",
                "reason": "CASCADE_CONFIRMED_ON_LOSING_POSITION",
                "cascade_score": 0.9,
            }
        ]
    }
    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[fill],
        mark_prices={"ALTAUSDT": 0.99},
        generated_utc="2026-06-11T10:05:00Z",
        config=PaperLifecycleConfig(portfolio_equity_usdt=10000.0),
        portfolio_guard=guard,
    )
    closed = result.get("closed_trades") or []
    assert any(
        t.get("symbol") == "ALTAUSDT"
        and (t.get("exit_reason") or t.get("close_reason")) == "TIER_0_PORTFOLIO_CASCADE_GUARD"
        for t in closed
    ), f"guard close not honored: {[(t.get('symbol'), t.get('exit_reason'), t.get('close_reason')) for t in closed]}"

    # Without a directive the same position stays open (no spurious closes).
    result2 = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[_fill(fill_id="guard2", symbol="ALTBUSDT", price=1.0, qty=10.0)],
        mark_prices={"ALTBUSDT": 0.999},
        generated_utc="2026-06-11T10:05:00Z",
        config=PaperLifecycleConfig(portfolio_equity_usdt=10000.0),
        portfolio_guard={"directives": []},
    )
    assert any(p.get("symbol") == "ALTBUSDT" for p in result2.get("open_positions") or [])
