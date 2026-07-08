"""Fixture-backed replay for advanced market-structure decision features.

The replay runner is deliberately pure: it does not read Redis, write Redis,
call an exchange, or mutate live state. It recomputes indicator payloads from
closed, point-in-time rows, attaches the resulting context to a candidate, and
then runs the same preemptive edge-control decision used by paper/live dry-run.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from v2.backend.app.services.market_structure import (
    compute_cvd_features,
    compute_fvg,
    compute_liquidity_zones,
    compute_structure,
    compute_trade_tape_features,
    compute_volume_profile,
    compute_vwap_features,
)
from v2.backend.app.services.market_structure.common import parse_time
from v2.backend.app.services.market_structure.decision_context import (
    ADVANCED_CONTEXT_FIELDS,
)
from v2.backend.app.services.preemptive_edge_control.decision import (
    evaluate_candidate,
)


SCHEMA_VERSION = "advanced_indicator_replay_v1"
REQUIRED_REPLAY_CATEGORIES = (
    "BTC_ETH_SOL_MAJOR_MOVES",
    "FAKE_BREAKOUTS",
    "FAKE_BREAKDOWNS",
    "LIQUIDITY_SWEEPS",
    "FVG_RETESTS",
    "HIGH_CONFIDENCE_LOSSES",
    "ATR_STOP_CLUSTERS",
    "RANGE_CHOP",
    "TREND_CONTINUATION",
)
ENTRY_CAPABLE_DECISIONS = frozenset(
    {"ALLOW", "REDUCE_SIZE_PAPER_ONLY", "POSITIVE_EDGE_PROBATION_PAPER"}
)
LOSS_PREVENTION_DECISIONS = frozenset({"NO_TRADE", "SHADOW_ONLY"})
FORBIDDEN_FEATURE_LABEL_KEYS = frozenset(
    {
        "future_label",
        "future_return_bps",
        "realized_future_window_label",
        "post_decision_return_bps",
        "outcome_label",
    }
)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _f(value: Any) -> float | None:
    try:
        if value is None or value == "" or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _candle(ts: datetime, open_: float, high: float, low: float, close: float, volume: float = 1000.0) -> dict[str, Any]:
    return {
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "taker_buy_base_vol": volume * (0.58 if close >= open_ else 0.42),
        "event_time": _iso(ts),
        "available_at": _iso(ts),
        "candle_closed_confirmed": True,
    }


def _candles_from_closes(base: datetime, closes: list[float], *, future_extra: float | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candles: list[dict[str, Any]] = []
    prev = closes[0]
    for idx, close in enumerate(closes):
        open_ = prev if idx else close
        high = max(open_, close) + max(0.25, abs(close - open_) * 0.3)
        low = min(open_, close) - max(0.25, abs(close - open_) * 0.3)
        candles.append(_candle(base + timedelta(minutes=idx), open_, high, low, close, 1000 + idx * 20))
        prev = close
    future: list[dict[str, Any]] = []
    if future_extra is not None:
        ts = base + timedelta(minutes=len(closes) + 10)
        future.append(_candle(ts, closes[-1], max(closes[-1], future_extra) + 1, min(closes[-1], future_extra) - 1, future_extra, 1400))
    return candles, future


def _trades(base: datetime, price: float, *, side: str = "buy", weak: bool = False, future: bool = False) -> list[dict[str, Any]]:
    rows = []
    for idx in range(6):
        ts = base + timedelta(minutes=idx)
        if future:
            ts = base + timedelta(minutes=30 + idx)
        rows.append(
            {
                "price": price + idx * 0.05,
                "quantity": 1.0 + idx * 0.1,
                "side": side if not weak or idx % 2 == 0 else ("sell" if side == "buy" else "buy"),
                "event_time": _iso(ts),
                "available_at": _iso(ts),
                "sweep_print": idx in {3, 4} and weak,
            }
        )
    return rows


def _healthy_rows(symbol: str, timeframe: str, side: str, strategy: str, regime: str, count: int = 5) -> list[dict[str, Any]]:
    return [
        {
            "symbol": symbol,
            "timeframe": timeframe,
            "side": side,
            "strategy_selected_mode": strategy,
            "market_regime_at_entry": regime,
            "confidence_calibrated": 0.68,
            "realized_pnl_bps": 35.0 + idx,
            "realized_net_pnl_usd": 3.5 + idx * 0.2,
            "gross_notional_usd": 1000.0,
            "exit_reason": "TAKE_PROFIT",
        }
        for idx in range(count)
    ]


def _loss_rows(symbol: str, timeframe: str, side: str, strategy: str, regime: str, *, atr: bool = False) -> list[dict[str, Any]]:
    return [
        {
            "symbol": symbol,
            "timeframe": timeframe,
            "side": side,
            "strategy_selected_mode": strategy,
            "market_regime_at_entry": regime,
            "confidence_calibrated": 0.91,
            "realized_pnl_bps": -28.0 - idx,
            "realized_net_pnl_usd": -2.8 - idx * 0.1,
            "gross_notional_usd": 1000.0,
            "exit_reason": "TIER_1_ATR_VOLATILITY_STOP" if atr else "STOP_LOSS",
        }
        for idx in range(5)
    ]


def _scenario(
    *,
    name: str,
    categories: list[str],
    symbol: str,
    side: str,
    closes: list[float],
    expected_decisions: list[str],
    strategy: str = "trend_mode",
    regime: str = "TREND",
    timeframe: str = "5m",
    expected_edge: float = 42.0,
    stop_distance: float = 60.0,
    atr_bps: float = 24.0,
    future_close: float | None = None,
    tape_side: str = "buy",
    tape_weak: bool = False,
    closed_rows: list[dict[str, Any]] | None = None,
    context_overrides: dict[str, Any] | None = None,
    future_label: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)
    candles, future_candles = _candles_from_closes(base, closes, future_extra=future_close)
    decision_time = base + timedelta(minutes=len(closes) - 1)
    price = closes[-1]
    return {
        "scenario_name": name,
        "categories": categories,
        "symbol": symbol,
        "timeframe": timeframe,
        "decision_time": _iso(decision_time),
        "price": price,
        "candles": candles,
        "future_candles": future_candles,
        "trades": _trades(base, price, side=tape_side, weak=tape_weak),
        "future_trades": _trades(base, price, side="sell" if tape_side == "buy" else "buy", weak=True, future=True),
        "candidate": {
            "symbol": symbol,
            "timeframe": timeframe,
            "side": side,
            "action": side,
            "strategy_id": strategy,
            "strategy_selected_mode": strategy,
            "market_regime": regime,
            "market_regime_at_entry": regime,
            "confidence_raw": 0.72,
            "confidence_calibrated": 0.68,
            "expected_move_bps": expected_edge + 8.0,
            "expected_move_after_cost_bps": expected_edge,
            "composite_microstructure_trust_score": 0.82,
            "trade_tape_confirmation_score": 0.72,
            "cross_venue_confirmation_score": 0.7,
            "stop_distance_bps": stop_distance,
            "ATR_bps": atr_bps,
            "spread_bps": 2.0,
            "slippage_bps": 2.0,
            "fee_bps": 1.0,
            "funding_bps": 0.1,
            "gross_notional_usd": 1000.0,
            "target_notional_usd": 1000.0,
            "risk_budget_usd": 8.0,
            "orderbook_depth_usd": 10000.0,
            "exit_feasibility_score": 0.9,
        },
        "closed_rows": closed_rows if closed_rows is not None else _healthy_rows(symbol, timeframe, side, strategy, regime),
        "context_overrides": context_overrides or {},
        "expected_decisions": expected_decisions,
        "future_label": future_label or {"future_return_bps": 40.0 if side == "long" else -40.0},
    }


def build_default_advanced_indicator_replay_scenarios() -> list[dict[str, Any]]:
    """Return the required replay matrix as deterministic point-in-time fixtures."""

    return [
        _scenario(
            name="btc_major_move_long_winner",
            categories=["BTC_ETH_SOL_MAJOR_MOVES"],
            symbol="BTCUSDT",
            side="long",
            closes=[100, 101, 102, 104, 106, 109, 112, 116, 120, 125, 131, 138],
            future_close=150,
            expected_decisions=["ALLOW"],
        ),
        _scenario(
            name="eth_major_move_short_winner",
            categories=["BTC_ETH_SOL_MAJOR_MOVES"],
            symbol="ETHUSDT",
            side="short",
            closes=[220, 218, 215, 211, 207, 202, 197, 191, 186, 181, 176, 170],
            tape_side="sell",
            regime="BEAR",
            future_close=150,
            expected_decisions=["ALLOW"],
        ),
        _scenario(
            name="sol_trend_continuation_winner",
            categories=["BTC_ETH_SOL_MAJOR_MOVES", "TREND_CONTINUATION"],
            symbol="SOLUSDT",
            side="long",
            closes=[50, 51, 52, 54, 55, 57, 58, 61, 63, 66, 69, 73],
            future_close=82,
            expected_decisions=["ALLOW"],
        ),
        _scenario(
            name="fake_breakout_high_sweep_risk_blocks_long",
            categories=["FAKE_BREAKOUTS", "LIQUIDITY_SWEEPS"],
            symbol="AVAXUSDT",
            side="long",
            closes=[100, 101, 102, 101, 103, 102, 104, 103, 105, 104, 107, 105],
            tape_weak=True,
            expected_decisions=["NO_TRADE"],
            context_overrides={"sweep_risk_long_side": 0.92, "trade_tape_confirmation_score": 0.25},
            future_close=95,
        ),
        _scenario(
            name="fake_breakdown_high_sweep_risk_blocks_short",
            categories=["FAKE_BREAKDOWNS", "LIQUIDITY_SWEEPS"],
            symbol="LINKUSDT",
            side="short",
            closes=[100, 99, 98, 99, 97, 98, 96, 97, 95, 96, 93, 95],
            tape_side="sell",
            tape_weak=True,
            regime="BEAR",
            expected_decisions=["NO_TRADE"],
            context_overrides={"sweep_risk_short_side": 0.9, "trade_tape_confirmation_score": 0.25},
            future_close=105,
        ),
        _scenario(
            name="fvg_retest_with_confirmation_not_standalone",
            categories=["FVG_RETESTS"],
            symbol="BNBUSDT",
            side="long",
            closes=[100, 101, 108, 107, 106, 110, 113, 115, 118, 121, 125, 130],
            expected_decisions=["ALLOW"],
            expected_edge=50.0,
            stop_distance=40.0,
            context_overrides={
                "bullish_fvg_present": True,
                "bearish_fvg_present": False,
                "fvg_retest_confirmed": True,
                "fvg_orderbook_trust_confluence": 0.82,
                "fvg_trade_tape_confirmation": 0.8,
                "fvg_expected_edge_after_cost": 50.0,
            },
            future_close=140,
        ),
        _scenario(
            name="high_confidence_loss_bucket_blocks_reentry",
            categories=["HIGH_CONFIDENCE_LOSSES"],
            symbol="CRVUSDT",
            side="short",
            closes=[100, 99, 101, 103, 104, 106, 108, 110, 113, 116, 120, 124],
            tape_side="sell",
            regime="HIGH_VOLATILITY",
            strategy="scalp_mode",
            expected_edge=18.0,
            stop_distance=50.0,
            closed_rows=_loss_rows("CRVUSDT", "5m", "short", "scalp_mode", "HIGH_VOLATILITY"),
            context_overrides={"sweep_risk_short_side": 0.65, "trade_tape_confirmation_score": 0.4},
            expected_decisions=["NO_TRADE"],
            future_close=135,
        ),
        _scenario(
            name="atr_stop_cluster_blocks_reentry",
            categories=["ATR_STOP_CLUSTERS"],
            symbol="DOGEUSDT",
            side="long",
            closes=[100, 101, 99, 102, 100, 103, 101, 104, 102, 105, 103, 106],
            closed_rows=_loss_rows("DOGEUSDT", "5m", "long", "trend_mode", "TREND", atr=True),
            expected_decisions=["NO_TRADE"],
            future_close=94,
        ),
        _scenario(
            name="range_chop_thin_edge_shadow_or_blocks",
            categories=["RANGE_CHOP"],
            symbol="ADAUSDT",
            side="long",
            closes=[100, 101, 100, 101, 99, 100, 101, 100, 99, 100, 101, 100],
            regime="RANGE",
            expected_edge=2.0,
            stop_distance=28.0,
            context_overrides={"sweep_risk_long_side": 0.55},
            expected_decisions=["NO_TRADE", "SHADOW_ONLY"],
            future_close=99,
        ),
    ]


def _merge_context(payloads: list[Mapping[str, Any]], overrides: Mapping[str, Any] | None) -> dict[str, Any]:
    context: dict[str, Any] = {}
    for payload in payloads:
        for field in ADVANCED_CONTEXT_FIELDS:
            value = payload.get(field)
            if value not in (None, ""):
                context[field] = value
    if isinstance(overrides, Mapping):
        for key, value in overrides.items():
            if value not in (None, ""):
                context[key] = value
    return context


def _payload_timestamp_safe(payload: Mapping[str, Any], decision_time: datetime) -> bool:
    available_at = parse_time(payload.get("available_at"))
    payload_decision_time = parse_time(payload.get("decision_time"))
    event_time = parse_time(payload.get("event_time"))
    return (
        available_at is not None
        and payload_decision_time is not None
        and event_time is not None
        and available_at <= decision_time
        and payload_decision_time <= decision_time
    )


def _forbidden_label_keys_present(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key) in FORBIDDEN_FEATURE_LABEL_KEYS:
                found.append(str(key))
            found.extend(_forbidden_label_keys_present(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_forbidden_label_keys_present(child))
    return found


def run_advanced_indicator_replay_scenarios(
    scenarios: list[Mapping[str, Any]] | None = None,
    *,
    generated_utc: str | None = None,
) -> dict[str, Any]:
    scenarios = scenarios or build_default_advanced_indicator_replay_scenarios()
    rows: list[dict[str, Any]] = []
    categories = set()
    future_leak_failures = 0
    expected_decision_failures = 0
    winning_blind_blocks = 0
    losing_not_prevented = 0
    fvg_standalone_approvals = 0

    for scenario in scenarios:
        name = str(scenario.get("scenario_name") or "")
        symbol = str(scenario.get("symbol") or "").upper()
        timeframe = str(scenario.get("timeframe") or "5m")
        decision_time = parse_time(scenario.get("decision_time"))
        if decision_time is None:
            raise ValueError(f"{name or 'scenario'} missing decision_time")
        categories.update(str(item) for item in scenario.get("categories") or [])
        candles = list(scenario.get("candles") or []) + list(scenario.get("future_candles") or [])
        trades = list(scenario.get("trades") or []) + list(scenario.get("future_trades") or [])
        price = _f(scenario.get("price"))
        candidate = dict(scenario.get("candidate") or {})
        expected_edge = _f(candidate.get("expected_move_after_cost_bps"))
        tape = compute_trade_tape_features(
            symbol=symbol,
            timeframe=timeframe,
            trades=trades,
            decision_time=decision_time,
        )
        liquidity = compute_liquidity_zones(
            symbol=symbol,
            timeframe=timeframe,
            candles=candles,
            price=price,
            trade_tape=tape,
            orderbook_features=scenario.get("orderbook_features"),
            liquidation_levels=scenario.get("liquidation_levels"),
            decision_time=decision_time,
        )
        fvg = compute_fvg(
            symbol=symbol,
            timeframe=timeframe,
            candles=candles,
            price=price,
            liquidity_zones=liquidity,
            orderbook_trust_score=_f(candidate.get("composite_microstructure_trust_score")),
            trade_tape={**tape, "expected_edge_after_cost_bps": expected_edge},
            decision_time=decision_time,
        )
        structure = compute_structure(
            symbol=symbol,
            timeframe=timeframe,
            candles=candles,
            price=price,
            decision_time=decision_time,
        )
        vwap = compute_vwap_features(
            symbol=symbol,
            timeframe=timeframe,
            candles=candles,
            price=price,
            decision_time=decision_time,
        )
        volume_profile = compute_volume_profile(
            symbol=symbol,
            timeframe=timeframe,
            candles=candles,
            price=price,
            decision_time=decision_time,
        )
        cvd = compute_cvd_features(
            symbol=symbol,
            timeframe=timeframe,
            candles=candles,
            price=price,
            decision_time=decision_time,
        )
        payloads = [liquidity, fvg, structure, vwap, volume_profile, cvd, tape]
        context = _merge_context(payloads, scenario.get("context_overrides"))
        replay_candidate = {
            **candidate,
            "advanced_indicator_context": context,
        }
        decision = evaluate_candidate(
            replay_candidate,
            closed_rows=[dict(row) for row in scenario.get("closed_rows") or []],
            continuous_edge_guardian_gate={
                "status": "ACTIVE",
                "a_grade_new_entries_allowed": True,
                "new_entries_allowed": True,
            },
        )
        decision_name = str(decision.get("preemptive_decision") or "")
        expected_decisions = {str(item) for item in scenario.get("expected_decisions") or []}
        payload_safe = all(_payload_timestamp_safe(payload, decision_time) for payload in payloads)
        excluded_future_rows = sum(
            int((payload.get("timestamp_lineage") or {}).get("excluded_future_rows") or 0)
            for payload in payloads
        )
        future_labels_used = bool(
            _forbidden_label_keys_present(replay_candidate)
            or _forbidden_label_keys_present(context)
        )
        expected_decision_pass = not expected_decisions or decision_name in expected_decisions
        if not expected_decision_pass:
            expected_decision_failures += 1
        future_leakage_pass = payload_safe and not future_labels_used
        if not future_leakage_pass:
            future_leak_failures += 1
        is_winning = any(category in {"BTC_ETH_SOL_MAJOR_MOVES", "TREND_CONTINUATION", "FVG_RETESTS"} for category in scenario.get("categories") or [])
        is_losing = any(category in {"HIGH_CONFIDENCE_LOSSES", "ATR_STOP_CLUSTERS", "FAKE_BREAKOUTS", "FAKE_BREAKDOWNS", "LIQUIDITY_SWEEPS", "RANGE_CHOP"} for category in scenario.get("categories") or [])
        if is_winning and decision_name == "NO_TRADE":
            winning_blind_blocks += 1
        if is_losing and decision_name not in LOSS_PREVENTION_DECISIONS:
            losing_not_prevented += 1
        if decision.get("fvg_standalone_allows_trade") is True:
            fvg_standalone_approvals += 1
        rows.append(
            {
                "scenario_name": name,
                "categories": list(scenario.get("categories") or []),
                "symbol": symbol,
                "timeframe": timeframe,
                "decision_time": scenario.get("decision_time"),
                "decision": decision_name,
                "preemptive_decision_id": decision.get("preemptive_decision_id"),
                "pre_trade_loss_probability": decision.get("pre_trade_loss_probability"),
                "advanced_indicator_status": decision.get("advanced_indicator_status"),
                "advanced_indicator_block_reasons": decision.get("advanced_indicator_block_reasons"),
                "advanced_indicator_caution_reasons": decision.get("advanced_indicator_caution_reasons"),
                "expected_decision_pass": expected_decision_pass,
                "future_leakage_pass": future_leakage_pass,
                "future_labels_used_as_features": future_labels_used,
                "excluded_future_rows": excluded_future_rows,
                "payload_timestamp_safe": payload_safe,
                "fvg_standalone_allows_trade": decision.get("fvg_standalone_allows_trade"),
                "winning_move_not_blindly_blocked": not (is_winning and decision_name == "NO_TRADE"),
                "old_losing_trade_blocked_or_improved": not (is_losing and decision_name not in LOSS_PREVENTION_DECISIONS),
                "entry_exit_decision_replayed": bool(decision.get("advanced_indicator_exit_plan_inputs")) and bool(decision.get("preemptive_decision_id")),
                "exit_plan_inputs": decision.get("advanced_indicator_exit_plan_inputs"),
            }
        )

    missing_categories = [
        category for category in REQUIRED_REPLAY_CATEGORIES if category not in categories
    ]
    all_entry_exit_replayed = all(row["entry_exit_decision_replayed"] for row in rows)
    ready = (
        not missing_categories
        and future_leak_failures == 0
        and expected_decision_failures == 0
        and winning_blind_blocks == 0
        and losing_not_prevented == 0
        and fvg_standalone_approvals == 0
        and all_entry_exit_replayed
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc or datetime.now(timezone.utc).isoformat(),
        "status": "ADVANCED_INDICATOR_REPLAY_READY" if ready else "ADVANCED_INDICATOR_REPLAY_BLOCKED",
        "scenario_count": len(rows),
        "required_categories": list(REQUIRED_REPLAY_CATEGORIES),
        "covered_categories": sorted(categories),
        "missing_categories": missing_categories,
        "future_leak_failures": future_leak_failures,
        "expected_decision_failures": expected_decision_failures,
        "winning_blind_blocks": winning_blind_blocks,
        "losing_not_prevented": losing_not_prevented,
        "fvg_standalone_approvals": fvg_standalone_approvals,
        "all_entry_exit_decisions_replayed": all_entry_exit_replayed,
        "future_labels_used_as_features": False if future_leak_failures == 0 else True,
        "rows": rows,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


__all__ = [
    "REQUIRED_REPLAY_CATEGORIES",
    "build_default_advanced_indicator_replay_scenarios",
    "run_advanced_indicator_replay_scenarios",
]
