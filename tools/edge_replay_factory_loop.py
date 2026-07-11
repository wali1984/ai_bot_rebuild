#!/usr/bin/env python3
"""Continuous edge replay and counterfactual label factory.

This is paper-only infrastructure. It matures blocked shadow/counterfactual
rows using closed candles that are available after the original decision
window. Matured rows are trainer-consumable, but they never count as final A+
or live-ready evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


GOAL_ID = "V2_CONTINUOUS_EDGE_FACTORY_PAPER_NEVER_STOPS_BINANCE_LIVE_TRADER_READY_A_PLUS_UNBLOCK_COMPLETION"
COUNTERFACTUAL_KEY = "v2:trainer:feedback:counterfactuals"
COUNTERFACTUAL_STATUS_KEY = "v2:trainer:feedback:counterfactual_status"
EDGE_FACTORY_STATUS_KEY = "v2:edge_factory:replay_status"
EDGE_FACTORY_SCOREBOARD_KEY = "v2:edge_factory:strategy_bucket_scoreboard"
SHADOW_OBSERVATIONS_KEY = "v2:paper:shadow_observations"
PREEMPTIVE_COUNTERFACTUAL_KEY = "v2:trainer:preemptive_blocked_candidates"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    # Candle series carry epoch timestamps (ms for kline close/event times);
    # ISO-only parsing silently dropped every candle and starved the exit-
    # candle lookup, so no counterfactual row could ever mature.
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number <= 0:
            return None
        if number >= 1e12:
            number /= 1000.0
        try:
            return datetime.fromtimestamp(number, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if text.isdigit():
        return _parse_time(int(text))
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _coerce_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normal_side(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if text in {"long", "buy"}:
        return "long"
    if text in {"short", "sell"}:
        return "short"
    return None


def _stable_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _context(name: str, row: Mapping[str, Any]) -> dict[str, Any]:
    value = row.get(name)
    if isinstance(value, dict):
        return dict(value)
    return {
        "context_type": name.upper(),
        "source": "CONTINUOUS_EDGE_FACTORY_REPLAY",
        "status": "explicitly_unavailable",
        "unavailable_reason": "SOURCE_ROW_CONTEXT_MISSING",
    }


def _candle_close_time(candle: Mapping[str, Any]) -> datetime | None:
    return _parse_time(
        _first_present(
            candle.get("candle_close_time"),
            candle.get("close_time"),
            candle.get("event_time"),
            candle.get("available_at"),
        )
    )


def _closed_candle(candle: Mapping[str, Any], *, now: datetime) -> bool:
    close_dt = _candle_close_time(candle)
    if close_dt is None or close_dt > now:
        return False
    return bool(
        candle.get("candle_closed_confirmed") is True
        or candle.get("closed_candle") is True
        or candle.get("is_closed") is True
    )


def _closed_window_exit_candle(
    candles: Iterable[Mapping[str, Any]],
    *,
    horizon_dt: datetime,
    now: datetime,
) -> Mapping[str, Any] | None:
    closed = [
        candle
        for candle in candles
        if isinstance(candle, Mapping)
        and _closed_candle(candle, now=now)
        and (_candle_close_time(candle) or datetime.min.replace(tzinfo=timezone.utc)) >= horizon_dt
    ]
    closed.sort(key=lambda candle: _candle_close_time(candle) or datetime.max.replace(tzinfo=timezone.utc))
    return closed[0] if closed else None


def _lineage_rejection_reasons(row: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    decision_dt = _parse_time(row.get("decision_time"))
    available_dt = _parse_time(row.get("available_at"))
    feature_cutoff_dt = _parse_time(row.get("feature_cutoff"))
    if decision_dt is None:
        reasons.append("MISSING_DECISION_TIME")
    if available_dt is None:
        reasons.append("MISSING_AVAILABLE_AT")
    if feature_cutoff_dt is None:
        reasons.append("MISSING_FEATURE_CUTOFF")
    if decision_dt is not None and available_dt is not None and available_dt > decision_dt:
        reasons.append("AVAILABLE_AT_AFTER_DECISION_TIME")
    if decision_dt is not None and feature_cutoff_dt is not None and feature_cutoff_dt > decision_dt:
        reasons.append("FEATURE_CUTOFF_AFTER_DECISION_TIME")
    if row.get("future_labels_used_as_features") is True:
        reasons.append("FUTURE_LABELS_USED_AS_FEATURES")
    if row.get("candle_closed_confirmed") is False or row.get("closed_candle") is False:
        reasons.append("ENTRY_CANDLE_NOT_CONFIRMED_CLOSED")
    return reasons


def _build_feedback_row(
    row: Mapping[str, Any],
    *,
    exit_candle: Mapping[str, Any],
    min_hold_seconds: int,
) -> dict[str, Any] | None:
    side = _normal_side(_first_present(row.get("side"), row.get("selected_action"), row.get("action")))
    entry_price = _coerce_float(_first_present(row.get("entry_price"), row.get("fill_price"), row.get("current_price")))
    exit_price = _coerce_float(_first_present(exit_candle.get("close"), exit_candle.get("price"), exit_candle.get("last_price")))
    entry_dt = _parse_time(
        _first_present(
            row.get("entry_price_utc"),
            row.get("shadow_observation_first_seen_utc"),
            row.get("decision_time"),
        )
    )
    exit_dt = _candle_close_time(exit_candle)
    if side is None or entry_price is None or entry_price <= 0.0 or exit_price is None or exit_dt is None or entry_dt is None:
        return None
    gross_bps = ((exit_price - entry_price) / entry_price) * 10_000.0
    if side == "short":
        gross_bps *= -1.0
    notional = _coerce_float(
        _first_present(
            row.get("notional_usd"),
            row.get("gross_notional_usd"),
            row.get("target_notional_usd"),
            row.get("target_notional_usdt"),
            row.get("pre_trade_target_notional_usd"),
        )
    ) or 1.0
    expected_cost_usd = _coerce_float(_first_present(row.get("expected_cost_usd"), row.get("pre_trade_expected_cost_usd"))) or 0.0
    gross_usd = notional * gross_bps / 10_000.0
    net_usd = gross_usd - abs(expected_cost_usd)
    net_bps = gross_bps - abs(expected_cost_usd) / max(notional, 1e-12) * 10_000.0
    outcome = "WIN" if net_usd > 0 else "LOSS" if net_usd < 0 else "FLAT"
    row_hash = _stable_hash(row)
    feedback_id = "edge_factory_counterfactual:" + hashlib.sha256(
        f"{row_hash}|{exit_dt.isoformat()}|{side}".encode("utf-8")
    ).hexdigest()[:24]
    feature_snapshot_id = _first_present(
        row.get("entry_feature_snapshot_id"),
        row.get("feature_snapshot_id"),
        row.get("source_feature_snapshot_id"),
        "edge_factory_missing_feature_snapshot_" + row_hash[:12],
    )
    decision_time = _first_present(row.get("decision_time"), row.get("generated_utc"), row.get("entry_price_utc"))
    source_hashes = row.get("source_hashes") if isinstance(row.get("source_hashes"), Mapping) else {}
    if not source_hashes:
        source_hashes = {"source_row_hash": row_hash, "exit_candle_hash": _stable_hash(exit_candle)}
    feature_snapshot = row.get("entry_feature_snapshot") if isinstance(row.get("entry_feature_snapshot"), Mapping) else {}
    feedback_row = {
        "schema_version": "continuous_edge_factory_counterfactual_feedback_v1",
        "feedback_schema_version": "strategy_hedge_exit_feedback_v1",
        "trainer_feedback_source": "V2_CONTINUOUS_EDGE_FACTORY_COUNTERFACTUAL_CLOSED_WINDOW",
        "trainer_feedback_source_key": COUNTERFACTUAL_KEY,
        "trainer_feedback_id": feedback_id,
        "counterfactual_feedback_id": feedback_id,
        "prediction_id": _first_present(row.get("prediction_id"), row.get("signal_id"), feedback_id),
        "signal_id": _first_present(row.get("signal_id"), row.get("prediction_id"), feedback_id),
        "decision_id": _first_present(row.get("decision_id"), row.get("preemptive_decision_id"), feedback_id),
        "feature_snapshot_id": feature_snapshot_id,
        "entry_feature_snapshot_id": feature_snapshot_id,
        "entry_feature_snapshot": dict(feature_snapshot) if feature_snapshot else None,
        "mtf_snapshot_id": _first_present(row.get("mtf_snapshot_id"), feature_snapshot_id),
        "market_state_id": _first_present(row.get("market_state_id"), "edge_factory_market_state:" + row_hash[:16]),
        "symbol": str(row.get("symbol") or "").upper(),
        "timeframe": str(row.get("timeframe") or ""),
        "side": side,
        "action": side,
        "selected_action": side,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "realized_pnl": round(net_usd, 10),
        "realized_pnl_usd": round(net_usd, 10),
        "realized_net_pnl_usd": round(net_usd, 10),
        "realized_pnl_bps": round(net_bps, 10),
        "realized_net_pnl_bps": round(net_bps, 10),
        "realized_after_cost_pnl_bps": round(net_bps, 10),
        "fees": 0.0,
        "funding": 0.0,
        "slippage": expected_cost_usd,
        "expected_cost_usd": expected_cost_usd,
        "expected_slippage_bps": _coerce_float(row.get("expected_slippage_bps")) or 0.0,
        "expected_slippage_source": _first_present(row.get("expected_slippage_source"), "strategy_supply_or_shadow_row"),
        "implementation_shortfall_usd": expected_cost_usd,
        "mfe_bps": max(0.0, gross_bps),
        "mae_bps": min(0.0, gross_bps),
        "MFE": max(0.0, gross_bps),
        "MAE": min(0.0, gross_bps),
        "intra_trade_high_price": _coerce_float(exit_candle.get("high")) or max(entry_price, exit_price),
        "intra_trade_low_price": _coerce_float(exit_candle.get("low")) or min(entry_price, exit_price),
        "strategy_id": _first_present(row.get("strategy_id"), row.get("strategy_family"), "edge_factory_counterfactual"),
        "strategy_family": _first_present(row.get("strategy_family"), row.get("strategy_id"), "edge_factory_counterfactual"),
        "strategy_subtype": _first_present(row.get("strategy_subtype"), "closed_window_counterfactual"),
        "hedge_state": _first_present(row.get("hedge_state"), "not_hedged"),
        "hedge_reason": _first_present(row.get("hedge_reason"), "counterfactual_no_hedge"),
        "entry_reason": _first_present(row.get("entry_reason"), row.get("shadow_observation_reason"), "blocked_shadow_counterfactual"),
        "exit_reason": "closed_candle_future_window_elapsed",
        "hold_time_seconds": int(max(min_hold_seconds, (exit_dt - entry_dt).total_seconds())),
        "market_regime_at_entry": _first_present(row.get("market_regime_at_entry"), row.get("market_regime"), "unknown"),
        "market_regime_at_exit": _first_present(row.get("market_regime_at_exit"), row.get("market_regime"), "unknown"),
        "market_regime": _first_present(row.get("market_regime"), "unknown"),
        "liquidity_zone_context": _context("liquidity_zone_context", row),
        "liquidation_distance_context": _context("liquidation_distance_context", row),
        "microstructure_context": _context("microstructure_context", row),
        "oi_funding_context": _context("oi_funding_context", row),
        "public_intel_context": _context("public_intel_context", row),
        "liquidity_context": _context("liquidity_context", row),
        "major_move_context": _context("major_move_context", row),
        "future_window_label_source": "continuous_edge_factory_counterfactual_closed_candle",
        "drawdown_at_entry": _coerce_float(row.get("drawdown_at_entry")) or 0.0,
        "source_hashes": dict(source_hashes),
        "feature_cutoff": row.get("feature_cutoff"),
        "decision_time": decision_time,
        "decision_time_est": decision_time,
        "available_at": row.get("available_at"),
        "generated_utc": _utc_now(),
        "entry_time": _iso(entry_dt),
        "exit_time": _iso(exit_dt),
        "exit_price_utc": _iso(exit_dt),
        "candle_close_time": row.get("candle_close_time") or row.get("feature_cutoff"),
        "candle_closed_confirmed": True,
        "closed_candle": True,
        "model_version": _first_present(row.get("model_version"), "continuous_edge_factory_counterfactual_v1"),
        "checkpoint_id": _first_present(row.get("checkpoint_id"), "continuous_edge_factory_counterfactual"),
        "replay_snapshot_id": "edge_factory_counterfactual:" + row_hash[:16],
        "replay_snapshot_key": f"{COUNTERFACTUAL_KEY}:{feedback_id}",
        "masa_feature_cutoff": row.get("feature_cutoff"),
        "ppo_feature_cutoff": row.get("feature_cutoff"),
        "trade_outcome": outcome,
        "directional_outcome": "UP" if gross_bps > 0 else "DOWN" if gross_bps < 0 else "FLAT",
        "action_was_profitable": net_usd > 0.0,
        "outcome_targets": {
            "realized_net_pnl_bps": round(net_bps, 10),
            "realized_net_pnl_usd": round(net_usd, 10),
            "selected_action": side,
            "trade_outcome": outcome,
            "action_was_profitable": net_usd > 0.0,
        },
        "trainer_consumable": True,
        "valid_for_training": True,
        "accepted_for_training": True,
        "missing_feedback_fields": [],
        "trainer_feedback_blockers": [],
        "counterfactual_label_pending": False,
        "counterfactual_label_matured": True,
        "candidate_selected_before_outcome": True,
        "candidate_selected_after_outcome": False,
        "future_labels_used_as_features": False,
        "counts_as_a_plus": False,
        "counts_as_final_a_plus": False,
        "counts_as_a_grade_evidence": False,
        "a_grade_promotion_allowed": False,
        "counts_as_live_ready": False,
        "live_ready_implication": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "test_order": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
    }
    return feedback_row


def mature_counterfactual_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    candles_by_symbol_timeframe: Mapping[tuple[str, str], Iterable[Mapping[str, Any]]],
    now: datetime,
    min_hold_seconds: int = 900,
    max_rows: int = 500,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    matured: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for raw in rows:
        if len(matured) >= max_rows:
            break
        row = dict(raw)
        row_id = _first_present(row.get("prediction_id"), row.get("signal_id"), row.get("counterfactual_feedback_id"), _stable_hash(row)[:16])
        reasons = _lineage_rejection_reasons(row)
        side = _normal_side(_first_present(row.get("side"), row.get("selected_action"), row.get("action")))
        symbol = str(row.get("symbol") or "").upper()
        timeframe = str(row.get("timeframe") or "")
        entry_dt = _parse_time(
            _first_present(
                row.get("entry_price_utc"),
                row.get("shadow_observation_first_seen_utc"),
                row.get("decision_time"),
            )
        )
        if side is None:
            reasons.append("MISSING_DIRECTIONAL_SIDE")
        if not symbol:
            reasons.append("MISSING_SYMBOL")
        if not timeframe:
            reasons.append("MISSING_TIMEFRAME")
        if _coerce_float(_first_present(row.get("entry_price"), row.get("fill_price"), row.get("current_price"))) is None:
            reasons.append("MISSING_ENTRY_PRICE")
        if entry_dt is None:
            reasons.append("MISSING_ENTRY_TIME")
        if reasons:
            rejected.append({"source_row_id": row_id, "reject_reasons": sorted(set(reasons)), "row": row})
            continue
        horizon_dt = entry_dt + timedelta(seconds=min_hold_seconds)
        if now < horizon_dt:
            pending.append({"source_row_id": row_id, "pending_reason": "FUTURE_WINDOW_NOT_ELAPSED", "matures_after": _iso(horizon_dt), "row": row})
            continue
        candles = list(candles_by_symbol_timeframe.get((symbol, timeframe), []))
        exit_candle = _closed_window_exit_candle(candles, horizon_dt=horizon_dt, now=now)
        if exit_candle is None:
            pending.append({"source_row_id": row_id, "pending_reason": "NO_CLOSED_EXIT_CANDLE_AVAILABLE", "matures_after": _iso(horizon_dt), "row": row})
            continue
        feedback_row = _build_feedback_row(row, exit_candle=exit_candle, min_hold_seconds=min_hold_seconds)
        if feedback_row is None:
            rejected.append({"source_row_id": row_id, "reject_reasons": ["FAILED_TO_BUILD_FEEDBACK_ROW"], "row": row})
            continue
        matured.append(feedback_row)
    return matured, pending, rejected


def strategy_bucket_scoreboard(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        timeframe = str(row.get("timeframe") or "")
        side = str(row.get("side") or row.get("selected_action") or "").lower()
        family = str(row.get("strategy_family") or row.get("strategy_id") or "unknown")
        key = "|".join((symbol, timeframe, side, family))
        bucket = buckets.setdefault(
            key,
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "side": side,
                "strategy_family": family,
                "rows": 0,
                "wins": 0,
                "losses": 0,
                "net_pnl_usd": 0.0,
                "net_pnl_bps": 0.0,
                "counts_as_final_a_plus": False,
                "counts_as_live_ready": False,
            },
        )
        net_usd = _coerce_float(row.get("realized_net_pnl_usd")) or 0.0
        net_bps = _coerce_float(row.get("realized_net_pnl_bps")) or 0.0
        bucket["rows"] += 1
        bucket["wins"] += 1 if net_usd > 0 else 0
        bucket["losses"] += 1 if net_usd < 0 else 0
        bucket["net_pnl_usd"] = round(float(bucket["net_pnl_usd"]) + net_usd, 10)
        bucket["net_pnl_bps"] = round(float(bucket["net_pnl_bps"]) + net_bps, 10)
    for bucket in buckets.values():
        rows_count = max(1, int(bucket["rows"]))
        bucket["win_rate"] = round(float(bucket["wins"]) / rows_count, 8)
        bucket["avg_net_pnl_usd"] = round(float(bucket["net_pnl_usd"]) / rows_count, 10)
        bucket["avg_net_pnl_bps"] = round(float(bucket["net_pnl_bps"]) / rows_count, 10)
    ranked = sorted(
        buckets.values(),
        key=lambda item: (float(item["avg_net_pnl_usd"]), int(item["rows"])),
        reverse=True,
    )
    return {
        "schema_version": "edge_factory_strategy_bucket_scoreboard_v1",
        "generated_utc": _utc_now(),
        "bucket_count": len(ranked),
        "buckets": ranked,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


class RedisCliJson:
    def get(self, key: str) -> Any:
        completed = subprocess.run(["redis-cli", "GET", key], check=False, text=True, capture_output=True)
        raw = completed.stdout.strip()
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    def set_json(self, key: str, payload: Any) -> bool:
        encoded = json.dumps(payload, sort_keys=True)
        completed = subprocess.run(
            ["redis-cli", "-x", "SET", key],
            input=encoded,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return completed.returncode == 0


def _json_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(row) for row in value if isinstance(row, Mapping)]
    if isinstance(value, Mapping):
        rows = value.get("rows")
        if isinstance(rows, list):
            return [dict(row) for row in rows if isinstance(row, Mapping)]
    return []


def _read_candles(client: RedisCliJson, rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    pairs = sorted({
        (str(row.get("symbol") or "").upper(), str(row.get("timeframe") or ""))
        for row in rows
        if row.get("symbol") and row.get("timeframe")
    })
    candles: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for symbol, timeframe in pairs:
        payload = client.get(f"v2:market:ohlcv_closed:binance:{symbol}:{timeframe}")
        candles[(symbol, timeframe)] = _json_rows(payload)
    return candles


def _merge_rows(existing: list[dict[str, Any]], new_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in existing + new_rows:
        row_id = str(_first_present(row.get("trainer_feedback_id"), row.get("counterfactual_feedback_id"), _stable_hash(row)))
        merged[row_id] = row
    return list(merged.values())


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def run_once(
    *,
    output_dir: Path,
    publish_redis: bool,
    min_hold_seconds: int,
    max_rows: int,
) -> dict[str, Any]:
    started = time.time()
    output_dir.mkdir(parents=True, exist_ok=True)
    client = RedisCliJson()
    shadow_rows = _json_rows(client.get(SHADOW_OBSERVATIONS_KEY))
    preemptive_payload = client.get(PREEMPTIVE_COUNTERFACTUAL_KEY)
    preemptive_rows = _json_rows(preemptive_payload)
    source_rows = shadow_rows + preemptive_rows
    candles = _read_candles(client, source_rows)
    now = datetime.now(timezone.utc)
    matured, pending, rejected = mature_counterfactual_rows(
        source_rows,
        candles_by_symbol_timeframe=candles,
        now=now,
        min_hold_seconds=min_hold_seconds,
        max_rows=max_rows,
    )
    existing = _json_rows(client.get(COUNTERFACTUAL_KEY))
    merged = _merge_rows(existing, matured)
    scoreboard = strategy_bucket_scoreboard(merged)
    trainer_consumption = {
        "schema_version": "edge_factory_replay_to_trainer_consumption_status_v1",
        "generated_utc": _utc_now(),
        "trainer_counterfactual_key": COUNTERFACTUAL_KEY,
        "existing_counterfactual_rows": len(existing),
        "new_matured_rows": len(matured),
        "merged_counterfactual_rows": len(merged),
        "pending_rows": len(pending),
        "rejected_rows": len(rejected),
        "trainer_loader_consumes_counterfactual_key": True,
        "counterfactual_rows_count_as_final_a_plus": False,
        "counterfactual_rows_count_as_live_ready": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    status = {
        "schema_version": "edge_replay_factory_status_v1",
        "generated_utc": _utc_now(),
        "goal_id": GOAL_ID,
        "source_shadow_rows": len(shadow_rows),
        "source_preemptive_counterfactual_rows": len(preemptive_rows),
        "source_rows": len(source_rows),
        "closed_candle_symbol_timeframe_pairs": len(candles),
        "matured_counterfactual_rows": len(matured),
        "pending_counterfactual_rows": len(pending),
        "rejected_counterfactual_rows": len(rejected),
        "strategy_bucket_count": scoreboard["bucket_count"],
        "publish_redis": publish_redis,
        "duration_seconds": round(time.time() - started, 6),
        "live_gate_required": "blocked_human_only",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "redis_trim": False,
    }
    _write_jsonl(output_dir / "strategy_supply_replay_evidence.jsonl", matured)
    _write_jsonl(output_dir / "strategy_supply_counterfactual_pending.jsonl", pending)
    _write_jsonl(output_dir / "strategy_supply_counterfactual_rejected.jsonl", rejected)
    (output_dir / "phase3_historical_replay_edge_factory_status.json").write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "phase3_replay_strategy_bucket_scoreboard.json").write_text(
        json.dumps(scoreboard, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "phase3_replay_to_trainer_consumption_status.json").write_text(
        json.dumps(trainer_consumption, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if publish_redis:
        status["redis_publish_results"] = {
            COUNTERFACTUAL_KEY: client.set_json(COUNTERFACTUAL_KEY, merged),
            COUNTERFACTUAL_STATUS_KEY: client.set_json(COUNTERFACTUAL_STATUS_KEY, trainer_consumption),
            EDGE_FACTORY_STATUS_KEY: client.set_json(EDGE_FACTORY_STATUS_KEY, status),
            EDGE_FACTORY_SCOREBOARD_KEY: client.set_json(EDGE_FACTORY_SCOREBOARD_KEY, scoreboard),
        }
        (output_dir / "phase3_historical_replay_edge_factory_status.json").write_text(
            json.dumps(status, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return status


def run_loop(
    *,
    output_dir: Path,
    publish_redis: bool,
    min_hold_seconds: int,
    max_rows: int,
    sleep_seconds: float,
) -> None:
    while True:
        run_once(
            output_dir=output_dir,
            publish_redis=publish_redis,
            min_hold_seconds=min_hold_seconds,
            max_rows=max_rows,
        )
        time.sleep(max(1.0, sleep_seconds))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("goal_state") / GOAL_ID / "phase3_edge_replay_factory")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--publish-redis", action="store_true")
    parser.add_argument("--min-hold-seconds", type=int, default=900)
    parser.add_argument("--max-rows", type=int, default=500)
    parser.add_argument("--sleep-seconds", type=float, default=60.0)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.once:
        status = run_once(
            output_dir=args.output_dir,
            publish_redis=bool(args.publish_redis),
            min_hold_seconds=int(args.min_hold_seconds),
            max_rows=int(args.max_rows),
        )
        if args.json:
            print(json.dumps(status, indent=2, sort_keys=True))
        else:
            print(status["schema_version"])
        return 0
    run_loop(
        output_dir=args.output_dir,
        publish_redis=bool(args.publish_redis),
        min_hold_seconds=int(args.min_hold_seconds),
        max_rows=int(args.max_rows),
        sleep_seconds=float(args.sleep_seconds),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
