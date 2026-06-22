"""Build paper-only accelerated replay evidence from closed V2 candle cache.

This CLI reads local Redis closed-candle snapshots, derives offline
counterfactual LONG/SHORT candidates from past-only candle features, labels
them with future closed candles, and writes local JSON artifacts only. It never
writes Redis, mutates exchange state, or routes orders.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.cli.v2_adaptive_capital_productivity_status import (
    DEFAULT_OUT_DIR,
    GOAL_ID,
    LIVE_GATE,
    SCHEMA_VERSION,
    SIGNAL_ACCURACY_TIMEFRAMES,
    STOP_WAITING_PHASE_ID,
    _coerce_float,
    _connect_redis,
    _first_present,
    _iso_from_ms,
    _parse_epoch_ms,
    _redis_json,
    _utc_iso,
)


ROWS_FILENAME = "closed_candle_replay_evidence_rows.jsonl"
STATUS_FILENAME = "closed_candle_replay_evidence_status.json"
DEFAULT_MAX_ROWS = 20_000
DEFAULT_MAX_KEYS = 1_000
DEFAULT_MIN_PAST_CANDLES = 12
DEFAULT_FUTURE_HORIZON_CANDLES = 5
DEFAULT_GROSS_NOTIONAL_USD = 1_000.0
DEFAULT_LEVERAGE = 2.0
DEFAULT_FEE_BPS = 8.0
TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 5 * 60,
    "15m": 15 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
}


def _closed_candle_key_parts(key: str) -> tuple[str, str] | None:
    parts = key.split(":")
    if len(parts) != 6:
        return None
    if parts[:4] != ["v2", "market", "ohlcv_closed", "binance"]:
        return None
    symbol = parts[4].strip().upper()
    timeframe = parts[5].strip()
    if not symbol or timeframe not in SIGNAL_ACCURACY_TIMEFRAMES:
        return None
    return symbol, timeframe


def _payload_rows(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, (dict, list))]
    if not isinstance(payload, dict):
        return []
    for key in ("candles", "rows", "items", "data", "market_candles"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, (dict, list))]
    if any(key in payload for key in ("close", "close_time", "candle_close_time", "ohlcv")):
        return [dict(payload)]
    return []


def _field_float(row: dict[str, Any], *fields: str) -> float | None:
    ohlcv = row.get("ohlcv") if isinstance(row.get("ohlcv"), dict) else {}
    for field in fields:
        value = _coerce_float(_first_present(row.get(field), ohlcv.get(field)))
        if value is not None:
            return value
    return None


def _closed_flag_valid(row: dict[str, Any], *, source_key: str) -> bool:
    flags = (
        row.get("candle_closed_confirmed"),
        row.get("closed_candle"),
        row.get("is_closed"),
        row.get("feature_eligible"),
    )
    if any(value is False for value in flags):
        return False
    if "ohlcv_closed:" in source_key:
        return True
    return any(value is True for value in flags)


def _normalized_candle(
    row: Any,
    *,
    source_key: str,
    symbol: str,
    timeframe: str,
    generated_ms: int,
) -> tuple[dict[str, Any] | None, str | None]:
    if isinstance(row, list) and len(row) >= 7:
        open_time_ms = _parse_epoch_ms(row[0])
        open_value = _coerce_float(row[1])
        high = _coerce_float(row[2])
        low = _coerce_float(row[3])
        close = _coerce_float(row[4])
        volume = _coerce_float(row[5])
        close_time_ms = _parse_epoch_ms(row[6])
        available_at_ms = close_time_ms
        quote_volume = None
    elif isinstance(row, dict):
        if not _closed_flag_valid(row, source_key=source_key):
            return None, "UNFINISHED_CANDLE"
        open_time_ms = _parse_epoch_ms(_first_present(row.get("candle_open_time"), row.get("open_time"), row.get("ts")))
        close_time_ms = _parse_epoch_ms(_first_present(
            row.get("candle_close_time"),
            row.get("close_time"),
            row.get("source_sequence_id"),
        ))
        available_at_ms = _parse_epoch_ms(_first_present(row.get("available_at"), row.get("ingested_at"), row.get("event_time")))
        open_value = _field_float(row, "open")
        high = _field_float(row, "high")
        low = _field_float(row, "low")
        close = _field_float(row, "close")
        volume = _field_float(row, "volume")
        quote_volume = _field_float(row, "quote_volume")
    else:
        return None, "UNSUPPORTED_CANDLE_ROW"

    if close_time_ms is None:
        return None, "MISSING_CANDLE_CLOSE_TIME"
    if available_at_ms is None:
        return None, "MISSING_AVAILABLE_AT"
    if available_at_ms < close_time_ms:
        return None, "AVAILABLE_AT_BEFORE_CANDLE_CLOSE"
    if close_time_ms > generated_ms:
        return None, "CANDLE_CLOSE_TIME_AFTER_GENERATED_AT"
    if available_at_ms > generated_ms:
        return None, "AVAILABLE_AT_AFTER_GENERATED_AT"
    if close is None or close <= 0.0:
        return None, "MISSING_OR_NON_POSITIVE_CLOSE"
    if high is None or high <= 0.0:
        high = close
    if low is None or low <= 0.0:
        low = close
    if open_value is None or open_value <= 0.0:
        open_value = close
    if low > high:
        return None, "LOW_ABOVE_HIGH"
    if open_time_ms is None:
        open_time_ms = close_time_ms - TIMEFRAME_SECONDS.get(timeframe, 60) * 1000 + 1
    if volume is None or volume < 0.0:
        volume = 0.0
    if quote_volume is None or quote_volume <= 0.0:
        quote_volume = close * volume if close > 0.0 else 0.0

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "source_redis_key": source_key,
        "open_time_ms": open_time_ms,
        "close_time_ms": close_time_ms,
        "available_at_ms": available_at_ms,
        "open": open_value,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "quote_volume": quote_volume,
    }, None


def _returns_bps(candles: list[dict[str, Any]], start: int, end: int) -> list[float]:
    values: list[float] = []
    for index in range(max(1, start), min(end, len(candles))):
        previous = _coerce_float(candles[index - 1].get("close"))
        current = _coerce_float(candles[index].get("close"))
        if previous is not None and current is not None and previous > 0.0:
            values.append((current / previous - 1.0) * 10000.0)
    return values


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def _range_bps(candles: list[dict[str, Any]]) -> float:
    highs = [_coerce_float(row.get("high")) for row in candles]
    lows = [_coerce_float(row.get("low")) for row in candles]
    closes = [_coerce_float(row.get("close")) for row in candles]
    highs = [value for value in highs if value is not None and value > 0.0]
    lows = [value for value in lows if value is not None and value > 0.0]
    closes = [value for value in closes if value is not None and value > 0.0]
    if not highs or not lows or not closes:
        return 0.0
    base = closes[-1]
    return (max(highs) / min(lows) - 1.0) * 10000.0 if base > 0.0 else 0.0


def _regime_bucket(
    *,
    lookback_candles: list[dict[str, Any]],
    lookback_returns_bps: list[float],
    current: dict[str, Any],
) -> str:
    cumulative = sum(lookback_returns_bps)
    volatility = _stddev(lookback_returns_bps)
    range_bps = _range_bps(lookback_candles)
    direction_changes = 0
    previous_sign = 0
    for value in lookback_returns_bps:
        sign = 1 if value > 0.0 else -1 if value < 0.0 else 0
        if previous_sign and sign and sign != previous_sign:
            direction_changes += 1
        if sign:
            previous_sign = sign
    current_close = float(current["close"])
    previous_high = max(float(row["high"]) for row in lookback_candles[:-1]) if len(lookback_candles) > 1 else current_close
    previous_low = min(float(row["low"]) for row in lookback_candles[:-1]) if len(lookback_candles) > 1 else current_close
    current_range = max(0.0, (float(current["high"]) / max(0.00000001, float(current["low"])) - 1.0) * 10000.0)
    body_bps = abs(float(current["close"]) / max(0.00000001, float(current["open"])) - 1.0) * 10000.0
    if volatility <= 8.0 and range_bps <= 35.0:
        return "squeeze"
    if direction_changes >= max(4, len(lookback_returns_bps) // 3) and abs(cumulative) <= max(25.0, volatility * 1.5):
        return "whipsaw"
    broke_high_and_rejected = current_close > previous_high and body_bps < current_range * 0.35
    broke_low_and_rejected = current_close < previous_low and body_bps < current_range * 0.35
    if broke_high_and_rejected or broke_low_and_rejected:
        return "false_breakout"
    if cumulative >= max(25.0, volatility * 1.5):
        return "bull"
    if cumulative <= -max(25.0, volatility * 1.5):
        return "bear"
    return "range"


def _strategy_family(*, side: str, regime: str, signal_bps: float) -> str:
    side_sign = 1.0 if side == "long" else -1.0
    aligned_with_signal = side_sign * signal_bps > 0.0
    if regime in {"bull", "bear"}:
        return "trend_continuation" if aligned_with_signal else "mean_reversion"
    if regime == "squeeze":
        return "volatility_expansion"
    if regime == "false_breakout":
        return "false_breakout_reversal" if not aligned_with_signal else "breakout_follow_through"
    if regime == "whipsaw":
        return "whipsaw_defense"
    return "range_rotation"


def _volatility_bucket(volatility_bps: float) -> str:
    if volatility_bps < 50.0:
        return "low"
    if volatility_bps < 150.0:
        return "medium"
    return "high"


def _liquidity_bucket(depth_usd: float) -> str:
    if depth_usd >= 250_000.0:
        return "high"
    if depth_usd >= 25_000.0:
        return "medium"
    return "low"


def _candidate_row(
    *,
    source_key: str,
    source_index: int,
    side: str,
    candles: list[dict[str, Any]],
    decision_index: int,
    future_index: int,
    min_past_candles: int,
    generated_utc: str,
) -> dict[str, Any]:
    current = candles[decision_index]
    future = candles[future_index]
    lookback = candles[decision_index - min_past_candles: decision_index + 1]
    lookback_returns = _returns_bps(candles, decision_index - min_past_candles + 1, decision_index + 1)
    volatility_bps = _stddev(lookback_returns)
    cumulative_bps = sum(lookback_returns)
    last_bps = lookback_returns[-1] if lookback_returns else 0.0
    signal_bps = cumulative_bps * 0.65 + last_bps * 0.35
    side_sign = 1.0 if side == "long" else -1.0
    entry_price = float(current["close"])
    exit_price = float(future["close"])
    future_return_bps = (exit_price / entry_price - 1.0) * 10000.0
    high_path = max(float(row["high"]) for row in candles[decision_index + 1: future_index + 1])
    low_path = min(float(row["low"]) for row in candles[decision_index + 1: future_index + 1])
    quote_volume = float(current.get("quote_volume") or 0.0)
    depth_usd = max(DEFAULT_GROSS_NOTIONAL_USD * 10.0, quote_volume * 0.02)
    gross_notional = min(DEFAULT_GROSS_NOTIONAL_USD, max(50.0, depth_usd * 0.05))
    allocated_margin = gross_notional / DEFAULT_LEVERAGE
    candle_range_bps = max(1.0, (float(current["high"]) / max(0.00000001, float(current["low"])) - 1.0) * 10000.0)
    observed_spread_bps = max(0.5, min(25.0, candle_range_bps * 0.02))
    depth_impact_bps = min(50.0, gross_notional / max(1.0, depth_usd) * 10000.0)
    expected_slippage_bps = max(0.5, min(50.0, observed_spread_bps * 0.5 + depth_impact_bps * 0.25))
    estimated_cost_bps = observed_spread_bps + expected_slippage_bps + DEFAULT_FEE_BPS
    expected_move_after_cost_bps = side_sign * signal_bps - estimated_cost_bps
    confidence = min(0.88, max(0.50, 0.55 + min(0.25, abs(signal_bps) / 240.0) + min(0.08, volatility_bps / 600.0)))
    regime = _regime_bucket(
        lookback_candles=lookback,
        lookback_returns_bps=lookback_returns,
        current=current,
    )
    strategy = _strategy_family(side=side, regime=regime, signal_bps=signal_bps)
    stop_distance_bps = max(30.0, min(300.0, volatility_bps * 1.5 if volatility_bps > 0.0 else candle_range_bps * 2.0))
    take_profit_bps = stop_distance_bps * 1.5
    funding_bps = 0.0
    after_cost_return_bps = side_sign * future_return_bps - estimated_cost_bps - funding_bps
    realized_pnl_usd = gross_notional * after_cost_return_bps / 10000.0
    expected_net_pnl_usd = gross_notional * expected_move_after_cost_bps / 10000.0
    expected_shortfall_usd = gross_notional * stop_distance_bps / 10000.0
    maintenance_margin_rate = 0.005
    liquidation_distance_bps = (1.0 / DEFAULT_LEVERAGE - maintenance_margin_rate) * 10000.0
    liquidation_buffer_bps = max(0.0, liquidation_distance_bps - stop_distance_bps - estimated_cost_bps)
    if side == "long":
        mfe_bps = max(0.0, (high_path / entry_price - 1.0) * 10000.0)
        mae_bps = max(0.0, (1.0 - low_path / entry_price) * 10000.0)
    else:
        mfe_bps = max(0.0, (1.0 - low_path / entry_price) * 10000.0)
        mae_bps = max(0.0, (high_path / entry_price - 1.0) * 10000.0)

    decision_time = _iso_from_ms(int(current["available_at_ms"]))
    feature_cutoff = _iso_from_ms(int(current["close_time_ms"]))
    closed_at = _iso_from_ms(int(future["close_time_ms"]))
    source_symbol = str(current["symbol"])
    timeframe = str(current["timeframe"])
    row_id = f"{source_symbol}:{timeframe}:{int(current['close_time_ms'])}:{side}"
    prediction_id = f"closed_candle_replay:{row_id}"
    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "phase_id": STOP_WAITING_PHASE_ID,
        "counterfactual_source_kind": "closed_candle_replay",
        "row_id": row_id,
        "prediction_id": prediction_id,
        "source_redis_key": f"{source_key}:closed_candle_replay:{int(current['close_time_ms'])}:{side}",
        "source_closed_candle_redis_key": source_key,
        "source_closed_candle_index": source_index,
        "symbol": source_symbol,
        "timeframe": timeframe,
        "side": side,
        "action": side,
        "strategy": strategy,
        "strategy_family": strategy,
        "market_regime": regime,
        "regime": regime,
        "volatility_bucket": _volatility_bucket(volatility_bps),
        "liquidity_bucket": _liquidity_bucket(depth_usd),
        "confidence": round(confidence, 8),
        "confidence_calibrated": round(confidence, 8),
        "confidence_source": "closed_candle_replay_past_only_proxy",
        "expected_move_after_cost_bps": round(expected_move_after_cost_bps, 8),
        "expected_net_edge_bps": round(expected_move_after_cost_bps, 8),
        "realized_after_cost_return_bps": round(after_cost_return_bps, 8),
        "after_cost_return_bps": round(after_cost_return_bps, 8),
        "realized_pnl_usd": round(realized_pnl_usd, 8),
        "outcome_after_cost_usd": round(realized_pnl_usd, 8),
        "expected_net_pnl_usd": round(expected_net_pnl_usd, 8),
        "entry_price": round(entry_price, 12),
        "exit_price": round(exit_price, 12),
        "closed_at": closed_at,
        "future_label_close_time": closed_at,
        "future_label_horizon_candles": future_index - decision_index,
        "future_label_used_as_outcome_only": True,
        "future_labels_used_as_features": False,
        "decision_time": decision_time,
        "available_at": decision_time,
        "generated_at": decision_time,
        "feature_cutoff": feature_cutoff,
        "entry_feature_decision_time": decision_time,
        "entry_feature_available_at": decision_time,
        "entry_feature_generated_at": decision_time,
        "entry_feature_cutoff": feature_cutoff,
        "entry_feature_candle_closed_confirmed": True,
        "candle_closed_confirmed": True,
        "closed_candle": True,
        "is_closed": True,
        "feature_eligible": True,
        "event_time": decision_time,
        "source_event_time": feature_cutoff,
        "generated_utc": generated_utc,
        "gross_notional_usd": round(gross_notional, 8),
        "notional": round(gross_notional, 8),
        "notional_usdt": round(gross_notional, 8),
        "allocated_margin_usd": round(allocated_margin, 8),
        "recommended_leverage": DEFAULT_LEVERAGE,
        "effective_leverage": DEFAULT_LEVERAGE,
        "leverage": DEFAULT_LEVERAGE,
        "recommended_margin_mode": "isolated_paper_simulated",
        "margin_mode": "isolated_paper_simulated",
        "maintenance_margin_rate": maintenance_margin_rate,
        "stop_distance_bps": round(stop_distance_bps, 8),
        "stop_loss_bps": round(stop_distance_bps, 8),
        "take_profit_structure": "one_r_two_r_grid",
        "take_profit_bps": round(take_profit_bps, 8),
        "hedge_enabled": False,
        "hedge_budget_usd": 0.0,
        "actual_observed_spread_entry_bps": round(observed_spread_bps, 8),
        "spread_bps": round(observed_spread_bps, 8),
        "spread_source": "closed_candle_range_proxy_at_decision_time",
        "orderbook_depth_usd": round(depth_usd, 8),
        "market_depth_capacity_usd": round(depth_usd, 8),
        "depth_impact_bps": round(depth_impact_bps, 8),
        "depth_impact_usd": round(gross_notional * depth_impact_bps / 10000.0, 8),
        "depth_source": "closed_candle_quote_volume_proxy_at_decision_time",
        "fee_bps": DEFAULT_FEE_BPS,
        "expected_fee_bps": DEFAULT_FEE_BPS,
        "expected_fees_usd": round(gross_notional * DEFAULT_FEE_BPS / 10000.0, 8),
        "expected_slippage_bps": round(expected_slippage_bps, 8),
        "expected_slippage_usd": round(gross_notional * expected_slippage_bps / 10000.0, 8),
        "expected_funding_bps": funding_bps,
        "funding_bps": funding_bps,
        "funding_rate": 0.0,
        "expected_funding_usd": 0.0,
        "funding_pnl_usd": 0.0,
        "funding_pnl_source": "neutral_no_historical_pit_funding_rate_available",
        "funding_pnl_accounting_status": "ACCOUNTED_NEUTRAL_WHEN_HISTORICAL_RATE_ABSENT",
        "liquidation_buffer_bps": round(liquidation_buffer_bps, 8),
        "liquidation_price_estimate": round(
            entry_price * (1.0 - 1.0 / DEFAULT_LEVERAGE + maintenance_margin_rate)
            if side == "long"
            else entry_price * (1.0 + 1.0 / DEFAULT_LEVERAGE - maintenance_margin_rate),
            12,
        ),
        "correlation_exposure_pct": 0.0,
        "portfolio_correlation": 0.0,
        "correlation_input_source": "single_candidate_replay_proxy_no_portfolio_overlap",
        "entry_atr_bps": round(volatility_bps, 8),
        "realized_volatility_bps": round(volatility_bps, 8),
        "mfe_bps": round(mfe_bps, 8),
        "mae_bps": round(mae_bps, 8),
        "drawdown_bps": round(-mae_bps, 8),
        "allocator_decision": "ALLOW_WITH_SIZE",
        "paper_only": True,
        "offline_replay_only": True,
        "places_real_order": False,
        "live_gate": LIVE_GATE,
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "live_symbols": [],
    }


def _source_status_from_sources(candle_sources: dict[str, list[Any]]) -> dict[str, Any]:
    key_parts = [_closed_candle_key_parts(key) for key in candle_sources]
    symbol_timeframes: dict[str, set[str]] = {}
    for parts in key_parts:
        if parts is None:
            continue
        symbol, timeframe = parts
        symbol_timeframes.setdefault(symbol, set()).add(timeframe)
    complete_symbols = sorted(
        symbol
        for symbol, timeframes in symbol_timeframes.items()
        if set(SIGNAL_ACCURACY_TIMEFRAMES).issubset(timeframes)
    )
    return {
        "source_key_count": len(candle_sources),
        "source_symbol_count": len(symbol_timeframes),
        "complete_five_timeframe_symbol_count": len(complete_symbols),
        "complete_five_timeframe_symbols_sample": complete_symbols[:100],
    }


def generate_closed_candle_replay_evidence(
    candle_sources: dict[str, list[Any]],
    *,
    generated_utc: str,
    max_rows: int = DEFAULT_MAX_ROWS,
    min_past_candles: int = DEFAULT_MIN_PAST_CANDLES,
    future_horizon_candles: int = DEFAULT_FUTURE_HORIZON_CANDLES,
    require_complete_timeframe_symbols: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    generated_ms = _parse_epoch_ms(generated_utc) or int(datetime.now(timezone.utc).timestamp() * 1000)
    source_status = _source_status_from_sources(candle_sources)
    symbol_timeframes: dict[str, set[str]] = {}
    for key in candle_sources:
        parts = _closed_candle_key_parts(key)
        if parts is not None:
            symbol, timeframe = parts
            symbol_timeframes.setdefault(symbol, set()).add(timeframe)
    complete_symbols = {
        symbol
        for symbol, timeframes in symbol_timeframes.items()
        if set(SIGNAL_ACCURACY_TIMEFRAMES).issubset(timeframes)
    }
    eligible_source_keys = [
        key
        for key in sorted(candle_sources)
        for parts in [_closed_candle_key_parts(key)]
        if parts is not None
        and (
            not require_complete_timeframe_symbols
            or parts[0] in complete_symbols
        )
    ]
    rows_per_source_cap = (
        max(2, math.ceil(max_rows / len(eligible_source_keys)))
        if eligible_source_keys
        else max_rows
    )

    rows: list[dict[str, Any]] = []
    reject_counts: dict[str, int] = {}
    key_statuses: list[dict[str, Any]] = []
    symbol_counts: dict[str, int] = {}
    timeframe_counts: dict[str, int] = {}
    side_counts: dict[str, int] = {}
    regime_counts: dict[str, int] = {}
    strategy_counts: dict[str, int] = {}

    def reject(reason: str, count: int = 1) -> None:
        reject_counts[reason] = reject_counts.get(reason, 0) + count

    for source_key in sorted(candle_sources):
        if len(rows) >= max_rows:
            break
        parts = _closed_candle_key_parts(source_key)
        if parts is None:
            reject("UNSUPPORTED_SOURCE_KEY")
            continue
        symbol, timeframe = parts
        if require_complete_timeframe_symbols and symbol not in complete_symbols:
            reject("SYMBOL_MISSING_COMPLETE_FIVE_TIMEFRAME_COVERAGE", len(candle_sources[source_key]))
            continue
        normalized: list[dict[str, Any]] = []
        key_reject_counts: dict[str, int] = {}
        for raw in candle_sources[source_key]:
            candle, reason = _normalized_candle(
                raw,
                source_key=source_key,
                symbol=symbol,
                timeframe=timeframe,
                generated_ms=generated_ms,
            )
            if candle is None:
                reason = reason or "UNKNOWN_CANDLE_REJECT"
                key_reject_counts[reason] = key_reject_counts.get(reason, 0) + 1
                reject(reason)
                continue
            normalized.append(candle)
        deduped = {
            int(candle["close_time_ms"]): candle
            for candle in normalized
        }
        candles = sorted(deduped.values(), key=lambda row: int(row["close_time_ms"]))
        if len(candles) <= min_past_candles + future_horizon_candles:
            reject("INSUFFICIENT_CLOSED_CANDLE_HISTORY_FOR_REPLAY")
            key_statuses.append({
                "source_key": source_key,
                "symbol": symbol,
                "timeframe": timeframe,
                "accepted_candle_count": len(candles),
                "generated_row_count": 0,
                "reject_counts": dict(sorted(key_reject_counts.items())),
            })
            continue

        key_row_start = len(rows)
        key_row_count = 0
        last_decision_index = len(candles) - future_horizon_candles - 1
        for decision_index in range(min_past_candles, last_decision_index + 1):
            if len(rows) >= max_rows or key_row_count >= rows_per_source_cap:
                break
            future_index = decision_index + future_horizon_candles
            if int(candles[future_index]["close_time_ms"]) <= int(candles[decision_index]["available_at_ms"]):
                reject("FUTURE_LABEL_NOT_AFTER_DECISION_TIME")
                continue
            for side in ("long", "short"):
                if len(rows) >= max_rows or key_row_count >= rows_per_source_cap:
                    break
                row = _candidate_row(
                    source_key=source_key,
                    source_index=decision_index,
                    side=side,
                    candles=candles,
                    decision_index=decision_index,
                    future_index=future_index,
                    min_past_candles=min_past_candles,
                    generated_utc=generated_utc,
                )
                rows.append(row)
                key_row_count += 1
                symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
                timeframe_counts[timeframe] = timeframe_counts.get(timeframe, 0) + 1
                side_counts[side] = side_counts.get(side, 0) + 1
                regime = str(row.get("market_regime") or "__unknown__")
                strategy = str(row.get("strategy") or "__unknown__")
                regime_counts[regime] = regime_counts.get(regime, 0) + 1
                strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
        key_statuses.append({
            "source_key": source_key,
            "symbol": symbol,
            "timeframe": timeframe,
            "accepted_candle_count": len(candles),
            "generated_row_count": len(rows) - key_row_start,
            "reject_counts": dict(sorted(key_reject_counts.items())),
        })

    status = {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "phase_id": STOP_WAITING_PHASE_ID,
        "generated_utc": generated_utc,
        "status": "READY_CLOSED_CANDLE_REPLAY_EVIDENCE" if rows else "NO_CLOSED_CANDLE_REPLAY_EVIDENCE",
        "row_count": len(rows),
        "max_rows": max_rows,
        "rows_per_source_key_cap": rows_per_source_cap,
        "eligible_source_key_count": len(eligible_source_keys),
        "min_past_candles": min_past_candles,
        "future_horizon_candles": future_horizon_candles,
        "require_complete_timeframe_symbols": require_complete_timeframe_symbols,
        "source_status": source_status,
        "source_keys_used_count": sum(1 for item in key_statuses if int(item.get("generated_row_count") or 0) > 0),
        "symbol_count": len(symbol_counts),
        "symbols_sample": sorted(symbol_counts)[:100],
        "timeframe_counts": {key: timeframe_counts[key] for key in sorted(timeframe_counts)},
        "side_counts": {key: side_counts[key] for key in sorted(side_counts)},
        "market_regime_counts": {key: regime_counts[key] for key in sorted(regime_counts)},
        "strategy_family_counts": {key: strategy_counts[key] for key in sorted(strategy_counts)},
        "reject_counts": {key: reject_counts[key] for key in sorted(reject_counts)},
        "key_status_sample": key_statuses[:50],
        "closed_candles_only": True,
        "feature_cutoff_lte_decision_time": True,
        "available_at_lte_decision_time": True,
        "future_data_labels_only": True,
        "paper_only": True,
        "offline_replay_only": True,
        "places_real_order": False,
        "live_gate": LIVE_GATE,
        "writes_redis": False,
        "mutates_exchange": False,
    }
    return rows, status


def read_closed_candle_sources_from_redis(*, max_keys: int = DEFAULT_MAX_KEYS) -> tuple[dict[str, list[Any]], dict[str, Any]]:
    client = _connect_redis()
    source_status: dict[str, Any] = {
        "redis_connected": client is not None,
        "scan_pattern": "v2:market:ohlcv_closed:binance:*",
        "max_keys": max_keys,
        "keys_scanned": 0,
        "payload_key_count": 0,
        "parse_or_empty_count": 0,
    }
    if client is None:
        return {}, source_status
    sources: dict[str, list[Any]] = {}
    try:
        iterator = client.scan_iter(match="v2:market:ohlcv_closed:binance:*", count=1000)
    except Exception as exc:  # noqa: BLE001
        source_status["scan_error"] = str(exc)
        return {}, source_status
    for key in iterator:
        if source_status["keys_scanned"] >= max_keys:
            break
        source_key = str(key)
        source_status["keys_scanned"] += 1
        if _closed_candle_key_parts(source_key) is None:
            continue
        rows = _payload_rows(_redis_json(client, source_key))
        if not rows:
            source_status["parse_or_empty_count"] += 1
            continue
        sources[source_key] = rows
        source_status["payload_key_count"] += 1
    return sources, source_status


def write_closed_candle_replay_evidence(
    rows: list[dict[str, Any]],
    status: dict[str, Any],
    *,
    out_dir: Path,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    row_path = out_dir / ROWS_FILENAME
    with row_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    status_path = out_dir / STATUS_FILENAME
    status_path.write_text(json.dumps(status, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--max-rows", type=int, default=DEFAULT_MAX_ROWS)
    parser.add_argument("--max-keys", type=int, default=DEFAULT_MAX_KEYS)
    parser.add_argument("--min-past-candles", type=int, default=DEFAULT_MIN_PAST_CANDLES)
    parser.add_argument("--future-horizon-candles", type=int, default=DEFAULT_FUTURE_HORIZON_CANDLES)
    parser.add_argument(
        "--allow-incomplete-timeframe-symbols",
        action="store_true",
        help="Include symbols that do not have all five required replay timeframes.",
    )
    args = parser.parse_args(argv)

    generated_utc = _utc_iso()
    candle_sources, redis_source_status = read_closed_candle_sources_from_redis(max_keys=args.max_keys)
    rows, status = generate_closed_candle_replay_evidence(
        candle_sources,
        generated_utc=generated_utc,
        max_rows=args.max_rows,
        min_past_candles=args.min_past_candles,
        future_horizon_candles=args.future_horizon_candles,
        require_complete_timeframe_symbols=not args.allow_incomplete_timeframe_symbols,
    )
    status["redis_source_status"] = redis_source_status
    write_closed_candle_replay_evidence(rows, status, out_dir=args.out_dir)
    print(json.dumps(status, indent=2, sort_keys=False))
    return 0 if rows else 2


if __name__ == "__main__":
    raise SystemExit(main())
