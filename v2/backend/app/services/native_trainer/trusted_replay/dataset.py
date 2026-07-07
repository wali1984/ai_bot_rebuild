"""Point-in-time trusted replay row construction.

Replay rows are outcome-supervised examples built from archived feature
snapshots and later finalized candles. They are intentionally not PPO rows.
"""
from __future__ import annotations

import math
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from v2.backend.app.services.market_state_integrity.trust import TRUST_SCHEMA_VERSION


HORIZON_SECONDS: dict[str, int] = {
    "5m": 5 * 60,
    "15m": 15 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
}
FUTURE_LABEL_PREFIXES = (
    "future_return",
    "future_",
    "label_",
    "target_",
    "realized_",
)
PIT_SAFE_REALIZED_FEATURES = {"realized_slippage_error"}


def _future_label_feature_name(name: Any) -> bool:
    lowered = str(name).lower()
    if lowered in PIT_SAFE_REALIZED_FEATURES:
        return False
    return lowered.startswith(FUTURE_LABEL_PREFIXES)


def parse_utc(value: Any) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        epoch = float(value)
        if epoch > 10_000_000_000:
            epoch /= 1000.0
        try:
            return datetime.fromtimestamp(epoch, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def timeframe_seconds(timeframe: str) -> int:
    unit = timeframe[-1:].lower()
    try:
        number = int(timeframe[:-1])
    except ValueError:
        return 60
    if unit == "m":
        return number * 60
    if unit == "h":
        return number * 60 * 60
    if unit == "d":
        return number * 24 * 60 * 60
    return 60


def snapshot_to_final_candle(snapshot: Mapping[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    reasons: list[str] = []
    features = snapshot.get("features") if isinstance(snapshot.get("features"), Mapping) else {}
    symbol = str(snapshot.get("symbol") or "").upper()
    timeframe = str(snapshot.get("timeframe") or "")
    feature_cutoff = parse_utc(snapshot.get("feature_cutoff"))
    available_at = parse_utc(snapshot.get("available_at") or snapshot.get("source_available_time"))
    if not symbol:
        reasons.append("SYMBOL_MISSING")
    if not timeframe:
        reasons.append("TIMEFRAME_MISSING")
    if not features:
        reasons.append("FEATURES_EMPTY")
    if feature_cutoff is None:
        reasons.append("FEATURE_CUTOFF_MISSING")
    if available_at is None:
        reasons.append("AVAILABLE_AT_MISSING")
    if snapshot.get("candle_closed_confirmed") is not True:
        reasons.append("OPEN_CANDLE_REJECTED")
    close_price = finite_float(
        features.get("close")
        or features.get("last_price")
        or features.get("price_last")
        or features.get("ohlcv_close")
    )
    if close_price is None or close_price <= 0.0:
        reasons.append("CLOSE_PRICE_MISSING")
    if reasons:
        return None, sorted(set(reasons))
    assert feature_cutoff is not None and available_at is not None and close_price is not None
    open_time = feature_cutoff - timedelta(seconds=timeframe_seconds(timeframe))
    raw_payload_hash = (
        str(snapshot.get("content_sha256"))
        if snapshot.get("content_sha256")
        else hashlib.sha256(
            json.dumps(
                {
                    "snapshot_id": snapshot.get("snapshot_id") or snapshot.get("feature_snapshot_id"),
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "feature_cutoff": iso_utc(feature_cutoff),
                    "available_at": iso_utc(available_at),
                    "features": {
                        name: features.get(name)
                        for name in ("open", "high", "low", "close", "last_price", "price_last")
                    },
                },
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
    )
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "candle_open_time": iso_utc(open_time),
        "candle_close_time": iso_utc(feature_cutoff),
        "event_time": iso_utc(feature_cutoff),
        "available_at": iso_utc(available_at),
        "is_closed": True,
        "closed_candle": True,
        "candle_closed_confirmed": True,
        "source": "v2_feature_snapshot_archive",
        "raw_payload_hash": raw_payload_hash,
        "open": finite_float(features.get("open")) or close_price,
        "high": finite_float(features.get("high")) or close_price,
        "low": finite_float(features.get("low")) or close_price,
        "close": close_price,
        "volume": finite_float(features.get("volume")) or 0.0,
        "source_snapshot_id": snapshot.get("snapshot_id") or snapshot.get("feature_snapshot_id"),
    }, []


def finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _candle_close_time(row: Mapping[str, Any]) -> datetime | None:
    return parse_utc(
        row.get("candle_close_time")
        or row.get("close_time")
        or row.get("closeTime")
        or row.get("event_time")
    )


def _candle_price(row: Mapping[str, Any], *names: str) -> float | None:
    for name in names:
        parsed = finite_float(row.get(name))
        if parsed is not None:
            return parsed
    return None


def _is_final_candle(row: Mapping[str, Any]) -> bool:
    return bool(
        row.get("is_closed") is True
        or row.get("closed_candle") is True
        or row.get("candle_closed_confirmed") is True
    )


def _later_finalized_candles(candles: Iterable[Mapping[str, Any]], decision_time: datetime) -> list[Mapping[str, Any]]:
    rows = [
        row
        for row in candles
        if isinstance(row, Mapping)
        and _is_final_candle(row)
        and (_candle_close_time(row) is not None)
        and (_candle_close_time(row) or decision_time) > decision_time
    ]
    rows.sort(key=lambda row: _candle_close_time(row) or decision_time)
    return rows


def _first_candle_at_or_after(
    candles: list[Mapping[str, Any]],
    target_time: datetime,
) -> Mapping[str, Any] | None:
    for candle in candles:
        close_time = _candle_close_time(candle)
        if close_time is not None and close_time >= target_time:
            return candle
    return None


def _directional_outcome(value_bps: float) -> str:
    if value_bps > 0:
        return "UP"
    if value_bps < 0:
        return "DOWN"
    return "FLAT"


def _trade_outcome(value_bps: float) -> str:
    if abs(value_bps) < 1e-9:
        return "BREAKEVEN"
    return "WIN" if value_bps > 0 else "LOSS"


def _target_action(value_bps: float, threshold_bps: float) -> str:
    if value_bps >= threshold_bps:
        return "long"
    if value_bps <= -threshold_bps:
        return "short"
    return "hold"


def replay_rejection_reasons(
    snapshot: Mapping[str, Any],
    *,
    candles: Iterable[Mapping[str, Any]],
) -> list[str]:
    reasons: list[str] = []
    features = snapshot.get("features") if isinstance(snapshot.get("features"), Mapping) else {}
    decision_time = parse_utc(snapshot.get("decision_time"))
    feature_cutoff = parse_utc(snapshot.get("feature_cutoff"))
    available_at = parse_utc(snapshot.get("available_at"))
    if not features:
        reasons.append("FEATURES_EMPTY")
    if any(_future_label_feature_name(name) for name in features):
        reasons.append("FUTURE_LABEL_PRESENT_IN_FEATURES")
    if feature_cutoff is None:
        reasons.append("FEATURE_CUTOFF_MISSING")
    if decision_time is None:
        reasons.append("DECISION_TIME_MISSING")
    if available_at is None:
        reasons.append("AVAILABLE_AT_MISSING")
    if feature_cutoff is not None and decision_time is not None and feature_cutoff > decision_time:
        reasons.append("FEATURE_CUTOFF_AFTER_DECISION_TIME")
    if available_at is not None and decision_time is not None and available_at > decision_time:
        reasons.append("AVAILABLE_AT_AFTER_DECISION_TIME")
    if snapshot.get("candle_closed_confirmed") is not True:
        reasons.append("OPEN_CANDLE_REJECTED")
    if snapshot.get("mtf_snapshot_id") in (None, ""):
        reasons.append("MTF_SNAPSHOT_ID_MISSING")
    if decision_time is not None and not _later_finalized_candles(candles, decision_time):
        reasons.append("NO_LATER_FINALIZED_CANDLES")
    return sorted(set(reasons))


def build_trusted_replay_row(
    snapshot: Mapping[str, Any],
    *,
    candles: Iterable[Mapping[str, Any]],
    round_trip_cost_bps: float = 2.0,
    action_threshold_bps: float = 4.0,
) -> tuple[dict[str, Any] | None, list[str]]:
    reasons = replay_rejection_reasons(snapshot, candles=candles)
    if reasons:
        return None, reasons
    decision_time = parse_utc(snapshot.get("decision_time"))
    feature_cutoff = parse_utc(snapshot.get("feature_cutoff"))
    available_at = parse_utc(snapshot.get("available_at"))
    assert decision_time is not None and feature_cutoff is not None and available_at is not None
    features = snapshot.get("features") if isinstance(snapshot.get("features"), Mapping) else {}
    entry_price = finite_float(
        features.get("close")
        or features.get("last_price")
        or features.get("price_last")
        or features.get("ohlcv_close")
    )
    if entry_price is None or entry_price <= 0.0:
        return None, ["ENTRY_PRICE_MISSING"]

    future_candles = _later_finalized_candles(candles, decision_time)
    returns: dict[str, float] = {}
    missing_horizons: list[str] = []
    for horizon, seconds in HORIZON_SECONDS.items():
        candle = _first_candle_at_or_after(future_candles, decision_time + timedelta(seconds=seconds))
        close_price = _candle_price(candle or {}, "close", "close_price", "c") if candle is not None else None
        if close_price is None or close_price <= 0.0:
            missing_horizons.append(horizon)
            continue
        returns[horizon] = ((close_price - entry_price) / entry_price) * 10_000.0
    if missing_horizons:
        return None, [f"FUTURE_CANDLE_HORIZON_MISSING_{name.upper()}" for name in missing_horizons]

    raw_after_cost = returns["15m"]
    after_cost = raw_after_cost - abs(round_trip_cost_bps) if raw_after_cost > 0 else raw_after_cost + abs(round_trip_cost_bps)
    target_action = _target_action(after_cost, action_threshold_bps)
    highs = [
        _candle_price(candle, "high", "high_price", "h")
        for candle in future_candles
        if (_candle_close_time(candle) or decision_time) <= decision_time + timedelta(hours=4)
    ]
    lows = [
        _candle_price(candle, "low", "low_price", "l")
        for candle in future_candles
        if (_candle_close_time(candle) or decision_time) <= decision_time + timedelta(hours=4)
    ]
    highs = [value for value in highs if value is not None]
    lows = [value for value in lows if value is not None]
    mfe = ((max(highs) - entry_price) / entry_price) * 10_000.0 if highs else max(0.0, after_cost)
    mae = ((min(lows) - entry_price) / entry_price) * 10_000.0 if lows else min(0.0, after_cost)
    directional = _directional_outcome(after_cost)
    trade_outcome = _trade_outcome(abs(after_cost) if target_action in {"long", "short"} else 0.0)
    value_baseline = finite_float(snapshot.get("policy_value") or snapshot.get("value_baseline")) or 0.0
    reward = after_cost / 100.0
    feature_names = sorted(str(name) for name in features.keys())
    missing_mask = snapshot.get("missing_mask") if isinstance(snapshot.get("missing_mask"), Mapping) else {}
    stale_mask = snapshot.get("stale_mask") if isinstance(snapshot.get("stale_mask"), Mapping) else {}
    missing_names = [name for name in feature_names if bool(missing_mask.get(name))]
    stale_names = [name for name in feature_names if bool(stale_mask.get(name))]
    row = {
        "sample_id": f"trusted_replay:{snapshot.get('snapshot_id')}",
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "trainer_feedback_source": "V2_DURABLE_FEATURE_SNAPSHOT_TRUSTED_REPLAY",
        "learning_mode": "outcome_supervised",
        "update_lane": "OUTCOME_SUPERVISED_TRUSTED_REPLAY",
        "prediction_id": snapshot.get("prediction_id") or f"trusted_replay_pred:{snapshot.get('snapshot_id')}",
        "signal_id": snapshot.get("signal_id") or f"trusted_replay_sig:{snapshot.get('snapshot_id')}",
        "decision_id": snapshot.get("decision_id") or f"trusted_replay_decision:{snapshot.get('snapshot_id')}",
        "feature_snapshot_id": snapshot.get("feature_snapshot_id") or snapshot.get("snapshot_id"),
        "entry_feature_snapshot_id": snapshot.get("feature_snapshot_id") or snapshot.get("snapshot_id"),
        "mtf_snapshot_id": snapshot.get("mtf_snapshot_id"),
        "replay_snapshot_id": snapshot.get("replay_snapshot_id") or f"trusted_replay:{snapshot.get('snapshot_id')}",
        "replay_snapshot_key": snapshot.get("replay_snapshot_key") or f"durable_feature_snapshot_archive:{snapshot.get('snapshot_id')}",
        "mtf_snapshot_valid": True,
        "mtf_snapshot_reject_reasons": [],
        "symbol": str(snapshot.get("symbol") or "").upper(),
        "timeframe": str(snapshot.get("timeframe") or ""),
        "feature_cutoff": iso_utc(feature_cutoff),
        "decision_time": iso_utc(decision_time),
        "decision_time_est": iso_utc(decision_time),
        "decision_cutoff_time_est": iso_utc(decision_time),
        "generated_at": iso_utc(decision_time),
        "generated_utc": iso_utc(decision_time),
        "available_at": iso_utc(available_at),
        "source_available_time": iso_utc(available_at),
        "source_event_time_est": iso_utc(feature_cutoff),
        "source_received_time_est": iso_utc(available_at),
        "latency_ms": 0,
        "candle_closed_confirmed": True,
        "candle_open_time": iso_utc(feature_cutoff - timedelta(seconds=timeframe_seconds(str(snapshot.get("timeframe") or "1m")))),
        "candle_close_time": iso_utc(feature_cutoff),
        "feature_freshness_state": "CURRENT",
        "trainer_consumable": True,
        "accepted_for_training": True,
        "valid_for_training": True,
        "row_classification": "TRAINABLE",
        "missing_feature_names": missing_names,
        "missing_feature_count": len(missing_names),
        "stale_feature_names": stale_names,
        "stale_feature_count": len(stale_names),
        "features": dict(features),
        "source_hashes": dict(snapshot.get("source_hashes") or {}),
        "model_version": snapshot.get("model_version") or "trusted_replay_labeler_v1",
        "checkpoint_id": snapshot.get("checkpoint_id") or "trusted_replay_no_prior_checkpoint",
        "selected_action": snapshot.get("selected_action"),
        "target_action": target_action,
        "future_return_5m_bps": returns["5m"],
        "future_return_15m_bps": returns["15m"],
        "future_return_1h_bps": returns["1h"],
        "future_return_4h_bps": returns["4h"],
        "future_return_after_cost_bps": after_cost,
        "directional_outcome": directional,
        "trade_outcome": trade_outcome,
        "maximum_favorable_excursion_bps": mfe,
        "maximum_adverse_excursion_bps": mae,
        "realized_after_cost_reward": reward,
        "value_baseline": value_baseline,
        "advantage": reward - value_baseline,
        "advantage_source": "realized_after_cost_reward_minus_value_baseline",
        "realized_reward_source": "future_return_after_cost_bps_from_finalized_candles",
        "uses_expected_move_as_realized_reward": False,
        "future_labels_not_in_feature_tensor": True,
        "outcome_targets": {
            "realized_net_pnl_bps": after_cost,
            "realized_net_pnl_usd": 0.0,
            "directional_outcome": directional,
            "trade_outcome": trade_outcome,
            "selected_action": snapshot.get("selected_action"),
            "target_action": target_action,
            "action_was_profitable": target_action in {"long", "short"},
            "holding_period": HORIZON_SECONDS["15m"],
            "fees": abs(round_trip_cost_bps),
            "slippage": None,
            "funding": features.get("funding_rate"),
            "MFE": mfe,
            "MAE": mae,
            "exit_reason": "TRUSTED_REPLAY_FUTURE_FINALIZED_CANDLE_HORIZON",
            "realized_after_cost_reward": reward,
            "value_baseline": value_baseline,
            "advantage": reward - value_baseline,
        },
    }
    return row, []
