from __future__ import annotations

from datetime import datetime, timezone
import json
import math

from v2.backend.app.cli import v2_adaptive_capital_productivity_status as status_module
from v2.backend.app.cli.v2_accelerated_closed_candle_replay_evidence import (
    generate_closed_candle_replay_evidence,
)
from v2.backend.app.cli.v2_adaptive_capital_productivity_status import (
    ADAPTIVE_CAPITAL_POLICY_VERSION,
    MANDATORY_PER_TRADE_FIELDS,
    P0_POLICY_VERSION,
    STATUS_FILENAMES,
    build_statuses,
    write_statuses,
)


def _trade(**overrides):
    row = {
        "symbol": "BTCUSDT",
        "side": "long",
        "paper_exit_policy_version": P0_POLICY_VERSION,
        "adaptive_capital_policy_version": ADAPTIVE_CAPITAL_POLICY_VERSION,
        "policy_activated_at": "2026-06-20T00:00:00Z",
        "realized_pnl_usd": 12.5,
        "funding_pnl_accounting_version": "PAPER_FUNDING_ACCRUAL_V1",
        "funding_pnl_accounting_status": "READY_FUNDING_PNL_ACCRUED",
        "funding_pnl_usd": -0.01,
        "funding_pnl_source": "FUNDING_RATE",
        "confidence_calibrated": 0.82,
        "expected_move_after_cost_bps": 75.0,
        "allocator_decision": "ALLOW_WITH_SIZE",
        "risk_budget_usd": 40.0,
        "gross_notional_usd": 500.0,
        "allocated_margin_usd": 250.0,
        "recommended_leverage": 2.0,
        "effective_leverage": 2.0,
        "recommended_margin_mode": "isolated_paper_simulated",
        "stop_distance_bps": 80.0,
        "liquidation_price_estimate": 50.0,
        "liquidation_buffer_bps": 4800.0,
        "expected_fees_usd": 0.2,
        "expected_slippage_usd": 0.1,
        "expected_funding_usd": 0.0,
        "expected_net_pnl_usd": 3.75,
        "expected_shortfall_usd": 60.0,
        "hedge_budget_usd": 0.0,
        "capital_allocation_reason": "adaptive_allocation_from_confidence_edge_market_quality_and_risk_budget",
    }
    row.update(overrides)
    return row


def _selection_model_inputs(
    *,
    leverage: float = 2.0,
    margin_mode: str = "isolated_paper_simulated",
    hedge_pct: float = 0.0,
) -> dict[str, object]:
    return {
        "raw_leverage_target": leverage,
        "leverage_target": leverage,
        "selected_leverage": leverage,
        "leverage_selection_reason": "moderate_edge_and_risk_budget_selects_dynamic_leverage",
        "selected_margin_mode": margin_mode,
        "margin_mode_selection_reason": "isolated_limits_tail_contagion_for_current_risk",
        "selected_hedge_budget_pct_of_risk": hedge_pct,
        "hedge_budget_selection_reason": (
            "hedge_budget_not_required_for_current_risk"
            if hedge_pct <= 0.0 else "correlation_drawdown_volatility_cost_pressure"
        ),
    }


def _paper_intent(**overrides):
    row = _trade(
        paper_exit_policy_version=None,
        symbol="LABUSDT",
        timeframe="4h",
        side="long",
        action="long",
        entry_price=12.389,
        fill_price=12.389,
        quantity=59.22920364,
        notional=733.79060393,
        notional_usdt=733.79060393,
        gross_notional_usd=733.79060393,
        allocated_margin_usd=733.79060393,
        allocator_decision="ALLOW_WITH_SIZE",
        paper_only=True,
        places_real_order=False,
        live_gate="blocked_human_only",
        paper_sizing_complete=True,
        paper_sizing_source="V2_ADAPTIVE_AI_CAPITAL_ALLOCATOR",
        entry_feature_decision_time="2026-06-20T01:30:09Z",
        entry_feature_available_at="2026-06-20T01:29:34Z",
        entry_feature_generated_at="2026-06-20T01:29:34Z",
        entry_feature_cutoff="2026-06-15T15:59:59Z",
        entry_feature_candle_closed_confirmed=True,
        correlation_exposure_pct=0.12,
        correlation_input_source="MARKET_OHLCV_RETURN_CORRELATION",
        correlation_input_status="READY",
        correlation_pair_count=3,
    )
    row["adaptive_allocation"] = {
        "adaptive_capital_policy_version": ADAPTIVE_CAPITAL_POLICY_VERSION,
        "allocator_decision": row["allocator_decision"],
        "target_notional_usdt": row["gross_notional_usd"],
        "target_quantity": row["quantity"],
        "correlation_adjustment": 0.33333333,
        "model_inputs": {
            **_selection_model_inputs(leverage=row["effective_leverage"]),
            "correlation_exposure_pct": row["correlation_exposure_pct"],
        },
    }
    row.update(overrides)
    return row


def _blocked_paper_intent(**overrides):
    row = _paper_intent(
        symbol="BLOCKEDUSDT",
        allocator_decision="BLOCK_NO_EDGE",
        quantity=0.0,
        notional=0.0,
        notional_usdt=0.0,
        gross_notional_usd=0.0,
        allocated_margin_usd=0.0,
        paper_sizing_complete=False,
        paper_sizing_source="V2_ADAPTIVE_ALLOCATOR_BLOCKED",
        paper_allocation_block_reason="BLOCK_NO_EDGE",
    )
    row["adaptive_allocation"].update({
        "allocator_decision": "BLOCK_NO_EDGE",
        "target_notional_usdt": 0.0,
        "target_quantity": 0.0,
        "gross_notional_usd": 0.0,
        "allocated_margin_usd": 0.0,
    })
    row.update(overrides)
    return row


def _paper_signal(**overrides):
    row = {
        "source_redis_key": "v2:signals:paper:BTCUSDT:1m",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "action": "long",
        "confidence_calibrated": 0.86,
        "expected_move_after_cost_bps": 90.0,
        "allocator_decision": "ALLOW_WITH_SIZE",
        "gross_notional_usd": 500.0,
        "orderbook_depth_usd": 2000.0,
        "realized_pnl_usd": 8.0,
        "actual_observed_spread_entry_bps": 2.0,
        "expected_slippage_bps": 2.0,
        "fee_bps": 4.0,
        "expected_funding_bps": 0.0,
        "entry_atr_bps": 30.0,
        "mfe_bps": 120.0,
        "mae_bps": 25.0,
        "decision_time": "2026-06-19T12:00:00Z",
        "available_at": "2026-06-19T11:59:00Z",
        "generated_at": "2026-06-19T11:58:00Z",
        "feature_cutoff": "2026-06-19T11:55:00Z",
        "entry_feature_candle_closed_confirmed": True,
    }
    row.update(overrides)
    return row


def _paper_signal_all_timeframes(**overrides):
    symbol = str(overrides.get("symbol") or "BTCUSDT")
    return [
        _paper_signal(
            **{
                **overrides,
                "symbol": symbol,
                "timeframe": timeframe,
                "source_redis_key": f"v2:signals:paper:{symbol}:{timeframe}",
            }
        )
        for timeframe in ("1m", "5m", "15m", "1h", "4h")
    ]


def _qualified_closed_candle_replay_policy_rows(
    *,
    validated_subset_only: bool = False,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    symbols = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    timeframes = ("1m", "5m", "15m", "1h", "4h")
    for symbol_index, symbol in enumerate(symbols):
        for timeframe_index, timeframe in enumerate(timeframes):
            index = symbol_index * len(timeframes) + timeframe_index
            side = "long" if index % 2 == 0 else "short"
            validated_subset_candidate = (
                side == "short" and timeframe in {"5m", "15m", "1h"}
            )
            rows.append({
                "row_id": f"qualified-replay-{symbol}-{timeframe}",
                "source_redis_key": f"closed_candle_replay:{symbol}:{timeframe}",
                "symbol": symbol,
                "timeframe": timeframe,
                "side": side,
                "action": side,
                "strategy": "range_reversion",
                "market_regime": "range",
                "decision_time": f"2026-06-20T12:{index:02d}:00Z",
                "available_at": "2026-06-20T11:59:30Z",
                "generated_at": "2026-06-20T11:59:20Z",
                "feature_cutoff": "2026-06-20T11:55:00Z",
                "future_label_close_time": f"2026-06-20T13:{index:02d}:00Z",
                "entry_feature_candle_closed_confirmed": True,
                "future_label_used_as_outcome_only": True,
                "future_labels_used_as_features": False,
                "confidence_calibrated": 0.86,
                "expected_move_after_cost_bps": 90.0,
                "after_cost_return_bps": 60.0,
                "realized_after_cost_return_bps": 60.0,
                "realized_pnl_usd": 6.0,
                "gross_notional_usd": 1000.0,
                "allocated_margin_usd": 500.0,
                "recommended_leverage": 2.0,
                "effective_leverage": 2.0,
                "recommended_margin_mode": "isolated_paper_simulated",
                "stop_distance_bps": 75.0,
                "take_profit_structure": "single_target",
                "hedge_budget_usd": 0.0,
                "actual_observed_spread_entry_bps": 1.2,
                "expected_slippage_bps": 1.4,
                "fee_bps": 4.0,
                "expected_funding_bps": 0.2,
                "funding_pnl_usd": -0.02,
                "funding_pnl_accounting_version": "PAPER_FUNDING_ACCRUAL_V1",
                "funding_pnl_accounting_status": "READY_FUNDING_PNL_ACCRUED",
                "expected_fees_usd": 0.4,
                "expected_slippage_usd": 0.14,
                "expected_funding_usd": 0.02,
                "liquidation_buffer_bps": 4000.0,
                "liquidation_price_estimate": 50.0,
                "orderbook_depth_usd": 300000.0,
                "correlation_exposure_pct": 0.12,
                "entry_atr_bps": 40.0,
                "mfe_bps": 120.0,
                "mae_bps": 20.0,
                "allocator_decision": (
                    "ALLOW_WITH_SIZE"
                    if not validated_subset_only or validated_subset_candidate
                    else "BLOCK_NO_EDGE"
                ),
                "paper_only": True,
                "places_real_order": False,
                "live_gate": "blocked_human_only",
                "approves_live": False,
                "approves_canary": False,
                "approves_legacy_shutdown": False,
                "approves_redis_trim": False,
                "live_symbols": [],
            })
    return rows


def _out_of_sample_reverify_row(
    *,
    fingerprint: str,
    row_id: str,
    symbol: str,
    side: str,
    timeframe: str = "5m",
    outcome_bps: float = 40.0,
    expected_edge_bps: float = 45.0,
    decision_minute: int = 0,
    holdout: bool = True,
) -> dict[str, object]:
    decision_time = f"2026-06-21T12:{decision_minute:02d}:00Z"
    outcome_time = f"2026-06-21T13:{decision_minute:02d}:00Z"
    pnl_usd = outcome_bps / 10000.0 * 1000.0
    row: dict[str, object] = {
        "row_id": row_id,
        "source_redis_key": f"out_of_sample_reverify:{symbol}:{timeframe}:{row_id}",
        "symbol": symbol,
        "timeframe": timeframe,
        "side": side,
        "action": side,
        "strategy": "range_reversion",
        "market_regime": "range",
        "volatility_bucket": "medium",
        "liquidity_bucket": "high",
        "decision_time": decision_time,
        "available_at": f"2026-06-21T11:{decision_minute:02d}:30Z",
        "generated_at": f"2026-06-21T11:{decision_minute:02d}:20Z",
        "feature_cutoff": f"2026-06-21T11:{decision_minute:02d}:00Z",
        "future_label_close_time": outcome_time,
        "closed_at": outcome_time,
        "entry_feature_candle_closed_confirmed": True,
        "future_label_used_as_outcome_only": True,
        "future_labels_used_as_features": False,
        "out_of_sample_reverify_candidate": True,
        "candidate_selection_tier": "A_GRADE_EXECUTION_PAPER",
        "selected_before_outcome": True,
        "candidate_selected_before_outcome": True,
        "selector_policy_fingerprint": fingerprint,
        "confidence_calibrated": 0.86,
        "expected_move_after_cost_bps": expected_edge_bps,
        "after_cost_return_bps": outcome_bps,
        "realized_after_cost_return_bps": outcome_bps,
        "realized_pnl_usd": pnl_usd,
        "gross_notional_usd": 1000.0,
        "allocated_margin_usd": 500.0,
        "recommended_leverage": 2.0,
        "effective_leverage": 2.0,
        "recommended_margin_mode": "isolated_paper_simulated",
        "stop_distance_bps": 75.0,
        "take_profit_structure": "single_target",
        "hedge_budget_usd": 0.0,
        "actual_observed_spread_entry_bps": 1.2,
        "depth_impact_bps": 0.2,
        "expected_slippage_bps": 1.4,
        "fee_bps": 4.0,
        "expected_funding_bps": 0.2,
        "funding_pnl_usd": -0.02,
        "expected_fees_usd": 0.4,
        "expected_slippage_usd": 0.14,
        "expected_funding_usd": 0.02,
        "liquidation_buffer_bps": 4000.0,
        "liquidation_price_estimate": 50.0,
        "orderbook_depth_usd": 300000.0,
        "correlation_exposure_pct": 0.12,
        "allocator_decision": "ALLOW_WITH_SIZE",
        "paper_only": True,
        "places_real_order": False,
        "live_gate": "blocked_human_only",
        "used_for_dynamic_a_grade_bucket_construction": False,
        "used_for_229_candidate_subset": False,
        "selector_training_window_overlap": False,
        "holdout_window_id": "untouched-window-1",
        "untouched_holdout_window": True,
        "out_of_sample_holdout": True,
    }
    if not holdout:
        row.update({
            "holdout_window_id": "",
            "untouched_holdout_window": False,
            "out_of_sample_holdout": False,
            "realtime_paper_reverify": True,
        })
    return row


def _accepted_intent_all_timeframes(**overrides):
    symbol = str(overrides.get("symbol") or "ACCEPTEDUSDT")
    rows = []
    for timeframe in ("1m", "5m", "15m", "1h", "4h"):
        row = _paper_intent(
            **{
                **overrides,
                "symbol": symbol,
                "timeframe": timeframe,
                "prediction_id": f"accepted_pred_{symbol}_{timeframe}",
                "source_prediction_id": f"accepted_pred_{symbol}_{timeframe}",
                "signal_id": f"accepted_sig_{symbol}_{timeframe}",
                "confidence_calibrated": 0.86,
                "expected_move_after_cost_bps": 90.0,
                "paper_only": True,
                "places_real_order": False,
                "live_gate": "blocked_human_only",
            }
        )
        row["adaptive_allocation"]["model_inputs"].update(
            {
                "spread_bps": 2.0,
                "slippage_bps": 2.0,
                "fee_bps": 4.0,
                "expected_funding_bps": 0.0,
                "orderbook_depth_usd": 2000.0,
            }
        )
        rows.append(row)
    return rows


def _ms(iso_value: str) -> int:
    return int(datetime.fromisoformat(iso_value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp() * 1000)


def _return_candles(symbol: str, returns: list[float], *, start_ms: int) -> list[dict[str, object]]:
    close = 100.0
    rows = []
    close_time = start_ms
    rows.append({
        "symbol": symbol,
        "timeframe": "1m",
        "close": close,
        "close_time": close_time,
        "candle_close_time": close_time,
        "available_at": close_time + 1,
        "candle_closed_confirmed": True,
        "closed_candle": True,
        "is_closed": True,
        "feature_eligible": True,
    })
    for index, return_value in enumerate(returns, start=1):
        close *= 1.0 + return_value
        close_time = start_ms + index * 60_000
        rows.append({
            "symbol": symbol,
            "timeframe": "1m",
            "close": close,
            "close_time": close_time,
            "candle_close_time": close_time,
            "available_at": close_time + 1,
            "candle_closed_confirmed": True,
            "closed_candle": True,
            "is_closed": True,
            "feature_eligible": True,
        })
    return rows


class _FakeRedis:
    def __init__(self, active_payloads: list[object], held_payload: object | None = None) -> None:
        self.active_payloads = list(active_payloads)
        self.held_payload = held_payload if held_payload is not None else []

    def get(self, key: str) -> str:
        if key == "v2:paper:intents":
            payload = self.active_payloads.pop(0) if self.active_payloads else []
            return json.dumps(payload)
        if key == "v2:paper:intents_held_by_paper_fill_gate":
            return json.dumps(self.held_payload)
        return "null"


def test_paper_intent_redis_read_retries_transient_unversioned_allocator_snapshot() -> None:
    unversioned = {
        "rows": [
            {
                "symbol": "BTCUSDT",
                "allocator_decision": "ALLOW_WITH_SIZE",
                "paper_sizing_complete": True,
                "adaptive_allocation": {"allocator_decision": "ALLOW_WITH_SIZE"},
            }
        ]
    }
    versioned = {
        "rows": [
            _paper_intent(symbol="BTCUSDT"),
        ]
    }

    rows = status_module._read_paper_intents_from_redis(
        _FakeRedis([unversioned, versioned]),
        attempts=2,
        retry_delay_seconds=0.0,
    )

    assert len(rows) == 1
    assert rows[0]["paper_intent_source"] == "v2:paper:intents"
    assert status_module._capital_policy_version(rows[0]) == ADAPTIVE_CAPITAL_POLICY_VERSION


def test_paper_intent_redis_read_retries_transient_empty_snapshot() -> None:
    versioned = {
        "rows": [
            _paper_intent(symbol="BTCUSDT"),
        ]
    }

    rows = status_module._read_paper_intents_from_redis(
        _FakeRedis([[], versioned]),
        attempts=2,
        retry_delay_seconds=0.0,
    )

    assert len(rows) == 1
    assert rows[0]["paper_intent_source"] == "v2:paper:intents"
    assert status_module._capital_policy_version(rows[0]) == ADAPTIVE_CAPITAL_POLICY_VERSION


def test_paper_intent_redis_read_retries_incomplete_selection_attribution_snapshot() -> None:
    incomplete = _paper_intent(
        symbol="SNAPUSDT",
        recommended_leverage=1.0,
        effective_leverage=1.0,
        gross_notional_usd=733.79060393,
        allocated_margin_usd=733.79060393,
    )
    incomplete["adaptive_allocation"].pop("model_inputs", None)
    complete = _paper_intent(
        symbol="SNAPUSDT",
        recommended_leverage=1.0,
        effective_leverage=1.0,
        gross_notional_usd=733.79060393,
        allocated_margin_usd=733.79060393,
    )
    complete["generated_utc"] = "2026-06-20T06:03:00Z"
    complete["adaptive_allocation"]["model_inputs"] = {
        **_selection_model_inputs(leverage=1.0),
        "selected_allocated_margin_usd": complete["allocated_margin_usd"],
    }

    rows = status_module._read_paper_intents_from_redis(
        _FakeRedis([{"rows": [incomplete]}, {"rows": [complete]}]),
        attempts=2,
        retry_delay_seconds=0.0,
    )

    assert len(rows) == 1
    assert rows[0]["symbol"] == "SNAPUSDT"
    assert status_module._paper_intent_snapshot_selection_attribution_complete(rows) is True
    assert status_module._paper_intent_snapshot_accounting_complete(rows) is True


def test_paper_intent_redis_read_falls_back_to_ledger_current_cycle_rows() -> None:
    unversioned = {
        "rows": [
            {
                "symbol": "BTCUSDT",
                "allocator_decision": "ALLOW_WITH_SIZE",
                "paper_sizing_complete": True,
                "adaptive_allocation": {"allocator_decision": "ALLOW_WITH_SIZE"},
            }
        ]
    }
    ledger = {
        "blocked": [
            _paper_intent(symbol="BTCUSDT"),
        ],
        "accepted": [
            _paper_intent(symbol="HISTORICALUSDT"),
        ],
    }

    rows = status_module._read_paper_intents_from_redis(
        _FakeRedis([unversioned]),
        attempts=1,
        retry_delay_seconds=0.0,
        fallback_ledger=ledger,
    )

    assert len(rows) == 1
    assert rows[0]["symbol"] == "BTCUSDT"
    assert rows[0]["paper_intent_source"] == "v2:paper:ledger.blocked"
    assert status_module._capital_policy_version(rows[0]) == ADAPTIVE_CAPITAL_POLICY_VERSION


def test_paper_intent_redis_read_prefers_newer_ledger_sized_snapshot() -> None:
    active = {
        "rows": [
            _blocked_paper_intent(symbol="ACTIVEUSDT", generated_utc="2026-06-20T06:00:00Z"),
        ]
    }
    ledger = {
        "blocked": [
            _paper_intent(symbol="LEDGERUSDT", generated_utc="2026-06-20T06:01:00Z"),
        ],
    }

    rows = status_module._read_paper_intents_from_redis(
        _FakeRedis([active]),
        attempts=1,
        retry_delay_seconds=0.0,
        fallback_ledger=ledger,
    )

    assert rows[0]["symbol"] == "LEDGERUSDT"
    assert rows[0]["paper_intent_source"] == "v2:paper:ledger.blocked"
    assert status_module._is_sized_pre_submit_intent(rows[0]) is True


def test_paper_intent_redis_read_prefers_newer_active_snapshot() -> None:
    active = {
        "rows": [
            _blocked_paper_intent(symbol="ACTIVEUSDT", generated_utc="2026-06-20T06:02:00Z"),
        ]
    }
    ledger = {
        "blocked": [
            _paper_intent(symbol="LEDGERUSDT", generated_utc="2026-06-20T06:01:00Z"),
        ],
    }

    rows = status_module._read_paper_intents_from_redis(
        _FakeRedis([active]),
        attempts=1,
        retry_delay_seconds=0.0,
        fallback_ledger=ledger,
    )

    assert rows[0]["symbol"] == "ACTIVEUSDT"
    assert rows[0]["paper_intent_source"] == "v2:paper:intents"
    assert status_module._is_sized_pre_submit_intent(rows[0]) is False


def test_build_statuses_reports_accounting_coverage_and_keeps_goal_no_go_until_evidence_exists() -> None:
    statuses = build_statuses(
        ledger={
            "open_positions": [_trade(symbol="ETHUSDT", realized_pnl_usd=0.0)],
            "closed_trades": [_trade(), _trade(symbol="SOLUSDT", side="short", realized_pnl_usd=8.0)],
        },
        portfolio={"equity": 10020.5},
        paper_status={"classification": "V2_TRADE_MANAGEMENT_PAPER_PRODUCTION_OK"},
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    accounting = statuses["margin_notional_leverage_accounting_status.json"]
    adaptive_policy = statuses["adaptive_capital_policy_status.json"]
    compounding = statuses["compounding_equity_status.json"]
    rare_event = statuses["rare_event_capital_stress_status.json"]
    capital = statuses["capital_productivity_runtime_status.json"]
    dashboard = statuses["operator_dashboard_payload.json"]
    pass_conditions = {
        condition["id"]: condition
        for condition in dashboard["pass_condition_status"]["conditions"]
    }
    thousand_x = dashboard["one_thousand_x_feasibility_status"]

    assert accounting["status"] == "PASSED"
    assert accounting["capital_policy_version"] == ADAPTIVE_CAPITAL_POLICY_VERSION
    assert accounting["blocker_reasons"] == []
    assert accounting["accounting_enforcement_status"] == "PASSED_RUNTIME_ACCOUNTING"
    assert accounting["runtime_row_count"] == 3
    assert accounting["historical_or_unversioned_runtime_row_count"] == 0
    assert accounting["new_trade_row_count"] == 3
    assert accounting["post_capital_policy_closed_row_count"] == 2
    assert accounting["mandatory_fields"] == list(MANDATORY_PER_TRADE_FIELDS)
    assert accounting["mandatory_field_coverage"] == 1.0
    assert accounting["leverage_margin_accounting_formula"] == "gross_notional_usd / allocated_margin_usd == effective_leverage"
    assert accounting["leverage_margin_consistency_row_count"] == 3
    assert accounting["leverage_margin_consistent_row_count"] == 3
    assert accounting["runtime_leverage_margin_consistency_status"] == "PASSED"
    assert accounting["leverage_margin_consistency_status"] == "PASSED"
    assert accounting["runtime_accounting_evidence"]["status"] == "PASSED"
    assert accounting["runtime_accounting_evidence"]["complete"] is True
    assert accounting["policy_activation_funding_evidence_status"]["status"] == "PASSED"
    assert accounting["policy_activation_funding_evidence_status"]["policy_activated_at_present_count"] == 3
    assert accounting["policy_activation_funding_evidence_status"]["funding_pnl_accounted_count"] == 2
    assert accounting["leverage_margin_inconsistent_count"] == 0
    assert accounting["leverage_margin_consistency_coverage"] == 1.0
    assert pass_conditions["mandatory_per_trade_accounting"]["status"] == "PASSED"
    assert pass_conditions["policy_activation_and_funding_accounting"]["status"] == "PASSED"
    assert pass_conditions["adaptive_selection_attribution"]["status"] == "NO_GO"
    assert pass_conditions["adaptive_selection_attribution"]["blocker_reasons"] == [
        "LEVERAGE_SELECTION_MODEL_INPUT_INCOMPLETE",
        "MARGIN_MODE_SELECTION_MODEL_INPUT_INCOMPLETE",
        "HEDGE_BUDGET_SELECTION_MODEL_INPUT_INCOMPLETE",
    ]
    assert pass_conditions["post_policy_outcome_count"]["status"] == "NO_GO"
    assert pass_conditions["counterfactual_a_grade_replay"]["status"] == "NO_GO"
    assert pass_conditions["minimum_profit_factor"]["status"] == "PASSED"
    assert pass_conditions["minimum_profit_factor"]["evidence"]["profit_factor"] == "inf"
    assert pass_conditions["minimum_profit_factor"]["evidence"]["minimum_required_profit_factor"] == 1.176
    assert capital["post_allocator_performance_status"] == "PASSED"
    assert capital["profit_factor"] == "inf"
    assert capital["post_allocator_win_rate"] == 1.0
    assert capital["post_allocator_realized_profit_usd"] == 20.5
    assert capital["post_allocator_realized_loss_usd"] == 0
    assert pass_conditions["one_thousand_x_explicit_horizon_classification"]["status"] == "PASSED"
    assert pass_conditions["one_thousand_x_explicit_horizon_classification"]["blocker_reasons"] == []
    assert pass_conditions["one_thousand_x_explicit_horizon_classification"]["evidence"]["explicit_horizon_classification"] is True
    assert pass_conditions["one_thousand_x_explicit_horizon_classification"]["evidence"]["no_guaranteed_return_claim"] is True
    assert dashboard["pass_condition_status"]["status"] == "NO_GO"
    assert "one_thousand_x_explicit_horizon_classification" not in dashboard["pass_condition_status"]["failed_conditions"]
    assert adaptive_policy["post_allocator_closed_outcome_count"] == 2
    assert adaptive_policy["closed_outcome_deficit_to_minimum"] == 298
    assert adaptive_policy["closed_outcome_progress_pct"] == 0.00666667
    assert adaptive_policy["open_positions_ready_to_become_closed_outcomes"] == 1
    assert adaptive_policy["projected_closed_outcome_count_after_current_open_positions_close"] == 3
    assert adaptive_policy["projected_closed_outcome_deficit_after_current_open_positions_close"] == 297
    acquisition = capital["evidence_acquisition_status"]
    assert acquisition["current_closed_outcome_count"] == 2
    assert acquisition["closed_outcome_deficit_to_minimum"] == 298
    assert acquisition["open_positions_ready_to_become_closed_outcomes"] == 1
    assert acquisition["projected_closed_outcome_deficit_after_current_open_positions_close"] == 297
    assert acquisition["status"] == "NO_GO_EVIDENCE_ACQUISITION_RATE_UNAVAILABLE"
    assert acquisition["timed_closed_outcome_count"] == 0
    assert acquisition["first_closed_outcome_at"] is None
    assert acquisition["latest_closed_outcome_at"] is None
    assert acquisition["hours_since_latest_closed_outcome"] is None
    assert acquisition["observed_window_days"] is None
    assert acquisition["observed_closed_outcome_interval_count"] == 0
    assert acquisition["observed_closed_outcomes_per_day"] is None
    assert acquisition["eta_days_to_300_closed_outcomes"] is None
    assert acquisition["eta_days_after_current_open_positions_close"] is None
    assert acquisition["counts_as_additional_pass_gate"] is False
    runtime_acquisition = acquisition["runtime_evidence_acquisition_status"]
    assert runtime_acquisition["status"] == "RUNTIME_STATUS_STALE"
    assert runtime_acquisition["paper_loop_status_present"] is True
    assert runtime_acquisition["paper_loop_status_stale"] is True
    assert runtime_acquisition["paper_loop_classification"] == "V2_TRADE_MANAGEMENT_PAPER_PRODUCTION_OK"
    assert runtime_acquisition["counts_as_additional_pass_gate"] is False
    assert adaptive_policy["evidence_acquisition_status"] == acquisition
    assert adaptive_policy["policy_evidence_progress"]["evidence_acquisition_status"] == acquisition
    assert adaptive_policy["runtime_evidence_acquisition_status"] == runtime_acquisition
    assert adaptive_policy["policy_evidence_progress"]["runtime_evidence_acquisition_status"] == runtime_acquisition
    assert compounding["evidence_acquisition_status"] == acquisition
    assert compounding["runtime_evidence_acquisition_status"] == runtime_acquisition
    assert dashboard["operator_go_readiness"]["evidence_acquisition_status"] == acquisition
    assert dashboard["operator_go_readiness"]["runtime_evidence_acquisition_status"] == runtime_acquisition
    assert dashboard["evidence_acquisition_status"] == acquisition
    assert dashboard["runtime_evidence_acquisition_status"] == runtime_acquisition
    assert capital["runtime_evidence_acquisition_status"] == runtime_acquisition
    assert adaptive_policy["long_closed_outcome_count"] == 1
    assert adaptive_policy["short_closed_outcome_count"] == 1
    assert adaptive_policy["both_long_short_evidence"] is True
    assert adaptive_policy["missing_directional_sides"] == []
    assert adaptive_policy["minimum_required_per_directional_side"] == 1
    assert adaptive_policy["post_allocator_side_counts"] == {"long": 1, "short": 1}
    assert adaptive_policy["minimum_required_symbol_count"] == 30
    assert adaptive_policy["minimum_required_symbols"] == 30
    assert adaptive_policy["symbol_diversity_deficit"] == 28
    assert adaptive_policy["symbol_diversity_progress_pct"] == 0.06666667
    assert compounding["post_allocator_closed_outcome_count"] == 2
    assert compounding["closed_outcome_evidence_count"] == 2
    assert compounding["minimum_required_closed_outcomes"] == 300
    assert compounding["closed_outcome_deficit_to_minimum"] == 298
    assert compounding["post_allocator_symbol_count"] == 2
    assert compounding["minimum_required_symbol_count"] == 30
    assert compounding["symbol_diversity_deficit"] == 28
    assert compounding["long_closed_outcome_count"] == 1
    assert compounding["short_closed_outcome_count"] == 1
    assert compounding["both_long_short_evidence"] is True
    assert compounding["positive_return_on_deployed_margin"] is True
    assert pass_conditions["compounding_evidence"]["evidence"]["closed_outcome_deficit_to_minimum"] == 298
    assert pass_conditions["compounding_evidence"]["evidence"]["post_allocator_symbol_count"] == 2
    assert dashboard["overall_status"] == "NO_GO"
    assert "counterfactual_capital_sweep_status" in dashboard["remaining_blockers"]
    assert dashboard["operator_safety"]["places_real_order"] is False
    assert rare_event["status"] == "PASSED"
    assert rare_event["stress_source"] == "runtime_adaptive_allocations"
    assert rare_event["runtime_stress_scope"] == (
        "current_open_adaptive_positions_plus_active_sized_pre_submit_candidates"
    )
    assert rare_event["counterfactual_best_configuration_count"] == 0
    assert rare_event["counterfactual_stress_status"] == "NO_GO_RARE_EVENT_CAPITAL_STRESS_NOT_RUN"
    assert rare_event["runtime_allocation_row_count"] == 1
    assert rare_event["runtime_stressed_row_count"] == 1
    assert rare_event["stressed_allocation_sample_count"] == 1
    assert rare_event["rare_event_blocker_reasons"] == []
    assert thousand_x["guaranteed_return_claim"] is False
    assert thousand_x["no_guaranteed_return_claim"] is True
    assert thousand_x["explicit_horizon_classification"] is True
    assert thousand_x["classification_dependency_gated"] is True
    assert thousand_x["current_evidence_supports_feasibility_status"] is False
    assert thousand_x["status"] == "UNSUPPORTED_CURRENT_EVIDENCE"
    assert thousand_x["classification"] == "UNSUPPORTED_DEPENDENCY_GATES_NOT_PASSED"
    assert thousand_x["initial_equity_usd"] == 10000.0
    assert thousand_x["horizon_days"] == 1825.0
    assert thousand_x["required_growth_multiple"] == 1000.0
    assert thousand_x["required_cagr"] == round(1000.0 ** (1.0 / 5.0) - 1.0, 12)
    assert thousand_x["required_daily_log_return"] == round(math.log(1000.0) / 1825.0, 12)
    assert thousand_x["observed_daily_log_return"] is None
    assert thousand_x["observed_cagr"] is None
    assert thousand_x["assumption_set"] == {
        "horizon_years": 5.0,
        "horizon_days": 1825.0,
        "target_multiple": 1000.0,
        "projection_is_descriptive_only": True,
        "requires_dependency_gates_to_pass": True,
        "guaranteed_return_claim": False,
    }
    assert thousand_x["required_log_growth"] == round(math.log(1000.0), 12)
    observed_growth = thousand_x["observed_growth_evidence"]
    assert observed_growth["current_paper_equity_usd"] == 10020.5
    assert observed_growth["observed_target_multiple"] == 1000.0
    assert observed_growth["observed_current_equity_multiple"] == 1.00205
    assert observed_growth["observed_current_log_growth_from_starting_equity"] == round(math.log(1.00205), 12)
    assert observed_growth["current_log_growth_gap_vs_required"] == round(math.log(1000.0) - math.log(1.00205), 12)
    assert observed_growth["projection_is_guarantee"] is False
    assert observed_growth["observed_growth_classification"] == "NO_OBSERVED_WINDOW_GROWTH_EVIDENCE"
    assert [row["status"] for row in observed_growth["window_evidence"]] == [
        "NO_WINDOW_CLOSED_TRADE_EVIDENCE",
        "NO_WINDOW_CLOSED_TRADE_EVIDENCE",
        "NO_WINDOW_CLOSED_TRADE_EVIDENCE",
    ]
    assert thousand_x["dependency_statuses"]["paper_live_pre_submit_parity_status"] == (
        "NO_GO_PRE_SUBMIT_PARITY_NO_INTENT_EVIDENCE"
    )
    assert thousand_x["dependency_statuses"]["rare_event_capital_stress_status"] == "PASSED"
    assert "PAPER_LIVE_PRE_SUBMIT_PARITY_NOT_PASSED" in thousand_x["feasibility_blocker_reasons"]
    assert "RARE_EVENT_STRESS_NOT_PASSED" not in thousand_x["feasibility_blocker_reasons"]
    assert adaptive_policy["policy_evidence_blocker_reasons"] == [
        "INSUFFICIENT_POST_ALLOCATOR_CLOSED_OUTCOMES",
        "INSUFFICIENT_SYMBOL_DIVERSITY",
        "FIXED_OR_UNPROVEN_RUNTIME_SIZE",
        "FIXED_OR_UNPROVEN_RUNTIME_LEVERAGE",
        "LEVERAGE_SELECTION_MODEL_INPUT_INCOMPLETE",
        "MARGIN_MODE_SELECTION_MODEL_INPUT_INCOMPLETE",
        "HEDGE_BUDGET_SELECTION_MODEL_INPUT_INCOMPLETE",
    ]
    assert adaptive_policy["no_fixed_runtime_size"] is False
    assert adaptive_policy["no_fixed_runtime_leverage"] is False
    assert adaptive_policy["runtime_size_leverage_evidence"] == {
        "row_count": 3,
        "runtime_size_variation_proven": False,
        "runtime_leverage_variation_proven": False,
        "notional_unique_count": 1,
        "allocated_margin_unique_count": 1,
        "recommended_leverage_unique_count": 1,
        "effective_leverage_unique_count": 1,
        "raw_leverage_target_unique_count": 0,
        "leverage_target_unique_count": 0,
        "selected_leverage_unique_count": 0,
        "recommended_margin_mode_unique_count": 1,
        "notional_values_sample": [500.0],
        "allocated_margin_values_sample": [250.0],
        "recommended_leverage_values": [2.0],
        "effective_leverage_values": [2.0],
        "raw_leverage_target_values": [],
        "leverage_target_values": [],
        "selected_leverage_values": [],
        "dynamic_leverage_recommendation_present": False,
        "dynamic_raw_leverage_target_variation_proven": False,
        "selected_leverage_below_raw_target_count": 0,
        "selected_leverage_filtered_to_1x_count": 0,
        "fixed_leverage_classification": "NO_DYNAMIC_LEVERAGE_SELECTION_EVIDENCE",
        "leverage_selection_reason_counts": {"__missing__": 3},
        "recommended_margin_modes": ["isolated_paper_simulated"],
        "capital_allocation_reason_counts": {
            "adaptive_allocation_from_confidence_edge_market_quality_and_risk_budget": 3,
        },
        "variation_blocker_reasons": [
            "FIXED_OR_UNPROVEN_RUNTIME_SIZE",
            "FIXED_OR_UNPROVEN_RUNTIME_LEVERAGE",
        ],
    }
    field_selection = adaptive_policy["adaptive_field_selection_evidence"]
    assert field_selection["row_count"] == 3
    assert field_selection["required_selection_field_coverage"] == 1.0
    assert field_selection["gross_notional_unique_count"] == 1
    assert field_selection["allocated_margin_unique_count"] == 1
    assert field_selection["effective_leverage_values"] == [2.0]
    assert field_selection["recommended_margin_modes"] == ["isolated_paper_simulated"]
    assert field_selection["hedge_budget_values_sample"] == [0.0]
    assert field_selection["positive_hedge_budget_count"] == 0
    assert field_selection["zero_hedge_budget_count"] == 3
    assert field_selection["leverage_selection_model_input_coverage"] == 0.0
    assert field_selection["margin_mode_selection_model_input_coverage"] == 0.0
    assert field_selection["hedge_budget_selection_model_input_coverage"] == 0.0
    assert field_selection["complete_selection_model_input_count"] == 0
    assert field_selection["complete_selection_model_input_coverage"] == 0.0
    assert field_selection["selection_model_input_missing_counts"] == {
        "complete_selection_model_input": 3,
        "hedge_budget_selection_model_input": 3,
        "leverage_selection_model_input": 3,
        "margin_mode_selection_model_input": 3,
    }
    assert field_selection["missing_selection_attribution_sample"][0]["missing_selection_attribution"] == [
        "leverage_selection_model_input",
        "margin_mode_selection_model_input",
        "hedge_budget_selection_model_input",
    ]
    assert field_selection["margin_mode_selection_reason_counts"] == {"__missing__": 3}
    assert field_selection["hedge_budget_selection_reason_counts"] == {"__missing__": 3}
    selection_attribution = adaptive_policy["adaptive_selection_attribution_status"]
    assert selection_attribution["status"] == "NO_GO_SELECTION_ATTRIBUTION_INCOMPLETE"
    assert selection_attribution["blocker_reasons"] == [
        "LEVERAGE_SELECTION_MODEL_INPUT_INCOMPLETE",
        "MARGIN_MODE_SELECTION_MODEL_INPUT_INCOMPLETE",
        "HEDGE_BUDGET_SELECTION_MODEL_INPUT_INCOMPLETE",
    ]
    assert selection_attribution["selection_model_input_missing_counts"] == {
        "complete_selection_model_input": 3,
        "hedge_budget_selection_model_input": 3,
        "leverage_selection_model_input": 3,
        "margin_mode_selection_model_input": 3,
    }
    assert len(selection_attribution["missing_selection_attribution_sample"]) == 3
    assert adaptive_policy["minimum_required_symbol_count"] == 30
    assert compounding["compounding_blocker_reasons"] == [
        "INSUFFICIENT_POST_ALLOCATOR_CLOSED_OUTCOMES",
        "INSUFFICIENT_SYMBOL_DIVERSITY",
        "FIXED_OR_UNPROVEN_RUNTIME_SIZE",
        "FIXED_OR_UNPROVEN_RUNTIME_LEVERAGE",
        "LEVERAGE_SELECTION_MODEL_INPUT_INCOMPLETE",
        "MARGIN_MODE_SELECTION_MODEL_INPUT_INCOMPLETE",
        "HEDGE_BUDGET_SELECTION_MODEL_INPUT_INCOMPLETE",
        "COUNTERFACTUAL_EFFICIENT_FRONTIER_NOT_READY",
    ]
    assert compounding["after_cost_expectancy_bps"] == 75.0
    assert compounding["counterfactual_efficient_frontier_ready"] is False


def test_evidence_acquisition_status_projects_eta_from_timed_closed_outcomes() -> None:
    status = status_module._evidence_acquisition_status(
        rows=[
            _trade(closed_at="2026-06-19T00:00:00Z"),
            _trade(symbol="SOLUSDT", side="short", closed_at="2026-06-20T00:00:00Z"),
        ],
        complete_open_row_count=1,
        current_symbol_count=2,
        symbol_diversity_deficit=28,
        generated_utc="2026-06-20T00:00:00Z",
    )

    assert status["status"] == "NO_GO_EVIDENCE_ACQUISITION_IN_PROGRESS"
    assert status["current_closed_outcome_count"] == 2
    assert status["minimum_required_closed_outcomes"] == 300
    assert status["closed_outcome_deficit_to_minimum"] == 298
    assert status["open_positions_ready_to_become_closed_outcomes"] == 1
    assert status["projected_closed_outcome_count_after_current_open_positions_close"] == 3
    assert status["projected_closed_outcome_deficit_after_current_open_positions_close"] == 297
    assert status["current_symbol_count"] == 2
    assert status["symbol_diversity_deficit"] == 28
    assert status["timed_closed_outcome_count"] == 2
    assert status["first_closed_outcome_at"] == "2026-06-19T00:00:00Z"
    assert status["latest_closed_outcome_at"] == "2026-06-20T00:00:00Z"
    assert status["hours_since_latest_closed_outcome"] == 0.0
    assert status["observed_window_days"] == 1.0
    assert status["observed_closed_outcome_interval_count"] == 1
    assert status["observed_closed_outcomes_per_day"] == 1.0
    assert status["eta_days_to_300_closed_outcomes"] == 298.0
    assert status["eta_days_after_current_open_positions_close"] == 297.0
    assert status["counts_as_additional_pass_gate"] is False


def test_evidence_acquisition_status_reports_runtime_paper_loop_blockers() -> None:
    status = status_module._evidence_acquisition_status(
        rows=[_trade(closed_at="2026-06-20T00:00:00Z")],
        complete_open_row_count=0,
        current_symbol_count=1,
        symbol_diversity_deficit=29,
        generated_utc="2026-06-21T05:13:40Z",
        paper_status={
            "classification": "V2_TRADE_MANAGEMENT_PAPER_PRODUCTION_OK",
            "started_at": "2026-06-21T05:13:20Z",
            "finished_at": "2026-06-21T05:13:37Z",
            "paper_signals_seen": 211,
            "intents_built": 211,
            "intents_accepted": 0,
            "intents_blocked": 211,
            "intents_held_by_paper_fill_gate": 0,
            "accepted_position_count": 3,
            "open_position_count": 3,
            "closed_trade_count": 1559,
            "persistent_accepted_fill_count": 4386,
            "realized_pnl_usd": 106.8605,
            "total_open_notional": 1418.1651,
            "v2_paper_keys_written_count": 12,
            "writes_legacy_redis": False,
            "places_real_order": False,
            "paper_adaptive_sizing_runtime_status": {
                "status": "ACTIVE_FOR_PAPER_AND_LIVE_PRE_SUBMIT",
                "allocator_decision_counts": {
                    "ALLOW_WITH_SIZE": 4386,
                    "BLOCK_DRAWDOWN_GUARD": 12,
                    "BLOCK_NO_EDGE": 390,
                },
                "sample_allocations": [
                    {
                        "allocator_decision": "BLOCK_DRAWDOWN_GUARD",
                        "capital_allocation_reason": "drawdown_guard_breached",
                    },
                    {
                        "allocator_decision": "BLOCK_NO_EDGE",
                        "capital_allocation_reason": "expected_move_after_cost_not_positive",
                    },
                ],
            },
            "paper_exploration_tier_status": {
                "status": "ACTIVE",
                "paper_only": True,
                "live_path_changed": False,
                "tiers": [
                    "A_GRADE_EXECUTION_PAPER",
                    "B_GRADE_EXPLORATION_PAPER",
                    "SHADOW_ONLY",
                    "NO_TRADE",
                ],
                "tier_counts": {"NO_TRADE": 211},
                "accepted_tier_counts": {},
                "legacy_accepted_without_tier_count": 4386,
                "b_grade_exploration_accepted_count": 0,
                "b_grade_exploration_budget_cap_applied_count": 0,
                "b_grade_exploration_observed_max_risk_fraction": 0.0,
                "b_grade_exploration_live_routing_blocked": True,
                "calibration_label_purpose": "B_GRADE_EXPLORATION_OUTCOME_LABEL",
            },
        },
    )

    runtime = status["runtime_evidence_acquisition_status"]
    assert runtime["status"] == "CURRENT_INTENTS_BLOCKED"
    assert runtime["paper_loop_status_stale"] is False
    assert runtime["paper_loop_status_age_seconds"] == 3.0
    assert runtime["current_intents_built"] == 211
    assert runtime["current_intents_accepted"] == 0
    assert runtime["current_intents_blocked"] == 211
    assert runtime["current_intents_all_blocked"] is True
    assert runtime["adaptive_allocator_decision_counts"]["BLOCK_DRAWDOWN_GUARD"] == 12
    assert runtime["current_sample_allocator_decision_counts"] == {
        "BLOCK_DRAWDOWN_GUARD": 1,
        "BLOCK_NO_EDGE": 1,
    }
    assert runtime["current_sample_allocation_reason_counts"] == {
        "drawdown_guard_breached": 1,
        "expected_move_after_cost_not_positive": 1,
    }
    tier_status = runtime["paper_exploration_tier_status"]
    assert tier_status["status"] == "ACTIVE"
    assert tier_status["tiers"] == [
        "A_GRADE_EXECUTION_PAPER",
        "B_GRADE_EXPLORATION_PAPER",
        "SHADOW_ONLY",
        "NO_TRADE",
    ]
    assert tier_status["tier_counts"] == {"NO_TRADE": 211}
    assert tier_status["legacy_accepted_without_tier_count"] == 4386
    assert tier_status["b_grade_exploration_live_routing_blocked"] is True
    assert runtime["writes_legacy_redis"] is False
    assert runtime["places_real_order"] is False
    assert runtime["counts_as_additional_pass_gate"] is False


def test_dashboard_projects_paper_exploration_tier_status_from_runtime() -> None:
    paper_tiers = {
        "status": "ACTIVE",
        "paper_only": True,
        "live_path_changed": False,
        "tiers": [
            "A_GRADE_EXECUTION_PAPER",
            "B_GRADE_EXPLORATION_PAPER",
            "SHADOW_ONLY",
            "NO_TRADE",
        ],
        "tier_counts": {
            "A_GRADE_EXECUTION_PAPER": 2,
            "B_GRADE_EXPLORATION_PAPER": 1,
            "NO_TRADE": 5,
        },
        "accepted_tier_counts": {
            "A_GRADE_EXECUTION_PAPER": 2,
            "B_GRADE_EXPLORATION_PAPER": 1,
        },
        "legacy_accepted_without_tier_count": 0,
        "b_grade_exploration_accepted_count": 1,
        "b_grade_exploration_budget_cap_applied_count": 1,
        "b_grade_exploration_observed_max_risk_fraction": 0.12,
        "b_grade_exploration_live_routing_blocked": True,
        "calibration_label_purpose": "B_GRADE_EXPLORATION_OUTCOME_LABEL",
    }
    statuses = build_statuses(
        ledger={"closed_trades": [_trade()]},
        portfolio={"equity": 10000.0},
        paper_status={
            "classification": "V2_TRADE_MANAGEMENT_PAPER_PRODUCTION_OK",
            "finished_at": "2026-06-21T05:13:37Z",
            "paper_exploration_tier_status": paper_tiers,
        },
        horizon_years=5.0,
        generated_utc="2026-06-21T05:13:40Z",
    )

    dashboard_tiers = statuses["operator_dashboard_payload.json"]["paper_exploration_tier_status"]
    readiness_tiers = statuses["operator_dashboard_payload.json"]["operator_go_readiness"][
        "paper_exploration_tier_status"
    ]
    artifact_tiers = statuses["paper_exploration_tier_status.json"]

    assert dashboard_tiers["accepted_tier_counts"]["B_GRADE_EXPLORATION_PAPER"] == 1
    assert dashboard_tiers["b_grade_exploration_budget_cap_applied_count"] == 1
    assert dashboard_tiers["b_grade_exploration_live_routing_blocked"] is True
    assert readiness_tiers == dashboard_tiers
    assert artifact_tiers == dashboard_tiers


def test_selection_attribution_treats_historical_runtime_gap_as_non_blocking_when_current_durable_evidence_is_complete() -> None:
    accepted_intent = _paper_intent(symbol="STRICTUSDT")
    statuses = build_statuses(
        ledger={
            "open_positions": [_trade(symbol="ETHUSDT", realized_pnl_usd=0.0)],
            "closed_trades": [_trade(), _trade(symbol="SOLUSDT", side="short", realized_pnl_usd=8.0)],
            "accepted": [accepted_intent],
        },
        portfolio={"equity": 10020.5},
        paper_status={"classification": "V2_TRADE_MANAGEMENT_PAPER_PRODUCTION_OK"},
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    adaptive_policy = statuses["adaptive_capital_policy_status.json"]
    readiness = statuses["operator_dashboard_payload.json"]["operator_go_readiness"]
    pass_conditions = {
        condition["id"]: condition
        for condition in statuses["operator_dashboard_payload.json"]["pass_condition_status"]["conditions"]
    }
    selection_attribution = adaptive_policy["adaptive_selection_attribution_status"]

    assert selection_attribution["status"] == "PASSED"
    assert selection_attribution["blocker_reasons"] == []
    assert selection_attribution["historical_runtime_selection_model_input_gap_non_blocking"] is True
    assert selection_attribution["historical_runtime_selection_model_input_gap_reasons"] == [
        "LEVERAGE_SELECTION_MODEL_INPUT_INCOMPLETE",
        "MARGIN_MODE_SELECTION_MODEL_INPUT_INCOMPLETE",
        "HEDGE_BUDGET_SELECTION_MODEL_INPUT_INCOMPLETE",
    ]
    assert selection_attribution["current_selection_model_input_enforcement_complete"] is True
    assert selection_attribution["current_selection_model_input_enforcement_source"] == (
        "durable_accepted_pre_submit_ledger"
    )
    assert selection_attribution["durable_accepted_pre_submit_selection_model_input_complete"] is True
    assert selection_attribution["durable_accepted_pre_submit_selection_model_input_candidate_count"] == 1
    assert selection_attribution["selection_model_input_missing_counts"] == {
        "complete_selection_model_input": 3,
        "hedge_budget_selection_model_input": 3,
        "leverage_selection_model_input": 3,
        "margin_mode_selection_model_input": 3,
    }
    assert pass_conditions["adaptive_selection_attribution"]["status"] == "PASSED"
    assert readiness["evidence_to_go"]["selection_attribution_rows_needed"] == 0
    assert readiness["evidence_to_go"]["leverage_selection_attribution_rows_needed"] == 0
    assert readiness["evidence_to_go"]["margin_mode_selection_attribution_rows_needed"] == 0
    assert readiness["evidence_to_go"]["hedge_budget_selection_attribution_rows_needed"] == 0
    assert "LEVERAGE_SELECTION_MODEL_INPUT_INCOMPLETE" not in adaptive_policy["policy_evidence_blocker_reasons"]
    assert "MARGIN_MODE_SELECTION_MODEL_INPUT_INCOMPLETE" not in adaptive_policy["policy_evidence_blocker_reasons"]
    assert "HEDGE_BUDGET_SELECTION_MODEL_INPUT_INCOMPLETE" not in adaptive_policy["policy_evidence_blocker_reasons"]


def test_selection_attribution_treats_historical_selection_field_gap_as_non_blocking_when_current_durable_evidence_is_complete() -> None:
    historical_incomplete = _trade(
        symbol="OLDSELECTUSDT",
        recommended_margin_mode=None,
        hedge_budget_usd=None,
        capital_allocation_reason=None,
    )
    durable_accepted = _paper_intent(symbol="STRICTSELECTUSDT")

    statuses = build_statuses(
        ledger={
            "open_positions": [historical_incomplete],
            "closed_trades": [_trade(), _trade(symbol="SOLUSDT", side="short", realized_pnl_usd=8.0)],
            "accepted": [durable_accepted],
        },
        portfolio={"equity": 10020.5},
        paper_status={"classification": "V2_TRADE_MANAGEMENT_PAPER_PRODUCTION_OK"},
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    adaptive_policy = statuses["adaptive_capital_policy_status.json"]
    readiness = statuses["operator_dashboard_payload.json"]["operator_go_readiness"]
    pass_conditions = {
        condition["id"]: condition
        for condition in statuses["operator_dashboard_payload.json"]["pass_condition_status"]["conditions"]
    }
    selection_attribution = adaptive_policy["adaptive_selection_attribution_status"]

    assert selection_attribution["status"] == "PASSED"
    assert selection_attribution["blocker_reasons"] == []
    assert selection_attribution["historical_runtime_selection_model_input_gap_non_blocking"] is True
    assert "SELECTION_FIELDS_INCOMPLETE" in selection_attribution[
        "historical_runtime_selection_model_input_gap_reasons"
    ]
    assert selection_attribution["current_selection_model_input_enforcement_complete"] is True
    assert selection_attribution["durable_accepted_pre_submit_selection_model_input_complete"] is True
    assert selection_attribution["required_selection_field_coverage"] < 1.0
    assert pass_conditions["adaptive_selection_attribution"]["status"] == "PASSED"
    assert readiness["evidence_to_go"]["selection_attribution_rows_needed"] == 0
    assert "SELECTION_FIELDS_INCOMPLETE" not in adaptive_policy["policy_evidence_blocker_reasons"]


def test_selection_attribution_uses_latest_durable_strict_suffix_for_current_enforcement() -> None:
    historical_prefix = []
    for index in range(3):
        row = _paper_intent(symbol=f"OLD{index}USDT")
        row["adaptive_allocation"]["model_inputs"] = {
            "mode": "paper",
            "price": row["entry_price"],
        }
        historical_prefix.append(row)
    strict_suffix = [
        _paper_intent(symbol=f"STRICT{index:02d}USDT")
        for index in range(status_module.MINIMUM_DURABLE_STRICT_SELECTION_MODEL_INPUT_SUFFIX)
    ]

    statuses = build_statuses(
        ledger={
            "open_positions": [_trade(symbol="ETHUSDT", realized_pnl_usd=0.0)],
            "closed_trades": [_trade(), _trade(symbol="SOLUSDT", side="short", realized_pnl_usd=8.0)],
            "accepted": [*historical_prefix, *strict_suffix],
        },
        portfolio={"equity": 10020.5},
        paper_status={"classification": "V2_TRADE_MANAGEMENT_PAPER_PRODUCTION_OK"},
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    adaptive_policy = statuses["adaptive_capital_policy_status.json"]
    parity = statuses["paper_live_pre_submit_parity_status.json"]
    readiness = statuses["operator_dashboard_payload.json"]["operator_go_readiness"]
    pass_conditions = {
        condition["id"]: condition
        for condition in statuses["operator_dashboard_payload.json"]["pass_condition_status"]["conditions"]
    }
    selection_attribution = adaptive_policy["adaptive_selection_attribution_status"]
    suffix_evidence = parity["durable_accepted_pre_submit_evidence"][
        "latest_strict_selection_model_input_suffix_evidence"
    ]

    assert selection_attribution["status"] == "PASSED"
    assert selection_attribution["blocker_reasons"] == []
    assert selection_attribution["historical_runtime_selection_model_input_gap_non_blocking"] is True
    assert selection_attribution["current_selection_model_input_enforcement_complete"] is True
    assert selection_attribution["current_selection_model_input_enforcement_source"] == (
        "durable_accepted_pre_submit_ledger_latest_strict_suffix"
    )
    assert selection_attribution["durable_accepted_pre_submit_selection_model_input_complete"] is True
    assert selection_attribution["durable_accepted_pre_submit_latest_strict_suffix_count"] == (
        status_module.MINIMUM_DURABLE_STRICT_SELECTION_MODEL_INPUT_SUFFIX
    )
    assert selection_attribution["durable_accepted_pre_submit_latest_strict_suffix_proves_current_enforcement"] is True
    assert selection_attribution[
        "durable_accepted_pre_submit_historical_prefix_selection_model_input_gap_count"
    ] == 3
    assert suffix_evidence["latest_strict_suffix_start_index"] == 3
    assert suffix_evidence["historical_prefix_selection_model_input_gap_non_blocking"] is True
    assert suffix_evidence["latest_strict_suffix_selection_model_input_evidence"][
        "complete_selection_model_input_coverage"
    ] == 1.0
    assert pass_conditions["adaptive_selection_attribution"]["status"] == "PASSED"
    assert readiness["evidence_to_go"]["selection_attribution_rows_needed"] == 0
    assert "LEVERAGE_SELECTION_MODEL_INPUT_INCOMPLETE" not in adaptive_policy["policy_evidence_blocker_reasons"]
    assert "MARGIN_MODE_SELECTION_MODEL_INPUT_INCOMPLETE" not in adaptive_policy["policy_evidence_blocker_reasons"]
    assert "HEDGE_BUDGET_SELECTION_MODEL_INPUT_INCOMPLETE" not in adaptive_policy["policy_evidence_blocker_reasons"]


def test_selection_attribution_does_not_accept_short_durable_strict_suffix() -> None:
    historical_prefix = _paper_intent(symbol="OLDUSDT")
    historical_prefix["adaptive_allocation"]["model_inputs"] = {"mode": "paper"}
    short_suffix_count = status_module.MINIMUM_DURABLE_STRICT_SELECTION_MODEL_INPUT_SUFFIX - 1
    strict_suffix = [
        _paper_intent(symbol=f"SHORT{index:02d}USDT")
        for index in range(short_suffix_count)
    ]

    statuses = build_statuses(
        ledger={
            "open_positions": [_trade(symbol="ETHUSDT", realized_pnl_usd=0.0)],
            "closed_trades": [_trade(), _trade(symbol="SOLUSDT", side="short", realized_pnl_usd=8.0)],
            "accepted": [historical_prefix, *strict_suffix],
        },
        portfolio={"equity": 10020.5},
        paper_status={"classification": "V2_TRADE_MANAGEMENT_PAPER_PRODUCTION_OK"},
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    adaptive_policy = statuses["adaptive_capital_policy_status.json"]
    parity = statuses["paper_live_pre_submit_parity_status.json"]
    readiness = statuses["operator_dashboard_payload.json"]["operator_go_readiness"]
    selection_attribution = adaptive_policy["adaptive_selection_attribution_status"]
    suffix_evidence = parity["durable_accepted_pre_submit_evidence"][
        "latest_strict_selection_model_input_suffix_evidence"
    ]

    assert selection_attribution["status"] == "NO_GO_SELECTION_ATTRIBUTION_INCOMPLETE"
    assert selection_attribution["current_selection_model_input_enforcement_complete"] is False
    assert selection_attribution["durable_accepted_pre_submit_selection_model_input_complete"] is False
    assert selection_attribution["durable_accepted_pre_submit_latest_strict_suffix_count"] == short_suffix_count
    assert selection_attribution["durable_accepted_pre_submit_latest_strict_suffix_proves_current_enforcement"] is False
    assert suffix_evidence["latest_strict_suffix_complete"] is True
    assert suffix_evidence["latest_strict_suffix_proves_current_enforcement"] is False
    assert readiness["evidence_to_go"]["selection_attribution_rows_needed"] == 3


def test_one_thousand_x_gate_can_pass_when_dependency_evidence_passes() -> None:
    symbols = [f"PASS{index:02d}USDT" for index in range(30)]
    timeframes = ("1m", "5m", "15m", "1h", "4h")
    closed_trades = []
    for index in range(300):
        leverage = 1.0 if index % 2 == 0 else 2.0
        gross = 2.0 + index / 100.0
        closed_trades.append(
            _trade(
                symbol=symbols[index % len(symbols)],
                side="long" if index % 2 == 0 else "short",
                timeframe=timeframes[index % len(timeframes)],
                realized_pnl_usd=2.0,
                gross_notional_usd=gross,
                allocated_margin_usd=gross / leverage,
                recommended_leverage=leverage,
                effective_leverage=leverage,
                expected_shortfall_usd=5.0,
                closed_at="2026-06-19T12:00:00Z",
                adaptive_allocation={
                    "model_inputs": _selection_model_inputs(
                        leverage=leverage,
                        hedge_pct=0.05 if index % 3 == 0 else 0.0,
                    ),
                },
            )
        )
    paper_signals = [
        row
        for symbol in symbols
        for row in _paper_signal_all_timeframes(symbol=symbol)
    ]
    paper_intent = _paper_intent(
        symbol=symbols[0],
        timeframe="1m",
        gross_notional_usd=250.0,
        allocated_margin_usd=250.0,
        notional=250.0,
        notional_usdt=250.0,
        orderbook_depth_usd=2000.0,
        actual_observed_spread_entry_bps=2.0,
        expected_slippage_bps=2.0,
        fee_bps=4.0,
        expected_funding_bps=0.0,
    )

    statuses = build_statuses(
        ledger={
            "open_positions": [
                _trade(
                    symbol=symbols[0],
                    gross_notional_usd=30.0,
                    allocated_margin_usd=15.0,
                    recommended_leverage=2.0,
                    effective_leverage=2.0,
                    expected_shortfall_usd=5.0,
                    correlation_exposure_pct=0.02,
                    adaptive_allocation={
                        "model_inputs": _selection_model_inputs(leverage=2.0),
                    },
                ),
            ],
            "closed_trades": closed_trades,
        },
        portfolio={"equity": 10600.0},
        paper_status={"classification": "V2_TRADE_MANAGEMENT_PAPER_PRODUCTION_OK"},
        paper_intents=[paper_intent],
        paper_signals=paper_signals,
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    dashboard = statuses["operator_dashboard_payload.json"]
    thousand_x = statuses["one_thousand_x_feasibility_status.json"]
    pass_conditions = {
        condition["id"]: condition
        for condition in dashboard["pass_condition_status"]["conditions"]
    }

    assert statuses["capital_productivity_runtime_status.json"]["status"] == "PASSED"
    assert statuses["counterfactual_capital_sweep_status.json"]["status"] == "PASSED"
    assert statuses["adaptive_capital_policy_status.json"]["status"] == "PASSED"
    assert statuses["compounding_equity_status.json"]["status"] == "PASSED"
    assert statuses["rare_event_capital_stress_status.json"]["status"] == "PASSED"
    assert statuses["paper_live_pre_submit_parity_status.json"]["status"] == "PASSED"
    assert thousand_x["status"] == "PASSED"
    assert thousand_x["classification"] in {
        "FEASIBLE_ON_CURRENT_WINDOW_PROJECTION_UNVERIFIED",
        "NOT_FEASIBLE_ON_CURRENT_OBSERVED_TRAJECTORY",
    }
    assert thousand_x["horizon_years"] == 5.0
    assert thousand_x["guaranteed_return_claim"] is False
    assert thousand_x["no_guaranteed_return_claim"] is True
    assert thousand_x["explicit_horizon_classification"] is True
    assert thousand_x["classification_dependency_gated"] is False
    assert thousand_x["current_evidence_supports_feasibility_status"] is True
    assert pass_conditions["adaptive_selection_attribution"]["status"] == "PASSED"
    assert pass_conditions["adaptive_selection_attribution"]["blocker_reasons"] == []
    assert pass_conditions["one_thousand_x_explicit_horizon_classification"]["status"] == "PASSED"
    assert dashboard["pass_condition_status"]["status"] == "PASSED"
    assert dashboard["overall_status"] == "PASSED"
    assert dashboard["remaining_blockers"] == []


def test_policy_activation_funding_evidence_fails_missing_timestamp_and_funding_source() -> None:
    missing_evidence_trade = _trade(
        policy_activated_at=None,
        funding_pnl_accounting_version=None,
        funding_pnl_accounting_status=None,
        funding_pnl_usd=0.0,
        funding_pnl_source=None,
        funding_rate=None,
        funding_bps=None,
        expected_funding_bps=None,
        actual_funding_bps=None,
        actual_funding_usd=None,
    )

    statuses = build_statuses(
        ledger={
            "open_positions": [],
            "closed_trades": [missing_evidence_trade],
        },
        portfolio={"equity": 10000.0},
        paper_status={"classification": "V2_TRADE_MANAGEMENT_PAPER_PRODUCTION_OK"},
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    policy = statuses["adaptive_capital_policy_status.json"]
    accounting = statuses["margin_notional_leverage_accounting_status.json"]
    dashboard = statuses["operator_dashboard_payload.json"]
    pass_conditions = {
        condition["id"]: condition
        for condition in dashboard["pass_condition_status"]["conditions"]
    }
    evidence = policy["policy_activation_funding_evidence_status"]

    assert evidence["status"] == "NO_GO_POLICY_ACTIVATION_FUNDING_EVIDENCE_INCOMPLETE"
    assert evidence["blocker_reasons"] == [
        "MISSING_POLICY_ACTIVATED_AT_ON_ENTRY_OR_OUTCOME_ROWS",
        "FUNDING_PNL_UNACCOUNTED_OR_SOURCE_MISSING",
    ]
    assert evidence["policy_activated_at_missing_count"] == 1
    assert evidence["funding_pnl_unaccounted_count"] == 1
    assert evidence["funding_pnl_unaccounted_sample"][0]["funding_pnl_usd"] == 0.0
    assert evidence["funding_pnl_unaccounted_sample"][0]["funding_pnl_source"] is None
    reconstruction = evidence["funding_pnl_reconstruction_status"]
    assert reconstruction["status"] == "NO_RECONSTRUCTABLE_FUNDING_PNL_DIAGNOSTIC"
    assert reconstruction["reconstructable_closed_outcome_count"] == 0
    assert reconstruction["unreconstructable_closed_outcome_count"] == 1
    assert reconstruction["counts_as_accounted_funding_pnl"] is False
    assert reconstruction["reconstruction_missing_reason_counts"]["MISSING_FUNDING_RATE_OR_BPS"] == 1
    assert evidence["current_forward_funding_accounting_enforcement_complete"] is False
    assert evidence["historical_closed_outcome_funding_gap_non_blocking"] is False
    assert evidence["closed_outcome_funding_accounting_status"] == (
        "NO_GO_CLOSED_OUTCOME_FUNDING_ACCOUNTING_INCOMPLETE"
    )
    forward_contract = evidence["forward_funding_accounting_contract_status"]
    assert forward_contract["status"] == "NO_FORWARD_POLICY_ENTRY_OR_OPEN_ROWS"
    assert forward_contract["forward_row_count"] == 0
    assert forward_contract["counts_as_closed_outcome_funding_gate"] is False
    assert evidence["portfolio_order_counter_status"]["status"] == "MISSING_NAMED_ORDER_COUNTERS"
    assert accounting["policy_activation_funding_evidence_status"] == evidence
    assert dashboard["policy_activation_funding_evidence_status"] == evidence
    audit_burn_down = dashboard["external_audit_blocker_burn_down"]
    assert dashboard["operator_go_readiness"]["external_audit_blocker_burn_down"] == audit_burn_down
    assert audit_burn_down["status"] == "NO_GO_EXTERNAL_AUDIT_BLOCKERS_REMAIN"
    assert "PERSIST_POLICY_ACTIVATED_AT_ON_ENTRY_FILL_AND_OUTCOME_ROWS" in (
        audit_burn_down["required_actions_remaining"]
    )
    assert "PERSIST_FUNDING_PNL_ACCRUAL_ON_CLOSED_OUTCOMES" in (
        audit_burn_down["required_actions_remaining"]
    )
    assert "ADD_EXPLICIT_NAMED_ORDER_COUNTERS_TO_PORTFOLIO_STATE" in (
        audit_burn_down["required_actions_remaining"]
    )
    assert audit_burn_down["policy_activated_at"]["missing_count"] == 1
    assert audit_burn_down["funding_pnl"]["unaccounted_count"] == 1
    assert audit_burn_down["funding_pnl"]["read_only_reconstruction_counts_as_gate"] is False
    assert audit_burn_down["funding_pnl"]["historical_closed_outcome_funding_gap_non_blocking"] is False
    assert audit_burn_down["named_order_counters"]["status"] == "MISSING_NAMED_ORDER_COUNTERS"
    assert audit_burn_down["counts_as_additional_pass_gate"] is False
    assert pass_conditions["policy_activation_and_funding_accounting"]["status"] == "NO_GO"
    assert pass_conditions["policy_activation_and_funding_accounting"]["blocker_reasons"] == (
        evidence["blocker_reasons"]
    )
    assert "MISSING_POLICY_ACTIVATED_AT_ON_ENTRY_OR_OUTCOME_ROWS" in policy["policy_evidence_blocker_reasons"]
    assert "FUNDING_PNL_UNACCOUNTED_OR_SOURCE_MISSING" in policy["policy_evidence_blocker_reasons"]


def test_policy_activation_funding_evidence_treats_historical_unreconstructable_gap_as_non_blocking_when_forward_contract_ready() -> None:
    closed_without_source = _trade(
        symbol="AEROUSDT",
        timeframe="1h",
        policy_activated_at="2026-06-20T07:05:29Z",
        funding_pnl_accounting_version=None,
        funding_pnl_accounting_status=None,
        funding_pnl_usd=None,
        funding_pnl_source=None,
        funding_rate=None,
        funding_bps=None,
        expected_funding_bps=None,
        actual_funding_bps=None,
        actual_funding_usd=None,
        hold_time_seconds=3600.0,
    )
    accepted_forward_ready = _paper_intent(
        symbol="BTCUSDT",
        timeframe="1m",
        funding_rate=0.00001,
        funding_bps=0.1,
        funding_interval_seconds=28800.0,
    )
    counters = {field: 0 for field in status_module.NAMED_ORDER_COUNTER_FIELDS}

    statuses = build_statuses(
        ledger={
            "open_positions": [],
            "closed_trades": [closed_without_source],
            "accepted": [accepted_forward_ready],
        },
        portfolio={
            "equity": 10012.5,
            "order_counters": counters,
            "order_counters_source": "unit_test",
        },
        paper_status={"classification": "V2_TRADE_MANAGEMENT_PAPER_PRODUCTION_OK"},
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    policy = statuses["adaptive_capital_policy_status.json"]
    dashboard = statuses["operator_dashboard_payload.json"]
    evidence = policy["policy_activation_funding_evidence_status"]
    pass_conditions = {
        condition["id"]: condition
        for condition in dashboard["pass_condition_status"]["conditions"]
    }

    assert evidence["status"] == "PASSED"
    assert evidence["blocker_reasons"] == []
    assert evidence["funding_pnl_accounted_count"] == 0
    assert evidence["funding_pnl_unaccounted_count"] == 1
    assert evidence["funding_pnl_unaccounted_reconstructable_count"] == 0
    assert evidence["funding_pnl_unaccounted_unreconstructable_count"] == 1
    assert evidence["current_forward_funding_accounting_enforcement_complete"] is True
    assert evidence["historical_closed_outcome_funding_gap_non_blocking"] is True
    assert evidence["closed_outcome_funding_accounting_status"] == (
        "PASSED_CURRENT_FORWARD_CONTRACT_WITH_HISTORICAL_UNRECONSTRUCTABLE_GAP"
    )
    assert evidence["forward_funding_accounting_contract_status"]["status"] == (
        "READY_FORWARD_FUNDING_ACCOUNTING_CONTRACT"
    )
    assert evidence["funding_pnl_unaccounted_sample"][0]["symbol"] == "AEROUSDT"
    assert evidence["funding_pnl_unaccounted_sample"][0]["funding_pnl_reconstructable"] is False
    assert pass_conditions["policy_activation_and_funding_accounting"]["status"] == "PASSED"
    assert "FUNDING_PNL_UNACCOUNTED_OR_SOURCE_MISSING" not in policy["policy_evidence_blocker_reasons"]
    audit_burn_down = dashboard["external_audit_blocker_burn_down"]
    assert "PERSIST_FUNDING_PNL_ACCRUAL_ON_CLOSED_OUTCOMES" not in (
        audit_burn_down["required_actions_remaining"]
    )
    assert audit_burn_down["funding_pnl"]["historical_closed_outcome_funding_gap_non_blocking"] is True


def test_policy_activation_funding_evidence_reports_named_order_counters() -> None:
    counters = {field: 0 for field in status_module.NAMED_ORDER_COUNTER_FIELDS}
    counters.update({
        "paper_accepted_intent_count": 3,
        "paper_accepted_fill_count": 2,
        "paper_economic_fill_count": 2,
        "paper_closed_position_count": 1,
    })

    statuses = build_statuses(
        ledger={
            "open_positions": [],
            "closed_trades": [_trade()],
        },
        portfolio={
            "equity": 10000.0,
            "order_counters": counters,
            "order_counters_source": "v2:paper:ledger + v2:paper:closed_trades",
        },
        paper_status={"classification": "V2_TRADE_MANAGEMENT_PAPER_PRODUCTION_OK"},
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    evidence = statuses["operator_dashboard_payload.json"]["policy_activation_funding_evidence_status"]
    counter_status = evidence["portfolio_order_counter_status"]

    assert evidence["status"] == "PASSED"
    assert counter_status["status"] == "READY"
    assert counter_status["missing_counter_fields"] == []
    assert counter_status["live_order_count"] == 0.0
    assert counter_status["test_order_count"] == 0.0
    assert counter_status["exchange_order_mutation_count"] == 0.0


def test_scan_redis_json_rows_backfills_signal_key_symbol_timeframe() -> None:
    class FakeRedis:
        def scan_iter(self, match: str, count: int = 1000):  # noqa: ARG002
            return iter(["v2:signals:paper:1000BONKUSDT:1m"])

        def get(self, key: str) -> str | None:
            assert key == "v2:signals:paper:1000BONKUSDT:1m"
            return json.dumps({
                "signal_id": "sig_paper_tick",
                "prediction_id": "pred_paper_tick",
                "confidence_calibrated": 0.8,
            })

    rows = status_module._scan_redis_json_rows(FakeRedis(), "v2:signals:paper:*")

    assert rows == [
        {
            "signal_id": "sig_paper_tick",
            "prediction_id": "pred_paper_tick",
            "confidence_calibrated": 0.8,
            "source_redis_key": "v2:signals:paper:1000BONKUSDT:1m",
            "source_redis_symbol": "1000BONKUSDT",
            "source_redis_timeframe": "1m",
            "symbol": "1000BONKUSDT",
            "timeframe": "1m",
        }
    ]


def test_one_thousand_x_explicit_gate_rejects_missing_horizon_and_guarantee_claim() -> None:
    missing_horizon_gate = status_module._one_thousand_x_explicit_classification_gate({
        "classification": "UNSUPPORTED_DEPENDENCY_GATES_NOT_PASSED",
        "horizon_years": 0.0,
        "horizon_days": 1.0,
        "guaranteed_return_claim": False,
    })
    guarantee_claim_gate = status_module._one_thousand_x_explicit_classification_gate({
        "classification": "NOT_FEASIBLE_ON_CURRENT_OBSERVED_TRAJECTORY",
        "horizon_years": 5.0,
        "horizon_days": 1825.0,
        "guaranteed_return_claim": True,
    })

    assert missing_horizon_gate["passed"] is False
    assert missing_horizon_gate["blocker_reasons"] == ["MISSING_EXPLICIT_HORIZON"]
    assert guarantee_claim_gate["passed"] is False
    assert guarantee_claim_gate["blocker_reasons"] == ["GUARANTEED_RETURN_CLAIM"]


def test_build_statuses_adds_dashboard_pnl_history_and_accuracy_matrix() -> None:
    statuses = build_statuses(
        ledger={
            "open_positions": [],
            "closed_trades": [
                _trade(symbol="BTCUSDT", side="flat", action="hold", timeframe="1m", realized_pnl_usd=10.0, closed_at="2026-06-19T23:00:00Z"),
                _trade(symbol="ETHUSDT", side="flat", action="hold", timeframe="5m", realized_pnl_usd=-4.0, closed_at="2026-06-16T00:00:00Z"),
                _trade(symbol="SOLUSDT", side="flat", action="hold", timeframe="15m", realized_pnl_usd=3.0, closed_at="2026-05-25T00:00:00Z"),
                _trade(symbol="ADAUSDT", side="flat", action="hold", timeframe="1h", realized_pnl_usd=99.0, closed_at="2026-05-01T00:00:00Z"),
            ],
        },
        portfolio={"equity": 10009.0},
        paper_status={},
        paper_signals=[
            _paper_signal(symbol="BTCUSDT", timeframe="1m", side="long", action="long", realized_pnl_usd=8.0, signal_id="sig_btc", prediction_id="pred_btc"),
            _paper_signal(symbol="ETHUSDT", timeframe="5m", side="short", action="short", realized_pnl_usd=-2.0, signal_id="sig_eth", prediction_id="pred_eth"),
        ],
        prediction_rows=[
            {"symbol": "XRPUSDT", "timeframe": "4h", "selected_action": "long", "prediction_id": "pred_xrp"},
        ],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    dashboard = statuses["operator_dashboard_payload.json"]
    capital = statuses["capital_productivity_runtime_status.json"]
    compounding = statuses["compounding_equity_status.json"]
    pnl_history = dashboard["pnl_history_status"]
    accuracy = dashboard["signal_prediction_accuracy_status"]
    dashboard_web = dashboard["dashboard_web_status"]
    thousand_x = dashboard["one_thousand_x_feasibility_status"]
    counterfactual = statuses["counterfactual_capital_sweep_status.json"]
    prediction_probe = counterfactual["prediction_counterfactual_probe"]

    windows = {row["window"]: row for row in pnl_history["windows"]}
    assert pnl_history["status"] == "READY"
    assert windows["1d"]["realized_pnl_usd"] == 10.0
    assert windows["7d"]["realized_pnl_usd"] == 6.0
    assert windows["30d"]["realized_pnl_usd"] == 9.0
    assert capital["pnl_history"]["windows"] == pnl_history["windows"]
    assert compounding["capital_productivity_status"] == capital["status"]
    assert compounding["capital_productivity_blocker_reasons"] == capital["capital_productivity_blocker_reasons"]
    assert compounding["capital_productivity_progress"] == capital["capital_productivity_progress"]
    assert compounding["pnl_history"]["windows"] == pnl_history["windows"]
    assert compounding["pnl_history_status"]["windows"] == pnl_history["windows"]
    assert thousand_x["pnl_history_status"]["windows"] == pnl_history["windows"]
    feasibility_windows = {
        row["window"]: row
        for row in thousand_x["observed_growth_evidence"]["window_evidence"]
    }
    assert thousand_x["classification"] == "UNSUPPORTED_DEPENDENCY_GATES_NOT_PASSED"
    assert thousand_x["horizon_days"] == 1825.0
    assert thousand_x["required_cagr"] == round(1000.0 ** (1.0 / 5.0) - 1.0, 12)
    assert thousand_x["observed_daily_log_return"] is not None
    assert thousand_x["observed_cagr"] is not None
    assert thousand_x["observed_growth_evidence"]["projection_is_guarantee"] is False
    assert feasibility_windows["1d"]["realized_pnl_usd"] == 10.0
    assert feasibility_windows["1d"]["required_window_pnl_usd"] > 0.0
    assert feasibility_windows["1d"]["window_pnl_shortfall_vs_required_usd"] > 0.0
    assert feasibility_windows["1d"]["status"] == "BELOW_REQUIRED_TRAJECTORY"

    cells = {
        (row["symbol"], row["timeframe"]): row
        for row in accuracy["by_symbol_timeframe"]
    }
    assert accuracy["status"] == "READY"
    assert accuracy["evaluated_row_count"] == 2
    assert accuracy["correct_count"] == 1
    assert accuracy["incorrect_count"] == 1
    assert accuracy["overall_accuracy"] == 0.5
    assert accuracy["timeframes"] == ["1m", "5m", "15m", "1h", "4h"]
    assert accuracy["timeframe_count"] == 5
    assert accuracy["symbol_universe_count"] == 5
    assert accuracy["required_symbol_timeframe_cell_count"] == 25
    assert accuracy["symbol_timeframe_cell_count"] == 25
    assert accuracy["evaluated_symbol_timeframe_cell_count"] == 2
    assert accuracy["required_symbol_timeframe_cells_without_evaluated_outcomes_count"] == 23
    assert accuracy["missing_evaluated_symbol_timeframe_cell_count"] == 23
    timeframes = {
        row["timeframe"]: row
        for row in accuracy["by_timeframe"]
    }
    symbols = {
        row["symbol"]: row
        for row in accuracy["by_symbol"]
    }
    assert timeframes["1m"]["evaluated_count"] == 1
    assert timeframes["1m"]["accuracy"] == 1.0
    assert timeframes["5m"]["evaluated_count"] == 1
    assert timeframes["5m"]["accuracy"] == 0.0
    assert timeframes["4h"]["prediction_count"] == 1
    assert timeframes["4h"]["status"] == "NO_EVALUATED_OUTCOMES"
    assert symbols["BTCUSDT"]["symbol_timeframe_cell_count"] == 5
    assert symbols["BTCUSDT"]["evaluated_symbol_timeframe_cell_count"] == 1
    assert symbols["BTCUSDT"]["accuracy"] == 1.0
    assert symbols["ETHUSDT"]["evaluated_count"] == 1
    assert symbols["ETHUSDT"]["accuracy"] == 0.0
    assert symbols["XRPUSDT"]["prediction_count"] == 1
    assert symbols["XRPUSDT"]["status"] == "NO_EVALUATED_OUTCOMES"
    assert cells[("BTCUSDT", "1m")]["accuracy"] == 1.0
    assert cells[("ETHUSDT", "5m")]["accuracy"] == 0.0
    assert cells[("XRPUSDT", "4h")]["prediction_count"] == 1
    assert cells[("XRPUSDT", "4h")]["status"] == "NO_EVALUATED_OUTCOMES"
    assert capital["signal_prediction_accuracy_status"]["overall_accuracy"] == 0.5
    assert compounding["signal_prediction_accuracy_status"]["overall_accuracy"] == 0.5
    assert compounding["signal_prediction_accuracy_status"]["by_symbol_timeframe"] == accuracy["by_symbol_timeframe"]
    assert dashboard_web["status"] == "READY"
    assert dashboard_web["all_required_pnl_windows_published"] is True
    assert dashboard_web["published_pnl_windows"] == ["1d", "7d", "30d"]
    assert dashboard_web["all_symbol_timeframe_accuracy_cells_published"] is True
    assert dashboard_web["required_accuracy_timeframes"] == ["1m", "5m", "15m", "1h", "4h"]
    assert dashboard_web["required_symbol_timeframe_cell_count"] == 25
    assert dashboard_web["published_symbol_timeframe_cell_count"] == 25
    assert dashboard_web["evaluated_symbol_timeframe_cell_count"] == 2
    assert dashboard_web["missing_evaluated_symbol_timeframe_cell_count"] == 23
    assert dashboard_web["web_surface_count"] == 16
    assert dashboard_web["all_tracked_surfaces_show_capital_productivity_status"] is True
    assert dashboard_web["all_tracked_surfaces_show_pnl_history_windows"] is True
    assert dashboard_web["all_tracked_surfaces_show_signal_prediction_accuracy"] is True
    assert dashboard_web["all_tracked_surfaces_show_all_symbol_timeframe_accuracy_matrix"] is True
    assert dashboard_web["row_level_accuracy_pnl_surface_count"] == 3
    surfaces = {row["surface_id"]: row for row in dashboard_web["surfaces"]}
    assert set(surfaces) == {
        "dashboard",
        "signals",
        "ai_predictions",
        "trainer_prediction_monitor",
        "trainer_admin",
        "signal_explainability",
        "history",
        "positions",
        "paper_trading",
        "executions",
        "trade_terminal",
        "binance_terminal",
        "mission_control",
        "operator_proof_dashboard",
        "market_intelligence",
        "technical_analysis",
    }
    assert surfaces["dashboard"]["shows_capital_productivity_status"] is True
    assert surfaces["dashboard"]["shows_pnl_history_windows"] is True
    assert all(row["shows_pnl_history_windows"] is True for row in surfaces.values())
    assert all(row["shows_signal_prediction_accuracy"] is True for row in surfaces.values())
    assert all(row["shows_all_symbol_timeframe_accuracy_matrix"] is True for row in surfaces.values())
    assert surfaces["signals"]["row_level_accuracy_pnl"] is True
    assert surfaces["ai_predictions"]["row_level_accuracy_pnl"] is True
    assert surfaces["trainer_prediction_monitor"]["row_level_accuracy_pnl"] is True
    assert compounding["dashboard_web_status"] == dashboard_web
    assert capital["prediction_row_count"] == 1
    assert counterfactual["prediction_row_count"] == 1
    assert prediction_probe["prediction_row_count"] == 1
    assert prediction_probe["probe_participates_in_counterfactual_pass_gate"] is False
    assert prediction_probe["a_grade_readiness"]["source_kind_counts"] == {"prediction": 1}
    assert prediction_probe["a_grade_readiness"]["source_kind_readiness"]["prediction"]["row_count"] == 1
    assert prediction_probe["a_grade_readiness"]["source_kind_readiness"]["prediction"]["not_a_grade_reason_counts"] == {
        "MISSING_AFTER_COST_EDGE": 1,
        "MISSING_CONFIDENCE": 1,
    }


def test_write_statuses_creates_required_outputs(tmp_path) -> None:
    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": [_trade()]},
        portfolio={"equity": 10012.5},
        paper_status={},
        horizon_years=3.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    write_statuses(statuses, tmp_path)

    for filename in STATUS_FILENAMES:
        assert (tmp_path / filename).exists()
        json.loads((tmp_path / filename).read_text())
    assert (tmp_path / "GO_NO_GO.md").exists()
    go_no_go = (tmp_path / "GO_NO_GO.md").read_text()
    assert "Overall status: **NO_GO**" in go_no_go
    assert "## Capital Productivity" in go_no_go
    assert "Closed post-allocator outcomes" in go_no_go
    assert "Closed outcome progress" in go_no_go
    assert "Break-even realized PnL gap" in go_no_go
    assert "## PnL History" in go_no_go
    assert "## Signal/Prediction Accuracy" in go_no_go
    assert "## Counterfactual Sweep" in go_no_go
    assert "Prediction rows probed" in go_no_go
    assert "Market cost requirement" in go_no_go
    assert "Market cost evidence coverage" in go_no_go
    assert "Near-A-grade market cost evidence coverage" in go_no_go
    assert "Counterfactual evidence acquisition" in go_no_go
    assert "Strict A-grade acquisition burn-down" in go_no_go
    assert "External audit blocker burn-down" in go_no_go
    assert "Market-cost-ready near-A-grade candidates if confidence improves" in go_no_go
    assert "Prediction probe is readiness-only" in go_no_go
    assert "## Evidence To GO" in go_no_go
    assert "Closed outcomes needed" in go_no_go
    assert "A-grade replay progress" in go_no_go
    assert "Profit factor burn-down" in go_no_go
    assert "## Adaptive Field Selection" in go_no_go
    assert "Selection attribution status" in go_no_go
    assert "Runtime leverage model-input coverage" in go_no_go
    assert "Current pre-submit field coverage" in go_no_go
    assert "Hedge-budget selection reason counts" in go_no_go
    assert "Current pre-submit hedge-budget reason counts" in go_no_go
    assert "## Allocator Calibration" in go_no_go
    assert "Current intent observation" in go_no_go
    assert "Forward funding accounting contract" in go_no_go
    assert "## Compounding Evidence" in go_no_go
    assert "Explicit horizon classification" in go_no_go
    assert "No guaranteed-return claim" in go_no_go


def test_build_statuses_excludes_legacy_rows_from_post_capital_accounting_denominator() -> None:
    legacy = _trade(adaptive_capital_policy_version=None, stop_distance_bps=None)
    versioned = _trade(symbol="ETHUSDT", realized_pnl_usd=0.0)

    statuses = build_statuses(
        ledger={
            "open_positions": [versioned],
            "closed_trades": [legacy],
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    accounting = statuses["margin_notional_leverage_accounting_status.json"]

    assert accounting["runtime_row_count"] == 2
    assert accounting["historical_or_unversioned_runtime_row_count"] == 1
    assert accounting["new_trade_row_count"] == 1
    assert accounting["rows_with_all_mandatory_fields"] == 1
    assert accounting["mandatory_field_coverage"] == 1.0
    assert accounting["leverage_margin_consistency_coverage"] == 1.0


def test_build_statuses_fails_accounting_when_margin_leverage_ratio_is_inconsistent() -> None:
    inconsistent = _trade(
        symbol="BADUSDT",
        gross_notional_usd=100.0,
        allocated_margin_usd=200.0,
        recommended_leverage=1.0,
        effective_leverage=1.0,
    )

    statuses = build_statuses(
        ledger={
            "open_positions": [inconsistent],
            "closed_trades": [],
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    accounting = statuses["margin_notional_leverage_accounting_status.json"]
    dashboard = statuses["operator_dashboard_payload.json"]
    pass_conditions = {
        condition["id"]: condition
        for condition in dashboard["pass_condition_status"]["conditions"]
    }

    assert accounting["status"] == "NO_GO_LEVERAGE_MARGIN_ACCOUNTING_INCONSISTENT"
    assert accounting["blocker_reasons"] == ["NO_GO_LEVERAGE_MARGIN_ACCOUNTING_INCONSISTENT"]
    assert accounting["accounting_enforcement_status"] == "NO_GO_LEVERAGE_MARGIN_ACCOUNTING_INCONSISTENT"
    assert accounting["mandatory_field_coverage"] == 1.0
    assert accounting["runtime_leverage_margin_consistency_status"] == "NO_GO_LEVERAGE_MARGIN_ACCOUNTING_INCONSISTENT"
    assert accounting["leverage_margin_consistency_status"] == "NO_GO_LEVERAGE_MARGIN_ACCOUNTING_INCONSISTENT"
    assert accounting["runtime_accounting_evidence"]["status"] == "NO_GO_LEVERAGE_MARGIN_ACCOUNTING_INCONSISTENT"
    assert accounting["runtime_accounting_evidence"]["complete"] is False
    assert accounting["leverage_margin_consistency_row_count"] == 1
    assert accounting["leverage_margin_consistent_row_count"] == 0
    assert accounting["leverage_margin_inconsistent_count"] == 1
    assert accounting["leverage_margin_consistency_coverage"] == 0.0
    assert accounting["leverage_margin_inconsistent_sample"] == [
        {
            "symbol": "BADUSDT",
            "timeframe": None,
            "side": "long",
            "gross_notional_usd": 100.0,
            "allocated_margin_usd": 200.0,
            "effective_leverage": 1.0,
            "gross_notional_to_allocated_margin_ratio": 0.5,
            "absolute_error": 0.5,
        }
    ]
    assert dashboard["operator_go_readiness"]["overall_status"] == "NO_GO"
    assert "margin_notional_leverage_accounting_status" in dashboard["remaining_blockers"]
    assert pass_conditions["mandatory_per_trade_accounting"]["status"] == "NO_GO"
    assert pass_conditions["mandatory_per_trade_accounting"]["blocker_reasons"] == [
        "NO_GO_LEVERAGE_MARGIN_ACCOUNTING_INCONSISTENT"
    ]
    assert pass_conditions["mandatory_per_trade_accounting"]["evidence"]["leverage_margin_inconsistent_count"] == 1


def test_build_statuses_allows_historical_accounting_gap_when_current_pre_submit_is_consistent() -> None:
    historical_inconsistent = _trade(
        symbol="OLDUSDT",
        gross_notional_usd=100.0,
        allocated_margin_usd=200.0,
        recommended_leverage=1.0,
        effective_leverage=1.0,
    )
    current_intent = _paper_intent(
        symbol="NOWUSDT",
        recommended_leverage=1.0,
        effective_leverage=1.0,
        gross_notional_usd=733.79060393,
        allocated_margin_usd=733.79060393,
    )

    statuses = build_statuses(
        ledger={
            "open_positions": [historical_inconsistent],
            "closed_trades": [],
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_intents=[current_intent],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    accounting = statuses["margin_notional_leverage_accounting_status.json"]
    dashboard = statuses["operator_dashboard_payload.json"]
    pass_conditions = {
        condition["id"]: condition
        for condition in dashboard["pass_condition_status"]["conditions"]
    }

    assert accounting["status"] == "PASSED"
    assert accounting["blocker_reasons"] == []
    assert accounting["accounting_enforcement_status"] == "PASSED_CURRENT_PRE_SUBMIT_ENFORCEMENT"
    assert accounting["runtime_accounting_complete"] is False
    assert accounting["current_accounting_enforcement_complete"] is True
    assert accounting["historical_runtime_leverage_margin_gap_non_blocking"] is True
    assert accounting["runtime_leverage_margin_consistency_status"] == "NO_GO_LEVERAGE_MARGIN_ACCOUNTING_INCONSISTENT"
    assert accounting["leverage_margin_consistency_status"] == "PASSED"
    assert accounting["runtime_accounting_evidence"]["status"] == "NO_GO_LEVERAGE_MARGIN_ACCOUNTING_INCONSISTENT"
    assert accounting["runtime_accounting_evidence"]["complete"] is False
    assert accounting["leverage_margin_inconsistent_count"] == 1
    assert accounting["current_pre_submit_accounting_evidence"]["row_count"] == 1
    assert accounting["current_pre_submit_accounting_evidence"]["status"] == "PASSED"
    assert accounting["current_pre_submit_accounting_evidence"]["leverage_margin_consistency_status"] == "PASSED"
    assert accounting["current_pre_submit_accounting_evidence"]["complete"] is True
    assert accounting["current_pre_submit_accounting_evidence"]["leverage_margin_inconsistent_count"] == 0
    assert pass_conditions["mandatory_per_trade_accounting"]["status"] == "PASSED"
    assert pass_conditions["mandatory_per_trade_accounting"]["evidence"][
        "historical_runtime_leverage_margin_gap_non_blocking"
    ] is True


def test_rare_event_stress_uses_current_exposure_not_closed_historical_allocations() -> None:
    oversized_closed = _trade(
        symbol="OLDUSDT",
        gross_notional_usd=50000.0,
        allocated_margin_usd=25000.0,
        recommended_leverage=2.0,
        effective_leverage=2.0,
        realized_pnl_usd=1.0,
    )
    current_open = _trade(
        symbol="NOWUSDT",
        gross_notional_usd=100.0,
        allocated_margin_usd=100.0,
        recommended_leverage=1.0,
        effective_leverage=1.0,
        realized_pnl_usd=0.0,
    )

    statuses = build_statuses(
        ledger={
            "open_positions": [current_open],
            "closed_trades": [oversized_closed],
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    rare_event = statuses["rare_event_capital_stress_status.json"]

    assert rare_event["status"] == "PASSED"
    assert rare_event["runtime_allocation_row_count"] == 1
    assert rare_event["runtime_stressed_row_count"] == 1
    assert rare_event["scenario_failures"] == []
    assert rare_event["scenario_total_loss_usd"]["liquidation_cascade"] == 10.0
    assert rare_event["stressed_allocation_sample"][0]["symbol"] == "NOWUSDT"


def test_rare_event_stress_passes_zero_current_runtime_exposure_without_counterfactual_configs() -> None:
    closed_only = _trade(
        symbol="OLDUSDT",
        gross_notional_usd=50000.0,
        allocated_margin_usd=25000.0,
        recommended_leverage=2.0,
        effective_leverage=2.0,
        realized_pnl_usd=1.0,
    )

    statuses = build_statuses(
        ledger={
            "open_positions": [],
            "closed_trades": [closed_only],
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    rare_event = statuses["rare_event_capital_stress_status.json"]
    dashboard = statuses["operator_dashboard_payload.json"]
    pass_conditions = {
        condition["id"]: condition
        for condition in dashboard["pass_condition_status"]["conditions"]
    }

    assert rare_event["status"] == "PASSED"
    assert rare_event["stress_source"] == "runtime_no_current_exposure"
    assert rare_event["no_current_runtime_exposure"] is True
    assert rare_event["counterfactual_best_configuration_count"] == 0
    assert rare_event["counterfactual_stress_status"] == "NO_GO_RARE_EVENT_CAPITAL_STRESS_NOT_RUN"
    assert rare_event["runtime_allocation_row_count"] == 0
    assert rare_event["runtime_stressed_row_count"] == 0
    assert rare_event["stressed_allocation_sample_count"] == 0
    assert rare_event["scenario_failures"] == []
    assert rare_event["completed_scenarios"] == rare_event["required_scenarios"]
    assert set(rare_event["scenario_total_loss_usd"].values()) == {0.0}
    assert pass_conditions["rare_event_capital_stress"]["status"] == "PASSED"


def test_build_statuses_allows_historical_accounting_gap_with_durable_pre_submit_accounting() -> None:
    historical_inconsistent = _trade(
        symbol="OLDUSDT",
        gross_notional_usd=100.0,
        allocated_margin_usd=200.0,
        recommended_leverage=1.0,
        effective_leverage=1.0,
    )
    durable_accepted = _paper_intent(
        symbol="DURABLEUSDT",
        recommended_leverage=1.0,
        effective_leverage=1.0,
        gross_notional_usd=733.79060393,
        allocated_margin_usd=733.79060393,
    )

    statuses = build_statuses(
        ledger={
            "open_positions": [historical_inconsistent],
            "closed_trades": [],
            "accepted": [durable_accepted],
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_intents=[],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    accounting = statuses["margin_notional_leverage_accounting_status.json"]
    dashboard = statuses["operator_dashboard_payload.json"]
    pass_conditions = {
        condition["id"]: condition
        for condition in dashboard["pass_condition_status"]["conditions"]
    }

    assert accounting["status"] == "PASSED"
    assert accounting["accounting_enforcement_status"] == "PASSED_CURRENT_PRE_SUBMIT_ENFORCEMENT"
    assert accounting["runtime_accounting_complete"] is False
    assert accounting["current_accounting_enforcement_complete"] is True
    assert accounting["current_accounting_enforcement_source"] == "v2:paper:ledger.accepted"
    assert accounting["leverage_margin_consistency_status"] == "PASSED"
    assert accounting["historical_runtime_leverage_margin_gap_non_blocking"] is True
    assert accounting["historical_runtime_accounting_gap_non_blocking"] is True
    assert accounting["current_pre_submit_accounting_evidence"]["row_count"] == 1
    assert accounting["current_pre_submit_accounting_evidence"]["complete"] is True
    assert pass_conditions["mandatory_per_trade_accounting"]["status"] == "PASSED"


def test_build_statuses_allows_historical_mandatory_field_gap_with_durable_pre_submit_accounting() -> None:
    historical_incomplete = _trade(
        symbol="OLDFIELDUSDT",
        recommended_margin_mode=None,
        stop_distance_bps=None,
        liquidation_buffer_bps=None,
        expected_fees_usd=None,
        expected_funding_usd=None,
        expected_net_pnl_usd=None,
        expected_shortfall_usd=None,
        hedge_budget_usd=None,
        capital_allocation_reason=None,
    )
    durable_accepted = _paper_intent(
        symbol="DURABLEFIELDUSDT",
        recommended_leverage=1.0,
        effective_leverage=1.0,
        gross_notional_usd=733.79060393,
        allocated_margin_usd=733.79060393,
    )

    statuses = build_statuses(
        ledger={
            "open_positions": [historical_incomplete],
            "closed_trades": [],
            "accepted": [durable_accepted],
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_intents=[],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    accounting = statuses["margin_notional_leverage_accounting_status.json"]
    dashboard = statuses["operator_dashboard_payload.json"]
    pass_conditions = {
        condition["id"]: condition
        for condition in dashboard["pass_condition_status"]["conditions"]
    }

    assert accounting["status"] == "PASSED"
    assert accounting["mandatory_field_coverage"] < 1.0
    assert accounting["runtime_accounting_complete"] is False
    assert accounting["current_accounting_enforcement_complete"] is True
    assert accounting["current_accounting_enforcement_source"] == "v2:paper:ledger.accepted"
    assert accounting["historical_runtime_mandatory_field_gap_non_blocking"] is True
    assert accounting["historical_runtime_accounting_gap_non_blocking"] is True
    assert accounting["current_pre_submit_accounting_evidence"]["row_count"] == 1
    assert accounting["current_pre_submit_accounting_evidence"]["complete"] is True
    assert pass_conditions["mandatory_per_trade_accounting"]["status"] == "PASSED"
    assert pass_conditions["mandatory_per_trade_accounting"]["evidence"][
        "historical_runtime_mandatory_field_gap_non_blocking"
    ] is True


def test_closed_outcome_reconciles_adaptive_policy_from_safe_accepted_fill() -> None:
    accepted = _paper_intent(
        symbol="RECONUSDT",
        timeframe="15m",
        side="short",
        action="short",
        signal_id="fill_recon_1",
        source_signal_id="fill_recon_1",
        fill_id="fill_recon_1",
        ledger_row_id="fill_recon_1",
        prediction_id="pred_recon_1",
        source_prediction_id="pred_recon_1",
        generated_utc="2026-06-20T00:00:10Z",
        original_fill_utc="2026-06-20T00:00:10Z",
        policy_activated_at="2026-06-20T00:00:10Z",
        expected_funding_bps=1.5,
        expected_funding_bps_source="v2:features:latest:RECONUSDT:15m.funding_rate",
        funding_rate=0.00015,
        funding_interval_seconds=28800.0,
    )
    closed = _trade(
        symbol="RECONUSDT",
        timeframe="15m",
        side="short",
        adaptive_capital_policy_version=None,
        entry_signal_id="fill_recon_1",
        entry_prediction_id="pred_recon_1",
        source_fill_ids=["fill_recon_1"],
        paper_only=True,
        places_real_order=False,
        exit_price_utc="2026-06-20T00:15:00Z",
        policy_activated_at=None,
        expected_funding_bps=None,
        funding_rate=None,
        funding_bps=None,
        funding_interval_seconds=None,
        funding_pnl_accounting_version=None,
        funding_pnl_accounting_status=None,
        funding_pnl_usd=None,
        funding_pnl_source=None,
        stop_distance_bps=None,
        expected_shortfall_usd=None,
        hedge_budget_usd=None,
    )

    statuses = build_statuses(
        ledger={
            "open_positions": [],
            "closed_trades": [closed],
            "accepted": [accepted],
        },
        portfolio={"equity": 10012.5},
        paper_status={},
        horizon_years=5.0,
        generated_utc="2026-06-20T00:20:00Z",
    )

    accounting = statuses["margin_notional_leverage_accounting_status.json"]
    capital = statuses["capital_productivity_runtime_status.json"]
    policy = statuses["adaptive_capital_policy_status.json"]
    compounding = statuses["compounding_equity_status.json"]
    reconciliation = capital["accepted_fill_policy_reconciliation"]
    policy_funding = policy["policy_activation_funding_evidence_status"]

    assert policy["post_allocator_closed_outcome_count"] == 1
    assert accounting["post_capital_policy_closed_row_count"] == 1
    assert accounting["post_capital_policy_closed_rows_with_all_mandatory_fields"] == 1
    assert accounting["mandatory_field_coverage"] == 1.0
    assert capital["post_allocator_closed_outcome_count"] == 1
    assert capital["return_on_deployed_margin"] == 0.05
    assert reconciliation["candidate_closed_match_count"] == 1
    assert reconciliation["reconciled_closed_outcome_count"] == 1
    assert reconciliation["complete_reconciled_closed_outcome_count"] == 1
    assert reconciliation["rejected_reason_counts"] == {}
    assert reconciliation["sample"][0]["accepted_fill_policy_reconciliation_ids"] == [
        "fill_recon_1",
        "pred_recon_1",
    ]
    assert set(reconciliation["sample"][0]["filled_mandatory_fields"]) == {
        "hedge_budget_usd",
        "expected_shortfall_usd",
        "stop_distance_bps",
    }
    assert set(reconciliation["sample"][0]["filled_policy_funding_metadata_fields"]) == {
        "expected_funding_bps",
        "expected_funding_bps_source",
        "funding_interval_seconds",
        "funding_rate",
        "policy_activated_at",
    }
    assert reconciliation["filled_policy_funding_metadata_counts"] == {
        "expected_funding_bps": 1,
        "expected_funding_bps_source": 1,
        "funding_interval_seconds": 1,
        "funding_rate": 1,
        "policy_activated_at": 1,
    }
    assert reconciliation["ambiguous_policy_funding_metadata_counts"] == {}
    assert policy_funding["policy_activation_audit_row_count"] == 2
    assert policy_funding["policy_activated_at_present_count"] == 2
    assert policy_funding["funding_pnl_accounted_count"] == 0
    assert policy_funding["funding_pnl_unaccounted_count"] == 1
    assert policy_funding["funding_pnl_accounting_version_counts"] == {"__missing__": 1}
    assert policy_funding["funding_pnl_accounting_status_counts"] == {"__missing__": 1}
    reconstruction = policy_funding["funding_pnl_reconstruction_status"]
    assert reconstruction["status"] == "READY_RECONSTRUCTABLE_FUNDING_PNL_DIAGNOSTIC"
    assert reconstruction["reconstructable_closed_outcome_count"] == 1
    assert reconstruction["unreconstructable_closed_outcome_count"] == 0
    assert reconstruction["reconstructed_funding_pnl_total_usd"] == 0.00231771
    assert reconstruction["reconstructed_funding_pnl_nonzero_count"] == 1
    assert reconstruction["counts_as_accounted_funding_pnl"] is False
    assert reconstruction["funding_accounting_version"] == "PAPER_FUNDING_ACCRUAL_V1"
    assert reconstruction["reconstruction_sample"][0]["funding_pnl_reconstructable"] is True
    assert reconstruction["reconstruction_sample"][0]["reconstructed_funding_pnl_usd"] == 0.00231771
    forward_contract = policy_funding["forward_funding_accounting_contract_status"]
    assert forward_contract["status"] == "READY_FORWARD_FUNDING_ACCOUNTING_CONTRACT"
    assert forward_contract["forward_row_count"] == 1
    assert forward_contract["ready_forward_row_count"] == 1
    assert forward_contract["funding_rate_or_bps_ready_count"] == 1
    assert forward_contract["funding_accounting_version"] == "PAPER_FUNDING_ACCRUAL_V1"
    assert "funding_pnl_accounting_version" in forward_contract["persisted_close_fields_required"]
    assert "funding_pnl_accounting_status" in forward_contract["persisted_close_fields_required"]
    assert "funding_pnl_formula" in forward_contract["persisted_close_fields_required"]
    assert "funding_pnl_side_sign" in forward_contract["persisted_close_fields_required"]
    assert forward_contract["missing_reason_counts"] == {}
    assert forward_contract["counts_as_closed_outcome_funding_gate"] is False
    assert compounding["accepted_fill_policy_reconciliation"]["complete_reconciled_closed_outcome_count"] == 1


def test_closed_outcome_reconciliation_fails_closed_when_accepted_fill_is_after_close() -> None:
    accepted = _paper_intent(
        symbol="FUTUREUSDT",
        signal_id="future_fill_1",
        source_signal_id="future_fill_1",
        fill_id="future_fill_1",
        ledger_row_id="future_fill_1",
        generated_utc="2026-06-20T00:30:00Z",
        original_fill_utc="2026-06-20T00:30:00Z",
    )
    closed = _trade(
        symbol="FUTUREUSDT",
        adaptive_capital_policy_version=None,
        entry_signal_id="future_fill_1",
        source_fill_ids=["future_fill_1"],
        paper_only=True,
        places_real_order=False,
        exit_price_utc="2026-06-20T00:10:00Z",
        expected_shortfall_usd=None,
    )

    statuses = build_statuses(
        ledger={
            "open_positions": [],
            "closed_trades": [closed],
            "accepted": [accepted],
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        horizon_years=5.0,
        generated_utc="2026-06-20T00:40:00Z",
    )

    accounting = statuses["margin_notional_leverage_accounting_status.json"]
    capital = statuses["capital_productivity_runtime_status.json"]
    policy = statuses["adaptive_capital_policy_status.json"]
    reconciliation = capital["accepted_fill_policy_reconciliation"]

    assert policy["post_allocator_closed_outcome_count"] == 0
    assert accounting["post_capital_policy_closed_row_count"] == 0
    assert accounting["new_trade_row_count"] == 0
    assert reconciliation["candidate_closed_match_count"] == 1
    assert reconciliation["reconciled_closed_outcome_count"] == 0
    assert reconciliation["complete_reconciled_closed_outcome_count"] == 0
    assert reconciliation["rejected_reason_counts"] == {"ACCEPTED_FILL_AFTER_CLOSE": 1}


def test_policy_evidence_progress_reports_open_ready_rows_and_mandatory_gaps() -> None:
    complete_closed = _trade(symbol="BTCUSDT", side="long", realized_pnl_usd=3.0)
    incomplete_closed = _trade(
        symbol="ETHUSDT",
        side="short",
        realized_pnl_usd=-1.0,
        expected_shortfall_usd=None,
    )
    open_ready = _trade(symbol="SOLUSDT", side="short", realized_pnl_usd=0.0)
    unversioned_complete = _trade(
        symbol="ADAUSDT",
        adaptive_capital_policy_version=None,
        realized_pnl_usd=2.0,
    )

    statuses = build_statuses(
        ledger={
            "open_positions": [open_ready],
            "closed_trades": [complete_closed, incomplete_closed, unversioned_complete],
        },
        portfolio={"equity": 10004.0},
        paper_status={},
        paper_signals=[
            _paper_signal(
                symbol="DOGEUSDT",
                timeframe="1m",
                confidence_calibrated=0.70,
                expected_move_after_cost_bps=18.0,
                signal_id="sig_doge",
                prediction_id="pred_doge",
                realized_pnl_usd=None,
            ),
            _paper_signal(
                symbol="XRPUSDT",
                timeframe="5m",
                confidence_calibrated=0.62,
                expected_move_after_cost_bps=12.0,
                signal_id="sig_xrp",
                prediction_id="pred_xrp",
                realized_pnl_usd=None,
            ),
        ],
        prediction_rows=[
            _paper_signal(
                source_redis_key="v2:prediction:ETHUSDT:15m",
                symbol="ETHUSDT",
                timeframe="15m",
                confidence_calibrated=0.68,
                expected_move_after_cost_bps=20.0,
                signal_id=None,
                prediction_id="pred_eth",
                realized_pnl_usd=None,
            ),
        ],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    accounting = statuses["margin_notional_leverage_accounting_status.json"]
    capital = statuses["capital_productivity_runtime_status.json"]
    policy = statuses["adaptive_capital_policy_status.json"]
    dashboard = statuses["operator_dashboard_payload.json"]
    progress = policy["policy_evidence_progress"]
    capital_progress = capital["capital_productivity_progress"]
    gap = policy["closed_outcome_evidence_gap_analysis"]
    symbol_opportunity = policy["symbol_diversity_opportunity_analysis"]
    readiness = dashboard["operator_go_readiness"]

    assert policy["post_allocator_closed_outcome_count"] == 1
    assert accounting["post_capital_policy_closed_row_count"] == 2
    assert accounting["post_capital_policy_closed_rows_with_all_mandatory_fields"] == 1
    assert accounting["post_capital_policy_closed_rows_missing_mandatory_fields"] == 1
    assert accounting["post_capital_policy_closed_missing_mandatory_field_counts"] == {
        "expected_shortfall_usd": 1,
    }
    assert accounting["post_capital_policy_closed_missing_mandatory_sample"] == [
        {
            "symbol": "ETHUSDT",
            "timeframe": None,
            "side": "short",
            "adaptive_capital_policy_version": ADAPTIVE_CAPITAL_POLICY_VERSION,
            "paper_exit_policy_version": P0_POLICY_VERSION,
            "missing_mandatory_fields": ["expected_shortfall_usd"],
        }
    ]
    assert accounting["post_capital_policy_open_row_count"] == 1
    assert accounting["post_capital_policy_open_rows_with_all_mandatory_fields"] == 1
    assert accounting["unversioned_runtime_row_count"] == 1
    assert accounting["unversioned_runtime_rows_with_all_mandatory_fields"] == 1

    assert progress["current_closed_outcome_count"] == 1
    assert progress["closed_outcome_deficit_to_minimum"] == 299
    assert policy["closed_outcome_deficit_to_minimum"] == 299
    assert policy["closed_outcome_progress_pct"] == 0.00333333
    assert progress["long_closed_outcome_count"] == 1
    assert progress["short_closed_outcome_count"] == 0
    assert progress["both_long_short_evidence"] is False
    assert progress["missing_directional_sides"] == ["short"]
    assert progress["minimum_required_per_directional_side"] == 1
    assert progress["symbol_count"] == 1
    assert progress["minimum_required_symbol_count"] == 30
    assert progress["minimum_required_symbols"] == 30
    assert progress["symbol_diversity_deficit"] == 29
    assert policy["symbol_diversity_progress_pct"] == 0.03333333
    assert progress["post_capital_policy_closed_row_count"] == 2
    assert progress["post_capital_policy_closed_rows_missing_mandatory_fields"] == 1
    assert progress["open_post_capital_policy_row_count"] == 1
    assert progress["open_positions_ready_to_become_closed_outcomes"] == 1
    assert progress["projected_closed_outcome_count_after_current_open_positions_close"] == 2
    assert progress["projected_closed_outcome_deficit_after_current_open_positions_close"] == 298
    assert policy["projected_closed_outcome_count_after_current_open_positions_close"] == 2
    assert policy["projected_closed_outcome_deficit_after_current_open_positions_close"] == 298
    assert progress["unversioned_runtime_row_count"] == 1
    assert progress["unversioned_runtime_rows_with_all_mandatory_fields"] == 1
    assert progress["strict_policy_version_required"] is True
    assert gap["raw_closed_trade_count"] == 3
    assert gap["post_p0_closed_trade_count"] == 3
    assert gap["non_p0_closed_trade_count"] == 0
    assert gap["post_capital_policy_closed_row_count"] == 2
    assert gap["complete_post_capital_policy_closed_outcome_count"] == 1
    assert gap["post_capital_policy_closed_missing_mandatory_count"] == 1
    assert gap["post_capital_policy_closed_missing_mandatory_field_counts"] == {
        "expected_shortfall_usd": 1,
    }
    assert gap["unversioned_post_p0_closed_count"] == 1
    assert gap["unversioned_post_p0_closed_with_all_mandatory_fields_count"] == 1
    assert gap["unversioned_post_p0_closed_with_all_mandatory_fields_sample"][0] == {
        "symbol": "ADAUSDT",
        "timeframe": None,
        "side": "long",
        "close_id": None,
        "entry_signal_id": None,
        "entry_prediction_id": None,
        "adaptive_capital_policy_version": None,
        "paper_exit_policy_version": P0_POLICY_VERSION,
        "missing_mandatory_fields": [],
        "realized_pnl_usd": 2.0,
        "allocated_margin_usd": 250.0,
    }
    assert gap["potential_complete_closed_outcomes_if_unversioned_rows_gain_safe_policy_lineage"] == 2
    assert gap["additional_complete_closed_outcomes_needed_after_unversioned_policy_lineage"] == 298
    assert gap["current_symbol_count"] == 1
    assert gap["current_symbols_sample"] == ["BTCUSDT"]
    assert gap["potential_symbol_count_if_unversioned_rows_gain_safe_policy_lineage"] == 2
    assert gap["potential_symbols_sample"] == ["ADAUSDT", "BTCUSDT"]
    assert gap["additional_symbols_needed_after_unversioned_policy_lineage"] == 28
    assert gap["open_positions_ready_to_become_closed_outcomes"] == 1
    assert gap["accepted_fill_candidate_closed_match_count"] == 0
    assert gap["accepted_fill_reconciled_closed_outcome_count"] == 0
    assert "accepted fill time must be <= close time" in gap["promotion_requirements"]
    assert capital["closed_outcome_evidence_gap_analysis"] == gap
    assert statuses["compounding_equity_status.json"]["closed_outcome_evidence_gap_analysis"] == gap
    assert readiness["closed_outcome_evidence_gap_analysis"] == gap
    assert capital["symbol_diversity_opportunity_analysis"] == symbol_opportunity
    assert statuses["compounding_equity_status.json"]["symbol_diversity_opportunity_analysis"] == symbol_opportunity
    assert readiness["symbol_diversity_opportunity_analysis"] == symbol_opportunity
    assert symbol_opportunity["status"] == "NO_GO_SYMBOL_DIVERSITY_EVIDENCE_INSUFFICIENT"
    assert symbol_opportunity["minimum_required_symbol_count"] == 30
    assert symbol_opportunity["current_closed_symbol_count"] == 1
    assert symbol_opportunity["current_closed_symbols"] == ["BTCUSDT"]
    assert symbol_opportunity["additional_symbols_needed"] == 29
    assert symbol_opportunity["gate_counts_only_complete_post_policy_closed_outcomes"] is True
    assert symbol_opportunity["candidate_symbols_do_not_count_until_closed"] is True
    assert symbol_opportunity["open_ready_symbols_not_yet_counted"] == ["SOLUSDT"]
    assert symbol_opportunity["open_ready_symbols_not_yet_counted_count"] == 1
    assert symbol_opportunity["signal_prediction_source_row_count"] == 3
    assert symbol_opportunity["signal_universe_symbol_count"] == 3
    assert symbol_opportunity["signal_universe_symbols_without_closed_outcomes_sample"] == [
        "DOGEUSDT",
        "ETHUSDT",
        "XRPUSDT",
    ]
    assert symbol_opportunity["positive_edge_candidate_symbols_without_closed_outcomes_count"] >= 4
    assert set(symbol_opportunity["positive_edge_candidate_symbols_without_closed_outcomes_sample"]) >= {
        "DOGEUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "XRPUSDT",
    }
    assert symbol_opportunity["near_a_grade_candidate_symbols_without_closed_outcomes_count"] >= 3
    assert set(symbol_opportunity["near_a_grade_candidate_symbols_without_closed_outcomes_sample"]) >= {
        "DOGEUSDT",
        "ETHUSDT",
        "SOLUSDT",
    }
    assert symbol_opportunity["potential_symbol_count_if_open_ready_and_positive_edge_candidates_close"] >= 5
    candidate_by_symbol = {
        row["symbol"]: row
        for row in symbol_opportunity["candidate_symbols_without_closed_outcomes_sample"]
    }
    assert candidate_by_symbol["DOGEUSDT"]["source_kind"] == "paper_signal"
    assert candidate_by_symbol["DOGEUSDT"]["confidence_gap_to_a_grade"] == 0.05
    assert candidate_by_symbol["DOGEUSDT"]["reasons"] == ["LOW_CONFIDENCE"]
    assert capital_progress["current_closed_outcome_count"] == 1
    assert capital_progress["closed_outcome_progress_pct"] == 0.00333333
    assert capital_progress["open_positions_ready_to_become_closed_outcomes"] == 1
    assert capital_progress["projected_closed_outcome_count_after_current_open_positions_close"] == 2
    assert capital_progress["projected_closed_outcome_deficit_after_current_open_positions_close"] == 298
    assert capital_progress["current_symbol_count"] == 1
    assert capital_progress["symbol_diversity_progress_pct"] == 0.03333333
    assert capital_progress["symbol_diversity_deficit"] == 29
    assert capital_progress["break_even_realized_pnl_gap_usd"] == 0.0
    assert capital_progress["return_on_deployed_margin_gap_to_zero"] == 0.0
    assert readiness["evidence_to_go"]["closed_outcomes_needed"] == 299
    assert readiness["evidence_to_go"]["closed_outcomes_needed_after_current_open_positions_close"] == 298
    assert readiness["evidence_to_go"]["additional_symbols_needed"] == 29
    assert readiness["evidence_to_go"]["selection_attribution_rows_needed"] == 3
    assert readiness["evidence_to_go"]["leverage_selection_attribution_rows_needed"] == 3
    assert readiness["evidence_to_go"]["margin_mode_selection_attribution_rows_needed"] == 3
    assert readiness["evidence_to_go"]["hedge_budget_selection_attribution_rows_needed"] == 3
    assert readiness["capital_productivity_progress"] == capital_progress
    assert readiness["policy_evidence_progress"] == progress
    assert readiness["adaptive_field_selection_evidence"] == policy["adaptive_field_selection_evidence"]
    assert readiness["adaptive_selection_attribution_status"] == policy["adaptive_selection_attribution_status"]
    assert readiness["pre_submit_adaptive_field_selection_evidence"] == (
        policy["pre_submit_adaptive_field_selection_evidence"]
    )
    assert readiness["counterfactual_replay_progress"]["counterfactual_source_row_count"] >= 1
    assert "a_grade_replay_evidence_deficit" in readiness["counterfactual_replay_progress"]


def test_adaptive_policy_reports_runtime_size_and_leverage_variation_evidence() -> None:
    statuses = build_statuses(
        ledger={
            "open_positions": [
                _trade(symbol="BTCUSDT", gross_notional_usd=400.0, allocated_margin_usd=200.0, recommended_leverage=2.0, effective_leverage=2.0),
                _trade(symbol="ETHUSDT", gross_notional_usd=900.0, allocated_margin_usd=300.0, recommended_leverage=3.0, effective_leverage=3.0),
            ],
            "closed_trades": [],
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    policy = statuses["adaptive_capital_policy_status.json"]
    evidence = policy["runtime_size_leverage_evidence"]
    field_selection = policy["adaptive_field_selection_evidence"]

    assert policy["no_fixed_runtime_size"] is True
    assert policy["no_fixed_runtime_leverage"] is True
    assert evidence["runtime_size_variation_proven"] is True
    assert evidence["runtime_leverage_variation_proven"] is True
    assert evidence["notional_values_sample"] == [400.0, 900.0]
    assert evidence["allocated_margin_values_sample"] == [200.0, 300.0]
    assert evidence["effective_leverage_values"] == [2.0, 3.0]
    assert evidence["fixed_leverage_classification"] == "SELECTED_RUNTIME_LEVERAGE_VARIES"
    assert field_selection["required_selection_field_coverage"] == 1.0
    assert field_selection["gross_notional_unique_count"] == 2
    assert field_selection["allocated_margin_unique_count"] == 2
    assert field_selection["effective_leverage_values"] == [2.0, 3.0]
    assert field_selection["recommended_margin_modes"] == ["isolated_paper_simulated"]
    assert field_selection["selection_model_input_missing_counts"] == {
        "complete_selection_model_input": 2,
        "hedge_budget_selection_model_input": 2,
        "leverage_selection_model_input": 2,
        "margin_mode_selection_model_input": 2,
    }
    assert "FIXED_OR_UNPROVEN_RUNTIME_SIZE" not in policy["policy_evidence_blocker_reasons"]
    assert "FIXED_OR_UNPROVEN_RUNTIME_LEVERAGE" not in policy["policy_evidence_blocker_reasons"]


def test_adaptive_field_selection_evidence_reports_margin_and_hedge_reasons() -> None:
    statuses = build_statuses(
        ledger={
            "open_positions": [
                _trade(
                    symbol="BTCUSDT",
                    gross_notional_usd=400.0,
                    allocated_margin_usd=400.0,
                    recommended_leverage=1.0,
                    effective_leverage=1.0,
                    recommended_margin_mode="isolated_paper_simulated",
                    hedge_budget_usd=0.0,
                    adaptive_allocation={
                        "model_inputs": {
                            **_selection_model_inputs(leverage=1.0, hedge_pct=0.0),
                            "selected_margin_mode": "isolated_paper_simulated",
                            "margin_mode_selection_reason": "isolated_limits_tail_contagion_for_current_risk",
                            "selected_hedge_budget_pct_of_risk": 0.0,
                            "hedge_budget_selection_reason": "hedge_budget_not_required_for_current_risk",
                        }
                    },
                ),
                _trade(
                    symbol="ETHUSDT",
                    gross_notional_usd=900.0,
                    allocated_margin_usd=300.0,
                    recommended_leverage=3.0,
                    effective_leverage=3.0,
                    recommended_margin_mode="cross_paper_simulated",
                    hedge_budget_usd=12.0,
                    adaptive_allocation={
                        "model_inputs": {
                            **_selection_model_inputs(
                                leverage=3.0,
                                margin_mode="cross_paper_simulated",
                                hedge_pct=0.2,
                            ),
                            "selected_margin_mode": "cross_paper_simulated",
                            "margin_mode_selection_reason": (
                                "paper_cross_margin_simulated_for_high_edge_low_portfolio_pressure"
                            ),
                            "selected_hedge_budget_pct_of_risk": 0.2,
                            "hedge_budget_selection_reason": "operator_hedge_budget_floor",
                        }
                    },
                ),
            ],
            "closed_trades": [],
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    evidence = statuses["adaptive_capital_policy_status.json"]["adaptive_field_selection_evidence"]

    assert evidence["row_count"] == 2
    assert evidence["required_selection_field_coverage"] == 1.0
    assert evidence["recommended_margin_modes"] == [
        "cross_paper_simulated",
        "isolated_paper_simulated",
    ]
    assert evidence["selected_margin_mode_values"] == [
        "cross_paper_simulated",
        "isolated_paper_simulated",
    ]
    assert evidence["leverage_selection_model_input_coverage"] == 1.0
    assert evidence["leverage_selection_reason_counts"] == {
        "moderate_edge_and_risk_budget_selects_dynamic_leverage": 2,
    }
    assert evidence["margin_mode_selection_model_input_coverage"] == 1.0
    assert evidence["margin_mode_selection_reason_counts"] == {
        "isolated_limits_tail_contagion_for_current_risk": 1,
        "paper_cross_margin_simulated_for_high_edge_low_portfolio_pressure": 1,
    }
    assert evidence["hedge_budget_values_sample"] == [0.0, 12.0]
    assert evidence["positive_hedge_budget_count"] == 1
    assert evidence["zero_hedge_budget_count"] == 1
    assert evidence["selected_hedge_budget_pct_values"] == [0.0, 0.2]
    assert evidence["hedge_budget_selection_model_input_coverage"] == 1.0
    assert evidence["complete_selection_model_input_count"] == 2
    assert evidence["complete_selection_model_input_coverage"] == 1.0
    assert evidence["selection_model_input_missing_counts"] == {
        "complete_selection_model_input": 0,
        "hedge_budget_selection_model_input": 0,
        "leverage_selection_model_input": 0,
        "margin_mode_selection_model_input": 0,
    }
    assert evidence["missing_selection_attribution_sample"] == []
    assert evidence["hedge_budget_selection_reason_counts"] == {
        "hedge_budget_not_required_for_current_risk": 1,
        "operator_hedge_budget_floor": 1,
    }


def test_adaptive_field_selection_evidence_derives_margin_attribution_from_recommended_mode() -> None:
    statuses = build_statuses(
        ledger={
            "open_positions": [
                _trade(
                    symbol="BTCUSDT",
                    gross_notional_usd=400.0,
                    allocated_margin_usd=400.0,
                    recommended_leverage=1.0,
                    effective_leverage=1.0,
                    recommended_margin_mode="isolated_paper_simulated",
                    hedge_budget_usd=0.0,
                    adaptive_allocation={
                        "recommended_margin_mode": "isolated_paper_simulated",
                        "model_inputs": {
                            "selected_leverage": 1.0,
                            "leverage_selection_reason": "after_cost_edge_too_small_for_dynamic_leverage",
                            "selected_hedge_budget_pct_of_risk": 0.0,
                            "hedge_budget_selection_reason": "hedge_budget_not_required_for_current_risk",
                        },
                    },
                ),
            ],
            "closed_trades": [],
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    evidence = statuses["adaptive_capital_policy_status.json"]["adaptive_field_selection_evidence"]

    assert evidence["leverage_selection_model_input_coverage"] == 1.0
    assert evidence["margin_mode_selection_model_input_coverage"] == 1.0
    assert evidence["hedge_budget_selection_model_input_coverage"] == 1.0
    assert evidence["complete_selection_model_input_coverage"] == 1.0
    assert evidence["selected_margin_mode_values"] == ["isolated_paper_simulated"]
    assert evidence["margin_mode_selection_reason_counts"] == {
        "isolated_limits_tail_contagion_for_current_risk": 1,
    }
    assert evidence["selection_model_input_missing_counts"] == {
        "complete_selection_model_input": 0,
        "hedge_budget_selection_model_input": 0,
        "leverage_selection_model_input": 0,
        "margin_mode_selection_model_input": 0,
    }


def test_adaptive_policy_distinguishes_dynamic_recommendations_capped_to_one_x() -> None:
    pre_submit_a = _paper_intent(
        symbol="BTCUSDT",
        gross_notional_usd=400.0,
        allocated_margin_usd=400.0,
        notional=400.0,
        notional_usdt=400.0,
        quantity=4.0,
        recommended_leverage=1.0,
        effective_leverage=1.0,
    )
    pre_submit_a["adaptive_allocation"].update({
        "gross_notional_usd": 400.0,
        "allocated_margin_usd": 400.0,
        "recommended_leverage": 1.0,
        "effective_leverage": 1.0,
        "model_inputs": {
            "raw_leverage_target": 2.0,
            "leverage_target": 1.0,
            "selected_leverage": 1.0,
            "leverage_selection_reason": "drawdown_pressure_caps_leverage_at_1x",
        },
    })
    pre_submit_b = _paper_intent(
        symbol="ETHUSDT",
        gross_notional_usd=900.0,
        allocated_margin_usd=900.0,
        notional=900.0,
        notional_usdt=900.0,
        quantity=9.0,
        recommended_leverage=1.0,
        effective_leverage=1.0,
    )
    pre_submit_b["adaptive_allocation"].update({
        "gross_notional_usd": 900.0,
        "allocated_margin_usd": 900.0,
        "recommended_leverage": 1.0,
        "effective_leverage": 1.0,
        "model_inputs": {
            "raw_leverage_target": 3.0,
            "leverage_target": 1.0,
            "selected_leverage": 1.0,
            "leverage_selection_reason": "after_cost_edge_too_small_for_dynamic_leverage",
        },
    })
    statuses = build_statuses(
        ledger={
            "open_positions": [
                _trade(
                    symbol="BTCUSDT",
                    gross_notional_usd=400.0,
                    allocated_margin_usd=400.0,
                    recommended_leverage=1.0,
                    effective_leverage=1.0,
                    adaptive_allocation={
                        "model_inputs": {
                            "raw_leverage_target": 2.0,
                            "leverage_target": 1.0,
                            "selected_leverage": 1.0,
                            "leverage_selection_reason": "drawdown_pressure_caps_leverage_at_1x",
                        }
                    },
                ),
                _trade(
                    symbol="ETHUSDT",
                    gross_notional_usd=900.0,
                    allocated_margin_usd=900.0,
                    recommended_leverage=1.0,
                    effective_leverage=1.0,
                    adaptive_allocation={
                        "model_inputs": {
                            "raw_leverage_target": 3.0,
                            "leverage_target": 1.0,
                            "selected_leverage": 1.0,
                            "leverage_selection_reason": "after_cost_edge_too_small_for_dynamic_leverage",
                        }
                    },
                ),
            ],
            "closed_trades": [],
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_intents=[pre_submit_a, pre_submit_b],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    policy = statuses["adaptive_capital_policy_status.json"]
    evidence = policy["runtime_size_leverage_evidence"]
    pre_submit_evidence = policy["pre_submit_size_leverage_evidence"]
    pre_submit_field_selection = policy["pre_submit_adaptive_field_selection_evidence"]

    assert policy["no_fixed_runtime_size"] is True
    assert policy["no_fixed_runtime_leverage"] is False
    assert policy["pre_submit_sized_policy_candidate_count"] == 2
    assert evidence["dynamic_leverage_recommendation_present"] is True
    assert evidence["dynamic_raw_leverage_target_variation_proven"] is True
    assert evidence["raw_leverage_target_values"] == [2.0, 3.0]
    assert evidence["leverage_target_values"] == [1.0]
    assert evidence["selected_leverage_values"] == [1.0]
    assert evidence["selected_leverage_below_raw_target_count"] == 2
    assert evidence["selected_leverage_filtered_to_1x_count"] == 2
    assert evidence["fixed_leverage_classification"] == (
        "DYNAMIC_RECOMMENDATIONS_CAPPED_OR_FILTERED_TO_1X_BY_CURRENT_RISK_OR_EDGE"
    )
    assert evidence["leverage_selection_reason_counts"] == {
        "after_cost_edge_too_small_for_dynamic_leverage": 1,
        "drawdown_pressure_caps_leverage_at_1x": 1,
    }
    assert pre_submit_evidence["dynamic_leverage_recommendation_present"] is True
    assert pre_submit_evidence["raw_leverage_target_values"] == [2.0, 3.0]
    assert pre_submit_evidence["selected_leverage_values"] == [1.0]
    assert pre_submit_evidence["fixed_leverage_classification"] == (
        "DYNAMIC_RECOMMENDATIONS_CAPPED_OR_FILTERED_TO_1X_BY_CURRENT_RISK_OR_EDGE"
    )
    assert pre_submit_field_selection["row_count"] == 2
    assert pre_submit_field_selection["required_selection_field_coverage"] == 1.0
    assert pre_submit_field_selection["gross_notional_unique_count"] == 2
    assert pre_submit_field_selection["allocated_margin_unique_count"] == 2
    assert pre_submit_field_selection["effective_leverage_values"] == [1.0]
    assert pre_submit_field_selection["leverage_selection_reason_counts"] == {
        "after_cost_edge_too_small_for_dynamic_leverage": 1,
        "drawdown_pressure_caps_leverage_at_1x": 1,
    }
    assert "FIXED_OR_UNPROVEN_RUNTIME_SIZE" not in policy["policy_evidence_blocker_reasons"]
    assert "FIXED_OR_UNPROVEN_RUNTIME_LEVERAGE" in policy["policy_evidence_blocker_reasons"]


def test_build_statuses_fails_when_no_versioned_capital_rows_exist() -> None:
    statuses = build_statuses(
        ledger={
            "open_positions": [],
            "closed_trades": [_trade(adaptive_capital_policy_version=None)],
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    accounting = statuses["margin_notional_leverage_accounting_status.json"]

    assert accounting["status"] == "NO_GO_NO_POST_CAPITAL_POLICY_ROWS"
    assert accounting["runtime_row_count"] == 1
    assert accounting["historical_or_unversioned_runtime_row_count"] == 1
    assert accounting["new_trade_row_count"] == 0
    assert accounting["mandatory_field_coverage"] == 0.0


def test_capital_productivity_reports_current_no_edge_idle_and_return_blockers() -> None:
    statuses = build_statuses(
        ledger={
            "open_positions": [
                _trade(symbol="BTCUSDT", gross_notional_usd=500.0, allocated_margin_usd=250.0),
            ],
            "closed_trades": [
                _trade(symbol="ETHUSDT", realized_pnl_usd=-5.0, gross_notional_usd=500.0, allocated_margin_usd=250.0),
            ],
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=[
            _paper_signal(
                allocator_decision="BLOCK_NO_EDGE",
                confidence_calibrated=0.82,
                expected_move_after_cost_bps=-5.0,
                expected_net_pnl_usd=-0.25,
            )
        ],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    capital = statuses["capital_productivity_runtime_status.json"]
    dashboard = statuses["operator_dashboard_payload.json"]
    pass_conditions = {
        condition["id"]: condition
        for condition in dashboard["pass_condition_status"]["conditions"]
    }

    assert capital["status"] == "NO_GO_INSUFFICIENT_CAPITAL_PRODUCTIVITY_EVIDENCE"
    assert "capital_productivity_runtime_status" in dashboard["remaining_blockers"]
    assert capital["capital_utilization_classification"] == "NO_EDGE_IDLE"
    assert capital["return_on_deployed_margin"] == -0.02
    assert capital["return_on_deployed_margin_numerator_usd"] == -5.0
    assert capital["return_on_deployed_margin_denominator_usd"] == 250.0
    assert capital["return_on_deployed_margin_formula"] == "post_allocator_realized_pnl_usd / closed_deployed_margin_usd"
    assert capital["post_allocator_realized_pnl_usd"] == -5.0
    assert capital["closed_deployed_margin_usd"] == 250.0
    assert capital["closed_gross_notional_usd"] == 500.0
    assert capital["post_allocator_closed_outcome_count"] == 1
    assert capital["minimum_required_closed_outcomes"] == 300
    assert capital["closed_outcome_deficit_to_minimum"] == 299
    progress = capital["capital_productivity_progress"]
    assert progress["current_closed_outcome_count"] == 1
    assert progress["closed_outcome_progress_pct"] == 0.00333333
    assert progress["open_positions_ready_to_become_closed_outcomes"] == 1
    assert progress["projected_closed_outcome_count_after_current_open_positions_close"] == 2
    assert progress["projected_closed_outcome_deficit_after_current_open_positions_close"] == 298
    assert progress["current_symbol_count"] == 1
    assert progress["minimum_required_symbol_count"] == 30
    assert progress["symbol_diversity_progress_pct"] == 0.03333333
    assert progress["symbol_diversity_deficit"] == 29
    assert progress["return_on_deployed_margin_gap_to_zero"] == 0.02
    assert progress["break_even_realized_pnl_gap_usd"] == 5.0
    assert progress["strict_positive_return_requires_realized_pnl_above_zero"] is True
    assert capital["positive_return_on_deployed_margin"] is False
    assert capital["after_cost_expectancy_bps"] == -5.0
    assert capital["positive_after_cost_expectancy"] is False
    assert capital["worst_expected_shortfall_pct_of_equity"] == 0.006
    assert capital["capital_productivity_blocker_reasons"] == [
        "NON_POSITIVE_RETURN_ON_DEPLOYED_MARGIN",
        "NON_POSITIVE_AFTER_COST_EXPECTANCY",
        "NON_POSITIVE_AFTER_COST_OPPORTUNITY_ROWS",
        "PROFIT_FACTOR_BELOW_MINIMUM",
        "NO_EDGE_IDLE_CAPITAL",
    ]
    assert capital["post_allocator_performance_status"] == "NO_GO_PROFIT_FACTOR_BELOW_MINIMUM"
    assert capital["profit_factor"] == 0.0
    assert capital["profit_factor_gap_to_minimum"] == 1.176
    assert capital["positive_edge_non_a_grade_opportunity_count"] == 0
    assert capital["idle_capital_positive_edge_not_a_grade_usd"] == 0.0
    assert capital["positive_edge_non_a_grade_diagnostics"]["row_count"] == 0
    deployed_margin_condition = pass_conditions["positive_deployed_margin_return"]
    assert deployed_margin_condition["status"] == "NO_GO"
    assert deployed_margin_condition["evidence"]["post_allocator_realized_pnl_usd"] == -5.0
    assert deployed_margin_condition["evidence"]["closed_deployed_margin_usd"] == 250.0
    assert deployed_margin_condition["evidence"]["positive_return_on_deployed_margin"] is False
    profit_factor_condition = pass_conditions["minimum_profit_factor"]
    assert profit_factor_condition["status"] == "NO_GO"
    assert profit_factor_condition["evidence"]["profit_factor"] == 0.0
    assert profit_factor_condition["evidence"]["minimum_required_profit_factor"] == 1.176


def test_capital_productivity_reports_profit_factor_below_operator_minimum() -> None:
    statuses = build_statuses(
        ledger={
            "open_positions": [_trade(symbol="BTCUSDT", realized_pnl_usd=0.0)],
            "closed_trades": [
                _trade(symbol="BTCUSDT", realized_pnl_usd=10.0),
                _trade(symbol="ETHUSDT", side="short", realized_pnl_usd=-9.0),
            ],
        },
        portfolio={"equity": 10001.0},
        paper_status={"classification": "V2_TRADE_MANAGEMENT_PAPER_PRODUCTION_OK"},
        paper_signals=[_paper_signal(expected_move_after_cost_bps=20.0)],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    capital = statuses["capital_productivity_runtime_status.json"]
    dashboard = statuses["operator_dashboard_payload.json"]
    pass_conditions = {
        condition["id"]: condition
        for condition in dashboard["pass_condition_status"]["conditions"]
    }

    assert capital["profit_factor"] == 1.11111111
    assert capital["minimum_required_profit_factor"] == 1.176
    assert capital["profit_factor_gap_to_minimum"] == 0.06488889
    burn_down = capital["profit_factor_burn_down"]
    assert burn_down["status"] == "NO_GO_PROFIT_FACTOR_BELOW_MINIMUM"
    assert burn_down["gross_profit_usd"] == 10.0
    assert burn_down["gross_loss_usd"] == 9.0
    assert burn_down["target_gross_profit_usd_at_current_loss"] == 10.584
    assert burn_down["additional_gross_profit_needed_usd"] == 0.584
    assert burn_down["gross_loss_capacity_usd_at_current_profit"] == 8.50340136
    assert burn_down["additional_gross_loss_headroom_usd"] == 0.0
    assert burn_down["closed_outcome_count"] == 2
    assert burn_down["closed_outcome_deficit_to_statistical_minimum"] == 298
    assert burn_down["sample_size_status"] == "NO_GO_PROFIT_FACTOR_COHORT_BELOW_300_OUTCOMES"
    assert burn_down["counts_as_profit_factor_gate"] is False
    assert capital["post_allocator_performance_status"] == "NO_GO_PROFIT_FACTOR_BELOW_MINIMUM"
    assert capital["post_allocator_win_rate"] == 0.5
    assert capital["post_allocator_realized_profit_usd"] == 10.0
    assert capital["post_allocator_realized_loss_usd"] == 9.0
    assert "PROFIT_FACTOR_BELOW_MINIMUM" in capital["capital_productivity_blocker_reasons"]
    assert pass_conditions["minimum_profit_factor"]["status"] == "NO_GO"
    assert pass_conditions["minimum_profit_factor"]["evidence"]["profit_factor"] == 1.11111111
    assert pass_conditions["minimum_profit_factor"]["evidence"]["profit_factor_burn_down"] == burn_down


def test_capital_productivity_distinguishes_positive_non_a_grade_edge_from_no_edge_idle() -> None:
    statuses = build_statuses(
        ledger={
            "open_positions": [
                _trade(symbol="BTCUSDT", gross_notional_usd=500.0, allocated_margin_usd=250.0),
            ],
            "closed_trades": [
                _trade(symbol="ETHUSDT", realized_pnl_usd=5.0, gross_notional_usd=500.0, allocated_margin_usd=250.0),
            ],
        },
        portfolio={"equity": 10005.0},
        paper_status={},
        paper_signals=[
            _paper_signal(
                symbol="SOLUSDT",
                confidence_calibrated=0.62,
                expected_move_after_cost_bps=60.0,
                expected_net_pnl_usd=3.0,
            )
        ],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    capital = statuses["capital_productivity_runtime_status.json"]

    assert capital["status"] == "PASSED"
    assert capital["capital_utilization_classification"] == "B_GRADE_EXPLORATION_PAPER_READY"
    assert capital["capital_productivity_blocker_reasons"] == []
    assert capital["return_on_deployed_margin"] == 0.02
    assert capital["after_cost_expectancy_bps"] == 60.0
    assert capital["positive_after_cost_opportunity_row_count"] == 1
    assert capital["positive_edge_non_a_grade_opportunity_count"] == 1
    assert capital["b_grade_exploration_candidate_count"] == 1
    assert capital["capital_productivity_progress"]["near_a_grade_positive_edge_count"] == 0
    assert capital["capital_productivity_progress"]["closest_positive_edge_confidence_gap_to_a_grade"] == 0.13
    assert capital["a_grade_opportunity_count"] == 0
    assert capital["dynamic_a_grade_opportunity_count"] == 0
    assert capital["idle_capital_no_edge_usd"] == 0.0
    assert capital["idle_capital_positive_edge_not_a_grade_usd"] == 0.0
    assert capital["positive_edge_non_a_grade_diagnostics"] == {
        "row_count": 1,
        "confidence_threshold": 0.75,
        "near_a_grade_confidence_threshold": 0.65,
        "near_a_grade_positive_edge_count": 0,
        "reason_counts": {"LOW_CONFIDENCE": 1},
        "side_counts": {"long": 1},
        "timeframe_counts": {"1m": 1},
        "max_confidence": 0.62,
        "max_after_cost_edge_bps": 60.0,
        "min_confidence_gap_to_a_grade": 0.13,
        "closest_positive_edge_to_a_grade": {
            "symbol": "SOLUSDT",
            "timeframe": "1m",
            "side": "long",
            "confidence": 0.62,
            "confidence_gap_to_a_grade": 0.13,
            "after_cost_edge_bps": 60.0,
            "edge_gap_to_positive_bps": 0.0,
            "allocator_decision": "ALLOW_WITH_SIZE",
            "reasons": ["LOW_CONFIDENCE"],
        },
        "top_after_cost_edge_not_a_grade": {
            "symbol": "SOLUSDT",
            "timeframe": "1m",
            "side": "long",
            "confidence": 0.62,
            "confidence_gap_to_a_grade": 0.13,
            "after_cost_edge_bps": 60.0,
            "edge_gap_to_positive_bps": 0.0,
            "allocator_decision": "ALLOW_WITH_SIZE",
            "reasons": ["LOW_CONFIDENCE"],
        },
        "sample": [
            {
                "symbol": "SOLUSDT",
                "timeframe": "1m",
                "side": "long",
                "confidence": 0.62,
                "confidence_gap_to_a_grade": 0.13,
                "after_cost_edge_bps": 60.0,
                "edge_gap_to_positive_bps": 0.0,
                "allocator_decision": "ALLOW_WITH_SIZE",
                "reasons": ["LOW_CONFIDENCE"],
            }
        ],
    }
    assert capital["positive_edge_non_a_grade_sample"] == [
        {
            "symbol": "SOLUSDT",
            "timeframe": "1m",
            "side": "long",
            "confidence": 0.62,
            "after_cost_edge_bps": 60.0,
            "allocator_decision": "ALLOW_WITH_SIZE",
        }
    ]


def test_capital_productivity_normalizes_signed_short_edge_for_status_evidence() -> None:
    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=_paper_signal_all_timeframes(
            symbol="ETHUSDT",
            side="short",
            action="short",
            confidence_calibrated=0.86,
            expected_move_after_cost_bps=-90.0,
            expected_net_pnl_usd=4.5,
        ),
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    capital = statuses["capital_productivity_runtime_status.json"]
    counterfactual = statuses["counterfactual_capital_sweep_status.json"]

    assert capital["after_cost_expectancy_bps"] == 90.0
    assert capital["positive_after_cost_opportunity_row_count"] == 5
    assert capital["non_positive_after_cost_opportunity_row_count"] == 0
    assert capital["a_grade_opportunity_count"] == 5
    assert capital["a_grade_opportunities_funded"] == 5
    assert "NON_POSITIVE_AFTER_COST_EXPECTANCY" not in capital["capital_productivity_blocker_reasons"]
    assert counterfactual["status"] == "PASSED"
    assert counterfactual["counterfactual_blocker_reasons"] == []
    assert counterfactual["source_coverage"]["source_coverage_status"] == "PASSED"
    assert counterfactual["source_coverage_status"] == "PASSED"
    assert counterfactual["source_coverage_ratio"] == 1.0
    assert counterfactual["required_symbol_timeframe_cell_count"] == 5
    assert counterfactual["observed_required_symbol_timeframe_cell_count"] == 5
    assert counterfactual["missing_required_symbol_timeframe_cell_count"] == 0
    assert counterfactual["a_grade_thresholds"] == {
        "confidence_min": 0.75,
        "after_cost_edge_bps_min_exclusive": 0.0,
        "allocator_blocked_decisions_excluded": True,
    }
    assert counterfactual["a_grade_before_temporal_count"] == 5
    assert counterfactual["event_time_valid_candidate_count"] == 5


def test_capital_productivity_uses_positive_expectancy_not_all_positive_opportunities() -> None:
    statuses = build_statuses(
        ledger={
            "open_positions": [_trade(symbol="BTCUSDT", realized_pnl_usd=0.0)],
            "closed_trades": [_trade(symbol="ETHUSDT", realized_pnl_usd=10.0)],
        },
        portfolio={"equity": 10010.0},
        paper_status={},
        paper_signals=[
            _paper_signal(symbol="BTCUSDT", expected_move_after_cost_bps=60.0),
            _paper_signal(
                symbol="SOLUSDT",
                expected_move_after_cost_bps=-10.0,
                allocator_decision="BLOCK_NO_EDGE",
            ),
        ],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    capital = statuses["capital_productivity_runtime_status.json"]

    assert capital["after_cost_expectancy_bps"] == 25.0
    assert capital["positive_after_cost_opportunity_row_count"] == 1
    assert capital["non_positive_after_cost_opportunity_row_count"] == 1
    assert "NON_POSITIVE_AFTER_COST_EXPECTANCY" not in capital["capital_productivity_blocker_reasons"]
    assert "NON_POSITIVE_AFTER_COST_OPPORTUNITY_ROWS" not in capital["capital_productivity_blocker_reasons"]


def test_portfolio_correlation_budget_passes_with_full_inputs_and_safe_exposure() -> None:
    statuses = build_statuses(
        ledger={
            "open_positions": [
                _trade(symbol="BTCUSDT", gross_notional_usd=300.0, allocated_margin_usd=150.0, correlation_exposure_pct=0.05),
                _trade(symbol="ETHUSDT", gross_notional_usd=250.0, allocated_margin_usd=125.0, correlation_exposure_pct=0.04),
            ],
            "closed_trades": [_trade()],
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    correlation = statuses["portfolio_correlation_budget_status.json"]

    assert correlation["status"] == "PASSED"
    assert correlation["correlation_matrix_ready"] is True
    assert correlation["portfolio_concentration_limits_enforced"] is True
    assert correlation["correlation_input_coverage"] == 1.0
    assert correlation["concentration_limit_breaches"] == []
    assert correlation["correlation_budget_breaches"] == []
    assert correlation["correlation_budget_reduction_required"] is False
    assert correlation["correlation_budget_reduction_plan"] == []
    assert correlation["correlation_blocker_reasons"] == []


def test_portfolio_correlation_budget_accepts_adaptive_allocation_model_input_correlation() -> None:
    statuses = build_statuses(
        ledger={
            "open_positions": [
                _trade(
                    symbol="BTCUSDT",
                    gross_notional_usd=300.0,
                    allocated_margin_usd=150.0,
                    adaptive_allocation={
                        "model_inputs": {"correlation_exposure_pct": 0.05}
                    },
                ),
                _trade(
                    symbol="ETHUSDT",
                    gross_notional_usd=250.0,
                    allocated_margin_usd=125.0,
                    adaptive_allocation={
                        "model_inputs": {"correlation_exposure_pct": 0.04}
                    },
                ),
            ],
            "closed_trades": [_trade()],
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    correlation = statuses["portfolio_correlation_budget_status.json"]

    assert correlation["status"] == "PASSED"
    assert correlation["correlation_input_coverage"] == 1.0
    assert correlation["correlation_input_missing_symbols"] == []
    assert correlation["max_observed_correlation_exposure_pct"] == 0.05


def test_portfolio_correlation_budget_fails_when_multi_symbol_inputs_are_missing() -> None:
    statuses = build_statuses(
        ledger={
            "open_positions": [
                _trade(symbol="BTCUSDT", gross_notional_usd=300.0, allocated_margin_usd=150.0),
                _trade(symbol="ETHUSDT", gross_notional_usd=250.0, allocated_margin_usd=125.0),
            ],
            "closed_trades": [_trade()],
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    correlation = statuses["portfolio_correlation_budget_status.json"]

    assert correlation["status"] == "NO_GO_CORRELATION_INPUTS_MISSING"
    assert correlation["correlation_matrix_ready"] is False
    assert correlation["correlation_input_coverage"] == 0.0
    assert correlation["correlation_input_count"] == 0
    assert correlation["correlation_input_missing_count"] == 2
    assert correlation["correlation_input_missing_symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert correlation["correlation_input_status_counts"] == {"MISSING": 2, "READY": 0}
    assert correlation["correlation_source_counts"] == {}
    assert correlation["correlation_input_missing_sample"] == [
        {
            "symbol": "BTCUSDT",
            "reason": "MISSING_MARKET_CANDLES",
            "diagnostics": {
                "source": None,
                "raw_candle_count": 0,
                "accepted_candle_count": 0,
                "return_count": 0,
            },
        },
        {
            "symbol": "ETHUSDT",
            "reason": "MISSING_MARKET_CANDLES",
            "diagnostics": {
                "source": None,
                "raw_candle_count": 0,
                "accepted_candle_count": 0,
                "return_count": 0,
            },
        },
    ]
    assert correlation["correlation_blocker_reasons"] == ["CORRELATION_INPUTS_MISSING"]


def test_portfolio_correlation_budget_reports_missing_inputs_and_budget_breach_together() -> None:
    statuses = build_statuses(
        ledger={
            "open_positions": [
                _trade(symbol="BTCUSDT", gross_notional_usd=300.0, allocated_margin_usd=150.0),
                _trade(symbol="ETHUSDT", gross_notional_usd=250.0, allocated_margin_usd=125.0, correlation_exposure_pct=0.25),
            ],
            "closed_trades": [_trade()],
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    correlation = statuses["portfolio_correlation_budget_status.json"]

    assert correlation["status"] == "NO_GO_CORRELATION_INPUTS_MISSING_AND_BUDGET_BREACH"
    assert correlation["correlation_matrix_ready"] is False
    assert correlation["correlation_input_missing_symbols"] == ["BTCUSDT"]
    assert correlation["correlation_input_missing_count"] == 1
    assert correlation["correlation_budget_breaches"] == [
        {
            "symbol": "ETHUSDT",
            "correlation_exposure_pct": 0.25,
            "limit_pct": 0.18,
        }
    ]
    assert correlation["correlation_budget_breach_count"] == 1
    assert correlation["correlation_budget_breach_sample"] == correlation["correlation_budget_breaches"]
    assert correlation["correlation_budget_reduction_required"] is True
    assert correlation["correlation_budget_reduction_plan_count"] == 1
    assert correlation["breached_correlation_open_notional_usd"] == 250.0
    assert correlation["symbol_margin_exposure_usd"]["ETHUSDT"] == 125.0
    assert correlation["correlation_budget_reduction_plan"] == [
        {
            "symbol": "ETHUSDT",
            "current_open_notional_usd": 250.0,
            "current_allocated_margin_usd": 125.0,
            "correlation_exposure_pct": 0.25,
            "limit_pct": 0.18,
            "excess_correlation_exposure_pct": 0.07,
            "new_allocation_correlation_adjustment": 0.0,
            "new_allocation_allowed_under_correlation_budget": False,
            "maximum_new_notional_usd_under_correlation_budget": 0.0,
            "current_position_action_required": True,
            "remediation_action": "block_new_allocations_and_reduce_or_hedge_existing_exposure_until_correlation_within_budget",
        }
    ]
    assert correlation["correlation_budget_reduction_plan_sample"] == correlation["correlation_budget_reduction_plan"]
    assert correlation["correlation_source_counts"] == {"position_or_feature_payload": 1}
    assert correlation["correlation_input_status_counts"] == {"MISSING": 1, "READY": 1}
    assert correlation["correlation_blocker_reasons"] == [
        "CORRELATION_INPUTS_MISSING",
        "CORRELATION_BUDGET_BREACH",
    ]


def test_portfolio_correlation_budget_derives_inputs_from_final_ohlcv_returns() -> None:
    returns_a = [0.001, -0.001, 0.001, -0.001] * 10
    returns_b = [0.001, 0.001, -0.001, -0.001] * 10
    start_ms = _ms("2026-06-20T00:30:00Z")

    statuses = build_statuses(
        ledger={
            "open_positions": [
                _trade(symbol="ALPHAUSDT", gross_notional_usd=300.0, allocated_margin_usd=150.0),
                _trade(symbol="BETAUSDT", gross_notional_usd=250.0, allocated_margin_usd=125.0),
            ],
            "closed_trades": [_trade()],
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        correlation_candles_by_symbol={
            "ALPHAUSDT": _return_candles("ALPHAUSDT", returns_a, start_ms=start_ms),
            "BETAUSDT": _return_candles("BETAUSDT", returns_b, start_ms=start_ms),
        },
        correlation_candle_sources_by_symbol={
            "ALPHAUSDT": "v2:market:ohlcv_closed:binance:ALPHAUSDT:1m",
            "BETAUSDT": "v2:market:ohlcv_closed:binance:BETAUSDT:1m",
        },
        horizon_years=5.0,
        generated_utc="2026-06-20T02:00:00Z",
    )

    correlation = statuses["portfolio_correlation_budget_status.json"]

    assert correlation["status"] == "PASSED"
    assert correlation["correlation_input_coverage"] == 1.0
    assert correlation["correlation_input_missing_symbols"] == []
    assert correlation["correlation_input_missing_count"] == 0
    assert correlation["correlation_input_missing_sample"] == []
    assert correlation["correlation_input_status_counts"] == {"MISSING": 0, "READY": 2}
    assert correlation["correlation_blocker_reasons"] == []
    assert correlation["derived_correlation_symbol_count"] == 2
    assert correlation["correlation_source_counts"] == {"market_ohlcv_return_correlation": 2}
    assert correlation["correlation_source_by_symbol"] == {
        "ALPHAUSDT": "market_ohlcv_return_correlation",
        "BETAUSDT": "market_ohlcv_return_correlation",
    }
    assert correlation["correlation_pair_counts_by_symbol"] == {
        "ALPHAUSDT": 1,
        "BETAUSDT": 1,
    }


def test_portfolio_correlation_budget_rejects_stale_derived_candle_inputs() -> None:
    returns_a = [0.001, -0.001, 0.001, -0.001] * 10
    returns_b = [0.001, 0.001, -0.001, -0.001] * 10
    stale_returns = [0.001, -0.0005, 0.0007, -0.0002] * 10

    statuses = build_statuses(
        ledger={
            "open_positions": [
                _trade(symbol="ALPHAUSDT", gross_notional_usd=300.0, allocated_margin_usd=150.0),
                _trade(symbol="BETAUSDT", gross_notional_usd=250.0, allocated_margin_usd=125.0),
                _trade(symbol="GAMMAUSDT", gross_notional_usd=200.0, allocated_margin_usd=100.0),
            ],
            "closed_trades": [_trade()],
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        correlation_candles_by_symbol={
            "ALPHAUSDT": _return_candles("ALPHAUSDT", returns_a, start_ms=_ms("2026-06-20T00:30:00Z")),
            "BETAUSDT": _return_candles("BETAUSDT", returns_b, start_ms=_ms("2026-06-20T00:30:00Z")),
            "GAMMAUSDT": _return_candles("GAMMAUSDT", stale_returns, start_ms=_ms("2026-06-15T16:00:00Z")),
        },
        horizon_years=5.0,
        generated_utc="2026-06-20T02:00:00Z",
    )

    correlation = statuses["portfolio_correlation_budget_status.json"]

    assert correlation["status"] == "NO_GO_CORRELATION_INPUTS_MISSING"
    assert correlation["correlation_input_count"] == 2
    assert correlation["correlation_input_coverage"] == 0.66666667
    assert correlation["correlation_input_missing_symbols"] == ["GAMMAUSDT"]
    assert correlation["correlation_input_missing_count"] == 1
    assert correlation["correlation_input_missing_reasons"] == {"GAMMAUSDT": "STALE_LAST_CANDLE"}
    assert correlation["correlation_input_missing_sample"][0]["symbol"] == "GAMMAUSDT"
    assert correlation["correlation_input_missing_sample"][0]["reason"] == "STALE_LAST_CANDLE"
    assert correlation["correlation_input_status_counts"] == {"MISSING": 1, "READY": 2}
    assert correlation["correlation_blocker_reasons"] == ["CORRELATION_INPUTS_MISSING"]


def test_portfolio_correlation_budget_rejects_future_candles_as_unfinished() -> None:
    returns_a = [0.001, -0.001, 0.001, -0.001] * 10
    returns_b = [0.001, 0.001, -0.001, -0.001] * 10
    future_returns = [0.0005, -0.0003, 0.0004, -0.0001] * 10

    statuses = build_statuses(
        ledger={
            "open_positions": [
                _trade(symbol="ALPHAUSDT", gross_notional_usd=300.0, allocated_margin_usd=150.0),
                _trade(symbol="BETAUSDT", gross_notional_usd=250.0, allocated_margin_usd=125.0),
                _trade(symbol="FUTUREUSDT", gross_notional_usd=200.0, allocated_margin_usd=100.0),
            ],
            "closed_trades": [_trade()],
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        correlation_candles_by_symbol={
            "ALPHAUSDT": _return_candles("ALPHAUSDT", returns_a, start_ms=_ms("2026-06-20T00:30:00Z")),
            "BETAUSDT": _return_candles("BETAUSDT", returns_b, start_ms=_ms("2026-06-20T00:30:00Z")),
            "FUTUREUSDT": _return_candles("FUTUREUSDT", future_returns, start_ms=_ms("2026-06-20T02:30:00Z")),
        },
        horizon_years=5.0,
        generated_utc="2026-06-20T02:00:00Z",
    )

    correlation = statuses["portfolio_correlation_budget_status.json"]

    assert correlation["status"] == "NO_GO_CORRELATION_INPUTS_MISSING"
    assert correlation["correlation_input_missing_symbols"] == ["FUTUREUSDT"]
    assert correlation["correlation_input_missing_reasons"] == {"FUTUREUSDT": "MISSING_ACCEPTED_CANDLES"}
    assert correlation["correlation_candle_diagnostics_by_symbol"]["FUTUREUSDT"]["reject_counts"] == {
        "CANDLE_CLOSE_TIME_AFTER_GENERATED_AT": 41
    }


def test_portfolio_correlation_budget_fails_on_single_symbol_concentration_breach() -> None:
    statuses = build_statuses(
        ledger={
            "open_positions": [
                _trade(symbol="BTCUSDT", gross_notional_usd=900.0, allocated_margin_usd=450.0, correlation_exposure_pct=0.05),
            ],
            "closed_trades": [_trade()],
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    correlation = statuses["portfolio_correlation_budget_status.json"]

    assert correlation["status"] == "NO_GO_PORTFOLIO_CONCENTRATION_BREACH"
    assert correlation["portfolio_concentration_limits_enforced"] is False
    assert correlation["correlation_blocker_reasons"] == ["PORTFOLIO_CONCENTRATION_BREACH"]
    assert correlation["concentration_limit_breaches"] == [
        {
            "symbol": "BTCUSDT",
            "exposure_pct": 0.09,
            "limit_pct": 0.08,
            "exposure_usd": 900.0,
        }
    ]


def test_pre_submit_parity_passes_for_complete_sized_adaptive_paper_intent() -> None:
    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={"classification": "V2_TRADE_MANAGEMENT_PAPER_PRODUCTION_OK"},
        paper_intents=[_paper_intent()],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    parity = statuses["paper_live_pre_submit_parity_status.json"]

    assert parity["status"] == "PASSED"
    assert parity["paper_intent_row_count"] == 1
    assert parity["paper_intent_source_counts"] == {"__unspecified__": 1}
    assert parity["paper_intent_policy_version_counts"] == {ADAPTIVE_CAPITAL_POLICY_VERSION: 1}
    assert parity["paper_intent_allocator_decision_counts"] == {"ALLOW_WITH_SIZE": 1}
    assert parity["paper_intent_sizing_complete_counts"] == {"True": 1}
    assert parity["versioned_adaptive_intent_count"] == 1
    assert parity["versioned_adaptive_intent_source_counts"] == {"__unspecified__": 1}
    assert parity["sized_pre_submit_candidate_count"] == 1
    assert parity["versioned_sized_pre_submit_candidate_count"] == 1
    assert parity["unversioned_sized_pre_submit_candidate_count"] == 0
    assert parity["unversioned_sized_pre_submit_candidate_sample"] == []
    assert parity["sized_pre_submit_candidate_source_counts"] == {"__unspecified__": 1}
    assert parity["candidate_field_coverage"] == 1.0
    assert parity["candidate_failure_sample"] == []
    assert parity["allocator_correlation_input_required"] is True
    assert parity["allocator_correlation_input_count"] == 1
    assert parity["allocator_correlation_input_coverage"] == 1.0
    assert parity["allocator_correlation_input_source_counts"] == {
        "MARKET_OHLCV_RETURN_CORRELATION": 1
    }
    assert parity["allocator_correlation_input_status_counts"] == {"READY": 1}
    assert parity["max_allocator_correlation_exposure_pct"] == 0.12
    assert parity["min_allocator_correlation_adjustment"] == 0.33333333
    assert parity["effective_liquidation_buffer_minimum_verified"] is True
    assert parity["effective_liquidation_buffer_minimum_evidence"]["status"] == "PASSED"
    dashboard = statuses["operator_dashboard_payload.json"]
    audit_liquidation = dashboard["external_audit_blocker_burn_down"][
        "liquidation_buffer_minimum"
    ]
    assert dashboard["liquidation_buffer_minimum_status"] == audit_liquidation
    assert dashboard["operator_go_readiness"]["liquidation_buffer_minimum_status"] == (
        audit_liquidation
    )
    assert audit_liquidation["verified"] is True
    assert audit_liquidation["evidence"]["status"] == "PASSED"
    assert parity["canonical_pre_submit_sample"][0]["symbol"] == "LABUSDT"
    assert parity["canonical_pre_submit_sample"][0]["places_real_order"] is False


def test_pre_submit_parity_fails_for_liquidation_buffer_below_minimum() -> None:
    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={"classification": "V2_TRADE_MANAGEMENT_PAPER_PRODUCTION_OK"},
        paper_intents=[_paper_intent(liquidation_buffer_bps=499.0)],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    parity = statuses["paper_live_pre_submit_parity_status.json"]
    minimum_evidence = parity["liquidation_buffer_minimum_evidence"]

    assert parity["status"] == "NO_GO_PRE_SUBMIT_PARITY_FIELD_MISMATCH"
    assert parity["candidate_failure_reason_counts"] == {
        "LIQUIDATION_BUFFER_BELOW_MINIMUM": 1
    }
    assert parity["candidate_failure_sample"][0]["reasons"] == [
        "LIQUIDATION_BUFFER_BELOW_MINIMUM"
    ]
    assert minimum_evidence["minimum_liquidation_buffer_bps"] == 500.0
    assert minimum_evidence["liquidation_buffer_below_minimum_count"] == 1
    assert minimum_evidence["status"] == "NO_GO_LIQUIDATION_BUFFER_BELOW_MINIMUM"


def test_build_statuses_documents_allocator_liquidity_regime_calibration_defaults() -> None:
    intent = _paper_intent(
        liquidity_adjustment=1.0,
        regime_adjustment=1.0,
        liquidity_score=1.0,
        regime_score=1.0,
    )
    intent["adaptive_allocation"].update({
        "liquidity_adjustment": 1.0,
        "regime_adjustment": 1.0,
    })
    intent["adaptive_allocation"]["model_inputs"].update({
        "liquidity_score": 1.0,
        "regime_score": 1.0,
    })
    intent.update({
        "allocator_liquidity_score_source": "legacy_default_liquidity_score",
        "allocator_liquidity_score_reason": "DEFAULT_NEUTRAL_LIQUIDITY_SCORE",
        "allocator_regime_score_source": "legacy_default_regime_score",
        "allocator_regime_score_reason": "DEFAULT_NEUTRAL_REGIME_SCORE",
    })
    current_blocked_intent = _blocked_paper_intent(
        allocator_liquidity_score=0.65,
        allocator_regime_score=0.75,
        liquidity_score=0.65,
        regime_score=0.75,
        allocator_liquidity_score_source="market_microstructure.orderbook_depth_usd+spread_bps",
        allocator_liquidity_score_reason="DERIVED_FROM_ORDERBOOK_DEPTH_AND_SPREAD",
        allocator_regime_score_source="strategy_router_regime_labels",
        allocator_regime_score_reason="REGIME_LABEL_CHOP_RANGE",
    )
    current_blocked_intent["adaptive_allocation"].update({
        "liquidity_adjustment": 0.65,
        "regime_adjustment": 0.75,
    })
    current_blocked_intent["adaptive_allocation"]["model_inputs"].update({
        "liquidity_score": 0.65,
        "regime_score": 0.75,
        "allocator_liquidity_score": 0.65,
        "allocator_regime_score": 0.75,
    })

    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": [], "accepted": [intent]},
        portfolio={"equity": 10000.0},
        paper_status={"classification": "V2_TRADE_MANAGEMENT_PAPER_PRODUCTION_OK"},
        paper_intents=[intent, current_blocked_intent],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    calibration = statuses["operator_dashboard_payload.json"]["allocator_calibration_status"]

    assert calibration["status"] == "DOCUMENTED_INPUT_CALIBRATION_GAP"
    assert calibration["calibration_gap_reasons"] == [
        "LIQUIDITY_ADJUSTMENT_CONSTANT_AT_DEFAULT_1_0",
        "REGIME_ADJUSTMENT_CONSTANT_AT_DEFAULT_1_0",
    ]
    assert calibration["liquidity_adjustment_formula"] == "clamp(liquidity_score, 0.0, 1.0)"
    assert calibration["regime_adjustment_formula"] == "clamp(regime_score, 0.2, 1.25)"
    assert calibration["constant_1_0_adjustments_are_documented"] is True
    assert calibration["liquidity_score_source_counts"] == {
        "legacy_default_liquidity_score": 2
    }
    assert calibration["liquidity_score_reason_counts"] == {
        "DEFAULT_NEUTRAL_LIQUIDITY_SCORE": 2
    }
    assert calibration["regime_score_source_counts"] == {
        "legacy_default_regime_score": 2
    }
    assert calibration["regime_score_reason_counts"] == {
        "DEFAULT_NEUTRAL_REGIME_SCORE": 2
    }
    current_observation = calibration["current_intent_calibration_observation"]
    assert current_observation["status"] == "READY_CURRENT_INTENT_CALIBRATION_OBSERVED"
    assert current_observation["current_versioned_intent_row_count"] == 2
    assert current_observation["current_sized_intent_row_count"] == 1
    assert current_observation["current_allocator_blocked_intent_count"] == 1
    assert current_observation["liquidity_score_values"] == [0.65, 1.0]
    assert current_observation["regime_score_values"] == [0.75, 1.0]
    assert current_observation["liquidity_adjustment_values"] == [0.65, 1.0]
    assert current_observation["regime_adjustment_values"] == [0.75, 1.0]
    assert current_observation["liquidity_score_source_counts"] == {
        "legacy_default_liquidity_score": 1,
        "market_microstructure.orderbook_depth_usd+spread_bps": 1,
    }
    assert current_observation["liquidity_score_reason_counts"] == {
        "DEFAULT_NEUTRAL_LIQUIDITY_SCORE": 1,
        "DERIVED_FROM_ORDERBOOK_DEPTH_AND_SPREAD": 1,
    }
    assert current_observation["regime_score_source_counts"] == {
        "legacy_default_regime_score": 1,
        "strategy_router_regime_labels": 1,
    }
    assert current_observation["regime_score_reason_counts"] == {
        "DEFAULT_NEUTRAL_REGIME_SCORE": 1,
        "REGIME_LABEL_CHOP_RANGE": 1,
    }
    assert current_observation["counts_as_policy_outcome_calibration_gate"] is False
    assert (
        current_observation["blocked_or_zero_notional_rows_count_as_closed_outcome_evidence"]
        is False
    )
    audit_calibration = statuses["operator_dashboard_payload.json"]["external_audit_blocker_burn_down"][
        "liquidity_regime_calibration"
    ]
    assert audit_calibration["fix_or_document_action_status"] == (
        "DOCUMENTED_INPUT_CALIBRATION_GAP_NOT_POLICY_READY"
    )
    assert audit_calibration["fix_or_document_action_remaining"] is False
    assert audit_calibration["policy_outcome_calibration_ready"] is False
    assert audit_calibration["counts_as_policy_outcome_calibration_gate"] is False
    assert statuses["operator_dashboard_payload.json"]["liquidity_regime_adjustment_status"] == (
        audit_calibration
    )
    assert statuses["operator_dashboard_payload.json"]["operator_go_readiness"][
        "liquidity_regime_adjustment_status"
    ] == audit_calibration
    assert audit_calibration["required_next_evidence"] == [
        "ACCUMULATE_POLICY_OUTCOMES_WITH_NON_DEFAULT_LIQUIDITY_AND_REGIME_ADJUSTMENTS"
    ]
    assert "FIX_OR_DOCUMENT_LIQUIDITY_AND_REGIME_CALIBRATION_INPUTS" not in (
        statuses["operator_dashboard_payload.json"]["external_audit_blocker_burn_down"][
            "required_actions_remaining"
        ]
    )
    assert statuses["adaptive_capital_policy_status.json"]["allocator_calibration_status"] == calibration


def test_pre_submit_parity_reports_active_and_held_intent_source_counts() -> None:
    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={"classification": "V2_TRADE_MANAGEMENT_PAPER_PRODUCTION_OK"},
        paper_intents=[
            _paper_intent(symbol="ACTIVEUSDT", paper_intent_source="v2:paper:intents"),
            _paper_intent(symbol="HELDUSDT", paper_intent_source="v2:paper:intents_held_by_paper_fill_gate"),
        ],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    parity = statuses["paper_live_pre_submit_parity_status.json"]

    assert parity["status"] == "PASSED"
    assert parity["paper_intent_active_row_count"] == 1
    assert parity["paper_intent_held_row_count"] == 1
    assert parity["paper_intent_source_counts"] == {
        "v2:paper:intents": 1,
        "v2:paper:intents_held_by_paper_fill_gate": 1,
    }
    assert parity["versioned_adaptive_intent_source_counts"] == {
        "v2:paper:intents": 1,
        "v2:paper:intents_held_by_paper_fill_gate": 1,
    }
    assert parity["sized_pre_submit_candidate_source_counts"] == {
        "v2:paper:intents": 1,
        "v2:paper:intents_held_by_paper_fill_gate": 1,
    }
    assert parity["versioned_sized_pre_submit_candidate_count"] == 2
    assert parity["unversioned_sized_pre_submit_candidate_count"] == 0
    assert parity["non_sized_versioned_intent_count"] == 0
    assert parity["non_sized_versioned_intent_reason_counts"] == {}
    assert parity["non_sized_versioned_intent_sample"] == []


def test_pre_submit_parity_explains_versioned_intents_without_sized_candidates() -> None:
    blocked_intent = _paper_intent(
        allocator_decision="BLOCK_NO_EDGE",
        paper_sizing_complete=False,
        quantity=0.0,
        notional=0.0,
        notional_usdt=0.0,
        gross_notional_usd=0.0,
        allocated_margin_usd=0.0,
        risk_budget_usd=0.0,
    )
    blocked_intent["adaptive_allocation"].update({
        "allocator_decision": "BLOCK_NO_EDGE",
        "target_notional_usdt": 0.0,
        "target_quantity": 0.0,
        "gross_notional_usd": 0.0,
        "allocated_margin_usd": 0.0,
        "risk_budget_usd": 0.0,
    })

    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_intents=[blocked_intent],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    parity = statuses["paper_live_pre_submit_parity_status.json"]

    assert parity["status"] == "NO_GO_PRE_SUBMIT_PARITY_NO_SIZED_INTENTS"
    assert parity["versioned_adaptive_intent_count"] == 1
    assert parity["sized_pre_submit_candidate_count"] == 0
    assert parity["non_sized_versioned_intent_count"] == 1
    assert parity["non_sized_versioned_intent_reason_counts"] == {
        "ALLOCATOR_DECISION_BLOCK_NO_EDGE": 1,
        "NON_POSITIVE_GROSS_NOTIONAL_USD": 1,
        "NON_POSITIVE_QUANTITY": 1,
        "PAPER_SIZING_COMPLETE_NOT_TRUE": 1,
    }
    assert parity["non_sized_versioned_intent_sample"][0]["symbol"] == "LABUSDT"
    assert parity["non_sized_versioned_intent_sample"][0]["reasons"] == [
        "ALLOCATOR_DECISION_BLOCK_NO_EDGE",
        "NON_POSITIVE_GROSS_NOTIONAL_USD",
        "NON_POSITIVE_QUANTITY",
        "PAPER_SIZING_COMPLETE_NOT_TRUE",
    ]


def test_pre_submit_parity_reports_unversioned_allocator_evidence_separately() -> None:
    unversioned_intent = _paper_intent(
        allocator_decision="BLOCK_NO_EDGE",
        paper_sizing_complete=False,
        quantity=0.0,
        notional=0.0,
        notional_usdt=0.0,
        gross_notional_usd=0.0,
        allocated_margin_usd=0.0,
        risk_budget_usd=0.0,
    )
    unversioned_intent.pop("adaptive_capital_policy_version", None)
    unversioned_intent["adaptive_allocation"].update({
        "allocator_decision": "BLOCK_NO_EDGE",
        "target_notional_usdt": 0.0,
        "target_quantity": 0.0,
        "gross_notional_usd": 0.0,
        "allocated_margin_usd": 0.0,
        "risk_budget_usd": 0.0,
    })
    unversioned_intent["adaptive_allocation"].pop("adaptive_capital_policy_version", None)

    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_intents=[
            unversioned_intent,
        ],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    parity = statuses["paper_live_pre_submit_parity_status.json"]

    assert parity["status"] == "NO_GO_PRE_SUBMIT_PARITY_UNVERSIONED_ALLOCATOR_EVIDENCE"
    assert parity["paper_intent_row_count"] == 1
    assert parity["paper_intent_policy_version_counts"] == {"__missing__": 1}
    assert parity["paper_intent_allocator_decision_counts"] == {"BLOCK_NO_EDGE": 1}
    assert parity["paper_intent_sizing_complete_counts"] == {"False": 1}
    assert parity["unversioned_allocator_evidence_count"] == 1
    assert parity["unversioned_allocator_evidence_decision_counts"] == {"BLOCK_NO_EDGE": 1}
    assert parity["unversioned_allocator_evidence_sample"][0]["symbol"] == "LABUSDT"
    assert parity["unversioned_allocator_evidence_sample"][0]["allocator_decision"] == "BLOCK_NO_EDGE"
    assert "allocator_decision" in parity["unversioned_allocator_evidence_sample"][0]["adaptive_allocation_keys"]
    assert parity["versioned_adaptive_intent_count"] == 0
    assert parity["sized_pre_submit_candidate_count"] == 0


def test_pre_submit_parity_fails_for_unversioned_sized_candidates() -> None:
    unversioned_intent = _paper_intent()
    unversioned_intent.pop("adaptive_capital_policy_version", None)
    unversioned_intent["adaptive_allocation"].pop("adaptive_capital_policy_version", None)

    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_intents=[
            unversioned_intent,
        ],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    parity = statuses["paper_live_pre_submit_parity_status.json"]

    assert parity["status"] == "NO_GO_PRE_SUBMIT_PARITY_FIELD_MISMATCH"
    assert parity["paper_intent_policy_version_counts"] == {"__missing__": 1}
    assert parity["sized_pre_submit_candidate_count"] == 1
    assert parity["versioned_sized_pre_submit_candidate_count"] == 0
    assert parity["unversioned_sized_pre_submit_candidate_count"] == 1
    assert parity["candidate_field_coverage"] == 0.0
    assert parity["candidate_failure_count"] == 1
    assert parity["candidate_failure_reason_counts"] == {
        "MISSING_ADAPTIVE_CAPITAL_POLICY_VERSION": 1,
    }
    assert parity["candidate_failure_sample"][0]["reasons"] == [
        "MISSING_ADAPTIVE_CAPITAL_POLICY_VERSION",
    ]
    assert parity["unversioned_sized_pre_submit_candidate_sample"][0]["symbol"] == "LABUSDT"


def test_pre_submit_parity_reports_durable_accepted_evidence_without_passing_active_snapshot() -> None:
    unversioned_intent = _paper_intent()
    unversioned_intent.pop("adaptive_capital_policy_version", None)
    unversioned_intent["adaptive_allocation"].pop("adaptive_capital_policy_version", None)
    accepted_intent = _paper_intent(symbol="ACCEPTEDUSDT")

    statuses = build_statuses(
        ledger={
            "open_positions": [],
            "closed_trades": [],
            "accepted": [accepted_intent],
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_intents=[unversioned_intent],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    parity = statuses["paper_live_pre_submit_parity_status.json"]
    durable = parity["durable_accepted_pre_submit_evidence"]

    assert parity["status"] == "NO_GO_PRE_SUBMIT_PARITY_FIELD_MISMATCH"
    assert parity["durable_accepted_pre_submit_used_for_gate"] is False
    assert parity["candidate_failure_reason_counts"] == {
        "MISSING_ADAPTIVE_CAPITAL_POLICY_VERSION": 1,
    }
    assert durable["status"] == "PASSED"
    assert durable["source"] == "v2:paper:ledger.accepted"
    assert durable["accepted_row_count"] == 1
    assert durable["versioned_accepted_row_count"] == 1
    assert durable["versioned_sized_accepted_candidate_count"] == 1
    assert durable["versioned_candidate_field_coverage"] == 1.0
    assert durable["versioned_candidate_failure_count"] == 0
    assert durable["canonical_versioned_pre_submit_sample"][0]["symbol"] == "ACCEPTEDUSDT"


def test_pre_submit_parity_uses_durable_accepted_evidence_when_active_snapshot_absent() -> None:
    accepted_intent = _paper_intent(symbol="ACCEPTEDUSDT")

    statuses = build_statuses(
        ledger={
            "open_positions": [],
            "closed_trades": [],
            "accepted": [accepted_intent],
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_intents=[],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    parity = statuses["paper_live_pre_submit_parity_status.json"]
    durable = parity["durable_accepted_pre_submit_evidence"]
    pass_conditions = {
        condition["id"]: condition
        for condition in statuses["operator_dashboard_payload.json"]["pass_condition_status"]["conditions"]
    }

    assert parity["status"] == "PASSED"
    assert parity["paper_intent_row_count"] == 0
    assert parity["sized_pre_submit_candidate_count"] == 0
    assert parity["durable_accepted_pre_submit_used_for_gate"] is True
    assert parity["effective_pre_submit_evidence_source"] == "durable_accepted_pre_submit_ledger"
    assert parity["effective_versioned_sized_pre_submit_candidate_count"] == 1
    assert parity["effective_liquidation_buffer_minimum_verified"] is True
    assert parity["effective_liquidation_buffer_minimum_evidence"] == (
        durable["liquidation_buffer_minimum_evidence"]
    )
    assert parity["parity_blocker_reasons"] == []
    assert durable["status"] == "PASSED"
    assert durable["versioned_sized_accepted_candidate_count"] == 1
    assert durable["versioned_candidate_field_coverage"] == 1.0
    assert durable["versioned_candidate_failure_count"] == 0

    parity_condition = pass_conditions["paper_live_pre_submit_parity"]
    assert parity_condition["status"] == "PASSED"
    assert parity_condition["evidence"]["effective_pre_submit_evidence_source"] == (
        "durable_accepted_pre_submit_ledger"
    )
    assert parity_condition["evidence"]["effective_versioned_sized_pre_submit_candidate_count"] == 1
    assert parity_condition["evidence"]["durable_accepted_pre_submit_used_for_gate"] is True
    assert parity_condition["evidence"]["durable_accepted_pre_submit_status"] == "PASSED"
    assert parity_condition["evidence"]["durable_versioned_sized_accepted_candidate_count"] == 1
    assert parity_condition["evidence"]["durable_versioned_candidate_field_coverage"] == 1.0
    assert parity_condition["evidence"]["durable_versioned_candidate_failure_count"] == 0
    assert parity_condition["evidence"]["effective_liquidation_buffer_minimum_verified"] is True
    assert parity_condition["evidence"]["effective_liquidation_buffer_minimum_evidence"] == (
        durable["liquidation_buffer_minimum_evidence"]
    )


def test_pre_submit_parity_uses_durable_accepted_evidence_when_active_snapshot_all_blocked() -> None:
    accepted_intent = _paper_intent(symbol="ACCEPTEDUSDT")
    blocked_intent = _blocked_paper_intent(
        symbol="BLOCKEDUSDT",
        paper_intent_source="v2:paper:intents",
    )

    statuses = build_statuses(
        ledger={
            "open_positions": [],
            "closed_trades": [],
            "accepted": [accepted_intent],
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_intents=[blocked_intent],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    parity = statuses["paper_live_pre_submit_parity_status.json"]
    pass_conditions = {
        condition["id"]: condition
        for condition in statuses["operator_dashboard_payload.json"]["pass_condition_status"]["conditions"]
    }

    assert parity["status"] == "PASSED"
    assert parity["paper_intent_active_row_count"] == 1
    assert parity["active_or_held_versioned_intent_count"] == 1
    assert parity["active_or_held_versioned_blocked_intent_count"] == 1
    assert parity["active_or_held_versioned_sized_intent_count"] == 0
    assert parity["active_or_held_versioned_unblocked_non_sized_intent_count"] == 0
    assert parity["active_or_held_versioned_intents_all_blocked"] is True
    assert parity["durable_accepted_pre_submit_used_for_gate"] is True
    assert parity["effective_pre_submit_evidence_source"] == (
        "durable_accepted_pre_submit_ledger_with_current_blocked_snapshot"
    )
    assert parity["effective_versioned_sized_pre_submit_candidate_count"] == 1
    assert parity["durable_accepted_pre_submit_gate_reason"] == (
        "current_active_or_held_versioned_intents_all_allocator_blocked"
    )
    assert parity["parity_blocker_reasons"] == []

    parity_condition = pass_conditions["paper_live_pre_submit_parity"]
    assert parity_condition["status"] == "PASSED"
    assert parity_condition["evidence"]["effective_pre_submit_evidence_source"] == (
        "durable_accepted_pre_submit_ledger_with_current_blocked_snapshot"
    )
    assert parity_condition["evidence"]["durable_accepted_pre_submit_used_for_gate"] is True


def test_pre_submit_parity_does_not_use_durable_evidence_for_unblocked_active_unsized_intent() -> None:
    accepted_intent = _paper_intent(symbol="ACCEPTEDUSDT")
    unsized_intent = _paper_intent(
        symbol="UNSIZEDUSDT",
        paper_intent_source="v2:paper:intents",
        paper_sizing_complete=False,
        quantity=0.0,
        notional=0.0,
        notional_usdt=0.0,
        gross_notional_usd=0.0,
        allocated_margin_usd=0.0,
        risk_budget_usd=0.0,
    )
    unsized_intent["adaptive_allocation"].update({
        "target_notional_usdt": 0.0,
        "target_quantity": 0.0,
        "gross_notional_usd": 0.0,
        "allocated_margin_usd": 0.0,
        "risk_budget_usd": 0.0,
    })

    statuses = build_statuses(
        ledger={
            "open_positions": [],
            "closed_trades": [],
            "accepted": [accepted_intent],
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_intents=[unsized_intent],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    parity = statuses["paper_live_pre_submit_parity_status.json"]

    assert parity["status"] == "NO_GO_PRE_SUBMIT_PARITY_NO_SIZED_INTENTS"
    assert parity["active_or_held_versioned_intents_all_blocked"] is False
    assert parity["active_or_held_versioned_unblocked_non_sized_intent_count"] == 1
    assert parity["active_or_held_versioned_unblocked_non_sized_intent_sample"][0]["symbol"] == (
        "UNSIZEDUSDT"
    )
    assert parity["durable_accepted_pre_submit_used_for_gate"] is False
    assert parity["effective_pre_submit_evidence_source"] == "none"
    assert parity["parity_blocker_reasons"] == ["NO_GO_PRE_SUBMIT_PARITY_NO_SIZED_INTENTS"]


def test_pre_submit_parity_uses_durable_accepted_evidence_when_only_blocked_ledger_rows_exist() -> None:
    accepted_intent = _paper_intent(symbol="ACCEPTEDUSDT")
    blocked_row = _paper_intent(
        symbol="BLOCKEDUSDT",
        allocator_decision="BLOCK_NO_EDGE",
        paper_sizing_complete=False,
        quantity=0.0,
        gross_notional_usd=0.0,
        allocated_margin_usd=0.0,
        paper_intent_source="v2:paper:ledger.blocked",
    )

    statuses = build_statuses(
        ledger={
            "open_positions": [],
            "closed_trades": [],
            "accepted": [accepted_intent],
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_intents=[blocked_row],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    parity = statuses["paper_live_pre_submit_parity_status.json"]

    assert parity["status"] == "PASSED"
    assert parity["paper_intent_active_row_count"] == 0
    assert parity["paper_intent_held_row_count"] == 0
    assert parity["paper_intent_source_counts"] == {"v2:paper:ledger.blocked": 1}
    assert parity["non_sized_versioned_intent_count"] == 1
    assert parity["durable_accepted_pre_submit_used_for_gate"] is True
    assert parity["effective_pre_submit_evidence_source"] == "durable_accepted_pre_submit_ledger"
    assert parity["effective_versioned_sized_pre_submit_candidate_count"] == 1
    assert parity["parity_blocker_reasons"] == []


def test_pre_submit_parity_fails_closed_for_future_leaking_or_unsafe_candidate() -> None:
    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_intents=[
            _paper_intent(
                places_real_order=True,
                entry_feature_available_at="2026-06-20T01:31:00Z",
            )
        ],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    parity = statuses["paper_live_pre_submit_parity_status.json"]

    assert parity["status"] == "NO_GO_PRE_SUBMIT_PARITY_FIELD_MISMATCH"
    assert parity["candidate_failure_count"] == 1
    assert parity["candidate_field_coverage"] == 0.0
    assert parity["candidate_failure_sample"][0]["reasons"] == [
        "AVAILABLE_AT_AFTER_DECISION_TIME",
        "UNSAFE_PLACES_REAL_ORDER",
    ]


def test_counterfactual_sweep_uses_paper_signal_source_rows() -> None:
    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=_paper_signal_all_timeframes(),
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    capital = statuses["capital_productivity_runtime_status.json"]
    counterfactual = statuses["counterfactual_capital_sweep_status.json"]

    assert capital["opportunity_source"] == "v2:signals:paper"
    assert capital["paper_signal_row_count"] == 5
    assert counterfactual["paper_signal_row_count"] == 5
    assert counterfactual["paper_intent_row_count"] == 0
    assert counterfactual["prediction_row_count"] == 0
    assert counterfactual["ledger_runtime_row_count"] == 0
    assert counterfactual["counterfactual_source_row_count"] == 5
    assert counterfactual["historical_a_grade_signal_count"] == 5
    assert counterfactual["event_time_valid_candidate_count"] == 5
    assert counterfactual["source_coverage"]["source_coverage_status"] == "PASSED"
    assert counterfactual["source_coverage"]["required_symbol_timeframe_cell_count"] == 5
    assert counterfactual["source_coverage"]["observed_required_symbol_timeframe_cell_count"] == 5
    assert counterfactual["source_coverage_status"] == "PASSED"
    assert counterfactual["source_coverage_ratio"] == 1.0
    assert counterfactual["required_symbol_timeframe_cell_count"] == 5
    assert counterfactual["observed_required_symbol_timeframe_cell_count"] == 5
    assert counterfactual["missing_required_symbol_timeframe_cell_count"] == 0
    assert counterfactual["sweep_result_count"] > 0
    assert counterfactual["config_space_audit"]["per_candidate_theoretical_configuration_count"] == 540
    assert counterfactual["config_space_audit"]["candidate_count"] == 5
    assert counterfactual["config_space_audit"]["event_time_valid_candidate_count"] == 5
    assert counterfactual["config_space_audit"]["theoretical_configuration_count"] == 2700
    assert counterfactual["config_space_audit"]["considered_count"] == 2700
    assert counterfactual["config_space_audit"]["feasible_count"] == counterfactual["sweep_result_count"]
    assert counterfactual["config_space_audit"]["pruned_count"] == counterfactual["config_space_audit"]["pruned_configuration_count"]
    assert counterfactual["config_space_audit"]["configuration_count_reconciled"] is True
    assert counterfactual["config_space_audit"]["feasible_plus_pruned_reconciled"] is True
    assert counterfactual["config_space_audit"]["feasible_configuration_count"] == counterfactual["sweep_result_count"]
    assert counterfactual["hedge_accounting_audit"]["status"] == "PASSED"
    assert counterfactual["hedge_accounting_audit"]["hedge_enabled_configuration_count"] > 0
    assert counterfactual["hedge_accounting_audit"]["hedge_disabled_configuration_count"] > 0
    assert counterfactual["hedge_accounting_audit"]["hedge_budget_positive_count"] == (
        counterfactual["hedge_accounting_audit"]["hedge_enabled_configuration_count"]
    )
    assert counterfactual["hedge_accounting_audit"]["max_hedge_budget_usd"] > 0.0
    assert counterfactual["config_axes"]["market_cost_evidence"] == "required_explicit_spread_slippage_fee_funding_bps_or_usd"
    assert counterfactual["config_axes"]["hedge_budget_model"] == {
        "hedge_cost_bps_when_enabled": 3.0,
        "tail_loss_reduction_factor_when_enabled": 0.75,
        "hedge_budget_usd_formula": "unhedged_expected_shortfall_usd - expected_shortfall_usd",
    }
    assert counterfactual["market_depth_capacity_requirement"] == "required_actual_depth_usd_or_orderbook_levels"
    assert counterfactual["market_cost_evidence_requirement"] == "required_explicit_spread_slippage_fee_funding_bps_or_usd"
    market_cost_coverage = counterfactual["market_cost_evidence_coverage_status"]
    assert market_cost_coverage["status"] == "PASSED"
    assert market_cost_coverage["candidate_row_count"] == 5
    assert market_cost_coverage["complete_candidate_count"] == 5
    assert len(market_cost_coverage["complete_candidate_sample"]) == 5
    assert market_cost_coverage["complete_candidate_sample"][0]["missing_market_cost_evidence"] == []
    assert market_cost_coverage["missing_reason_counts"] == {}
    assert market_cost_coverage["field_present_counts"] == {
        "fee_bps": 5,
        "funding_bps": 5,
        "market_depth_usd": 5,
        "slippage_bps": 5,
        "spread_bps": 5,
    }
    readiness = counterfactual["a_grade_readiness"]
    assert readiness["source_kind_counts"] == {"paper_signal": 5}
    assert readiness["source_kind_readiness"]["paper_signal"]["a_grade_before_temporal_count"] == 5
    assert readiness["source_kind_readiness"]["paper_signal"]["event_time_valid_candidate_count"] == 5
    assert readiness["source_kind_readiness"]["paper_signal"]["best_configuration_count"] == 5
    progress = counterfactual["counterfactual_replay_progress"]
    assert progress["a_grade_source_kind_counts"] == {"paper_signal": 5}
    assert progress["a_grade_source_kind_readiness"]["paper_signal"]["best_configuration_count"] == 5
    assert progress["configuration_count_reconciled"] is True
    assert progress["feasible_plus_pruned_reconciled"] is True
    assert progress["theoretical_configuration_count"] == 2700
    assert progress["configurations_considered_count"] == 2700
    selected = counterfactual["best_configurations_sample"][0]["selected"]
    assert selected["market_cost_evidence_sources"] == {
        "fee_bps": "fee_bps",
        "funding_bps": "expected_funding_bps",
        "slippage_bps": "expected_slippage_bps",
        "spread_bps": "actual_observed_spread_entry_bps",
    }


def test_dynamic_a_grade_calibration_promotes_proven_low_confidence_bucket_without_lowering_global_threshold() -> None:
    closed_trades = [
        _trade(
            trade_id=f"calibrated_{index}",
            symbol="BTCUSDT",
            timeframe="1m",
            strategy="range_reversion",
            market_regime="range",
            side="long",
            confidence_calibrated=0.62,
            expected_move_after_cost_bps=60.0,
            realized_pnl_usd=6.0,
            gross_notional_usd=1000.0,
            allocated_margin_usd=500.0,
            decision_time="2026-06-19T12:00:00Z",
            available_at="2026-06-19T11:59:00Z",
            generated_at="2026-06-19T11:58:00Z",
            feature_cutoff="2026-06-19T11:55:00Z",
            entry_feature_candle_closed_confirmed=True,
            entry_atr_bps=30.0,
            orderbook_depth_usd=2000.0,
        )
        for index in range(30)
    ]
    dynamic_candidate = _paper_signal(
        symbol="BTCUSDT",
        timeframe="1m",
        source_redis_key="v2:signals:paper:BTCUSDT:1m",
        strategy="range_reversion",
        market_regime="range",
        confidence_calibrated=0.62,
        expected_move_after_cost_bps=60.0,
        realized_pnl_usd=None,
        gross_notional_usd=1000.0,
        allocated_margin_usd=500.0,
        decision_time="2026-06-20T12:00:00Z",
        available_at="2026-06-20T11:59:00Z",
        generated_at="2026-06-20T11:58:00Z",
        feature_cutoff="2026-06-20T11:55:00Z",
        entry_feature_candle_closed_confirmed=True,
        entry_atr_bps=30.0,
        orderbook_depth_usd=2000.0,
    )
    exploration_candidate = _paper_signal(
        symbol="ETHUSDT",
        timeframe="5m",
        source_redis_key="v2:signals:paper:ETHUSDT:5m",
        strategy="breakout",
        market_regime="squeeze",
        confidence_calibrated=0.62,
        expected_move_after_cost_bps=60.0,
        realized_pnl_usd=None,
        gross_notional_usd=1000.0,
        allocated_margin_usd=500.0,
        decision_time="2026-06-20T12:00:00Z",
        available_at="2026-06-20T11:59:00Z",
        generated_at="2026-06-20T11:58:00Z",
        feature_cutoff="2026-06-20T11:55:00Z",
        entry_feature_candle_closed_confirmed=True,
        entry_atr_bps=30.0,
        orderbook_depth_usd=2000.0,
    )

    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": closed_trades},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=[dynamic_candidate, exploration_candidate],
        horizon_years=5.0,
        generated_utc="2026-06-21T00:00:00Z",
    )

    calibration = statuses["a_grade_dynamic_calibration_status.json"]
    matrix = statuses["a_grade_bucket_performance_matrix.json"]
    resolution = statuses["positive_edge_below_a_grade_resolution.json"]
    capital = statuses["capital_productivity_runtime_status.json"]
    phase = statuses[
        "v2_stop_waiting_a_grade_calibration_accelerated_replay_and_capital_deployment_status.json"
    ]
    dashboard = statuses["operator_dashboard_payload.json"]

    assert calibration["status"] == "PASSED"
    assert calibration["fixed_global_confidence_threshold_preserved"] == 0.75
    assert calibration["global_threshold_lowered"] is False
    assert calibration["dynamic_a_grade_candidate_count"] == 1
    assert calibration["strict_a_grade_candidate_count"] == 0
    assert matrix["eligible_bucket_count"] == 1
    eligible_bucket = calibration["eligible_bucket_sample"][0]
    assert eligible_bucket["confidence_bucket"] == "0.60-0.65"
    assert eligible_bucket["sample_count"] == 30
    assert eligible_bucket["dynamic_a_grade_eligible"] is True
    assert resolution["classification_counts"]["A_GRADE_EXECUTION_PAPER"] == 1
    assert resolution["classification_counts"]["B_GRADE_EXPLORATION_PAPER"] == 1
    assert resolution["fixed_dollar_budget_used"] is False
    assert resolution["a_grade_execution_paper_sample"][0]["confidence"] == 0.62
    assert resolution["a_grade_execution_paper_sample"][0]["strict_a_grade"] is False
    assert resolution["a_grade_execution_paper_sample"][0]["dynamic_a_grade_eligible"] is True
    assert 0.0 < resolution["b_grade_exploration_paper_sample"][0]["risk_budget_fraction_of_normal_adaptive"] <= 0.25
    assert capital["capital_utilization_classification"] == "DYNAMIC_A_GRADE_PAPER_DEPLOYMENT_VALIDATED"
    assert capital["a_grade_opportunity_count"] == 1
    assert capital["strict_a_grade_opportunity_count"] == 0
    assert capital["dynamic_a_grade_opportunity_count"] == 1
    assert capital["dynamic_a_grade_opportunities_funded"] == 1
    assert capital["dynamic_a_grade_opportunities_underfunded"] == 0
    assert phase["dynamic_a_grade_calibration_status"] == "PASSED"
    assert phase["status"].endswith("_BLOCKED")
    assert "ACCELERATED_REPLAY_EVIDENCE_NOT_READY" in phase["blocker_reasons"]
    assert dashboard["a_grade_dynamic_calibration_status"] == calibration
    assert dashboard["positive_edge_below_a_grade_resolution"] == resolution


def test_accelerated_replay_counts_event_time_valid_outcome_labels_without_strict_a_grade_sweep() -> None:
    closed_trades = [
        _trade(
            trade_id=f"replay_label_{index}",
            symbol=symbol,
            timeframe=timeframe,
            side=side,
            confidence_calibrated=0.62,
            expected_move_after_cost_bps=55.0,
            realized_pnl_usd=6.0,
            gross_notional_usd=1000.0,
            allocated_margin_usd=500.0,
            decision_time=f"2026-06-20T12:0{index}:00Z",
            available_at=f"2026-06-20T12:0{index}:00Z",
            generated_at=f"2026-06-20T12:0{index}:00Z",
            feature_cutoff=f"2026-06-20T12:0{index}:00Z",
            entry_feature_candle_closed_confirmed=True,
            take_profit_structure="single_target",
            actual_observed_spread_entry_bps=1.5,
            orderbook_depth_usd=250000.0,
            correlation_exposure_pct=0.10,
        )
        for index, (symbol, timeframe, side) in enumerate(
            (
                ("BTCUSDT", "1m", "long"),
                ("ETHUSDT", "5m", "short"),
                ("SOLUSDT", "15m", "long"),
                ("BNBUSDT", "1h", "short"),
            )
        )
    ]

    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": closed_trades},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=[],
        horizon_years=5.0,
        generated_utc="2026-06-21T00:00:00Z",
    )

    replay = statuses["accelerated_counterfactual_replay_status.json"]
    phase = statuses[
        "v2_stop_waiting_a_grade_calibration_accelerated_replay_and_capital_deployment_status.json"
    ]

    assert replay["event_time_valid_label_count"] == 4
    assert replay["replayed_economic_candidate_count"] == 4
    assert replay["strict_sweep_replayed_economic_candidate_count"] == 0
    assert replay["strict_sweep_event_time_valid_candidate_count"] == 0
    assert replay["strict_sweep_best_configuration_count"] == 0
    assert replay["replay_expectancy_gate_scope"] == (
        "dynamic_a_grade_execution_paper_validated_replay_candidates"
    )
    assert replay["replay_expectancy_positive"] is False
    assert replay["expectancy_after_cost_bps"] is None
    assert replay["unfiltered_replay_expectancy_positive"] is True
    assert replay["unfiltered_replay_expectancy_after_cost_bps"] == 60.0
    assert replay["validated_replay_deployment_status"]["status"] == (
        "BLOCKED_DYNAMIC_VALIDATED_REPLAY_DEPLOYMENT"
    )
    assert replay["simulation_accounting_coverage_status"]["status"] == "PASSED"
    assert replay["side_counts"] == {"long": 2, "short": 2}
    assert "INSUFFICIENT_EVENT_TIME_VALID_REPLAY_OUTCOMES" in replay["blocker_reasons"]
    assert "VALIDATED_REPLAY_DEPLOYMENT_EXPECTANCY_NOT_PROVEN" in replay["blocker_reasons"]
    assert "NO_FEASIBLE_COUNTERFACTUAL_BEST_CONFIGURATIONS" in replay["blocker_reasons"]
    assert "INCOMPLETE_SIMULATION_ACCOUNTING_COVERAGE" not in replay["blocker_reasons"]
    assert phase["fast_evidence_gate"]["replayed_economic_candidate_count"] == 4
    assert phase["fast_evidence_gate"]["positive_replay_expectancy_after_cost"] is False
    assert phase["status"].endswith("_BLOCKED")


def test_accelerated_replay_uses_dynamic_validated_expectancy_even_when_unfiltered_replay_is_negative() -> None:
    def replay_trade(
        *,
        trade_id: str,
        symbol: str,
        timeframe: str,
        side: str,
        strategy: str,
        market_regime: str,
        expected_move_after_cost_bps: float,
        realized_pnl_usd: float,
        index: int,
    ) -> dict[str, object]:
        hour = 12 + index // 60
        minute = index % 60
        decision_time = f"2026-06-20T{hour:02d}:{minute:02d}:00Z"
        return _trade(
            trade_id=trade_id,
            symbol=symbol,
            timeframe=timeframe,
            side=side,
            strategy=strategy,
            market_regime=market_regime,
            confidence_calibrated=0.62,
            expected_move_after_cost_bps=expected_move_after_cost_bps,
            realized_pnl_usd=realized_pnl_usd,
            gross_notional_usd=1000.0,
            allocated_margin_usd=500.0,
            decision_time=decision_time,
            available_at=decision_time,
            generated_at=decision_time,
            feature_cutoff=decision_time,
            entry_feature_candle_closed_confirmed=True,
            take_profit_structure="single_target",
            actual_observed_spread_entry_bps=1.5,
            orderbook_depth_usd=250000.0,
            correlation_exposure_pct=0.10,
        )

    validated_positive_rows = [
        replay_trade(
            trade_id=f"validated_positive_{index}",
            symbol="BTCUSDT",
            timeframe="1m",
            side="long",
            strategy="range_reversion",
            market_regime="range",
            expected_move_after_cost_bps=60.0,
            realized_pnl_usd=6.0,
            index=index,
        )
        for index in range(30)
    ]
    unvalidated_negative_rows = [
        replay_trade(
            trade_id=f"unvalidated_negative_{index}",
            symbol="ETHUSDT",
            timeframe="5m",
            side="short",
            strategy="breakout",
            market_regime="squeeze",
            expected_move_after_cost_bps=25.0,
            realized_pnl_usd=-12.0,
            index=30 + index,
        )
        for index in range(40)
    ]

    statuses = build_statuses(
        ledger={
            "open_positions": [],
            "closed_trades": [*validated_positive_rows, *unvalidated_negative_rows],
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=[],
        horizon_years=5.0,
        generated_utc="2026-06-21T00:00:00Z",
    )

    replay = statuses["accelerated_counterfactual_replay_status.json"]
    phase = statuses[
        "v2_stop_waiting_a_grade_calibration_accelerated_replay_and_capital_deployment_status.json"
    ]

    assert replay["replayed_economic_candidate_count"] == 70
    assert replay["replay_expectancy_gate_scope"] == (
        "dynamic_a_grade_execution_paper_validated_replay_candidates"
    )
    assert replay["validated_replay_deployment_status"]["status"] == "PASSED"
    assert replay["validated_replay_candidate_count"] == 30
    assert replay["validated_replay_symbol_count"] == 1
    assert replay["validated_replay_expectancy_after_cost_bps"] == 60.0
    assert replay["validated_replay_profit_factor"] == "inf"
    assert replay["expectancy_after_cost_bps"] == 60.0
    assert replay["replay_expectancy_positive"] is True
    assert replay["unfiltered_replay_expectancy_positive"] is False
    assert math.isclose(
        replay["unfiltered_replay_expectancy_after_cost_bps"],
        -42.85714286,
    )
    assert "VALIDATED_REPLAY_DEPLOYMENT_EXPECTANCY_NOT_PROVEN" not in replay["blocker_reasons"]
    assert "NON_POSITIVE_OR_MISSING_REPLAY_EXPECTANCY" not in replay["blocker_reasons"]
    assert "INSUFFICIENT_EVENT_TIME_VALID_REPLAY_OUTCOMES" in replay["blocker_reasons"]
    assert phase["fast_evidence_gate"]["positive_replay_expectancy_after_cost"] is True
    assert phase["status"].endswith("_BLOCKED")


def test_stop_waiting_phase_accepts_replay_symbol_diversity_without_relaxing_operator_go_symbol_gate(
    monkeypatch,
) -> None:
    monkeypatch.setattr(status_module, "DYNAMIC_A_GRADE_MIN_BUCKET_SAMPLE_COUNT", 1)
    monkeypatch.setattr(status_module, "DYNAMIC_A_GRADE_MIN_POSITIVE_OUTCOME_LCB", 0.1)
    monkeypatch.setattr(status_module, "ACCELERATED_REPLAY_MIN_ECONOMIC_OUTCOMES", 2)
    monkeypatch.setattr(status_module, "ACCELERATED_REPLAY_MIN_SYMBOLS", 2)
    monkeypatch.setattr(status_module, "FAST_GATE_MIN_REALTIME_OUTCOMES", 2)
    monkeypatch.setattr(status_module, "FAST_GATE_MIN_REALTIME_SYMBOLS", 3)
    monkeypatch.setattr(status_module, "FAST_GATE_MIN_REALTIME_SIDE_CLOSES", 1)
    monkeypatch.setattr(status_module, "SIGNAL_ACCURACY_TIMEFRAMES", ("1m", "5m"))

    closed_trades = [
        _trade(
            trade_id="phase_replay_symbol_btc",
            symbol="BTCUSDT",
            timeframe="1m",
            side="long",
            strategy="range_reversion",
            market_regime="range",
            confidence_calibrated=0.86,
            expected_move_after_cost_bps=90.0,
            realized_pnl_usd=9.0,
            gross_notional_usd=1000.0,
            allocated_margin_usd=500.0,
            decision_time="2026-06-20T12:00:00Z",
            available_at="2026-06-20T12:00:00Z",
            generated_at="2026-06-20T12:00:00Z",
            feature_cutoff="2026-06-20T12:00:00Z",
            entry_feature_candle_closed_confirmed=True,
            take_profit_structure="single_target",
            actual_observed_spread_entry_bps=1.5,
            orderbook_depth_usd=250000.0,
            correlation_exposure_pct=0.10,
        ),
        _trade(
            trade_id="phase_replay_symbol_eth",
            symbol="ETHUSDT",
            timeframe="5m",
            side="short",
            strategy="range_reversion",
            market_regime="range",
            confidence_calibrated=0.86,
            expected_move_after_cost_bps=90.0,
            realized_pnl_usd=9.0,
            gross_notional_usd=1000.0,
            allocated_margin_usd=500.0,
            decision_time="2026-06-20T12:05:00Z",
            available_at="2026-06-20T12:05:00Z",
            generated_at="2026-06-20T12:05:00Z",
            feature_cutoff="2026-06-20T12:05:00Z",
            entry_feature_candle_closed_confirmed=True,
            take_profit_structure="single_target",
            actual_observed_spread_entry_bps=1.5,
            orderbook_depth_usd=250000.0,
            correlation_exposure_pct=0.10,
        ),
    ]

    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": closed_trades},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=_paper_signal_all_timeframes(
            symbol="BTCUSDT",
            confidence_calibrated=0.86,
            expected_move_after_cost_bps=90.0,
            realized_pnl_usd=None,
            allocated_margin_usd=250.0,
        ),
        horizon_years=5.0,
        generated_utc="2026-06-21T00:00:00Z",
    )

    phase = statuses[
        "v2_stop_waiting_a_grade_calibration_accelerated_replay_and_capital_deployment_status.json"
    ]
    dashboard = statuses["operator_dashboard_payload.json"]

    assert "INSUFFICIENT_PHASE_SYMBOL_DIVERSITY" not in phase["blocker_reasons"]
    assert "INSUFFICIENT_REALTIME_PAPER_SYMBOLS_FOR_PHASE" not in phase["blocker_reasons"]
    fast_gate = phase["fast_evidence_gate"]
    assert fast_gate["realtime_paper_symbol_count"] == 2
    assert fast_gate["minimum_realtime_paper_symbols"] == 3
    assert fast_gate["realtime_symbol_diversity_pass"] is False
    assert fast_gate["realtime_symbol_diversity_still_counts_for_operator_go"] is True
    assert fast_gate["replay_symbol_count"] == 2
    assert fast_gate["minimum_replay_symbols"] == 2
    assert fast_gate["replay_symbol_diversity_pass"] is True
    assert fast_gate["phase_symbol_diversity_pass"] is True
    assert fast_gate["phase_symbol_diversity_basis"] == "accelerated_replay"
    assert "symbol_diversity" in dashboard["operator_go_readiness"]["failed_conditions"]


def test_qualified_replay_policy_evidence_burns_down_passive_operator_waiting_blockers(
    monkeypatch,
) -> None:
    monkeypatch.setattr(status_module, "DYNAMIC_A_GRADE_MIN_BUCKET_SAMPLE_COUNT", 1)
    monkeypatch.setattr(status_module, "DYNAMIC_A_GRADE_MIN_POSITIVE_OUTCOME_LCB", 0.1)
    monkeypatch.setattr(status_module, "MINIMUM_POST_ALLOCATOR_CLOSED_OUTCOMES", 15)
    monkeypatch.setattr(status_module, "MINIMUM_POLICY_SYMBOL_COUNT", 3)
    monkeypatch.setattr(status_module, "ACCELERATED_REPLAY_MIN_ECONOMIC_OUTCOMES", 15)
    monkeypatch.setattr(status_module, "ACCELERATED_REPLAY_MIN_SYMBOLS", 3)

    closed_trades = [
        _trade(
            trade_id="realtime-long-btc",
            symbol="BTCUSDT",
            timeframe="1m",
            side="long",
            strategy="range_reversion",
            market_regime="range",
            realized_pnl_usd=7.0,
            gross_notional_usd=1000.0,
            allocated_margin_usd=500.0,
            decision_time="2026-06-20T12:00:00Z",
            available_at="2026-06-20T11:59:30Z",
            generated_at="2026-06-20T11:59:20Z",
            feature_cutoff="2026-06-20T11:55:00Z",
            entry_feature_candle_closed_confirmed=True,
            take_profit_structure="single_target",
            actual_observed_spread_entry_bps=1.2,
            expected_slippage_bps=1.4,
            fee_bps=4.0,
            expected_funding_bps=0.2,
            orderbook_depth_usd=300000.0,
            correlation_exposure_pct=0.12,
        ),
        _trade(
            trade_id="realtime-short-eth",
            symbol="ETHUSDT",
            timeframe="5m",
            side="short",
            strategy="range_reversion",
            market_regime="range",
            realized_pnl_usd=5.0,
            gross_notional_usd=1000.0,
            allocated_margin_usd=500.0,
            decision_time="2026-06-20T12:05:00Z",
            available_at="2026-06-20T12:04:30Z",
            generated_at="2026-06-20T12:04:20Z",
            feature_cutoff="2026-06-20T12:00:00Z",
            entry_feature_candle_closed_confirmed=True,
            take_profit_structure="single_target",
            actual_observed_spread_entry_bps=1.2,
            expected_slippage_bps=1.4,
            fee_bps=4.0,
            expected_funding_bps=0.2,
            orderbook_depth_usd=300000.0,
            correlation_exposure_pct=0.12,
        ),
    ]

    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": closed_trades},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=[],
        closed_candle_replay_evidence_rows=_qualified_closed_candle_replay_policy_rows(),
        horizon_years=5.0,
        generated_utc="2026-06-21T00:00:00Z",
    )

    replay = statuses["accelerated_counterfactual_replay_status.json"]
    adaptive = statuses["adaptive_capital_policy_status.json"]
    compounding = statuses["compounding_equity_status.json"]
    readiness = statuses["operator_dashboard_payload.json"]["operator_go_readiness"]
    conditions = {
        condition["id"]: condition
        for condition in statuses["operator_dashboard_payload.json"]["pass_condition_status"]["conditions"]
    }
    evidence_to_go = readiness["evidence_to_go"]

    assert replay["status"] == "PASSED"
    assert replay["validated_replay_deployment_status"]["status"] == "PASSED"
    assert replay["validated_replay_candidate_count"] == 15
    assert replay["validated_replay_symbol_count"] == 3

    replay_policy = adaptive["qualified_replay_policy_evidence_status"]
    assert replay_policy["status"] == "PASSED"
    assert replay_policy["counts_as_policy_evidence"] is True
    assert replay_policy["does_not_wait_for_300_realtime_closes"] is True
    assert replay_policy["policy_evidence_basis"] == "qualified_accelerated_replay"
    assert replay_policy["qualified_replay_outcome_count"] == 15
    assert replay_policy["validated_replay_symbol_count"] == 3
    assert adaptive["post_allocator_closed_outcome_count"] == 2
    assert adaptive["symbol_count"] == 2
    assert adaptive["effective_policy_outcome_count"] == 15
    assert adaptive["effective_policy_symbol_count"] == 3
    assert adaptive["effective_policy_closed_outcome_deficit_to_minimum"] == 0
    assert adaptive["effective_policy_symbol_diversity_deficit"] == 0
    assert compounding["policy_evidence_basis"] == "qualified_accelerated_replay"
    assert compounding["effective_policy_closed_outcome_deficit_to_minimum"] == 0
    assert compounding["effective_policy_symbol_diversity_deficit"] == 0
    assert conditions["post_policy_outcome_count"]["status"] == "PASSED"
    assert conditions["symbol_diversity"]["status"] == "PASSED"
    assert "post_policy_outcome_count" not in readiness["failed_conditions"]
    assert "symbol_diversity" not in readiness["failed_conditions"]
    assert evidence_to_go["closed_outcomes_needed"] == 0
    assert evidence_to_go["additional_symbols_needed"] == 0
    assert evidence_to_go["realtime_closed_outcomes_needed"] == 13
    assert evidence_to_go["realtime_additional_symbols_needed"] == 1
    assert evidence_to_go["policy_evidence_basis"] == "qualified_accelerated_replay"


def test_qualified_replay_policy_evidence_separates_replay_coverage_from_validated_subset(
    monkeypatch,
) -> None:
    monkeypatch.setattr(status_module, "DYNAMIC_A_GRADE_MIN_BUCKET_SAMPLE_COUNT", 1)
    monkeypatch.setattr(status_module, "DYNAMIC_A_GRADE_MIN_POSITIVE_OUTCOME_LCB", 0.1)
    monkeypatch.setattr(status_module, "MINIMUM_POST_ALLOCATOR_CLOSED_OUTCOMES", 15)
    monkeypatch.setattr(status_module, "MINIMUM_POLICY_SYMBOL_COUNT", 3)
    monkeypatch.setattr(status_module, "ACCELERATED_REPLAY_MIN_ECONOMIC_OUTCOMES", 15)
    monkeypatch.setattr(status_module, "ACCELERATED_REPLAY_MIN_SYMBOLS", 3)

    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=[],
        closed_candle_replay_evidence_rows=_qualified_closed_candle_replay_policy_rows(
            validated_subset_only=True,
        ),
        horizon_years=5.0,
        generated_utc="2026-06-21T00:00:00Z",
    )

    replay = statuses["accelerated_counterfactual_replay_status.json"]
    adaptive = statuses["adaptive_capital_policy_status.json"]
    readiness = statuses["operator_dashboard_payload.json"]["operator_go_readiness"]
    conditions = {
        condition["id"]: condition
        for condition in statuses["operator_dashboard_payload.json"]["pass_condition_status"]["conditions"]
    }

    assert replay["status"] == "PASSED"
    assert replay["observed_timeframes"] == ["15m", "1h", "1m", "4h", "5m"]
    assert replay["side_counts"] == {"long": 8, "short": 7}
    assert replay["validated_replay_deployment_status"]["status"] == "PASSED"
    assert replay["validated_replay_deployment_status"]["validated_replay_timeframes"] == [
        "15m",
        "1h",
        "5m",
    ]
    assert replay["validated_replay_deployment_status"]["validated_replay_side_counts"] == {
        "short": 5,
    }

    replay_policy = adaptive["qualified_replay_policy_evidence_status"]
    assert replay_policy["status"] == "PASSED"
    assert replay_policy["replay_timeframes"] == ["15m", "1h", "1m", "4h", "5m"]
    assert replay_policy["replay_side_counts"] == {"long": 8, "short": 7}
    assert replay_policy["validated_replay_timeframes"] == ["15m", "1h", "5m"]
    assert replay_policy["validated_replay_side_counts"] == {"short": 5}
    assert replay_policy["effective_policy_outcome_count"] == 15
    assert replay_policy["effective_policy_symbol_count"] == 3
    assert replay_policy["effective_policy_long_count"] == 8
    assert replay_policy["effective_policy_short_count"] == 7
    assert conditions["post_policy_outcome_count"]["status"] == "PASSED"
    assert conditions["symbol_diversity"]["status"] == "PASSED"
    assert "post_policy_outcome_count" not in readiness["failed_conditions"]
    assert "symbol_diversity" not in readiness["failed_conditions"]


def test_out_of_sample_live_grade_reverify_blocks_runtime_readiness_without_sidecars() -> None:
    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=[],
        enforce_out_of_sample_reverify_gate=True,
        horizon_years=5.0,
        generated_utc="2026-06-21T00:00:00Z",
    )

    dashboard = statuses["operator_dashboard_payload.json"]
    reverify = statuses["out_of_sample_live_grade_reverify_status.json"]
    conditions = {
        condition["id"]: condition
        for condition in dashboard["pass_condition_status"]["conditions"]
    }

    assert reverify["status"] == "NO_GO_OUT_OF_SAMPLE_LIVE_GRADE_REVERIFY_INCOMPLETE"
    assert "HOLDOUT_REVERIFY_NOT_PASSED" in reverify["blocker_reasons"]
    assert "REALTIME_PAPER_REVERIFY_NOT_PASSED" in reverify["blocker_reasons"]
    assert dashboard["overall_status"] == "NO_GO"
    assert "out_of_sample_live_grade_reverify_status" in dashboard["remaining_blockers"]
    assert conditions["out_of_sample_live_grade_reverify"]["status"] == "NO_GO"
    assert statuses["one_thousand_x_feasibility_status.json"]["status"] == (
        "NO_GO_1000X_FEASIBILITY_REQUIRES_OUT_OF_SAMPLE_LIVE_GRADE_REVERIFY"
    )


def test_out_of_sample_live_grade_reverify_passes_frozen_holdout_and_realtime_rows(
    monkeypatch,
) -> None:
    monkeypatch.setattr(status_module, "OUT_OF_SAMPLE_MIN_HOLDOUT_OUTCOMES", 4)
    monkeypatch.setattr(status_module, "OUT_OF_SAMPLE_MIN_REALTIME_CLOSED_OUTCOMES", 4)
    monkeypatch.setattr(status_module, "OUT_OF_SAMPLE_MIN_SYMBOL_COUNT", 3)
    monkeypatch.setattr(status_module, "OUT_OF_SAMPLE_MAX_PROFIT_CONCENTRATION_SHARE", 1.0)
    manifest = status_module._frozen_live_grade_policy_manifest("2026-06-21T00:00:00Z")
    fingerprint = manifest["selector_policy_fingerprint"]
    holdout_rows = [
        _out_of_sample_reverify_row(
            fingerprint=fingerprint,
            row_id="holdout-1",
            symbol="BTCUSDT",
            side="long",
            outcome_bps=40.0,
            decision_minute=1,
        ),
        _out_of_sample_reverify_row(
            fingerprint=fingerprint,
            row_id="holdout-2",
            symbol="ETHUSDT",
            side="short",
            outcome_bps=-10.0,
            decision_minute=2,
        ),
        _out_of_sample_reverify_row(
            fingerprint=fingerprint,
            row_id="holdout-3",
            symbol="SOLUSDT",
            side="long",
            outcome_bps=30.0,
            decision_minute=3,
        ),
        _out_of_sample_reverify_row(
            fingerprint=fingerprint,
            row_id="holdout-4",
            symbol="ETHUSDT",
            side="short",
            outcome_bps=20.0,
            decision_minute=4,
        ),
    ]
    realtime_rows = [
        _out_of_sample_reverify_row(
            fingerprint=fingerprint,
            row_id=f"realtime-{index}",
            symbol=symbol,
            side=side,
            outcome_bps=outcome_bps,
            decision_minute=10 + index,
            holdout=False,
        )
        for index, (symbol, side, outcome_bps) in enumerate(
            (
                ("BTCUSDT", "long", 35.0),
                ("ETHUSDT", "short", -5.0),
                ("SOLUSDT", "long", 25.0),
                ("ETHUSDT", "short", 15.0),
            ),
            start=1,
        )
    ]

    status = status_module._out_of_sample_live_grade_reverify_status(
        generated_utc="2026-06-21T00:00:00Z",
        operator_safety={
            "paper_only": True,
            "places_real_order": False,
            "test_orders": False,
            "leverage_mutation": False,
            "margin_mode_mutation": False,
            "live_gate": "blocked_human_only",
        },
        accelerated_replay_status={
            "validated_replay_candidate_count": 229,
            "validated_replay_symbol_count": 56,
            "validated_replay_expectancy_after_cost_bps": 30.0,
            "validated_replay_profit_factor": 3.32,
        },
        holdout_rows=holdout_rows,
        holdout_source_status={"source": "unit_holdout", "exists": True},
        realtime_rows=realtime_rows,
        realtime_source_status={"source": "unit_realtime", "exists": True},
    )

    assert status["status"] == "PASSED"
    assert status["holdout_reverify_status"]["status"] == "PASSED"
    assert status["realtime_paper_reverify_status"]["status"] == "PASSED"
    assert status["realtime_vs_replay_projection_status"]["status"] == "PASSED"
    assert status["honest_interpretation"]["live_readiness"] == "blocked_human_only"


def test_out_of_sample_live_grade_reverify_fails_symbol_concentration(
    monkeypatch,
) -> None:
    monkeypatch.setattr(status_module, "OUT_OF_SAMPLE_MIN_HOLDOUT_OUTCOMES", 4)
    monkeypatch.setattr(status_module, "OUT_OF_SAMPLE_MIN_REALTIME_CLOSED_OUTCOMES", 4)
    monkeypatch.setattr(status_module, "OUT_OF_SAMPLE_MIN_SYMBOL_COUNT", 3)
    monkeypatch.setattr(status_module, "OUT_OF_SAMPLE_MAX_PROFIT_CONCENTRATION_SHARE", 0.35)
    manifest = status_module._frozen_live_grade_policy_manifest("2026-06-21T00:00:00Z")
    fingerprint = manifest["selector_policy_fingerprint"]
    concentrated_rows = [
        _out_of_sample_reverify_row(
            fingerprint=fingerprint,
            row_id="concentrated-1",
            symbol="BTCUSDT",
            side="long",
            outcome_bps=80.0,
            decision_minute=1,
        ),
        _out_of_sample_reverify_row(
            fingerprint=fingerprint,
            row_id="concentrated-2",
            symbol="ETHUSDT",
            side="short",
            outcome_bps=5.0,
            decision_minute=2,
        ),
        _out_of_sample_reverify_row(
            fingerprint=fingerprint,
            row_id="concentrated-3",
            symbol="SOLUSDT",
            side="long",
            outcome_bps=5.0,
            decision_minute=3,
        ),
        _out_of_sample_reverify_row(
            fingerprint=fingerprint,
            row_id="concentrated-4",
            symbol="ETHUSDT",
            side="short",
            outcome_bps=-10.0,
            decision_minute=4,
        ),
    ]
    realtime_rows = [
        _out_of_sample_reverify_row(
            fingerprint=fingerprint,
            row_id=f"realtime-pass-{index}",
            symbol=symbol,
            side=side,
            outcome_bps=outcome_bps,
            decision_minute=10 + index,
            holdout=False,
        )
        for index, (symbol, side, outcome_bps) in enumerate(
            (
                ("BTCUSDT", "long", 35.0),
                ("ETHUSDT", "short", -5.0),
                ("SOLUSDT", "long", 25.0),
                ("ETHUSDT", "short", 15.0),
            ),
            start=1,
        )
    ]

    status = status_module._out_of_sample_live_grade_reverify_status(
        generated_utc="2026-06-21T00:00:00Z",
        operator_safety={
            "paper_only": True,
            "places_real_order": False,
            "test_orders": False,
            "leverage_mutation": False,
            "margin_mode_mutation": False,
            "live_gate": "blocked_human_only",
        },
        accelerated_replay_status={
            "validated_replay_candidate_count": 229,
            "validated_replay_symbol_count": 56,
            "validated_replay_expectancy_after_cost_bps": 30.0,
            "validated_replay_profit_factor": 3.32,
        },
        holdout_rows=concentrated_rows,
        holdout_source_status={"source": "unit_holdout", "exists": True},
        realtime_rows=realtime_rows,
        realtime_source_status={"source": "unit_realtime", "exists": True},
    )

    holdout = status["holdout_reverify_status"]
    assert status["status"] == "NO_GO_OUT_OF_SAMPLE_LIVE_GRADE_REVERIFY_INCOMPLETE"
    assert "HOLDOUT_REVERIFY_NOT_PASSED" in status["blocker_reasons"]
    assert "HOLDOUT_PROFIT_CONCENTRATION_EXCEEDED" in holdout["blocker_reasons"]
    assert holdout["profit_concentration_status"]["symbol"]["status"] == "CONCENTRATED"


def test_accelerated_replay_audits_post_hoc_bundles_before_counting_labels() -> None:
    valid_bundle = {
        "prediction_id": "bundle-valid-1",
        "symbol": "HBARUSDT",
        "timeframe": "1m",
        "side": "short",
        "generated_at": "2026-06-20T12:10:00Z",
        "bundle_generated_at": "2026-06-20T12:10:00Z",
        "decision_time": "2026-06-20T12:00:00Z",
        "available_at": "2026-06-20T11:59:30Z",
        "entry_feature_generated_at": "2026-06-20T11:59:20Z",
        "feature_cutoff": "2026-06-20T11:55:00Z",
        "entry_feature_candle_closed_confirmed": True,
        "trainer_output": {
            "selected_action": "short",
            "confidence_calibrated": 0.64,
            "expected_move_after_cost_bps": -18.0,
        },
        "future_outcomes": {
            "5m": {
                "after_cost_return_bps": 12.0,
                "drawdown_bps": 4.0,
                "max_favorable_bps": 20.0,
                "max_adverse_bps": -4.0,
                "fee_drag_bps": 5.0,
                "slippage_estimate_bps": 2.0,
                "source": "V2_MINER_PRICE_TIMELINE",
                "samples": 4,
            },
        },
        "label": "correct_trade",
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "live_symbols": [],
    }
    missing_available_at_bundle = {
        **valid_bundle,
        "prediction_id": "bundle-missing-available-at",
        "symbol": "SUIUSDT",
        "available_at": None,
        "entry_feature_available_at": None,
    }

    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=[],
        post_hoc_replay_bundles=[valid_bundle, missing_available_at_bundle],
        horizon_years=5.0,
        generated_utc="2026-06-21T00:00:00Z",
    )

    replay = statuses["accelerated_counterfactual_replay_status.json"]
    audit = replay["post_hoc_replay_bundle_audit"]

    assert audit["complete_primary_outcome_count"] == 2
    assert audit["event_time_valid_label_count"] == 1
    assert audit["invalid_reason_counts"]["MISSING_AVAILABLE_AT"] == 1
    assert replay["post_hoc_replay_event_time_valid_label_count"] == 1
    assert replay["event_time_valid_label_count"] == 1
    assert replay["side_counts"] == {"short": 1}
    assert replay["source_kind_counts"] == {"post_hoc_replay_outcome_bundle": 1}
    assert replay["valid_label_sample"][0]["source_kind"] == "post_hoc_replay_outcome_bundle"


def test_accelerated_replay_audits_native_trainer_replay_sidecar_before_counting_labels() -> None:
    valid_row = {
        "row_id": "native-valid-1",
        "feature_snapshot_id": "BTCUSDT:1m:2026-06-20T12:00:00Z",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "action": "long",
        "decision_time": "2026-06-20T12:00:00Z",
        "available_at": "2026-06-20T11:59:59Z",
        "entry_feature_available_at": "2026-06-20T11:59:59Z",
        "entry_feature_generated_at": "2026-06-20T11:59:58Z",
        "feature_cutoff": "2026-06-20T11:59:00Z",
        "entry_feature_cutoff": "2026-06-20T11:59:00Z",
        "entry_feature_candle_closed_confirmed": True,
        "after_cost_return_bps": 18.0,
        "realized_after_cost_return_bps": 18.0,
        "gross_notional_usd": 1000.0,
        "allocated_margin_usd": 500.0,
        "recommended_leverage": 2.0,
        "recommended_margin_mode": "isolated_paper_simulated",
        "stop_distance_bps": 75.0,
        "take_profit_structure": "single_target",
        "hedge_budget_usd": 0.0,
        "actual_observed_spread_entry_bps": 1.2,
        "orderbook_depth_usd": 250000.0,
        "expected_fees_usd": 0.2,
        "expected_slippage_usd": 0.1,
        "expected_funding_usd": 0.0,
        "liquidation_buffer_bps": 4000.0,
        "correlation_exposure_pct": 0.12,
        "paper_only": True,
        "places_real_order": False,
        "live_gate": "blocked_human_only",
    }
    missing_available_at_row = {
        **valid_row,
        "row_id": "native-missing-available-at",
        "symbol": "ETHUSDT",
        "available_at": None,
        "entry_feature_available_at": None,
    }

    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=[],
        native_trainer_replay_evidence_rows=[valid_row, missing_available_at_row],
        horizon_years=5.0,
        generated_utc="2026-06-21T00:00:00Z",
    )

    replay = statuses["accelerated_counterfactual_replay_status.json"]
    audit = replay["native_trainer_replay_evidence_audit"]

    assert audit["source_row_count"] == 2
    assert audit["complete_after_cost_outcome_count"] == 2
    assert audit["event_time_valid_label_count"] == 1
    assert audit["invalid_reason_counts"]["MISSING_AVAILABLE_AT"] == 1
    assert replay["native_trainer_replay_event_time_valid_label_count"] == 1
    assert replay["event_time_valid_label_count"] == 1
    assert replay["side_counts"] == {"long": 1}
    assert replay["source_kind_counts"] == {"native_trainer_replay_dataset": 1}
    assert replay["simulation_accounting_coverage_status"]["status"] == "PASSED"
    assert replay["valid_label_sample"][0]["source_kind"] == "native_trainer_replay_dataset"


def test_closed_candle_replay_generator_uses_closed_features_and_future_labels_only() -> None:
    candles = _return_candles(
        "BTCUSDT",
        [0.002, 0.001, -0.0005, 0.0015, 0.002, 0.001, 0.0005, 0.001, 0.002, 0.001],
        start_ms=_ms("2026-06-20T00:00:00Z"),
    )
    unfinished = {
        **candles[-1],
        "close_time": _ms("2026-06-20T00:11:00Z"),
        "candle_close_time": _ms("2026-06-20T00:11:00Z"),
        "available_at": _ms("2026-06-20T00:11:01Z"),
        "candle_closed_confirmed": False,
    }

    rows, status = generate_closed_candle_replay_evidence(
        {"v2:market:ohlcv_closed:binance:BTCUSDT:1m": [*candles, unfinished]},
        generated_utc="2026-06-21T00:00:00Z",
        max_rows=8,
        min_past_candles=4,
        future_horizon_candles=2,
        require_complete_timeframe_symbols=False,
    )

    assert status["status"] == "READY_CLOSED_CANDLE_REPLAY_EVIDENCE"
    assert status["reject_counts"]["UNFINISHED_CANDLE"] == 1
    assert rows
    first = rows[0]
    assert first["counterfactual_source_kind"] == "closed_candle_replay"
    assert first["entry_feature_candle_closed_confirmed"] is True
    assert first["future_labels_used_as_features"] is False
    assert first["future_label_used_as_outcome_only"] is True
    assert first["feature_cutoff"] <= first["decision_time"]
    assert first["available_at"] <= first["decision_time"]
    assert first["future_label_close_time"] > first["decision_time"]
    assert first["paper_only"] is True
    assert first["places_real_order"] is False
    for field in (
        "gross_notional_usd",
        "allocated_margin_usd",
        "recommended_leverage",
        "recommended_margin_mode",
        "stop_distance_bps",
        "take_profit_structure",
        "hedge_budget_usd",
        "actual_observed_spread_entry_bps",
        "orderbook_depth_usd",
        "expected_fees_usd",
        "expected_slippage_usd",
        "expected_funding_usd",
        "liquidation_buffer_bps",
        "correlation_exposure_pct",
    ):
        assert field in first


def test_accelerated_replay_audits_closed_candle_replay_sidecar_before_counting_labels() -> None:
    rows, _status = generate_closed_candle_replay_evidence(
        {
            "v2:market:ohlcv_closed:binance:BTCUSDT:1m": _return_candles(
                "BTCUSDT",
                [0.001, 0.001, 0.001, 0.001, 0.001, 0.001, 0.001, 0.001],
                start_ms=_ms("2026-06-20T00:00:00Z"),
            )
        },
        generated_utc="2026-06-21T00:00:00Z",
        max_rows=2,
        min_past_candles=3,
        future_horizon_candles=2,
        require_complete_timeframe_symbols=False,
    )
    valid_row = rows[0]
    invalid_row = {
        **valid_row,
        "row_id": "closed-candle-invalid-future-label",
        "prediction_id": "closed-candle-invalid-future-label",
        "future_label_close_time": valid_row["decision_time"],
    }

    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=[],
        closed_candle_replay_evidence_rows=[valid_row, invalid_row],
        horizon_years=5.0,
        generated_utc="2026-06-21T00:00:00Z",
    )

    replay = statuses["accelerated_counterfactual_replay_status.json"]
    audit = replay["closed_candle_replay_evidence_audit"]

    assert audit["source_row_count"] == 2
    assert audit["complete_after_cost_outcome_count"] == 2
    assert audit["event_time_valid_label_count"] == 1
    assert audit["invalid_reason_counts"]["FUTURE_LABEL_NOT_AFTER_DECISION_TIME"] == 1
    assert replay["closed_candle_replay_event_time_valid_label_count"] == 1
    assert replay["event_time_valid_label_count"] == 1
    assert replay["source_kind_counts"] == {"closed_candle_replay": 1}
    assert replay["simulation_accounting_coverage_status"]["status"] == "PASSED"
    assert replay["valid_label_sample"][0]["source_kind"] == "closed_candle_replay"


def test_counterfactual_sweep_uses_safe_durable_accepted_ledger_rows() -> None:
    statuses = build_statuses(
        ledger={
            "open_positions": [],
            "closed_trades": [],
            "accepted": _accepted_intent_all_timeframes(),
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=[],
        paper_intents=[],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    counterfactual = statuses["counterfactual_capital_sweep_status.json"]
    accepted_evidence = counterfactual["paper_ledger_accepted_counterfactual_evidence"]

    assert counterfactual["paper_signal_row_count"] == 0
    assert counterfactual["paper_intent_row_count"] == 0
    assert counterfactual["paper_ledger_accepted_counterfactual_row_count"] == 5
    assert accepted_evidence["status"] == "READY"
    assert accepted_evidence["source"] == "v2:paper:ledger.accepted"
    assert accepted_evidence["counterfactual_row_count"] == 5
    assert accepted_evidence["bounded_to_current_source_symbol_timeframe_cells"] is False
    assert counterfactual["counterfactual_source_row_count"] == 5
    assert counterfactual["status"] == "PASSED"
    assert counterfactual["source_coverage_status"] == "PASSED"
    assert counterfactual["a_grade_readiness"]["source_kind_counts"] == {
        "paper_ledger_accepted": 5
    }
    assert counterfactual["market_cost_evidence_coverage_status"]["status"] == "PASSED"
    assert counterfactual["market_cost_evidence_coverage_status"]["complete_by_source_kind"] == {
        "paper_ledger_accepted": 5
    }
    selected = counterfactual["best_configurations_sample"][0]["selected"]
    assert selected["market_cost_evidence_sources"] == {
        "fee_bps": "adaptive_allocation.model_inputs.fee_bps",
        "funding_bps": "adaptive_allocation.model_inputs.expected_funding_bps",
        "slippage_bps": "adaptive_allocation.model_inputs.slippage_bps",
        "spread_bps": "adaptive_allocation.model_inputs.spread_bps",
    }


def test_counterfactual_durable_accepted_rows_do_not_expand_active_source_coverage() -> None:
    accepted_rows = _accepted_intent_all_timeframes(symbol="DOGEUSDT")
    statuses = build_statuses(
        ledger={
            "open_positions": [],
            "closed_trades": [],
            "accepted": accepted_rows,
        },
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=_paper_signal_all_timeframes(symbol="BTCUSDT"),
        paper_intents=[],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    counterfactual = statuses["counterfactual_capital_sweep_status.json"]
    accepted_evidence = counterfactual["paper_ledger_accepted_counterfactual_evidence"]

    assert counterfactual["paper_signal_row_count"] == 5
    assert counterfactual["paper_ledger_accepted_counterfactual_row_count"] == 0
    assert accepted_evidence["bounded_to_current_source_symbol_timeframe_cells"] is True
    assert accepted_evidence["current_source_symbol_timeframe_cell_count"] == 5
    assert accepted_evidence["excluded_reason_counts"] == {
        "OUTSIDE_CURRENT_SOURCE_SYMBOL_TIMEFRAME_CELL": 5
    }
    assert counterfactual["source_coverage"]["source_symbol_sample"] == ["BTCUSDT"]
    assert counterfactual["source_coverage_status"] == "PASSED"


def test_prediction_counterfactual_probe_is_non_gating() -> None:
    prediction_row = _paper_signal(
        source_redis_key="v2:prediction:ETHUSDT:1m",
        symbol="ETHUSDT",
        timeframe="1m",
        side="long",
        action="long",
        confidence_calibrated=0.91,
        expected_move_after_cost_bps=110.0,
    )
    for field in (
        "gross_notional_usd",
        "orderbook_depth_usd",
        "actual_observed_spread_entry_bps",
        "expected_slippage_bps",
        "fee_bps",
        "expected_funding_bps",
    ):
        prediction_row.pop(field, None)

    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=_paper_signal_all_timeframes(),
        prediction_rows=[prediction_row],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    counterfactual = statuses["counterfactual_capital_sweep_status.json"]
    probe = counterfactual["prediction_counterfactual_probe"]

    assert counterfactual["status"] == "PASSED"
    assert counterfactual["counterfactual_source_row_count"] == 5
    assert counterfactual["paper_signal_row_count"] == 5
    assert counterfactual["prediction_row_count"] == 1
    assert probe["probe_participates_in_counterfactual_pass_gate"] is False
    assert probe["source_coverage_required_for_pass"] is False
    assert probe["prediction_row_count"] == 1
    assert probe["a_grade_before_temporal_count"] == 1
    assert probe["event_time_valid_candidate_count"] == 1
    assert probe["best_configuration_count"] == 0
    assert probe["skipped_no_feasible_configuration_reason_counts"] == {
        "MISSING_ACTUAL_SPREAD": 1,
        "MISSING_FEES": 1,
        "MISSING_FUNDING": 1,
        "MISSING_MARKET_DEPTH": 1,
        "MISSING_SLIPPAGE": 1,
    }
    probe_market_cost_coverage = probe["market_cost_evidence_coverage_status"]
    assert probe_market_cost_coverage["status"] == "NO_GO_MARKET_COST_EVIDENCE_INCOMPLETE"
    assert probe_market_cost_coverage["source_row_count"] == 1
    assert probe_market_cost_coverage["candidate_row_count"] == 1
    assert probe_market_cost_coverage["complete_candidate_count"] == 0
    assert probe_market_cost_coverage["missing_reason_counts"] == {
        "MISSING_ACTUAL_SPREAD": 1,
        "MISSING_FEES": 1,
        "MISSING_FUNDING": 1,
        "MISSING_MARKET_DEPTH": 1,
        "MISSING_SLIPPAGE": 1,
    }
    readiness = probe["a_grade_readiness"]
    assert readiness["source_kind_counts"] == {"prediction": 1}
    assert readiness["source_kind_readiness"]["prediction"]["a_grade_before_temporal_count"] == 1
    assert readiness["source_kind_readiness"]["prediction"]["event_time_valid_candidate_count"] == 1
    assert readiness["source_kind_readiness"]["prediction"]["best_configuration_count"] == 0
    assert readiness["source_kind_readiness"]["prediction"]["no_feasible_configuration_count"] == 1


def test_near_a_grade_counterfactual_probe_is_non_gating() -> None:
    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=_paper_signal_all_timeframes(
            confidence_calibrated=0.70,
            signal_id="sig-near-grade",
            prediction_id="pred-near-grade",
            feature_snapshot_id="snap-near-grade",
            market_cost_evidence_status="COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE",
            market_cost_evidence_missing_fields=[],
            market_cost_evidence_pit_reject_reasons=[],
        ),
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    counterfactual = statuses["counterfactual_capital_sweep_status.json"]
    dashboard = statuses["operator_dashboard_payload.json"]
    probe = counterfactual["near_a_grade_counterfactual_probe"]
    progress = counterfactual["counterfactual_replay_progress"]
    next_gaps = counterfactual["counterfactual_next_evidence_gaps"]
    strict_burn_down = counterfactual["strict_a_grade_acquisition_burn_down"]

    assert counterfactual["status"] == "NO_GO_COUNTERFACTUAL_REPLAY_NOT_COMPLETE"
    assert counterfactual["counterfactual_blocker_reasons"] == ["NO_A_GRADE_SIGNALS"]
    assert progress["counterfactual_blocker_reasons"] == ["NO_A_GRADE_SIGNALS"]
    assert progress["counterfactual_next_evidence_gaps"] == next_gaps
    assert next_gaps["status"] == "NO_GO_COUNTERFACTUAL_EVIDENCE_GAPS_REMAIN"
    assert next_gaps["required_next_evidence"] == [
        "PRODUCE_A_GRADE_SIGNAL_WITH_CONFIDENCE_AND_POSITIVE_AFTER_COST_EDGE",
        "GENERATE_FEASIBLE_COUNTERFACTUAL_CONFIGURATION_WITH_DEPTH_AND_COSTS",
    ]
    assert next_gaps["a_grade_signal_gap_count"] == 1
    assert next_gaps["best_configuration_gap_count"] == 1
    assert next_gaps["closest_a_grade_capture_request_sample"] == (
        counterfactual["near_a_grade_sample"][:5]
    )
    assert next_gaps["strict_a_grade_acquisition_burn_down"] == strict_burn_down
    assert progress["strict_a_grade_acquisition_burn_down"] == strict_burn_down
    assert dashboard["operator_go_readiness"]["strict_a_grade_acquisition_burn_down"] == (
        strict_burn_down
    )
    assert strict_burn_down["status"] == "NO_GO_NO_STRICT_A_GRADE_SIGNALS"
    assert strict_burn_down["strict_confidence_threshold"] == 0.75
    assert strict_burn_down["historical_a_grade_signal_count"] == 0
    assert strict_burn_down["event_time_valid_a_grade_count"] == 0
    assert strict_burn_down["best_configuration_count"] == 0
    assert strict_burn_down["a_grade_signal_gap_count"] == 1
    assert strict_burn_down["closest_confidence_gap_to_a_grade"] == 0.05
    assert strict_burn_down["closest_edge_gap_to_positive_bps"] == 0.0
    assert strict_burn_down["near_a_grade_candidate_count"] == 5
    assert strict_burn_down["near_a_grade_market_cost_ready_if_confidence_improves_count"] == 5
    assert strict_burn_down["strict_a_grade_gate_relaxed"] is False
    assert strict_burn_down["counts_as_counterfactual_a_grade_gate"] is False
    closest = next_gaps["closest_a_grade_capture_request_sample"][0]
    assert closest["source_kind"] == "paper_signal"
    assert closest["signal_id"] == "sig-near-grade"
    assert closest["prediction_id"] == "pred-near-grade"
    assert closest["feature_snapshot_id"] == "snap-near-grade"
    assert closest["decision_time"] == "2026-06-19T12:00:00Z"
    assert closest["available_at"] == "2026-06-19T11:59:00Z"
    assert closest["generated_at"] == "2026-06-19T11:58:00Z"
    assert closest["feature_cutoff"] == "2026-06-19T11:55:00Z"
    assert str(closest["source_redis_key"]).startswith("v2:signals:paper:BTCUSDT:")
    assert closest["market_cost_evidence_status"] == "COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE"
    assert closest["market_cost_evidence_missing_fields"] == []
    assert closest["market_cost_evidence_pit_reject_reasons"] == [
        "MISSING_FEATURE_PAYLOAD_FOR_MARKET_COST_EVIDENCE"
    ]
    assert counterfactual["historical_a_grade_signal_count"] == 0
    assert counterfactual["best_configuration_count"] == 0
    assert probe["probe_participates_in_counterfactual_pass_gate"] is False
    assert probe["confidence_threshold"] == 0.65
    assert probe["a_grade_thresholds"]["confidence_min"] == 0.65
    assert probe["status"] == "PASSED"
    assert probe["a_grade_before_temporal_count"] == 5
    assert probe["event_time_valid_candidate_count"] == 5
    assert probe["skipped_temporal_invalid_count"] == 0
    assert probe["skipped_temporal_invalid_sample"] == []
    assert probe["skipped_no_feasible_configuration_count"] == 0
    assert probe["skipped_no_feasible_configuration_reason_counts"] == {}
    assert probe["skipped_no_feasible_configuration_sample"] == []
    assert probe["best_configuration_count"] == 5
    assert probe["config_space_audit"]["candidate_count"] == 5
    assert probe["config_space_audit"]["theoretical_configuration_count"] == 2700
    assert probe["config_space_audit"]["considered_count"] == 2700
    assert probe["config_space_audit"]["feasible_count"] == probe["sweep_result_count"]
    assert probe["hedge_accounting_audit"]["status"] == "PASSED"


def test_counterfactual_reports_strict_a_grade_intersection_blockers() -> None:
    high_confidence_no_edge = _paper_signal(
        symbol="HIGHNOEDGEUSDT",
        timeframe="1m",
        side="long",
        action="long",
        confidence_calibrated=0.80,
        expected_move_after_cost_bps=-5.0,
        signal_id="sig-high-no-edge",
        prediction_id="pred-high-no-edge",
    )
    low_confidence_positive_edge = _paper_signal(
        symbol="LOWEDGEUSDT",
        timeframe="5m",
        side="long",
        action="long",
        confidence_calibrated=0.70,
        expected_move_after_cost_bps=40.0,
        signal_id="sig-low-edge",
        prediction_id="pred-low-edge",
    )
    blocked_high_confidence_positive_edge = _paper_signal(
        symbol="BLOCKEDGEUSDT",
        timeframe="15m",
        side="short",
        action="short",
        confidence_calibrated=0.82,
        expected_move_after_cost_bps=25.0,
        allocator_decision="BLOCK_NO_EDGE",
        signal_id="sig-blocked-edge",
        prediction_id="pred-blocked-edge",
    )

    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=[
            high_confidence_no_edge,
            low_confidence_positive_edge,
            blocked_high_confidence_positive_edge,
        ],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    counterfactual = statuses["counterfactual_capital_sweep_status.json"]
    dashboard = statuses["operator_dashboard_payload.json"]
    analysis = counterfactual["a_grade_blocker_analysis"]
    next_gaps = counterfactual["counterfactual_next_evidence_gaps"]

    assert counterfactual["status"] == "NO_GO_COUNTERFACTUAL_REPLAY_NOT_COMPLETE"
    assert analysis["status"] == "NO_GO_A_GRADE_INTERSECTION_INCOMPLETE"
    assert analysis["confidence_threshold"] == 0.75
    assert analysis["row_count"] == 3
    assert analysis["source_kind_counts"] == {"paper_signal": 3}
    assert analysis["directional_row_count"] == 3
    assert analysis["confidence_at_or_above_threshold_count"] == 2
    assert analysis["positive_after_cost_edge_count"] == 2
    assert analysis["positive_edge_below_confidence_count"] == 1
    assert analysis["high_confidence_missing_or_non_positive_edge_count"] == 1
    assert analysis["high_confidence_and_positive_edge_count"] == 1
    assert analysis["high_confidence_positive_edge_allocator_blocked_count"] == 1
    assert analysis["strict_a_grade_before_temporal_count"] == 0
    assert analysis["event_time_valid_a_grade_count"] == 0
    assert analysis["blocker_reasons"] == [
        "NO_STRICT_A_GRADE_INTERSECTION",
        "POSITIVE_EDGE_ROWS_BELOW_CONFIDENCE_THRESHOLD",
        "HIGH_CONFIDENCE_ROWS_MISSING_OR_NON_POSITIVE_EDGE",
        "HIGH_CONFIDENCE_POSITIVE_EDGE_ROWS_ALLOCATOR_BLOCKED",
    ]
    assert analysis["not_a_grade_reason_counts"] == {
        "ALLOCATOR_BLOCK_NO_EDGE": 1,
        "LOW_CONFIDENCE": 1,
        "NON_POSITIVE_AFTER_COST_EDGE": 1,
    }
    assert analysis["high_confidence_missing_or_non_positive_edge_sample"][0]["symbol"] == (
        "HIGHNOEDGEUSDT"
    )
    assert analysis["high_confidence_missing_or_non_positive_edge_sample"][0]["reasons"] == [
        "NON_POSITIVE_AFTER_COST_EDGE"
    ]
    assert analysis["positive_edge_below_confidence_sample"][0]["symbol"] == "LOWEDGEUSDT"
    assert analysis["positive_edge_below_confidence_sample"][0]["reasons"] == ["LOW_CONFIDENCE"]
    assert analysis["high_confidence_positive_edge_allocator_blocked_sample"][0]["symbol"] == (
        "BLOCKEDGEUSDT"
    )
    assert analysis["high_confidence_positive_edge_allocator_blocked_sample"][0]["reasons"] == [
        "ALLOCATOR_BLOCK_NO_EDGE"
    ]
    assert counterfactual["counterfactual_replay_progress"]["a_grade_blocker_analysis"] == analysis
    assert next_gaps["a_grade_blocker_analysis"] == analysis
    assert dashboard["operator_go_readiness"]["a_grade_blocker_analysis"] == analysis
    assert (
        dashboard["operator_go_readiness"]["counterfactual_evidence_acquisition_status"]
        == counterfactual["counterfactual_evidence_acquisition_status"]
    )

    go_no_go = status_module.go_no_go_markdown(dashboard)
    assert "A-grade blocker analysis" in go_no_go
    assert "A-grade intersection counts" in go_no_go
    assert "Counterfactual evidence acquisition" in go_no_go
    assert "HIGHNOEDGEUSDT" in go_no_go


def test_near_a_grade_counterfactual_probe_exposes_no_feasible_count_and_sample() -> None:
    paper_signals = _paper_signal_all_timeframes(confidence_calibrated=0.70)
    for field in (
        "orderbook_depth_usd",
        "actual_observed_spread_entry_bps",
        "expected_slippage_bps",
        "fee_bps",
        "expected_funding_bps",
    ):
        paper_signals[0].pop(field)

    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=paper_signals,
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    counterfactual = statuses["counterfactual_capital_sweep_status.json"]
    probe = counterfactual["near_a_grade_counterfactual_probe"]
    resolution = statuses["positive_edge_below_a_grade_resolution.json"]
    replay = statuses["accelerated_counterfactual_replay_status.json"]
    next_gaps = counterfactual["counterfactual_next_evidence_gaps"]
    acquisition = counterfactual["counterfactual_evidence_acquisition_status"]

    assert counterfactual["status"] == "NO_GO_COUNTERFACTUAL_REPLAY_NOT_COMPLETE"
    assert counterfactual["counterfactual_blocker_reasons"] == ["NO_A_GRADE_SIGNALS"]
    assert next_gaps["required_next_evidence"] == [
        "PRODUCE_A_GRADE_SIGNAL_WITH_CONFIDENCE_AND_POSITIVE_AFTER_COST_EDGE",
        "CAPTURE_EXPLICIT_ENTRY_MARKET_COST_FIELDS_AT_DECISION_TIME",
        "GENERATE_FEASIBLE_COUNTERFACTUAL_CONFIGURATION_WITH_DEPTH_AND_COSTS",
    ]
    assert next_gaps["near_a_grade_complete_market_cost_evidence_count"] == 4
    assert next_gaps["near_a_grade_candidate_market_cost_evidence_count"] == 5
    assert len(next_gaps["near_a_grade_market_cost_ready_sample"]) == 4
    assert next_gaps["near_a_grade_missing_market_cost_reason_counts"] == {
        "MISSING_ACTUAL_SPREAD": 1,
        "MISSING_FEES": 1,
        "MISSING_FUNDING": 1,
        "MISSING_MARKET_DEPTH": 1,
        "MISSING_SLIPPAGE": 1,
    }
    assert next_gaps["near_a_grade_pruned_configuration_reason_counts"] == {
        "MISSING_MARKET_DEPTH": 540,
    }
    assert probe["probe_participates_in_counterfactual_pass_gate"] is False
    assert probe["status"] == "NO_GO_COUNTERFACTUAL_REPLAY_NOT_COMPLETE"
    assert probe["a_grade_before_temporal_count"] == 5
    assert probe["event_time_valid_candidate_count"] == 5
    assert probe["best_configuration_count"] == 4
    assert probe["skipped_no_feasible_configuration_count"] == 1
    assert probe["skipped_no_feasible_configuration_reason_counts"] == {
        "MISSING_ACTUAL_SPREAD": 1,
        "MISSING_FEES": 1,
        "MISSING_FUNDING": 1,
        "MISSING_MARKET_DEPTH": 1,
        "MISSING_SLIPPAGE": 1,
    }
    assert probe["skipped_no_feasible_configuration_sample"] == [
        {
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "source_kind": "paper_signal",
            "reasons": [
                "MISSING_ACTUAL_SPREAD",
                "MISSING_FEES",
                "MISSING_FUNDING",
                "MISSING_MARKET_DEPTH",
                "MISSING_SLIPPAGE",
            ],
        }
    ]
    market_cost_coverage = probe["market_cost_evidence_coverage_status"]
    assert market_cost_coverage["status"] == "NO_GO_MARKET_COST_EVIDENCE_INCOMPLETE"
    assert market_cost_coverage["candidate_row_count"] == 5
    assert market_cost_coverage["complete_candidate_count"] == 4
    assert market_cost_coverage["missing_reason_counts"] == {
        "MISSING_ACTUAL_SPREAD": 1,
        "MISSING_FEES": 1,
        "MISSING_FUNDING": 1,
        "MISSING_MARKET_DEPTH": 1,
        "MISSING_SLIPPAGE": 1,
    }
    assert market_cost_coverage["incomplete_candidate_sample"][0]["missing_market_cost_evidence"] == [
        "MISSING_ACTUAL_SPREAD",
        "MISSING_SLIPPAGE",
        "MISSING_FEES",
        "MISSING_FUNDING",
        "MISSING_MARKET_DEPTH",
    ]
    assert acquisition["status"] == "WAITING_FOR_A_GRADE_CONFIDENCE_WITH_MARKET_COST_READY"
    assert acquisition["strict_a_grade_gate_relaxed"] is False
    assert acquisition["strict_a_grade_candidate_count"] == 0
    assert acquisition["near_a_grade_candidate_count"] == 5
    assert acquisition["near_a_grade_market_cost_complete_count"] == 4
    assert acquisition["near_a_grade_market_cost_incomplete_count"] == 1
    assert acquisition["near_a_grade_market_cost_ready_if_confidence_improves_count"] == 4
    assert acquisition["blocker_reasons"] == [
        "NO_STRICT_A_GRADE_CANDIDATE",
        "POSITIVE_EDGE_BELOW_CONFIDENCE_THRESHOLD",
        "NEAR_A_GRADE_MARKET_COST_CAPTURE_INCOMPLETE",
    ]
    assert acquisition["required_next_evidence"] == [
        "PRODUCE_A_GRADE_SIGNAL_WITH_CONFIDENCE_AND_POSITIVE_AFTER_COST_EDGE",
        "CAPTURE_EXPLICIT_ENTRY_MARKET_COST_FIELDS_AT_DECISION_TIME",
    ]
    assert len(acquisition["near_a_grade_market_cost_ready_sample"]) == 4
    assert acquisition["near_a_grade_market_cost_capture_required_sample"][0]["symbol"] == "BTCUSDT"


def test_counterfactual_probe_enriches_paper_signal_temporal_context_from_prediction_lineage() -> None:
    paper_signals = _paper_signal_all_timeframes(confidence_calibrated=0.70)
    prediction_rows = []
    for index, signal in enumerate(paper_signals):
        prediction_id = f"prediction-{index}"
        signal["prediction_id"] = prediction_id
        signal["generated_est"] = "2026-06-19T12:00:00Z"
        for field in ("decision_time", "available_at", "generated_at", "feature_cutoff"):
            signal.pop(field, None)
        prediction_rows.append({
            "prediction_id": prediction_id,
            "symbol": signal["symbol"],
            "timeframe": signal["timeframe"],
            "decision_time": "2026-06-19T11:59:30Z",
            "available_at": "2026-06-19T11:59:00Z",
            "feature_cutoff": "2026-06-19T11:55:00Z",
        })

    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=paper_signals,
        prediction_rows=prediction_rows,
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    counterfactual = statuses["counterfactual_capital_sweep_status.json"]
    probe = counterfactual["near_a_grade_counterfactual_probe"]
    resolution = statuses["positive_edge_below_a_grade_resolution.json"]
    replay = statuses["accelerated_counterfactual_replay_status.json"]

    assert counterfactual["status"] == "NO_GO_COUNTERFACTUAL_REPLAY_NOT_COMPLETE"
    assert counterfactual["counterfactual_blocker_reasons"] == ["NO_A_GRADE_SIGNALS"]
    assert counterfactual["counterfactual_temporal_enriched_paper_signal_count"] == 5
    assert counterfactual["counterfactual_temporal_enrichment_sample"][0] == {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "prediction_id": "prediction-0",
        "filled_fields": ["available_at", "decision_time", "feature_cutoff", "generated_at"],
    }
    assert probe["status"] == "PASSED"
    assert probe["a_grade_before_temporal_count"] == 5
    assert probe["event_time_valid_candidate_count"] == 5
    assert probe["skipped_temporal_invalid_count"] == 0
    assert probe["skipped_no_feasible_configuration_count"] == 0
    assert probe["skipped_no_feasible_configuration_sample"] == []
    assert probe["best_configuration_count"] == 5
    assert resolution["b_grade_exploration_candidate_count"] == 5
    assert resolution["shadow_only_candidate_count"] == 0
    assert resolution["b_grade_exploration_paper_sample"][0]["market_state_valid"] is True
    assert (
        0.0
        < resolution["b_grade_exploration_paper_sample"][0]["risk_budget_fraction_of_normal_adaptive"]
        <= 0.25
    )
    assert replay["event_time_valid_label_count"] == 5
    assert replay["side_counts"] == {"long": 5}


def test_counterfactual_probe_enriches_missing_signal_quality_from_prediction_lineage() -> None:
    paper_signals = _paper_signal_all_timeframes()
    prediction_rows = []
    for index, signal in enumerate(paper_signals):
        prediction_id = f"quality-prediction-{index}"
        signal["prediction_id"] = prediction_id
        signal.pop("confidence_calibrated", None)
        signal.pop("expected_move_after_cost_bps", None)
        prediction_rows.append({
            "prediction_id": prediction_id,
            "symbol": signal["symbol"],
            "timeframe": signal["timeframe"],
            "confidence_calibrated": 0.82,
            "expected_move_after_cost_bps": 35.0,
            "decision_time": "2026-06-19T11:59:30Z",
            "available_at": "2026-06-19T11:59:00Z",
            "generated_at": "2026-06-19T11:59:00Z",
            "feature_cutoff": "2026-06-19T11:55:00Z",
        })

    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=paper_signals,
        prediction_rows=prediction_rows,
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    counterfactual = statuses["counterfactual_capital_sweep_status.json"]
    readiness = counterfactual["a_grade_readiness"]["source_kind_readiness"]["paper_signal"]
    progress = counterfactual["counterfactual_replay_progress"]

    assert counterfactual["counterfactual_signal_quality_enriched_paper_signal_count"] == 5
    assert counterfactual["counterfactual_signal_quality_enrichment_sample"][0] == {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "prediction_id": "quality-prediction-0",
        "filled_fields": ["confidence_calibrated", "expected_move_after_cost_bps"],
    }
    assert readiness["a_grade_before_temporal_count"] == 5
    assert readiness["event_time_valid_candidate_count"] == 5
    assert readiness["best_configuration_count"] == 5
    assert progress["a_grade_before_temporal_count"] == 5
    assert progress["event_time_valid_candidate_count"] == 5
    assert progress["best_configuration_count"] == 5


def test_counterfactual_probe_enriches_paper_signal_market_cost_from_prediction_lineage() -> None:
    paper_signals = _paper_signal_all_timeframes(confidence_calibrated=0.70)
    prediction_rows = []
    source_fields = {
        "actual_observed_spread_entry_bps": "v2:features:latest:BTCUSDT:{timeframe}.bid_ask_spread_bps",
        "expected_slippage_bps": "prediction.expected_slippage_bps",
        "fee_bps": "prediction.fee_bps",
        "expected_funding_bps": "v2:features:latest:BTCUSDT:{timeframe}.funding_rate",
        "orderbook_depth_usd": "v2:features:latest:BTCUSDT:{timeframe}.orderbook_depth_usd",
    }
    for index, signal in enumerate(paper_signals):
        prediction_id = f"market-cost-prediction-{index}"
        signal["prediction_id"] = prediction_id
        for field in status_module.COUNTERFACTUAL_MARKET_COST_LINEAGE_FIELDS:
            signal.pop(field, None)
        prediction_rows.append({
            "prediction_id": prediction_id,
            "symbol": signal["symbol"],
            "timeframe": signal["timeframe"],
            "actual_observed_spread_entry_bps": 1.5,
            "expected_slippage_bps": 2.0,
            "fee_bps": 4.0,
            "expected_funding_bps": 0.25,
            "orderbook_depth_usd": 250000.0,
            "market_cost_evidence_status": "COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE",
            "market_cost_evidence_missing_fields": [],
            "market_cost_evidence_pit_reject_reasons": [],
            "market_cost_evidence_source_fields": {
                field: source.format(timeframe=signal["timeframe"])
                for field, source in source_fields.items()
            },
        })

    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=paper_signals,
        prediction_rows=prediction_rows,
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    counterfactual = statuses["counterfactual_capital_sweep_status.json"]
    probe = counterfactual["near_a_grade_counterfactual_probe"]
    coverage = probe["market_cost_evidence_coverage_status"]

    assert counterfactual["counterfactual_market_cost_enriched_paper_signal_count"] == 5
    assert counterfactual["counterfactual_market_cost_enrichment_sample"][0] == {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "prediction_id": "market-cost-prediction-0",
        "filled_fields": [
            "actual_observed_spread_entry_bps",
            "expected_funding_bps",
            "expected_slippage_bps",
            "fee_bps",
            "orderbook_depth_usd",
        ],
        "market_cost_evidence_status": "COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE",
    }
    assert coverage["status"] == "PASSED"
    assert coverage["candidate_row_count"] == 5
    assert coverage["complete_candidate_count"] == 5
    assert coverage["missing_reason_counts"] == {}
    assert probe["best_configuration_count"] == 5


def test_counterfactual_probe_enriches_market_cost_from_pit_feature_snapshot_lineage() -> None:
    paper_signals = _paper_signal_all_timeframes(confidence_calibrated=0.70)
    prediction_rows = []
    feature_rows = []
    for index, signal in enumerate(paper_signals):
        prediction_id = f"feature-market-cost-prediction-{index}"
        feature_snapshot_id = f"feature-snapshot-{index}"
        signal["prediction_id"] = prediction_id
        signal["feature_snapshot_id"] = feature_snapshot_id
        for field in status_module.COUNTERFACTUAL_MARKET_COST_LINEAGE_FIELDS:
            signal.pop(field, None)
        prediction_rows.append({
            "prediction_id": prediction_id,
            "symbol": signal["symbol"],
            "timeframe": signal["timeframe"],
            "decision_time": "2026-06-19T12:00:00Z",
            "available_at": "2026-06-19T11:59:00Z",
            "feature_cutoff": "2026-06-19T11:55:00Z",
            "feature_snapshot_id": feature_snapshot_id,
        })
        feature_rows.append({
            "source_redis_key": f"v2:features:latest:BTCUSDT:{signal['timeframe']}",
            "symbol": signal["symbol"],
            "timeframe": signal["timeframe"],
            "feature_snapshot_id": feature_snapshot_id,
            "available_at": "2026-06-19T11:58:30Z",
            "generated_at": "2026-06-19T11:58:30Z",
            "feature_cutoff": "2026-06-19T11:55:00Z",
            "features": {
                "bid_ask_spread_bps": 1.5,
                "funding_rate": 0.000025,
            },
            "expected_slippage_bps": 2.0,
            "fee_bps": 4.0,
            "orderbook_depth_usd": 250000.0,
        })

    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=paper_signals,
        prediction_rows=prediction_rows,
        feature_rows=feature_rows,
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    counterfactual = statuses["counterfactual_capital_sweep_status.json"]
    prediction_probe = counterfactual["prediction_counterfactual_probe"]
    probe = counterfactual["near_a_grade_counterfactual_probe"]
    coverage = probe["market_cost_evidence_coverage_status"]

    assert prediction_probe["prediction_feature_market_cost_enriched_count"] == 5
    assert prediction_probe["prediction_feature_market_cost_enrichment_sample"][0] == {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "prediction_id": "feature-market-cost-prediction-0",
        "filled_fields": [
            "actual_observed_spread_entry_bps",
            "expected_funding_bps",
            "expected_slippage_bps",
            "fee_bps",
            "orderbook_depth_usd",
        ],
        "market_cost_evidence_status": "COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE",
        "pit_reject_reasons": [],
    }
    assert counterfactual["counterfactual_market_cost_enriched_paper_signal_count"] == 5
    assert counterfactual["counterfactual_feature_market_cost_enriched_paper_signal_count"] == 5
    assert counterfactual["counterfactual_feature_market_cost_enrichment_sample"][0]["filled_fields"] == [
        "actual_observed_spread_entry_bps",
        "expected_funding_bps",
        "expected_slippage_bps",
        "fee_bps",
        "orderbook_depth_usd",
    ]
    assert coverage["status"] == "PASSED"
    assert coverage["candidate_row_count"] == 5
    assert coverage["complete_candidate_count"] == 5
    assert coverage["pit_reject_reason_counts"] == {}
    assert probe["best_configuration_count"] == 5


def test_counterfactual_feature_market_cost_enrichment_flattens_nested_cost_contexts() -> None:
    signal = _paper_signal(
        confidence_calibrated=0.70,
        prediction_id="nested-feature-market-cost-prediction",
    )
    signal["feature_snapshot_id"] = "nested-feature-market-cost-snapshot"
    for field in status_module.COUNTERFACTUAL_MARKET_COST_LINEAGE_FIELDS:
        signal.pop(field, None)

    feature_row = {
        "source_redis_key": "v2:features:latest:BTCUSDT:1m",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_snapshot_id": "nested-feature-market-cost-snapshot",
        "available_at": "2026-06-19T11:58:30Z",
        "generated_at": "2026-06-19T11:58:30Z",
        "feature_cutoff": "2026-06-19T11:55:00Z",
        "features": {
            "market_microstructure": {
                "actual_spread_bps": 1.25,
                "estimated_slippage_bps": 1.75,
            },
            "orderbook_context": {
                "entry_orderbook_depth_usd": 250000.0,
            },
            "funding_context": {
                "expected_funding_rate": -0.000025,
            },
            "model_inputs": {
                "fee_rate": 0.0004,
            },
        },
    }

    evidence = status_module._feature_market_cost_evidence_enrichment(
        decision_row={
            **signal,
            "decision_time": "2026-06-19T12:00:00Z",
        },
        feature_payload=feature_row,
        feature_source_key=feature_row["source_redis_key"],
    )

    assert evidence["market_cost_evidence_status"] == "COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE"
    assert evidence["actual_observed_spread_entry_bps"] == 1.25
    assert evidence["expected_slippage_bps"] == 1.75
    assert evidence["fee_bps"] == 4.0
    assert evidence["expected_funding_bps"] == 0.25
    assert evidence["orderbook_depth_usd"] == 250000.0
    assert evidence["market_cost_evidence_source_fields"] == {
        "actual_observed_spread_entry_bps": "v2:features:latest:BTCUSDT:1m.actual_spread_bps",
        "expected_slippage_bps": "v2:features:latest:BTCUSDT:1m.estimated_slippage_bps",
        "fee_bps": "v2:features:latest:BTCUSDT:1m.fee_rate",
        "expected_funding_bps": "v2:features:latest:BTCUSDT:1m.expected_funding_rate",
        "orderbook_depth_usd": "v2:features:latest:BTCUSDT:1m.entry_orderbook_depth_usd",
    }
    assert evidence["market_cost_evidence_pit_reject_reasons"] == []

    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=[signal],
        prediction_rows=[{
            "prediction_id": "nested-feature-market-cost-prediction",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "decision_time": "2026-06-19T12:00:00Z",
            "available_at": "2026-06-19T11:59:00Z",
            "feature_cutoff": "2026-06-19T11:55:00Z",
            "feature_snapshot_id": "nested-feature-market-cost-snapshot",
        }],
        feature_rows=[feature_row],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    counterfactual = statuses["counterfactual_capital_sweep_status.json"]
    prediction_probe = counterfactual["prediction_counterfactual_probe"]
    probe = counterfactual["near_a_grade_counterfactual_probe"]
    coverage = probe["market_cost_evidence_coverage_status"]

    assert prediction_probe["prediction_feature_market_cost_enriched_count"] == 1
    assert counterfactual["counterfactual_feature_market_cost_enriched_paper_signal_count"] == 1
    assert counterfactual["counterfactual_feature_market_cost_enrichment_sample"][0]["filled_fields"] == [
        "actual_observed_spread_entry_bps",
        "expected_funding_bps",
        "expected_slippage_bps",
        "fee_bps",
        "orderbook_depth_usd",
    ]
    assert coverage["status"] == "PASSED"
    assert coverage["candidate_row_count"] == 1
    assert coverage["complete_candidate_count"] == 1
    assert coverage["missing_reason_counts"] == {}
    assert coverage["pit_reject_reason_counts"] == {}
    assert probe["best_configuration_count"] == 1


def test_counterfactual_feature_enrichment_prefers_signal_lineage_feature_snapshot() -> None:
    signal = _paper_signal(
        confidence_calibrated=0.70,
        prediction_id="prediction-with-different-feature-snapshot",
    )
    signal.pop("feature_snapshot_id", None)
    signal["lineage_ids"] = {"feature_snapshot_id": "signal-lineage-feature-snapshot"}
    for field in status_module.COUNTERFACTUAL_MARKET_COST_LINEAGE_FIELDS:
        signal.pop(field, None)

    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=[signal],
        prediction_rows=[{
            "prediction_id": "prediction-with-different-feature-snapshot",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "decision_time": "2026-06-19T12:00:00Z",
            "available_at": "2026-06-19T11:59:00Z",
            "feature_cutoff": "2026-06-19T11:55:00Z",
            "feature_snapshot_id": "prediction-feature-snapshot",
        }],
        feature_rows=[
            {
                "source_redis_key": "v2:features:snapshot:signal-lineage-feature-snapshot",
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "feature_snapshot_id": "signal-lineage-feature-snapshot",
                "available_at": "2026-06-19T11:58:30Z",
                "generated_at": "2026-06-19T11:58:30Z",
                "feature_cutoff": "2026-06-19T11:55:00Z",
                "features": {
                    "bid_ask_spread_bps": 1.5,
                    "funding_rate": 0.000025,
                },
                "expected_slippage_bps": 2.0,
                "fee_bps": 4.0,
                "orderbook_depth_usd": 250000.0,
            },
            {
                "source_redis_key": "v2:features:latest:BTCUSDT:1m",
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "feature_snapshot_id": "newer-latest-feature-snapshot",
                "available_at": "2026-06-19T12:01:00Z",
                "generated_at": "2026-06-19T12:01:00Z",
                "feature_cutoff": "2026-06-19T12:00:30Z",
                "actual_observed_spread_entry_bps": 99.0,
                "expected_slippage_bps": 99.0,
                "fee_bps": 99.0,
                "expected_funding_bps": 99.0,
                "orderbook_depth_usd": 1.0,
            },
        ],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    counterfactual = statuses["counterfactual_capital_sweep_status.json"]
    probe = counterfactual["near_a_grade_counterfactual_probe"]
    coverage = probe["market_cost_evidence_coverage_status"]
    sample = counterfactual["counterfactual_feature_market_cost_enrichment_sample"][0]

    assert counterfactual["counterfactual_feature_market_cost_enriched_paper_signal_count"] == 1
    assert sample["filled_fields"] == [
        "actual_observed_spread_entry_bps",
        "expected_funding_bps",
        "expected_slippage_bps",
        "fee_bps",
        "orderbook_depth_usd",
    ]
    assert sample["pit_reject_reasons"] == []
    assert coverage["status"] == "PASSED"
    assert coverage["candidate_row_count"] == 1
    assert coverage["complete_candidate_count"] == 1
    assert coverage["pit_reject_reason_counts"] == {}
    assert coverage["missing_reason_counts"] == {}
    assert probe["best_configuration_count"] == 1


def test_counterfactual_feature_enrichment_uses_signal_snapshot_without_prediction() -> None:
    signal = _paper_signal(confidence_calibrated=0.70)
    signal.pop("prediction_id", None)
    signal.pop("source_prediction_id", None)
    signal.pop("entry_prediction_id", None)
    signal["feature_snapshot_id"] = "standalone-signal-feature-snapshot"
    for field in status_module.COUNTERFACTUAL_MARKET_COST_LINEAGE_FIELDS:
        signal.pop(field, None)

    enriched = status_module._counterfactual_signal_rows_with_prediction_temporal_context(
        paper_signals=[signal],
        prediction_rows=[],
        feature_rows=[{
            "source_redis_key": "v2:features:snapshot:standalone-signal-feature-snapshot",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "feature_snapshot_id": "standalone-signal-feature-snapshot",
            "available_at": "2026-06-19T11:58:30Z",
            "generated_at": "2026-06-19T11:58:30Z",
            "feature_cutoff": "2026-06-19T11:55:00Z",
            "features": {
                "bid_ask_spread_bps": 1.5,
                "funding_rate": 0.000025,
            },
            "expected_slippage_bps": 2.0,
            "fee_bps": 4.0,
            "orderbook_depth_usd": 250000.0,
        }],
    )

    assert enriched[0]["counterfactual_feature_market_cost_enrichment_source"] == (
        "paper_signal_feature_snapshot_pit"
    )
    assert enriched[0]["counterfactual_feature_market_cost_enrichment_fields"] == [
        "actual_observed_spread_entry_bps",
        "expected_funding_bps",
        "expected_slippage_bps",
        "fee_bps",
        "orderbook_depth_usd",
    ]

    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=[signal],
        prediction_rows=[],
        feature_rows=[{
            "source_redis_key": "v2:features:snapshot:standalone-signal-feature-snapshot",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "feature_snapshot_id": "standalone-signal-feature-snapshot",
            "available_at": "2026-06-19T11:58:30Z",
            "generated_at": "2026-06-19T11:58:30Z",
            "feature_cutoff": "2026-06-19T11:55:00Z",
            "features": {
                "bid_ask_spread_bps": 1.5,
                "funding_rate": 0.000025,
            },
            "expected_slippage_bps": 2.0,
            "fee_bps": 4.0,
            "orderbook_depth_usd": 250000.0,
        }],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    counterfactual = statuses["counterfactual_capital_sweep_status.json"]
    probe = counterfactual["near_a_grade_counterfactual_probe"]
    coverage = probe["market_cost_evidence_coverage_status"]

    assert counterfactual["counterfactual_feature_market_cost_enriched_paper_signal_count"] == 1
    assert coverage["status"] == "PASSED"
    assert coverage["candidate_row_count"] == 1
    assert coverage["complete_candidate_count"] == 1
    assert coverage["missing_reason_counts"] == {}
    assert probe["best_configuration_count"] == 1


def test_counterfactual_market_cost_enrichment_uses_pit_symbol_timeframe_fallback() -> None:
    signal = _paper_signal(confidence_calibrated=0.70)
    for field in status_module.COUNTERFACTUAL_MARKET_COST_LINEAGE_FIELDS:
        signal.pop(field, None)
    prediction = {
        "prediction_id": "symbol-timeframe-market-cost-prediction",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "decision_time": "2026-06-19T12:00:00Z",
        "available_at": "2026-06-19T11:59:00Z",
        "feature_cutoff": "2026-06-19T11:55:00Z",
        "actual_observed_spread_entry_bps": 1.5,
        "expected_slippage_bps": 2.0,
        "fee_bps": 4.0,
        "expected_funding_bps": 0.25,
        "orderbook_depth_usd": 250000.0,
        "market_cost_evidence_status": "COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE",
        "market_cost_evidence_missing_fields": [],
        "market_cost_evidence_pit_reject_reasons": [],
        "market_cost_evidence_source_fields": {
            "actual_observed_spread_entry_bps": "prediction.actual_observed_spread_entry_bps",
            "expected_slippage_bps": "prediction.expected_slippage_bps",
            "fee_bps": "prediction.fee_bps",
            "expected_funding_bps": "prediction.expected_funding_bps",
            "orderbook_depth_usd": "prediction.orderbook_depth_usd",
        },
    }

    enriched = status_module._counterfactual_signal_rows_with_prediction_temporal_context(
        paper_signals=[signal],
        prediction_rows=[prediction],
    )
    enriched_row = enriched[0]

    assert enriched_row["counterfactual_market_cost_enrichment_source"] == (
        "paper_signal_prediction_symbol_timeframe_pit_fallback"
    )
    assert enriched_row["counterfactual_market_cost_enrichment_prediction_id"] == (
        "symbol-timeframe-market-cost-prediction"
    )
    assert enriched_row["counterfactual_market_cost_enrichment_fields"] == [
        "actual_observed_spread_entry_bps",
        "expected_funding_bps",
        "expected_slippage_bps",
        "fee_bps",
        "orderbook_depth_usd",
    ]

    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=[signal],
        prediction_rows=[prediction],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )
    counterfactual = statuses["counterfactual_capital_sweep_status.json"]
    probe = counterfactual["near_a_grade_counterfactual_probe"]
    coverage = probe["market_cost_evidence_coverage_status"]

    assert counterfactual["counterfactual_market_cost_enriched_paper_signal_count"] == 1
    assert coverage["status"] == "PASSED"
    assert coverage["candidate_row_count"] == 1
    assert coverage["complete_candidate_count"] == 1
    assert probe["best_configuration_count"] == 1


def test_counterfactual_market_cost_symbol_timeframe_fallback_rejects_future_prediction() -> None:
    signal = _paper_signal(
        confidence_calibrated=0.70,
        decision_time="2026-06-19T11:59:00Z",
    )
    for field in status_module.COUNTERFACTUAL_MARKET_COST_LINEAGE_FIELDS:
        signal.pop(field, None)
    prediction = {
        "prediction_id": "future-symbol-timeframe-market-cost-prediction",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "decision_time": "2026-06-19T12:00:00Z",
        "available_at": "2026-06-19T11:59:30Z",
        "feature_cutoff": "2026-06-19T11:55:00Z",
        "actual_observed_spread_entry_bps": 1.5,
        "expected_slippage_bps": 2.0,
        "fee_bps": 4.0,
        "expected_funding_bps": 0.25,
        "orderbook_depth_usd": 250000.0,
        "market_cost_evidence_status": "COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE",
        "market_cost_evidence_missing_fields": [],
        "market_cost_evidence_pit_reject_reasons": [],
        "market_cost_evidence_source_fields": {
            "actual_observed_spread_entry_bps": "prediction.actual_observed_spread_entry_bps",
            "expected_slippage_bps": "prediction.expected_slippage_bps",
            "fee_bps": "prediction.fee_bps",
            "expected_funding_bps": "prediction.expected_funding_bps",
            "orderbook_depth_usd": "prediction.orderbook_depth_usd",
        },
    }

    enriched = status_module._counterfactual_signal_rows_with_prediction_temporal_context(
        paper_signals=[signal],
        prediction_rows=[prediction],
    )
    enriched_row = enriched[0]

    assert "counterfactual_market_cost_enrichment_source" not in enriched_row
    assert "counterfactual_market_cost_enrichment_fields" not in enriched_row
    for field in status_module.COUNTERFACTUAL_MARKET_COST_LINEAGE_FIELDS:
        assert field not in enriched_row

    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=[signal],
        prediction_rows=[prediction],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )
    counterfactual = statuses["counterfactual_capital_sweep_status.json"]
    coverage = counterfactual["near_a_grade_counterfactual_probe"]["market_cost_evidence_coverage_status"]

    assert counterfactual["counterfactual_market_cost_enriched_paper_signal_count"] == 0
    assert coverage["status"] == "NO_GO_MARKET_COST_EVIDENCE_INCOMPLETE"
    assert coverage["complete_candidate_count"] == 0


def test_counterfactual_feature_market_cost_enrichment_rejects_snapshot_mismatch() -> None:
    signal = _paper_signal(confidence_calibrated=0.70, prediction_id="prediction-with-mismatched-feature")
    for field in status_module.COUNTERFACTUAL_MARKET_COST_LINEAGE_FIELDS:
        signal.pop(field, None)

    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=[signal],
        prediction_rows=[{
            "prediction_id": "prediction-with-mismatched-feature",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "decision_time": "2026-06-19T12:00:00Z",
            "available_at": "2026-06-19T11:59:00Z",
            "feature_cutoff": "2026-06-19T11:55:00Z",
            "feature_snapshot_id": "prediction-feature-snapshot",
        }],
        feature_rows=[{
            "source_redis_key": "v2:features:latest:BTCUSDT:1m",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "feature_snapshot_id": "newer-latest-feature-snapshot",
            "available_at": "2026-06-19T12:01:00Z",
            "generated_at": "2026-06-19T12:01:00Z",
            "feature_cutoff": "2026-06-19T11:55:00Z",
            "actual_observed_spread_entry_bps": 1.5,
            "expected_slippage_bps": 2.0,
            "fee_bps": 4.0,
            "expected_funding_bps": 0.25,
            "orderbook_depth_usd": 250000.0,
        }],
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    counterfactual = statuses["counterfactual_capital_sweep_status.json"]
    probe = counterfactual["near_a_grade_counterfactual_probe"]
    coverage = probe["market_cost_evidence_coverage_status"]
    snapshot_audit = counterfactual["feature_snapshot_lookup_audit"]

    assert counterfactual["counterfactual_market_cost_enriched_paper_signal_count"] == 0
    assert counterfactual["counterfactual_feature_market_cost_enriched_paper_signal_count"] == 0
    assert coverage["status"] == "NO_GO_MARKET_COST_EVIDENCE_INCOMPLETE"
    assert coverage["candidate_row_count"] == 1
    assert coverage["complete_candidate_count"] == 0
    assert coverage["pit_reject_reason_counts"] == {
        "FEATURE_AVAILABLE_AT_AFTER_DECISION_TIME": 1,
        "FEATURE_GENERATED_AT_AFTER_DECISION_TIME": 1,
        "FEATURE_SNAPSHOT_MISMATCH_FOR_MARKET_COST_EVIDENCE": 1,
        "MISSING_EXACT_FEATURE_SNAPSHOT_FOR_MARKET_COST_EVIDENCE": 1,
    }
    assert snapshot_audit == {
        "status": "NO_GO_EXACT_FEATURE_SNAPSHOT_GAPS",
        "requested_feature_snapshot_id_count": 1,
        "available_exact_feature_snapshot_id_count": 0,
        "archived_exact_feature_snapshot_id_count": 0,
        "missing_exact_feature_snapshot_id_count": 1,
        "missing_exact_feature_snapshot_id_sample": ["prediction-feature-snapshot"],
    }
    assert coverage["incomplete_candidate_sample"][0]["missing_market_cost_evidence"] == [
        "MISSING_ACTUAL_SPREAD",
        "MISSING_SLIPPAGE",
        "MISSING_FEES",
        "MISSING_FUNDING",
        "MISSING_MARKET_DEPTH",
    ]
    capture_request = coverage["incomplete_candidate_capture_request_sample"][0]
    assert capture_request["symbol"] == "BTCUSDT"
    assert capture_request["timeframe"] == "1m"
    assert capture_request["feature_snapshot_id"] == "prediction-feature-snapshot"
    assert capture_request["decision_time"] == "2026-06-19T12:00:00Z"
    assert capture_request["market_cost_evidence_pit_reject_reasons"] == [
        "FEATURE_AVAILABLE_AT_AFTER_DECISION_TIME",
        "FEATURE_GENERATED_AT_AFTER_DECISION_TIME",
        "FEATURE_SNAPSHOT_MISMATCH_FOR_MARKET_COST_EVIDENCE",
        "MISSING_EXACT_FEATURE_SNAPSHOT_FOR_MARKET_COST_EVIDENCE",
    ]
    assert capture_request["required_capture_fields"]["MISSING_FEES"]["accepted_fields"] == [
        "actual_fee_bps",
        "fee_bps",
        "taker_fee_bps",
        "expected_fee_bps",
        "estimated_fee_bps",
        "fee_estimate_bps",
        "commission_bps",
        "fee_rate",
        "taker_fee_rate",
        "expected_fee_rate",
        "estimated_fee_rate",
        "commission_rate",
        "actual_fees_usd",
        "expected_fees_usd",
    ]


def test_counterfactual_feature_market_cost_enrichment_derives_coinapi_side_depth() -> None:
    long_signal = _paper_signal(
        confidence_calibrated=0.70,
        prediction_id="long-prediction-with-coinapi-depth",
    )
    long_signal["action"] = "long"
    long_signal["side"] = "long"
    short_signal = _paper_signal(
        confidence_calibrated=0.70,
        prediction_id="short-prediction-with-coinapi-depth",
    )
    short_signal["timeframe"] = "5m"
    short_signal["action"] = "short"
    short_signal["side"] = "short"
    for signal in (long_signal, short_signal):
        for field in status_module.COUNTERFACTUAL_MARKET_COST_LINEAGE_FIELDS:
            signal.pop(field, None)

    prediction_rows = [
        {
            "prediction_id": "long-prediction-with-coinapi-depth",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "decision_time": "2026-06-19T12:00:00Z",
            "available_at": "2026-06-19T11:59:00Z",
            "feature_cutoff": "2026-06-19T11:55:00Z",
        },
        {
            "prediction_id": "short-prediction-with-coinapi-depth",
            "symbol": "BTCUSDT",
            "timeframe": "5m",
            "decision_time": "2026-06-19T12:00:00Z",
            "available_at": "2026-06-19T11:59:00Z",
            "feature_cutoff": "2026-06-19T11:55:00Z",
        },
    ]
    feature_rows = [
        {
            "source_redis_key": "v2:features:latest:BTCUSDT:1m",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "available_at": "2026-06-19T11:58:30Z",
            "generated_at": "2026-06-19T11:58:30Z",
            "feature_cutoff": "2026-06-19T11:55:00Z",
            "features": {
                "bid_ask_spread_bps": 1.5,
                "funding_rate": 0.000025,
                "coinapi_best_bid_px": 100.0,
                "coinapi_best_ask_px": 101.0,
                "coinapi_book_bid_sum_5": 8.0,
                "coinapi_book_ask_sum_5": 6.0,
            },
            "expected_slippage_bps": 2.0,
            "fee_bps": 4.0,
        },
        {
            "source_redis_key": "v2:features:latest:BTCUSDT:5m",
            "symbol": "BTCUSDT",
            "timeframe": "5m",
            "available_at": "2026-06-19T11:58:30Z",
            "generated_at": "2026-06-19T11:58:30Z",
            "feature_cutoff": "2026-06-19T11:55:00Z",
            "features": {
                "bid_ask_spread_bps": 1.5,
                "funding_rate": 0.000025,
                "coinapi_best_bid_px": 100.0,
                "coinapi_best_ask_px": 101.0,
                "coinapi_book_bid_sum_5": 8.0,
                "coinapi_book_ask_sum_5": 6.0,
            },
            "expected_slippage_bps": 2.0,
            "fee_bps": 4.0,
        },
    ]
    long_evidence = status_module._feature_market_cost_evidence_enrichment(
        decision_row={
            **long_signal,
            "decision_time": "2026-06-19T12:00:00Z",
        },
        feature_payload=feature_rows[0],
        feature_source_key=feature_rows[0]["source_redis_key"],
    )
    short_evidence = status_module._feature_market_cost_evidence_enrichment(
        decision_row={
            **short_signal,
            "decision_time": "2026-06-19T12:00:00Z",
        },
        feature_payload=feature_rows[1],
        feature_source_key=feature_rows[1]["source_redis_key"],
    )

    statuses = build_statuses(
        ledger={"open_positions": [], "closed_trades": []},
        portfolio={"equity": 10000.0},
        paper_status={},
        paper_signals=[long_signal, short_signal],
        prediction_rows=prediction_rows,
        feature_rows=feature_rows,
        horizon_years=5.0,
        generated_utc="2026-06-20T00:00:00Z",
    )

    counterfactual = statuses["counterfactual_capital_sweep_status.json"]
    enrichment_sample = counterfactual["counterfactual_feature_market_cost_enrichment_sample"]
    enriched_by_timeframe = {row["timeframe"]: row for row in enrichment_sample}
    probe = counterfactual["near_a_grade_counterfactual_probe"]
    coverage = probe["market_cost_evidence_coverage_status"]
    best_by_timeframe = {
        row["timeframe"]: row["selected"]
        for row in probe["best_configurations_sample"]
        if row["timeframe"] in {"1m", "5m"}
    }

    assert coverage["status"] == "PASSED"
    assert coverage["complete_candidate_count"] == 2
    assert coverage["missing_reason_counts"] == {}
    assert enriched_by_timeframe["1m"]["filled_fields"] == ["orderbook_depth_usd"]
    assert long_evidence["orderbook_depth_usd"] == 606.0
    assert short_evidence["orderbook_depth_usd"] == 800.0
    assert long_evidence["market_cost_evidence_source_fields"]["orderbook_depth_usd"] == (
        "v2:features:latest:BTCUSDT:1m.coinapi_book_ask_sum_5*coinapi_best_ask_px"
    )
    assert short_evidence["market_cost_evidence_source_fields"]["orderbook_depth_usd"] == (
        "v2:features:latest:BTCUSDT:5m.coinapi_book_bid_sum_5*coinapi_best_bid_px"
    )
    assert best_by_timeframe["1m"]["market_depth_source"] == "orderbook_depth_usd"
    assert best_by_timeframe["5m"]["market_depth_source"] == "orderbook_depth_usd"
    assert best_by_timeframe["1m"]["market_depth_capacity_usd"] == 606.0
    assert best_by_timeframe["5m"]["market_depth_capacity_usd"] == 800.0


def test_feature_market_cost_enrichment_models_slippage_from_pit_spread_without_fee() -> None:
    evidence = status_module._feature_market_cost_evidence_enrichment(
        decision_row={
            "prediction_id": "prediction-with-modeled-slippage",
            "side": "long",
            "decision_time": "2026-06-19T12:00:00Z",
        },
        feature_payload={
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "available_at": "2026-06-19T11:58:30Z",
            "generated_at": "2026-06-19T11:58:30Z",
            "feature_cutoff": "2026-06-19T11:55:00Z",
            "features": {
                "bid_ask_spread_bps": 2.0,
                "volatility_bps": 10.0,
                "liquidity_score": 0.4,
                "funding_rate": 0.000025,
                "depth_total_usd": 250000.0,
            },
        },
        feature_source_key="v2:features:latest:BTCUSDT:1m",
    )

    assert evidence["market_cost_evidence_status"] == "PARTIAL_EXPLICIT_MARKET_COST_EVIDENCE"
    assert evidence["market_cost_evidence_missing_fields"] == ["MISSING_FEES"]
    assert evidence["actual_observed_spread_entry_bps"] == 2.0
    assert math.isclose(evidence["expected_slippage_bps"], 1.61)
    assert evidence["expected_funding_bps"] == 0.25
    assert evidence["orderbook_depth_usd"] == 250000.0
    assert evidence["market_cost_evidence_source_fields"]["expected_slippage_bps"] == (
        "v2:features:latest:BTCUSDT:1m."
        "MODELED_FROM_OBSERVED_SPREAD_VOLATILITY_LIQUIDITY(bid_ask_spread_bps,volatility_bps,liquidity_score)"
    )
    assert evidence["market_cost_evidence_pit_reject_reasons"] == []
    assert evidence["market_cost_evidence_source_lineage"]["source"] == (
        "status_generator_pit_feature_payload_fields_with_modeled_slippage_from_pit_spread"
    )


def test_market_cost_coverage_accepts_allocator_model_input_fee_and_funding() -> None:
    row = _paper_signal(confidence_calibrated=0.70)
    row.update({
        "side": "long",
        "action": "long",
        "expected_move_after_cost_bps": 50.0,
        "actual_observed_spread_entry_bps": 1.5,
        "expected_slippage_bps": 2.0,
        "orderbook_depth_usd": 250000.0,
        "adaptive_allocation": {
            "model_inputs": {
                "fee_bps": 4.0,
                "expected_funding_bps": 0.25,
            },
        },
    })
    row.pop("fee_bps", None)
    row.pop("expected_funding_bps", None)

    coverage = status_module._market_cost_evidence_coverage_status(
        [row],
        confidence_threshold=0.65,
        scope="unit_allocator_model_input_market_cost",
    )

    assert coverage["status"] == "PASSED"
    assert coverage["candidate_row_count"] == 1
    assert coverage["complete_candidate_count"] == 1
    assert coverage["missing_reason_counts"] == {}
    assert coverage["field_present_counts"] == {
        "fee_bps": 1,
        "funding_bps": 1,
        "market_depth_usd": 1,
        "slippage_bps": 1,
        "spread_bps": 1,
    }


def test_feature_market_cost_enrichment_converts_explicit_rate_and_estimated_bps_aliases() -> None:
    evidence = status_module._feature_market_cost_evidence_enrichment(
        decision_row={
            "prediction_id": "prediction-with-rate-aliases",
            "side": "long",
            "decision_time": "2026-06-19T12:00:00Z",
        },
        feature_payload={
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "available_at": "2026-06-19T11:58:30Z",
            "generated_at": "2026-06-19T11:58:30Z",
            "feature_cutoff": "2026-06-19T11:55:00Z",
            "features": {
                "bid_ask_spread_bps": 1.25,
                "estimated_slippage_bps": 1.75,
                "fee_rate": 0.0004,
                "expected_funding_rate": -0.000025,
                "depth_total_usd": 250000.0,
            },
        },
        feature_source_key="v2:features:latest:BTCUSDT:1m",
    )

    assert evidence["market_cost_evidence_status"] == "COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE"
    assert evidence["actual_observed_spread_entry_bps"] == 1.25
    assert evidence["expected_slippage_bps"] == 1.75
    assert evidence["fee_bps"] == 4.0
    assert evidence["expected_funding_bps"] == 0.25
    assert evidence["orderbook_depth_usd"] == 250000.0
    assert evidence["market_cost_evidence_missing_fields"] == []
    assert evidence["market_cost_evidence_source_fields"] == {
        "actual_observed_spread_entry_bps": "v2:features:latest:BTCUSDT:1m.bid_ask_spread_bps",
        "expected_slippage_bps": "v2:features:latest:BTCUSDT:1m.estimated_slippage_bps",
        "fee_bps": "v2:features:latest:BTCUSDT:1m.fee_rate",
        "expected_funding_bps": "v2:features:latest:BTCUSDT:1m.expected_funding_rate",
        "orderbook_depth_usd": "v2:features:latest:BTCUSDT:1m.depth_total_usd",
    }


def test_market_cost_coverage_accepts_explicit_rate_and_estimated_bps_aliases() -> None:
    row = _paper_signal(confidence_calibrated=0.70)
    row.update({
        "side": "long",
        "action": "long",
        "expected_move_after_cost_bps": 50.0,
        "estimated_slippage_bps": 1.75,
        "fee_rate": 0.0004,
        "funding_rate": -0.000025,
        "orderbook_depth_usd": 250000.0,
    })
    for field in ("expected_slippage_bps", "fee_bps", "expected_funding_bps"):
        row.pop(field, None)

    coverage = status_module._market_cost_evidence_coverage_status(
        [row],
        confidence_threshold=0.65,
        scope="unit_explicit_rate_alias_market_cost",
    )

    assert coverage["status"] == "PASSED"
    assert coverage["candidate_row_count"] == 1
    assert coverage["complete_candidate_count"] == 1
    assert coverage["missing_reason_counts"] == {}
    assert coverage["incomplete_candidate_sample"] == []
    assert coverage["complete_candidate_sample"][0]["missing_market_cost_evidence"] == []
    assert coverage["complete_candidate_sample"][0]["present_market_cost_evidence_fields"] == {
        "fee_bps": "fee_rate",
        "funding_bps": "funding_rate",
        "market_depth_usd": "orderbook_depth_usd",
        "slippage_bps": "estimated_slippage_bps",
        "spread_bps": "actual_observed_spread_entry_bps",
    }
    assert coverage["field_present_counts"] == {
        "fee_bps": 1,
        "funding_bps": 1,
        "market_depth_usd": 1,
        "slippage_bps": 1,
        "spread_bps": 1,
    }


def test_archived_feature_rows_are_read_by_exact_feature_snapshot_id() -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.store = {
                "v2:features:snapshot:feature-snapshot-1": json.dumps({
                    "symbol": "BTCUSDT",
                    "timeframe": "1m",
                    "feature_snapshot_id": "feature-snapshot-1",
                    "available_at": "2026-06-19T11:58:30Z",
                }),
            }

        def get(self, key: str) -> str | None:
            return self.store.get(key)

    rows = status_module._read_archived_feature_rows_from_redis(
        FakeRedis(),
        [
            {"feature_snapshot_id": "feature-snapshot-1"},
            {"feature_snapshot_id": "missing-feature-snapshot"},
            {"lineage_ids": {"feature_snapshot_id": "feature-snapshot-1"}},
        ],
    )

    assert rows == [
        {
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "feature_snapshot_id": "feature-snapshot-1",
            "available_at": "2026-06-19T11:58:30Z",
            "source_redis_key": "v2:features:snapshot:feature-snapshot-1",
        }
    ]


def test_counterfactual_market_cost_enrichment_requires_explicit_source_fields() -> None:
    signal = _paper_signal(prediction_id="prediction-without-source-map")
    for field in status_module.COUNTERFACTUAL_MARKET_COST_LINEAGE_FIELDS:
        signal.pop(field, None)
    enriched = status_module._counterfactual_signal_rows_with_prediction_temporal_context(
        paper_signals=[signal],
        prediction_rows=[{
            "prediction_id": "prediction-without-source-map",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "actual_observed_spread_entry_bps": 1.5,
            "expected_slippage_bps": 2.0,
            "fee_bps": 4.0,
            "expected_funding_bps": 0.25,
            "orderbook_depth_usd": 250000.0,
        }],
    )

    row = enriched[0]
    assert "counterfactual_market_cost_enrichment_fields" not in row
    for field in status_module.COUNTERFACTUAL_MARKET_COST_LINEAGE_FIELDS:
        assert field not in row
