#!/usr/bin/env python3
"""Continuous edge replay and counterfactual label factory.

This is paper-only infrastructure. It matures blocked shadow/counterfactual
rows using closed candles that are available after the original decision
window. Matured rows are trainer-consumable, but they never count as final A+
or live-ready evidence.
"""
from __future__ import annotations

import argparse
import codecs
import fcntl
import hashlib
import heapq
import itertools
import json
import math
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from v2.backend.app.services.durable_paper_evidence_archive import (
    ARCHIVE_SCHEMA_VERSION,
    COUNTERFACTUAL_ARCHIVE_STREAM_ID,
    COUNTERFACTUAL_REPLACEMENT_INTENT_KIND,
    COUNTERFACTUAL_REPLACEMENT_INTENT_SCHEMA,
    COUNTERFACTUAL_REPLACEMENT_OUTCOME_KIND,
    COUNTERFACTUAL_REPLACEMENT_OUTCOME_SCHEMA,
    COUNTERFACTUAL_VERIFIED_LATEST_ROWS_MAX_BYTES,
    REDIS_SOURCE_COMPARE_ENDPOINT_CONTRACT,
    ArchiveCandidate,
    DurablePaperEvidenceArchive,
    canonical_json,
    counterfactual_archive_identity,
    counterfactual_archive_sort_key,
    ordered_rows_sha256,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.config import (
    DEFAULT_MAX_TRAINING_ROWS_PER_CYCLE,
)


GOAL_ID = "V2_CONTINUOUS_EDGE_FACTORY_PAPER_NEVER_STOPS_BINANCE_LIVE_TRADER_READY_A_PLUS_UNBLOCK_COMPLETION"
COUNTERFACTUAL_KEY = "v2:trainer:feedback:counterfactuals"
COUNTERFACTUAL_STATUS_KEY = "v2:trainer:feedback:counterfactual_status"
EDGE_FACTORY_STATUS_KEY = "v2:edge_factory:replay_status"
EDGE_FACTORY_SCOREBOARD_KEY = "v2:edge_factory:strategy_bucket_scoreboard"
SHADOW_OBSERVATIONS_KEY = "v2:paper:shadow_observations"
PREEMPTIVE_COUNTERFACTUAL_KEY = "v2:trainer:preemptive_blocked_candidates"
DEFAULT_COUNTERFACTUAL_ARCHIVE_PATH = Path(
    ".local_data/v2_edge_replay_factory/counterfactual_evidence.sqlite3"
)
TRAINER_HOT_MAX_ROWS_ENV = "V2_EDGE_FACTORY_TRAINER_HOT_MAX_ROWS"
COUNTERFACTUAL_ARCHIVE_PATH_ENV = "V2_EDGE_FACTORY_COUNTERFACTUAL_ARCHIVE_PATH"
COUNTERFACTUAL_STREAM_CHUNK_BYTES = 64 * 1024
COUNTERFACTUAL_MAX_JSON_ROW_BYTES = 16 * 1024 * 1024
COUNTERFACTUAL_ARCHIVE_BATCH_MAX_BYTES = 32 * 1024 * 1024


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
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


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


def _iter_top_level_json_array_chunks(
    chunks: Iterable[str],
    *,
    max_buffer_chars: int = COUNTERFACTUAL_MAX_JSON_ROW_BYTES,
) -> Iterable[dict[str, Any]]:
    """Incrementally decode a top-level JSON array with bounded row memory."""

    def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in pairs:
            if key in output:
                raise ValueError(f"counterfactual_json_duplicate_object_key:{key}")
            output[key] = value
        return output

    def reject_nonfinite_constant(value: str) -> Any:
        raise ValueError(f"counterfactual_json_nonfinite_constant:{value}")

    decoder = json.JSONDecoder(
        object_pairs_hook=strict_object,
        parse_constant=reject_nonfinite_constant,
    )
    buffer = ""
    position = 0
    started = False
    completed = False
    expect_value = True
    items_seen = 0
    for chunk in itertools.chain(chunks, (None,)):
        eof = chunk is None
        if chunk:
            buffer += chunk
        while True:
            while position < len(buffer) and buffer[position].isspace():
                position += 1
            if completed:
                if position < len(buffer):
                    raise ValueError("counterfactual_json_trailing_data")
                break
            if not started:
                if position >= len(buffer):
                    break
                if buffer[position] != "[":
                    raise ValueError("counterfactual_json_top_level_array_required")
                position += 1
                started = True
                expect_value = True
                continue
            while position < len(buffer) and buffer[position].isspace():
                position += 1
            if position >= len(buffer):
                break
            if expect_value:
                if buffer[position] == "]":
                    if items_seen:
                        raise ValueError("counterfactual_json_trailing_comma")
                    completed = True
                    position += 1
                    continue
                value_start = position
                try:
                    value, end = decoder.raw_decode(buffer, position)
                except json.JSONDecodeError:
                    break
                if not isinstance(value, Mapping):
                    raise ValueError("counterfactual_json_row_not_object")
                if len(buffer[value_start:end].encode("utf-8")) > max(
                    1, int(max_buffer_chars)
                ):
                    raise ValueError(
                        "counterfactual_json_row_exceeds_memory_safety_bound"
                    )
                position = end
                expect_value = False
                items_seen += 1
                yield dict(value)
                continue
            token = buffer[position]
            if token == ",":
                position += 1
                expect_value = True
                continue
            if token == "]":
                completed = True
                position += 1
                continue
            raise ValueError("counterfactual_json_array_separator_invalid")

        if position:
            buffer = buffer[position:]
            position = 0
        if len(buffer.encode("utf-8")) > max(1, int(max_buffer_chars)):
            raise ValueError("counterfactual_json_row_exceeds_memory_safety_bound")
        if eof:
            if not started:
                # A missing Redis key is an empty source, not a fabricated row.
                if not buffer.strip():
                    return
                raise ValueError("counterfactual_json_top_level_array_required")
            if not completed:
                raise ValueError("counterfactual_json_array_truncated_or_invalid")
            if buffer.strip():
                raise ValueError("counterfactual_json_trailing_data")
            return


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
    """Read only an explicit candle-close clock.

    ``event_time`` and ``available_at`` are different clocks and therefore
    must never be substituted for the close boundary.
    """

    return _parse_time(
        _first_present(
            candle.get("candle_close_time"),
            candle.get("close_time"),
        )
    )


def _candle_available_time(candle: Mapping[str, Any]) -> datetime | None:
    return _parse_time(candle.get("available_at"))


def _closed_candle(candle: Mapping[str, Any], *, now: datetime) -> bool:
    close_dt = _candle_close_time(candle)
    available_dt = _candle_available_time(candle)
    if (
        close_dt is None
        or available_dt is None
        or close_dt >= now
        or available_dt > now
        or available_dt < close_dt
    ):
        return False
    finality_values = [
        value
        for value in (
            candle.get("candle_closed_confirmed"),
            candle.get("closed_candle"),
            candle.get("is_closed"),
        )
        if isinstance(value, bool)
    ]
    return bool(finality_values and all(finality_values) and any(finality_values))


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


def _positive_counterfactual_notional(row: Mapping[str, Any]) -> tuple[float | None, str | None]:
    """Return only a pre-outcome, explicitly positive counterfactual notional."""

    for field in (
        "notional_usd",
        "gross_notional_usd",
        "target_notional_usd",
        "target_notional_usdt",
        "pre_trade_target_notional_usd",
        "recommended_notional_usd",
        "preemptive_simulated_target_notional_usd",
    ):
        value = _coerce_float(row.get(field))
        if value is not None and value > 0.0:
            return value, field
    return None, None


def _counterfactual_cost_contract(
    row: Mapping[str, Any],
    *,
    decision_dt: datetime | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Resolve an exact, decision-time production-cost decomposition in bps."""

    reasons: list[str] = []
    if row.get("production_grade_cost_evidence") is not True:
        reasons.append("PRODUCTION_GRADE_COST_EVIDENCE_UNPROVEN")
    if row.get("runtime_cost_capture_status") != "PRODUCTION_GRADE_COST_CAPTURE":
        reasons.append("RUNTIME_COST_CAPTURE_NOT_PRODUCTION_GRADE")
    if row.get("fallback_cost_flag") is not False:
        reasons.append("FALLBACK_COST_EVIDENCE_NOT_EXPLICITLY_FALSE")
    if row.get("cost_source_allowed") is not True:
        reasons.append("COST_SOURCE_NOT_EXPLICITLY_ALLOWED")
    if row.get("market_cost_evidence_status") != "COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE":
        reasons.append("MARKET_COST_EVIDENCE_INCOMPLETE")
    for rejection_field in (
        "market_cost_evidence_pit_reject_reasons",
        "runtime_cost_capture_temporal_reject_reasons",
        "runtime_cost_capture_source_reject_reasons",
    ):
        value = row.get(rejection_field)
        if not isinstance(value, list) or value:
            reasons.append(f"{rejection_field.upper()}_NOT_EXPLICITLY_EMPTY")

    capture_dt = _parse_time(row.get("runtime_cost_capture_decision_time"))
    if capture_dt is None:
        reasons.append("RUNTIME_COST_CAPTURE_DECISION_TIME_MISSING")
    elif decision_dt is not None and capture_dt > decision_dt:
        reasons.append("RUNTIME_COST_CAPTURE_AFTER_DECISION")

    source_fields = row.get("cost_evidence_source_fields")
    if not isinstance(source_fields, Mapping):
        reasons.append("COST_EVIDENCE_SOURCE_FIELDS_MISSING")
    else:
        for source_name in ("depth_impact", "fee", "funding", "latency", "partial_fill"):
            if source_fields.get(source_name) in (None, ""):
                reasons.append(f"COST_EVIDENCE_SOURCE_{source_name.upper()}_MISSING")
    if row.get("expected_slippage_source") in (None, ""):
        reasons.append("EXPECTED_SLIPPAGE_SOURCE_MISSING")

    raw_components = {
        "fees_bps": _coerce_float(
            _first_present(row.get("fee_bps_for_allocator"), row.get("fee_bps"))
        ),
        "expected_slippage_bps": _coerce_float(row.get("expected_slippage_bps")),
        "funding_bps": _coerce_float(
            _first_present(
                row.get("expected_funding_bps_for_allocator"),
                row.get("expected_funding_bps"),
            )
        ),
        "depth_impact_bps": _coerce_float(
            _first_present(
                row.get("depth_derived_price_impact_bps"),
                row.get("depth_price_impact_bps"),
            )
        ),
        "latency_reserve_bps": _coerce_float(row.get("latency_reserve_bps")),
        "partial_fill_adjustment_bps": _coerce_float(
            row.get("partial_fill_adjustment_bps")
        ),
    }
    for component_name, value in raw_components.items():
        if value is None:
            reasons.append(f"EXPLICIT_{component_name.upper()}_MISSING_OR_NONFINITE")
        elif component_name != "funding_bps" and value < 0.0:
            reasons.append(f"EXPLICIT_{component_name.upper()}_NEGATIVE")
    total_bps = _coerce_float(row.get("estimated_production_cost_bps"))
    if total_bps is None or total_bps < 0.0:
        reasons.append("ESTIMATED_PRODUCTION_COST_BPS_MISSING_NONFINITE_OR_NEGATIVE")

    if reasons:
        return None, sorted(set(reasons))
    components = {key: float(value) for key, value in raw_components.items() if value is not None}
    component_sum = sum(components.values())
    assert total_bps is not None
    if not math.isclose(total_bps, component_sum, rel_tol=1e-9, abs_tol=1e-9):
        return None, ["ESTIMATED_PRODUCTION_COST_COMPONENT_SUM_MISMATCH"]
    execution_friction_bps = (
        components["expected_slippage_bps"]
        + components["depth_impact_bps"]
        + components["latency_reserve_bps"]
        + components["partial_fill_adjustment_bps"]
    )
    return {
        **components,
        "execution_friction_bps": execution_friction_bps,
        "total_cost_bps": float(total_bps),
        "cost_unit": "bps",
        "cost_capture_decision_time": _iso(capture_dt),
        "cost_source_fields": dict(source_fields),
        "expected_slippage_source": row.get("expected_slippage_source"),
    }, []


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
    if row.get("future_labels_used_as_features") is not False:
        reasons.append("FUTURE_LABEL_FEATURE_EXCLUSION_UNPROVEN")
    if row.get("candidate_selected_before_outcome") is not True:
        reasons.append("CANDIDATE_PRE_OUTCOME_SELECTION_UNPROVEN")
    if row.get("candidate_selected_after_outcome") is not False:
        reasons.append("CANDIDATE_POST_OUTCOME_SELECTION_NOT_EXPLICITLY_FALSE")

    entry_finality_values = [
        value
        for value in (
            row.get("candle_closed_confirmed"),
            row.get("closed_candle"),
            row.get("entry_feature_candle_closed_confirmed"),
            row.get("strategy_feature_snapshot_candle_closed_confirmed"),
        )
        if isinstance(value, bool)
    ]
    if not entry_finality_values or not all(entry_finality_values):
        reasons.append("ENTRY_CANDLE_FINALITY_UNPROVEN_OR_CONFLICTING")
    entry_close_dt = _parse_time(row.get("candle_close_time"))
    if entry_close_dt is None:
        reasons.append("ENTRY_CANDLE_CLOSE_TIME_MISSING")
    elif decision_dt is not None and entry_close_dt >= decision_dt:
        reasons.append("ENTRY_CANDLE_NOT_CLOSED_STRICTLY_BEFORE_DECISION")

    for cutoff_name in ("masa_feature_cutoff", "ppo_feature_cutoff"):
        cutoff_value = row.get(cutoff_name)
        if cutoff_value in (None, ""):
            reasons.append(f"{cutoff_name.upper()}_MISSING")
            continue
        cutoff_dt = _parse_time(cutoff_value)
        if cutoff_dt is None:
            reasons.append(f"{cutoff_name.upper()}_INVALID")
        elif decision_dt is not None and cutoff_dt > decision_dt:
            reasons.append(f"{cutoff_name.upper()}_AFTER_DECISION_TIME")

    notional, _notional_source = _positive_counterfactual_notional(row)
    if notional is None:
        reasons.append("POSITIVE_PRE_OUTCOME_COUNTERFACTUAL_NOTIONAL_MISSING")
    _costs, cost_reasons = _counterfactual_cost_contract(
        row,
        decision_dt=decision_dt,
    )
    reasons.extend(cost_reasons)
    return reasons


def _build_feedback_row(
    row: Mapping[str, Any],
    *,
    exit_candle: Mapping[str, Any],
    min_hold_seconds: int,
    label_generated_at: datetime,
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
    exit_available_dt = _candle_available_time(exit_candle)
    decision_dt = _parse_time(row.get("decision_time"))
    entry_close_dt = _parse_time(row.get("candle_close_time"))
    notional, notional_source = _positive_counterfactual_notional(row)
    costs, cost_reasons = _counterfactual_cost_contract(
        row,
        decision_dt=decision_dt,
    )
    if (
        side is None
        or entry_price is None
        or entry_price <= 0.0
        or exit_price is None
        or exit_dt is None
        or exit_available_dt is None
        or entry_dt is None
        or decision_dt is None
        or entry_close_dt is None
        or notional is None
        or costs is None
        or cost_reasons
        or exit_dt >= label_generated_at
        or exit_available_dt > label_generated_at
        or exit_available_dt < exit_dt
        or exit_dt <= decision_dt
    ):
        return None
    gross_bps = ((exit_price - entry_price) / entry_price) * 10_000.0
    if side == "short":
        gross_bps *= -1.0
    total_cost_bps = float(costs["total_cost_bps"])
    expected_cost_usd = notional * total_cost_bps / 10_000.0
    gross_usd = notional * gross_bps / 10_000.0
    net_bps = gross_bps - total_cost_bps
    net_usd = notional * net_bps / 10_000.0
    outcome = "WIN" if net_bps > 0 else "LOSS" if net_bps < 0 else "BREAKEVEN"
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
    decision_time = _iso(decision_dt)
    source_hashes = row.get("source_hashes") if isinstance(row.get("source_hashes"), Mapping) else {}
    source_hashes = dict(source_hashes)
    source_hashes.setdefault("source_row_hash", row_hash)
    source_hashes["exit_candle_hash"] = _stable_hash(exit_candle)
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
        "counterfactual_notional_usd": notional,
        "counterfactual_notional_source": notional_source,
        "counterfactual_notional_selected_before_outcome": True,
        "gross_pnl_bps": round(gross_bps, 10),
        "gross_pnl_usd": round(gross_usd, 10),
        "realized_pnl": round(net_usd, 10),
        "realized_pnl_usd": round(net_usd, 10),
        "realized_net_pnl_usd": round(net_usd, 10),
        "realized_pnl_bps": round(net_bps, 10),
        "realized_net_pnl_bps": round(net_bps, 10),
        "realized_after_cost_pnl_bps": round(net_bps, 10),
        "fees": round(float(costs["fees_bps"]), 10),
        "funding": round(float(costs["funding_bps"]), 10),
        "slippage": round(float(costs["execution_friction_bps"]), 10),
        "explicit_cost_unit": "bps",
        "explicit_total_cost_bps": round(total_cost_bps, 10),
        "explicit_cost_components": dict(costs),
        "expected_cost_usd": round(expected_cost_usd, 10),
        "expected_slippage_bps": round(float(costs["expected_slippage_bps"]), 10),
        "expected_slippage_source": costs["expected_slippage_source"],
        "implementation_shortfall_usd": round(
            notional * float(costs["execution_friction_bps"]) / 10_000.0,
            10,
        ),
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
        "source_hashes": source_hashes,
        "feature_cutoff": row.get("feature_cutoff"),
        "decision_time": decision_time,
        "decision_time_est": decision_time,
        "available_at": row.get("available_at"),
        "generated_utc": _iso(label_generated_at),
        "entry_time": _iso(entry_dt),
        "exit_time": _iso(exit_dt),
        "exit_price_utc": _iso(exit_dt),
        "exit_candle_close_time": _iso(exit_dt),
        "exit_candle_available_at": _iso(exit_available_dt),
        "label_available_at": _iso(exit_available_dt),
        "label_generated_at": _iso(label_generated_at),
        "label_available_at_not_after_generated_at": True,
        "label_exit_strictly_after_decision": exit_dt > decision_dt,
        "candle_close_time": _iso(entry_close_dt),
        "candle_closed_confirmed": True,
        "closed_candle": True,
        "model_version": _first_present(row.get("model_version"), "continuous_edge_factory_counterfactual_v1"),
        "checkpoint_id": _first_present(row.get("checkpoint_id"), "continuous_edge_factory_counterfactual"),
        "replay_snapshot_id": "edge_factory_counterfactual:" + row_hash[:16],
        "replay_snapshot_key": f"{COUNTERFACTUAL_KEY}:{feedback_id}",
        "masa_feature_cutoff": row.get("masa_feature_cutoff"),
        "ppo_feature_cutoff": row.get("ppo_feature_cutoff"),
        "trade_outcome": outcome,
        "directional_outcome": "UP" if gross_bps > 0 else "DOWN" if gross_bps < 0 else "FLAT",
        "action_was_profitable": net_bps > 0.0,
        "outcome_targets": {
            "realized_net_pnl_bps": round(net_bps, 10),
            "realized_net_pnl_usd": round(net_usd, 10),
            "gross_pnl_bps": round(gross_bps, 10),
            "gross_pnl_usd": round(gross_usd, 10),
            "fees": round(float(costs["fees_bps"]), 10),
            "slippage": round(float(costs["execution_friction_bps"]), 10),
            "funding": round(float(costs["funding_bps"]), 10),
            "explicit_cost_unit": "bps",
            "explicit_total_cost_bps": round(total_cost_bps, 10),
            "counterfactual_notional_usd": notional,
            "counterfactual_notional_source": notional_source,
            "selected_action": side,
            "trade_outcome": outcome,
            "action_was_profitable": net_bps > 0.0,
            "exit_time": _iso(exit_dt),
            "label_available_at": _iso(exit_available_dt),
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
        decision_dt = _parse_time(row.get("decision_time"))
        if entry_dt is not None and decision_dt is not None and entry_dt < decision_dt:
            reasons.append("ENTRY_TIME_BEFORE_DECISION_TIME")
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
        feedback_row = _build_feedback_row(
            row,
            exit_candle=exit_candle,
            min_hold_seconds=min_hold_seconds,
            label_generated_at=now,
        )
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


@dataclass
class StableRedisSourceGuard:
    key: str
    pipeline: Any
    redis_client: Any
    source_exists: bool
    observed_source_byte_length: int
    started_utc: str
    observed_source_sha256: str | None = None
    source_stream_complete: bool = False
    active: bool = True


class RedisCliJson:
    def __init__(self, redis_url: str | None = None) -> None:
        self.redis_url = str(
            redis_url
            or os.environ.get("V2_REDIS_URL")
            or os.environ.get("REDIS_URL")
            or os.environ.get("LEGACY_REDIS_URL")
            or "redis://127.0.0.1:6379/0"
        )
        self._redis_cli_argv = ["redis-cli", "-u", self.redis_url]
        self._active_source_guards: dict[str, StableRedisSourceGuard] = {}

    def get(self, key: str) -> Any:
        completed = subprocess.run(
            [*self._redis_cli_argv, "GET", key],
            check=False,
            text=True,
            capture_output=True,
        )
        raw = completed.stdout.strip()
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    def set_json(self, key: str, payload: Any) -> bool:
        encoded = canonical_json(payload)
        completed = subprocess.run(
            [*self._redis_cli_argv, "-x", "SET", key],
            input=encoded,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return completed.returncode == 0 and completed.stdout.strip() == "OK"

    def begin_stable_source_guard(self, key: str) -> StableRedisSourceGuard:
        """WATCH the source before streaming it on a separate bounded reader."""

        import redis as redis_lib

        redis_client = redis_lib.Redis.from_url(
            self.redis_url,
            decode_responses=False,
        )
        pipeline = redis_client.pipeline()
        try:
            pipeline.watch(key)
            source_exists = bool(pipeline.exists(key))
            observed_length = int(pipeline.strlen(key) or 0)
        except Exception:
            pipeline.reset()
            redis_client.close()
            raise
        guard = StableRedisSourceGuard(
            key=str(key),
            pipeline=pipeline,
            redis_client=redis_client,
            source_exists=source_exists,
            observed_source_byte_length=observed_length,
            started_utc=_utc_now(),
        )
        self._active_source_guards[str(key)] = guard
        return guard

    def replace_json_if_source_unchanged(
        self,
        key: str,
        payload: Any,
        guard: StableRedisSourceGuard,
    ) -> dict[str, Any]:
        """Atomically SET only if WATCH proves the streamed source was stable."""

        if not isinstance(guard, StableRedisSourceGuard) or not guard.active:
            raise ValueError("counterfactual_source_guard_invalid_or_inactive")
        if str(key) != guard.key:
            raise ValueError("counterfactual_source_guard_key_mismatch")
        if guard.source_stream_complete is not True:
            raise ValueError("counterfactual_source_stream_not_complete")
        if guard.observed_source_sha256 in (None, ""):
            raise ValueError("counterfactual_source_stream_digest_missing")
        encoded = canonical_json(payload)
        result: dict[str, Any]
        try:
            guard.pipeline.multi()
            guard.pipeline.set(key, encoded)
            transaction_result = guard.pipeline.execute()
            write_succeeded = bool(
                isinstance(transaction_result, list)
                and len(transaction_result) == 1
                and transaction_result[0]
            )
            result = {
                "source_guard_supported": True,
                "source_guard_acquired": True,
                "source_unchanged_at_replace": True,
                "source_concurrency_conflict": False,
                "write_attempted": True,
                "write_succeeded": write_succeeded,
                "write_outcome": (
                    "ATOMIC_REPLACE_SUCCEEDED"
                    if write_succeeded
                    else "ATOMIC_REPLACE_COMMAND_REJECTED"
                ),
                "redis_state_after_attempt_known": True,
            }
        except Exception as exc:  # redis-py is intentionally isolated here
            if exc.__class__.__name__ == "WatchError":
                result = {
                    "source_guard_supported": True,
                    "source_guard_acquired": True,
                    "source_unchanged_at_replace": False,
                    "source_concurrency_conflict": True,
                    "write_attempted": False,
                    "write_succeeded": False,
                    "write_outcome": "SOURCE_CHANGED_ATOMIC_REPLACE_ABORTED",
                    "redis_state_after_attempt_known": True,
                }
            else:
                result = {
                    "source_guard_supported": True,
                    "source_guard_acquired": True,
                    "source_unchanged_at_replace": None,
                    "source_concurrency_conflict": False,
                    "write_attempted": True,
                    "write_succeeded": False,
                    "write_outcome": (
                        "ATOMIC_REPLACE_RESULT_UNKNOWN:"
                        f"{type(exc).__name__}:{str(exc)[:240]}"
                    ),
                    "redis_state_after_attempt_known": False,
                }
        finally:
            guard.active = False
            self._active_source_guards.pop(guard.key, None)
            guard.pipeline.reset()
            guard.redis_client.close()
        result.update(
            {
                "source_compare_method": "REDIS_WATCH_MULTI_EXEC_KEY_VERSION",
                "source_compare_endpoint_contract": (
                    REDIS_SOURCE_COMPARE_ENDPOINT_CONTRACT
                ),
                "source_compare_atomic_with_write": True,
                "source_compare_performed_immediately_before_write": True,
                "observed_source_exists": guard.source_exists,
                "observed_source_byte_length": (
                    guard.observed_source_byte_length
                ),
                "observed_source_sha256": guard.observed_source_sha256,
            }
        )
        return result

    def cancel_stable_source_guard(self, guard: StableRedisSourceGuard) -> None:
        if not isinstance(guard, StableRedisSourceGuard) or not guard.active:
            return
        guard.active = False
        self._active_source_guards.pop(guard.key, None)
        guard.pipeline.reset()
        guard.redis_client.close()

    def iter_json_array(self, key: str) -> Iterable[dict[str, Any]]:
        """Stream a Redis JSON array without capturing the whole value in RAM."""

        process = subprocess.Popen(  # noqa: S603 - fixed redis-cli argv
            [*self._redis_cli_argv, "--raw", "GET", key],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if process.stdout is None or process.stderr is None:
            process.kill()
            raise RuntimeError("redis_cli_stream_pipes_unavailable")
        utf8_decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
        guard = self._active_source_guards.get(str(key))
        source_digest = hashlib.sha256()
        source_bytes_seen = 0
        framing_bytes = bytearray()

        def decoded_chunks() -> Iterable[str]:
            nonlocal source_bytes_seen
            while True:
                raw = process.stdout.read(COUNTERFACTUAL_STREAM_CHUNK_BYTES)
                if not raw:
                    tail = utf8_decoder.decode(b"", final=True)
                    if tail:
                        yield tail
                    break
                source_bytes = raw
                if guard is not None:
                    remaining = max(
                        0,
                        guard.observed_source_byte_length - source_bytes_seen,
                    )
                    source_bytes = raw[:remaining]
                    framing_bytes.extend(raw[remaining:])
                    if len(framing_bytes) > 2:
                        raise RuntimeError(
                            "redis_cli_stream_source_changed_length_during_guard"
                        )
                    source_bytes_seen += len(source_bytes)
                    source_digest.update(source_bytes)
                decoded = utf8_decoder.decode(source_bytes, final=False)
                if decoded:
                    yield decoded

        try:
            yield from _iter_top_level_json_array_chunks(decoded_chunks())
            stderr = process.stderr.read().decode("utf-8", errors="replace").strip()
            return_code = process.wait()
            if return_code != 0:
                raise RuntimeError(
                    f"redis_cli_stream_get_failed:{return_code}:{stderr[:240]}"
                )
            if guard is not None:
                if source_bytes_seen != guard.observed_source_byte_length:
                    raise RuntimeError(
                        "redis_cli_stream_source_length_mismatch:"
                        f"{source_bytes_seen}!={guard.observed_source_byte_length}"
                    )
                if bytes(framing_bytes) not in {b"", b"\n", b"\r\n"}:
                    raise RuntimeError(
                        "redis_cli_stream_unexpected_protocol_framing"
                    )
                if guard.source_exists and guard.observed_source_byte_length == 0:
                    raise ValueError("counterfactual_json_top_level_array_required")
                guard.observed_source_sha256 = source_digest.hexdigest()
                guard.source_stream_complete = True
        finally:
            process.stdout.close()
            process.stderr.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def _json_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(row) for row in value if isinstance(row, Mapping)]
    if isinstance(value, Mapping):
        rows = value.get("rows")
        if isinstance(rows, list):
            return [dict(row) for row in rows if isinstance(row, Mapping)]
    return []


def _iter_counterfactual_rows(client: Any) -> Iterable[dict[str, Any]]:
    streamer = getattr(client, "iter_json_array", None)
    if callable(streamer):
        yield from streamer(COUNTERFACTUAL_KEY)
        return
    yield from _json_rows(client.get(COUNTERFACTUAL_KEY))


def _bounded_preview_hot_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    """Select the latest unique identities with memory bounded by ``limit``."""

    bounded_limit = max(1, int(limit))
    selected: dict[str, tuple[str, dict[str, Any]]] = {}
    heap: list[tuple[str, str]] = []
    input_rows = 0
    for raw in rows:
        input_rows += 1
        row = dict(raw)
        identity = _counterfactual_identity(row)
        if identity in selected:
            continue
        sort_key = _counterfactual_sort_key(row)
        item = (sort_key, identity)
        if len(selected) < bounded_limit:
            selected[identity] = (sort_key, row)
            heapq.heappush(heap, item)
            continue
        if item <= heap[0]:
            continue
        _old_sort, old_identity = heapq.heapreplace(heap, item)
        selected.pop(old_identity, None)
        selected[identity] = (sort_key, row)
    hot_rows = [row for _sort_key, row in selected.values()]
    hot_rows.sort(key=_counterfactual_sort_key)
    return hot_rows, input_rows


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
        # Feedback ids are immutable logical identities.  Preserve the first
        # copy so an idempotent replay cannot rewrite an already observed
        # label merely because its operational generated_utc changed.
        merged.setdefault(row_id, row)
    return sorted(merged.values(), key=_counterfactual_sort_key)


def _counterfactual_identity(row: Mapping[str, Any]) -> str:
    return counterfactual_archive_identity(row)


def _counterfactual_sort_key(row: Mapping[str, Any]) -> str:
    """Outcome-blind deterministic order for the trainer hot working set."""

    return counterfactual_archive_sort_key(row)


def _counterfactual_semantic_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    # generated_utc records when an idempotent factory run happened, not a
    # model feature or label.  Excluding it from duplicate comparison avoids
    # treating the same immutable feedback id as a different logical row.
    return {key: value for key, value in row.items() if key != "generated_utc"}


def _archive_counterfactual_rows_and_select_hot_set_locked(
    *,
    archive_path: Path,
    rows: Iterable[Mapping[str, Any]] | None = None,
    source_rows: Iterable[Mapping[str, Any]] | None = None,
    new_rows: Iterable[Mapping[str, Any]] = (),
    trainer_hot_max_rows: int,
    source_snapshot_id: str | None = None,
    observed_source_byte_length: int | None = None,
    source_fingerprint_state: Any = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Archive and snapshot every source occurrence before hot selection.

    ``rows`` is retained as a compatibility alias for callers whose whole input
    is the source being replaced.  Runtime callers pass ``source_rows`` and
    ``new_rows`` separately so the rollback snapshot reconstructs the exact
    pre-replacement Redis array, while newly matured rows are still archived
    before they can enter the bounded hot set.
    """

    if rows is not None and source_rows is not None:
        raise ValueError("counterfactual_archive_source_rows_ambiguous")
    source_iterable = rows if rows is not None else source_rows
    if source_iterable is None:
        source_iterable = ()

    hot_limit = max(1, int(trainer_hot_max_rows))
    archive = DurablePaperEvidenceArchive(
        archive_path,
        stream_id=COUNTERFACTUAL_ARCHIVE_STREAM_ID,
    )
    attempted_rows = 0
    inserted_rows = 0
    duplicate_rows = 0
    identity_conflicts = 0
    conflict_ids: list[str] = []
    archive_batches_committed = 0
    batch: list[ArchiveCandidate] = []
    batch_encoded_bytes = 0
    append_result = None
    source_snapshot = str(
        source_snapshot_id
        or f"counterfactual_source_snapshot:{time.time_ns()}"
    )
    archive.begin_source_snapshot(
        snapshot_id=source_snapshot,
        source_key=COUNTERFACTUAL_KEY,
    )
    source_snapshot_count = 0
    source_snapshot_digest = hashlib.sha256(b"").hexdigest()
    source_snapshot_error: str | None = None
    source_canonical_byte_length = 2
    all_rows_digest = hashlib.sha256()
    all_semantic_rows_digest = hashlib.sha256()

    def flush_batch(*, snapshot_occurrences: bool) -> None:
        nonlocal attempted_rows
        nonlocal inserted_rows
        nonlocal duplicate_rows
        nonlocal identity_conflicts
        nonlocal archive_batches_committed
        nonlocal append_result
        nonlocal source_snapshot_count
        nonlocal source_snapshot_digest
        nonlocal source_snapshot_error
        nonlocal batch_encoded_bytes
        if not batch:
            return
        append_result = archive.append_unique(batch)
        archive_batches_committed += 1
        attempted_rows += append_result.attempted_rows
        inserted_rows += append_result.inserted_rows
        duplicate_rows += append_result.duplicate_rows
        identity_conflicts += append_result.identity_conflicts
        for conflict_id in append_result.identity_conflict_ids:
            if conflict_id not in conflict_ids and len(conflict_ids) < 20:
                conflict_ids.append(conflict_id)
        if snapshot_occurrences and source_snapshot_error is None:
            if append_result.identity_conflicts:
                source_snapshot_error = "SOURCE_IDENTITY_CONFLICT"
            else:
                try:
                    occurrence_result = archive.append_source_snapshot_occurrences(
                        snapshot_id=source_snapshot,
                        expected_start_index=source_snapshot_count,
                        candidates=batch,
                    )
                except Exception as exc:  # fail closed; no replacement follows
                    source_snapshot_error = (
                        f"{type(exc).__name__}:{str(exc)[:240]}"
                    )
                else:
                    source_snapshot_count = int(
                        occurrence_result["occurrence_count"]
                    )
                    source_snapshot_digest = str(
                        occurrence_result["ordered_occurrence_sha256"]
                    )
        batch.clear()
        batch_encoded_bytes = 0

    def process_rows(
        input_rows: Iterable[Mapping[str, Any]],
        *,
        snapshot_occurrences: bool,
    ) -> None:
        nonlocal source_canonical_byte_length
        nonlocal batch_encoded_bytes
        for raw_row in input_rows:
            row = dict(raw_row)
            encoded = canonical_json(row).encode("utf-8")
            if len(encoded) > COUNTERFACTUAL_MAX_JSON_ROW_BYTES:
                raise ValueError(
                    "counterfactual_json_row_exceeds_memory_safety_bound"
                )
            if (
                batch
                and batch_encoded_bytes + len(encoded)
                > COUNTERFACTUAL_ARCHIVE_BATCH_MAX_BYTES
            ):
                flush_batch(snapshot_occurrences=snapshot_occurrences)
            candidate = ArchiveCandidate(
                record_id=_counterfactual_identity(row),
                sort_key=_counterfactual_sort_key(row),
                payload=row,
                semantic_payload=_counterfactual_semantic_payload(row),
            )
            semantic_encoded = canonical_json(
                _counterfactual_semantic_payload(row)
            ).encode("utf-8")
            all_rows_digest.update(len(encoded).to_bytes(8, "big"))
            all_rows_digest.update(encoded)
            all_semantic_rows_digest.update(
                len(semantic_encoded).to_bytes(8, "big")
            )
            all_semantic_rows_digest.update(semantic_encoded)
            if snapshot_occurrences:
                if source_snapshot_count or batch:
                    source_canonical_byte_length += 1
                source_canonical_byte_length += len(encoded)
            batch.append(candidate)
            batch_encoded_bytes += len(encoded)
            if (
                len(batch) >= 512
                or batch_encoded_bytes
                >= COUNTERFACTUAL_ARCHIVE_BATCH_MAX_BYTES
            ):
                flush_batch(snapshot_occurrences=snapshot_occurrences)
        flush_batch(snapshot_occurrences=snapshot_occurrences)

    try:
        process_rows(source_iterable, snapshot_occurrences=True)
    except Exception:
        # A late streaming/parser/identity failure must not strand hundreds of
        # megabytes of occurrence payloads in an IN_PROGRESS snapshot.  The
        # immutable unique archive may already contain committed batches, but
        # the Redis source is untouched and its incomplete rollback mapping is
        # removed before the failure is propagated.
        batch.clear()
        try:
            archive.abort_source_snapshot(
                source_snapshot,
                reason="SOURCE_STREAM_FAILED",
            )
        except ValueError:
            pass
        raise
    if source_snapshot_error is None:
        try:
            observed_source_sha256 = None
            source_stream_complete = None
            if source_fingerprint_state is not None:
                if isinstance(source_fingerprint_state, Mapping):
                    observed_source_sha256 = source_fingerprint_state.get(
                        "observed_source_sha256",
                        source_fingerprint_state.get("source_sha256"),
                    )
                    source_stream_complete = source_fingerprint_state.get(
                        "source_stream_complete"
                    )
                else:
                    observed_source_sha256 = getattr(
                        source_fingerprint_state,
                        "observed_source_sha256",
                        None,
                    )
                    source_stream_complete = getattr(
                        source_fingerprint_state,
                        "source_stream_complete",
                        None,
                    )
                if source_stream_complete is not True:
                    raise ValueError(
                        "counterfactual_source_stream_fingerprint_incomplete"
                    )
            source_snapshot_status = archive.finalize_source_snapshot(
                snapshot_id=source_snapshot,
                expected_occurrence_count=source_snapshot_count,
                expected_ordered_occurrence_sha256=source_snapshot_digest,
                observed_source_byte_length=(
                    source_canonical_byte_length
                    if observed_source_byte_length is None
                    else max(0, int(observed_source_byte_length))
                ),
                observed_source_sha256=(
                    None
                    if observed_source_sha256 in (None, "")
                    else str(observed_source_sha256)
                ),
            )
            source_snapshot_status = archive.verify_source_snapshot(
                source_snapshot
            )
        except Exception as exc:
            source_snapshot_error = f"{type(exc).__name__}:{str(exc)[:240]}"
            try:
                archive.abort_source_snapshot(
                    source_snapshot,
                    reason="FINALIZATION_FAILED",
                )
            except ValueError:
                pass
            source_snapshot_status = {}
    else:
        archive.abort_source_snapshot(
            source_snapshot,
            reason=source_snapshot_error,
        )
        source_snapshot_status = {}

    process_rows(new_rows, snapshot_occurrences=False)
    if append_result is None:
        append_result = archive.append_unique(())
    archive_input_accounted = (
        attempted_rows == inserted_rows + duplicate_rows + identity_conflicts
    )
    integrity = archive.verify_integrity(
        identity_resolver=_counterfactual_identity,
        sort_key_resolver=_counterfactual_sort_key,
    )
    hot_rows = archive.latest_rows(
        hot_limit,
        identity_resolver=_counterfactual_identity,
        sort_key_resolver=_counterfactual_sort_key,
        max_payload_bytes=COUNTERFACTUAL_VERIFIED_LATEST_ROWS_MAX_BYTES,
    )
    hot_payload_bytes = sum(
        len(canonical_json(row).encode("utf-8")) for row in hot_rows
    )
    archive_ready = (
        identity_conflicts == 0
        and integrity.get("integrity_verified") is True
        and source_snapshot_error is None
        and source_snapshot_status.get("rollback_reconstruction_verified") is True
        and archive_input_accounted
    )
    return hot_rows, {
        "schema_version": "edge_factory_counterfactual_archive_hot_cache_status_v1",
        "status": (
            "DURABLE_ARCHIVE_READY_BOUNDED_HOT_CACHE"
            if archive_ready
            else "DURABLE_ARCHIVE_IDENTITY_CONFLICT_FAIL_CLOSED"
        ),
        "archive_schema_version": ARCHIVE_SCHEMA_VERSION,
        "durable_archive_path": str(archive_path),
        "durable_archive_stream_id": COUNTERFACTUAL_ARCHIVE_STREAM_ID,
        "archive_attempted_rows": attempted_rows,
        "archive_inserted_unique_rows": inserted_rows,
        "archive_duplicate_rows": duplicate_rows,
        "archive_identity_conflicts": identity_conflicts,
        "archive_identity_conflict_ids": conflict_ids,
        "archive_batches_committed": archive_batches_committed,
        "archive_batch_max_rows": 512,
        "archive_batch_max_payload_bytes": (
            COUNTERFACTUAL_ARCHIVE_BATCH_MAX_BYTES
        ),
        "archive_input_materialized_in_memory": False,
        "archive_all_input_rows_accounted_for": archive_input_accounted,
        "archive_input_ordered_rows_sha256": all_rows_digest.hexdigest(),
        "archive_input_ordered_semantic_rows_sha256": (
            all_semantic_rows_digest.hexdigest()
        ),
        "durable_archive_total_unique_rows": append_result.total_unique_rows,
        "durable_archive_unique_record_chain_sha256": append_result.archive_chain_sha256,
        "durable_archive_integrity_verified": integrity.get("integrity_verified"),
        "durable_archive_integrity_unique_rows": integrity.get("total_unique_rows"),
        "durable_archive_integrity_total_occurrences": integrity.get(
            "total_occurrences"
        ),
        "source_snapshot_id": source_snapshot,
        "source_snapshot_status": source_snapshot_status.get(
            "snapshot_status",
            "ABORTED_OR_INCOMPLETE",
        ),
        "source_snapshot_error": source_snapshot_error,
        "source_snapshot_occurrence_count": source_snapshot_status.get(
            "occurrence_count",
            source_snapshot_count,
        ),
        "source_snapshot_ordered_occurrence_sha256": (
            source_snapshot_status.get(
                "ordered_occurrence_sha256",
                source_snapshot_digest,
            )
        ),
        "source_snapshot_observed_redis_byte_length": (
            source_snapshot_status.get("observed_source_byte_length")
        ),
        "source_snapshot_canonical_json_byte_length": (
            source_snapshot_status.get("canonical_json_byte_length")
        ),
        "source_snapshot_canonical_json_sha256": (
            source_snapshot_status.get("canonical_json_sha256")
        ),
        "source_snapshot_observed_source_sha256": (
            source_snapshot_status.get("observed_source_sha256")
        ),
        "source_snapshot_fingerprint_contract": (
            "REDIS_STRLEN_PLUS_STREAMED_RAW_SHA256_WITH_WATCH_MULTI_EXEC_CAS"
            if source_fingerprint_state is not None
            else "CANONICAL_JSON_SOURCE_SHA256_NON_REDIS_CALLER"
        ),
        "source_snapshot_rollback_reconstruction_verified": (
            source_snapshot_status.get("rollback_reconstruction_verified")
            is True
        ),
        "redis_key": COUNTERFACTUAL_KEY,
        "redis_role": "BOUNDED_TRAINER_HOT_WORKING_SET_NOT_DURABLE_ARCHIVE",
        "redis_hot_max_rows": hot_limit,
        "redis_hot_max_payload_bytes": (
            COUNTERFACTUAL_VERIFIED_LATEST_ROWS_MAX_BYTES
        ),
        "redis_hot_rows": len(hot_rows),
        "redis_hot_payload_bytes": hot_payload_bytes,
        "redis_hot_rows_omitted_but_preserved_in_archive": max(
            0,
            append_result.total_unique_rows - len(hot_rows),
        ),
        "redis_hot_ordered_rows_sha256": ordered_rows_sha256(hot_rows),
        "redis_hot_ordered_semantic_rows_sha256": ordered_rows_sha256(
            _counterfactual_semantic_payload(row) for row in hot_rows
        ),
        "hot_selection_basis": "decision_time_then_stable_feedback_id",
        "hot_selection_uses_outcome_fields": False,
        "hot_limit_is_operational_resource_control_not_market_admission_threshold": True,
        "all_unique_rows_archived_before_hot_cache_replace": archive_ready,
        "counterfactual_rows_count_as_final_a_plus": False,
        "counterfactual_rows_count_as_live_ready": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def archive_counterfactual_rows_and_select_hot_set(
    *,
    archive_path: Path,
    rows: Iterable[Mapping[str, Any]] | None = None,
    source_rows: Iterable[Mapping[str, Any]] | None = None,
    new_rows: Iterable[Mapping[str, Any]] = (),
    trainer_hot_max_rows: int,
    source_snapshot_id: str | None = None,
    observed_source_byte_length: int | None = None,
    source_fingerprint_state: Any = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run one archive migration under a crash-released process lock."""

    normalized_archive_path = Path(archive_path)
    normalized_archive_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = normalized_archive_path.with_name(
        normalized_archive_path.name + ".migration.lock"
    )
    with lock_path.open("a+b") as lock_handle:
        try:
            fcntl.flock(
                lock_handle.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except BlockingIOError as exc:
            raise RuntimeError(
                "counterfactual_archive_migration_already_in_progress"
            ) from exc
        archive = DurablePaperEvidenceArchive(
            normalized_archive_path,
            stream_id=COUNTERFACTUAL_ARCHIVE_STREAM_ID,
        )
        recovery = archive.abort_in_progress_source_snapshots(
            source_key=COUNTERFACTUAL_KEY,
            reason="RECOVERED_AFTER_EXCLUSIVE_WORKER_LOCK_REACQUIRED",
        )
        try:
            hot_rows, status = (
                _archive_counterfactual_rows_and_select_hot_set_locked(
                    archive_path=normalized_archive_path,
                    rows=rows,
                    source_rows=source_rows,
                    new_rows=new_rows,
                    trainer_hot_max_rows=trainer_hot_max_rows,
                    source_snapshot_id=source_snapshot_id,
                    observed_source_byte_length=observed_source_byte_length,
                    source_fingerprint_state=source_fingerprint_state,
                )
            )
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    status["exclusive_archive_migration_lock"] = {
        "lock_path": str(lock_path),
        "lock_acquired": True,
        "lock_released": True,
        "crash_releases_lock": True,
        "stale_in_progress_snapshot_recovery": recovery,
    }
    return hot_rows, status


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
    counterfactual_archive_path: Path = DEFAULT_COUNTERFACTUAL_ARCHIVE_PATH,
    trainer_hot_max_rows: int = DEFAULT_MAX_TRAINING_ROWS_PER_CYCLE,
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
    existing_counterfactual_rows = 0
    archive_status: dict[str, Any]
    source_guard: Any = None
    if publish_redis:
        try:
            begin_source_guard = getattr(client, "begin_stable_source_guard", None)
            if not callable(begin_source_guard):
                raise RuntimeError(
                    "counterfactual_stable_source_guard_not_supported"
                )
            source_guard = begin_source_guard(COUNTERFACTUAL_KEY)
            observed_source_byte_length = int(
                (
                    source_guard.get("observed_source_byte_length")
                    if isinstance(source_guard, Mapping)
                    else getattr(
                        source_guard,
                        "observed_source_byte_length",
                        -1,
                    )
                )
                or 0
            )
            if observed_source_byte_length < 0:
                raise ValueError(
                    "counterfactual_source_guard_byte_length_invalid"
                )

            def counted_existing_rows() -> Iterable[dict[str, Any]]:
                nonlocal existing_counterfactual_rows
                for existing_row in _iter_counterfactual_rows(client):
                    existing_counterfactual_rows += 1
                    yield existing_row

            trainer_hot_rows, archive_status = archive_counterfactual_rows_and_select_hot_set(
                archive_path=counterfactual_archive_path,
                source_rows=counted_existing_rows(),
                new_rows=matured,
                trainer_hot_max_rows=trainer_hot_max_rows,
                source_snapshot_id=(
                    f"counterfactual_source_snapshot:{time.time_ns()}"
                ),
                observed_source_byte_length=observed_source_byte_length,
                source_fingerprint_state=source_guard,
            )
        except Exception as exc:  # noqa: BLE001 - fail closed without replacing Redis
            cancel_source_guard = getattr(
                client,
                "cancel_stable_source_guard",
                None,
            )
            if source_guard is not None and callable(cancel_source_guard):
                cancel_source_guard(source_guard)
            source_guard = None
            trainer_hot_rows = []
            archive_status = {
                "schema_version": "edge_factory_counterfactual_archive_hot_cache_status_v1",
                "status": "DURABLE_ARCHIVE_WRITE_FAILED_FAIL_CLOSED",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "durable_archive_path": str(counterfactual_archive_path),
                "redis_key": COUNTERFACTUAL_KEY,
                "redis_role": "BOUNDED_TRAINER_HOT_WORKING_SET_NOT_DURABLE_ARCHIVE",
                "redis_hot_max_rows": max(1, int(trainer_hot_max_rows)),
                "all_unique_rows_archived_before_hot_cache_replace": False,
                "counterfactual_rows_count_as_final_a_plus": False,
                "counterfactual_rows_count_as_live_ready": False,
                "paper_only": True,
                "routes_to_live": False,
                "places_real_order": False,
            }
    else:
        trainer_hot_rows, preview_input_rows = _bounded_preview_hot_rows(
            itertools.chain(_iter_counterfactual_rows(client), matured),
            limit=trainer_hot_max_rows,
        )
        existing_counterfactual_rows = max(0, preview_input_rows - len(matured))
        archive_status = {
            "schema_version": "edge_factory_counterfactual_archive_hot_cache_status_v1",
            "status": "PREVIEW_ONLY_ARCHIVE_NOT_MUTATED",
            "durable_archive_path": str(counterfactual_archive_path),
            "redis_key": COUNTERFACTUAL_KEY,
            "redis_role": "BOUNDED_TRAINER_HOT_WORKING_SET_NOT_DURABLE_ARCHIVE",
            "redis_hot_max_rows": max(1, int(trainer_hot_max_rows)),
            "redis_hot_rows": len(trainer_hot_rows),
            "redis_hot_ordered_rows_sha256": ordered_rows_sha256(trainer_hot_rows),
            "redis_hot_ordered_semantic_rows_sha256": ordered_rows_sha256(
                _counterfactual_semantic_payload(row) for row in trainer_hot_rows
            ),
            "hot_selection_basis": "decision_time_then_stable_feedback_id",
            "hot_selection_uses_outcome_fields": False,
            "hot_limit_is_operational_resource_control_not_market_admission_threshold": True,
            "all_unique_rows_archived_before_hot_cache_replace": False,
            "counterfactual_rows_count_as_final_a_plus": False,
            "counterfactual_rows_count_as_live_ready": False,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }
    scoreboard = strategy_bucket_scoreboard(trainer_hot_rows)
    scoreboard["row_scope"] = "BOUNDED_TRAINER_HOT_WORKING_SET"
    scoreboard["row_scope_count"] = len(trainer_hot_rows)
    scoreboard["row_scope_ordered_rows_sha256"] = ordered_rows_sha256(trainer_hot_rows)
    scoreboard["not_final_a_plus_evidence"] = True
    trainer_consumption = {
        "schema_version": "edge_factory_replay_to_trainer_consumption_status_v1",
        "generated_utc": _utc_now(),
        "trainer_counterfactual_key": COUNTERFACTUAL_KEY,
        "existing_counterfactual_rows": existing_counterfactual_rows,
        "new_matured_rows": len(matured),
        "merged_counterfactual_rows": archive_status.get(
            "durable_archive_total_unique_rows",
            len(trainer_hot_rows),
        ),
        "counterfactual_source_streamed_without_full_materialization": True,
        "durable_archive_total_unique_rows": archive_status.get(
            "durable_archive_total_unique_rows"
        ),
        "redis_hot_counterfactual_rows": len(trainer_hot_rows),
        "redis_hot_max_rows": max(1, int(trainer_hot_max_rows)),
        "redis_role": "BOUNDED_TRAINER_HOT_WORKING_SET_NOT_DURABLE_ARCHIVE",
        "durable_archive_path": str(counterfactual_archive_path),
        "archive_hot_cache_status": archive_status.get("status"),
        "archive_hot_cache_contract": archive_status,
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
        "counterfactual_archive_hot_cache": archive_status,
        "publish_redis": publish_redis,
        "duration_seconds": round(time.time() - started, 6),
        "live_gate_required": "blocked_human_only",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "redis_list_trim": False,
        "redis_counterfactual_string_replaced_with_bounded_hot_working_set": (
            False
        ),
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
        cache_publish_allowed = (
            archive_status.get("all_unique_rows_archived_before_hot_cache_replace") is True
            and source_guard is not None
        )
        archive = DurablePaperEvidenceArchive(
            counterfactual_archive_path,
            stream_id=COUNTERFACTUAL_ARCHIVE_STREAM_ID,
        )
        replacement_attempt_id = (
            f"counterfactual_hot_cache_replace:{time.time_ns()}"
        )
        archive_chain = str(
            archive_status.get("durable_archive_unique_record_chain_sha256")
            or ""
        )
        archive_total_rows = int(
            archive_status.get("durable_archive_total_unique_rows") or 0
        )
        replacement_intent_result: dict[str, Any] = {}
        replacement_intent_error: str | None = None
        if cache_publish_allowed:
            replacement_intent = {
                "schema_version": COUNTERFACTUAL_REPLACEMENT_INTENT_SCHEMA,
                "operation_id": f"{replacement_attempt_id}:intent",
                "generated_utc": _utc_now(),
                "redis_key": COUNTERFACTUAL_KEY,
                "source_guard_acquired_before_stream": True,
                "source_snapshot_id": archive_status.get("source_snapshot_id"),
                "source_snapshot_occurrence_count": archive_status.get(
                    "source_snapshot_occurrence_count"
                ),
                "source_snapshot_ordered_occurrence_sha256": archive_status.get(
                    "source_snapshot_ordered_occurrence_sha256"
                ),
                "source_snapshot_observed_redis_byte_length": archive_status.get(
                    "source_snapshot_observed_redis_byte_length"
                ),
                "source_snapshot_canonical_json_byte_length": archive_status.get(
                    "source_snapshot_canonical_json_byte_length"
                ),
                "source_snapshot_canonical_json_sha256": archive_status.get(
                    "source_snapshot_canonical_json_sha256"
                ),
                "source_snapshot_observed_source_sha256": archive_status.get(
                    "source_snapshot_observed_source_sha256"
                ),
                "source_snapshot_fingerprint_contract": archive_status.get(
                    "source_snapshot_fingerprint_contract"
                ),
                "source_snapshot_rollback_reconstruction_verified": (
                    archive_status.get(
                        "source_snapshot_rollback_reconstruction_verified"
                    )
                    is True
                ),
                "archive_chain_sha256": archive_chain,
                "archive_total_unique_rows": archive_total_rows,
                "archive_integrity_verified": archive_status.get(
                    "durable_archive_integrity_verified"
                )
                is True,
                "all_input_rows_accounted_for": archive_status.get(
                    "archive_all_input_rows_accounted_for"
                )
                is True,
                "target_hot_rows": len(trainer_hot_rows),
                "target_hot_max_rows": max(1, int(trainer_hot_max_rows)),
                "target_hot_max_payload_bytes": (
                    COUNTERFACTUAL_VERIFIED_LATEST_ROWS_MAX_BYTES
                ),
                "target_hot_payload_bytes": sum(
                    len(canonical_json(row).encode("utf-8"))
                    for row in trainer_hot_rows
                ),
                "target_hot_ordered_rows_sha256": ordered_rows_sha256(
                    trainer_hot_rows
                ),
                "archive_first_before_redis_replace": True,
                "paper_only": True,
                "routes_to_live": False,
                "places_real_order": False,
            }
            try:
                replacement_intent_result = archive.append_operation_receipt(
                    operation_id=f"{replacement_attempt_id}:intent",
                    operation_kind=COUNTERFACTUAL_REPLACEMENT_INTENT_KIND,
                    receipt=replacement_intent,
                    expected_archive_chain_sha256=archive_chain,
                    expected_total_unique_rows=archive_total_rows,
                )
                persisted_intent = archive.latest_operation_receipt(
                    operation_kind=COUNTERFACTUAL_REPLACEMENT_INTENT_KIND
                )
                if (
                    persisted_intent is None
                    or persisted_intent.get("operation_id")
                    != f"{replacement_attempt_id}:intent"
                    or persisted_intent.get("receipt_sha256")
                    != replacement_intent_result.get("receipt_sha256")
                ):
                    raise RuntimeError(
                        "counterfactual_replacement_intent_readback_mismatch"
                    )
            except Exception as exc:  # fail closed before Redis mutation
                replacement_intent_error = (
                    f"{type(exc).__name__}:{str(exc)[:240]}"
                )
                cache_publish_allowed = False

        cache_write_succeeded = False
        cache_readback_verified = False
        cache_readback_rows = 0
        cache_readback_digest: str | None = None
        replacement_result: dict[str, Any] = {
            "source_guard_supported": source_guard is not None,
            "source_guard_acquired": source_guard is not None,
            "source_unchanged_at_replace": None,
            "source_concurrency_conflict": False,
            "write_attempted": False,
            "write_succeeded": False,
            "write_outcome": "ARCHIVE_OR_INTENT_NOT_READY_REPLACE_NOT_ATTEMPTED",
            "redis_state_after_attempt_known": True,
        }
        if cache_publish_allowed:
            atomic_replace = getattr(
                client,
                "replace_json_if_source_unchanged",
                None,
            )
            if not callable(atomic_replace):
                replacement_result["write_outcome"] = (
                    "ATOMIC_SOURCE_COMPARE_AND_SET_NOT_SUPPORTED"
                )
            else:
                try:
                    raw_replacement_result = atomic_replace(
                        COUNTERFACTUAL_KEY,
                        trainer_hot_rows,
                        source_guard,
                    )
                except Exception as exc:
                    replacement_result = {
                        "source_guard_supported": True,
                        "source_guard_acquired": True,
                        "source_unchanged_at_replace": None,
                        "source_concurrency_conflict": False,
                        "write_attempted": None,
                        "write_succeeded": False,
                        "write_outcome": (
                            "ATOMIC_REPLACE_CALL_FAILED:"
                            f"{type(exc).__name__}:{str(exc)[:240]}"
                        ),
                        "redis_state_after_attempt_known": False,
                    }
                else:
                    source_guard = None
                    if not isinstance(raw_replacement_result, Mapping):
                        replacement_result = {
                            "source_guard_supported": True,
                            "source_guard_acquired": True,
                            "source_unchanged_at_replace": None,
                            "source_concurrency_conflict": False,
                            "write_attempted": None,
                            "write_succeeded": False,
                            "write_outcome": (
                                "ATOMIC_REPLACE_RECEIPT_MISSING"
                            ),
                            "redis_state_after_attempt_known": False,
                        }
                    else:
                        replacement_result = dict(raw_replacement_result)
            cache_write_succeeded = (
                replacement_result.get("write_succeeded") is True
            )
            if cache_write_succeeded:
                try:
                    readback_rows = _json_rows(client.get(COUNTERFACTUAL_KEY))
                    cache_readback_rows = len(readback_rows)
                    cache_readback_digest = ordered_rows_sha256(readback_rows)
                    cache_readback_verified = bool(
                        len(readback_rows) == len(trainer_hot_rows)
                        and cache_readback_digest
                        == ordered_rows_sha256(trainer_hot_rows)
                    )
                except Exception as exc:
                    cache_readback_verified = False
                    replacement_result["readback_error"] = (
                        f"{type(exc).__name__}:{str(exc)[:240]}"
                    )
        if source_guard is not None:
            cancel_source_guard = getattr(
                client,
                "cancel_stable_source_guard",
                None,
            )
            if callable(cancel_source_guard):
                cancel_source_guard(source_guard)
            source_guard = None
        cache_replace_verified = bool(
            cache_publish_allowed
            and cache_write_succeeded
            and cache_readback_verified
        )
        if cache_replace_verified:
            rollback_status = "NOT_REQUIRED_REPLACEMENT_VERIFIED"
        elif replacement_result.get("source_concurrency_conflict") is True:
            rollback_status = (
                "NOT_REQUIRED_SOURCE_CHANGED_ATOMIC_REPLACEMENT_ABORTED"
            )
        elif replacement_result.get("write_attempted") is False:
            rollback_status = "NOT_REQUIRED_REDIS_NOT_MUTATED_BY_TOOL"
        else:
            rollback_status = (
                "ROLLBACK_AVAILABLE_FROM_DURABLE_ORDERED_SOURCE_SNAPSHOT"
            )
        no_data_loss_proven = bool(
            archive_status.get("all_unique_rows_archived_before_hot_cache_replace")
            is True
            and archive_status.get(
                "source_snapshot_rollback_reconstruction_verified"
            )
            is True
        )
        replacement_outcome = {
            "schema_version": COUNTERFACTUAL_REPLACEMENT_OUTCOME_SCHEMA,
            "operation_id": f"{replacement_attempt_id}:outcome",
            "intent_operation_id": f"{replacement_attempt_id}:intent",
            "intent_receipt_sha256": replacement_intent_result.get(
                "receipt_sha256"
            ),
            "generated_utc": _utc_now(),
            "redis_key": COUNTERFACTUAL_KEY,
            "source_snapshot_id": archive_status.get("source_snapshot_id"),
            "source_snapshot_occurrence_count": archive_status.get(
                "source_snapshot_occurrence_count"
            ),
            "source_snapshot_ordered_occurrence_sha256": archive_status.get(
                "source_snapshot_ordered_occurrence_sha256"
            ),
            "source_snapshot_canonical_json_sha256": archive_status.get(
                "source_snapshot_canonical_json_sha256"
            ),
            "source_snapshot_observed_source_sha256": archive_status.get(
                "source_snapshot_observed_source_sha256"
            ),
            "source_snapshot_fingerprint_contract": archive_status.get(
                "source_snapshot_fingerprint_contract"
            ),
            "source_snapshot_rollback_reconstruction_verified": (
                archive_status.get(
                    "source_snapshot_rollback_reconstruction_verified"
                )
                is True
            ),
            "archive_chain_sha256": archive_chain,
            "archive_total_unique_rows": archive_total_rows,
            "target_hot_rows": len(trainer_hot_rows),
            "target_hot_max_payload_bytes": (
                COUNTERFACTUAL_VERIFIED_LATEST_ROWS_MAX_BYTES
            ),
            "target_hot_payload_bytes": sum(
                len(canonical_json(row).encode("utf-8"))
                for row in trainer_hot_rows
            ),
            "target_hot_ordered_rows_sha256": ordered_rows_sha256(
                trainer_hot_rows
            ),
            "atomic_replace": replacement_result,
            "hot_cache_readback_rows": cache_readback_rows,
            "hot_cache_readback_ordered_rows_sha256": cache_readback_digest,
            "hot_cache_readback_digest_verified": cache_readback_verified,
            "hot_cache_replace_verified": cache_replace_verified,
            "rollback_status": rollback_status,
            "no_data_loss_proven": no_data_loss_proven,
            "rollback_api": (
                "DurablePaperEvidenceArchive.source_snapshot_json_chunks"
            ),
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }
        replacement_outcome_result: dict[str, Any] = {}
        replacement_outcome_error: str | None = None
        if replacement_intent_result:
            try:
                replacement_outcome_result = archive.append_operation_receipt(
                    operation_id=f"{replacement_attempt_id}:outcome",
                    operation_kind=COUNTERFACTUAL_REPLACEMENT_OUTCOME_KIND,
                    receipt=replacement_outcome,
                    expected_archive_chain_sha256=archive_chain,
                    expected_total_unique_rows=archive_total_rows,
                )
                persisted_outcome = archive.latest_operation_receipt(
                    operation_kind=COUNTERFACTUAL_REPLACEMENT_OUTCOME_KIND
                )
                if (
                    persisted_outcome is None
                    or persisted_outcome.get("operation_id")
                    != f"{replacement_attempt_id}:outcome"
                    or persisted_outcome.get("receipt_sha256")
                    != replacement_outcome_result.get("receipt_sha256")
                ):
                    raise RuntimeError(
                        "counterfactual_replacement_outcome_readback_mismatch"
                    )
            except Exception as exc:
                replacement_outcome_error = (
                    f"{type(exc).__name__}:{str(exc)[:240]}"
                )
        verified_readiness = archive.verified_replacement_readiness(
            source_key=COUNTERFACTUAL_KEY,
        )
        snapshot_retention: dict[str, Any] = {
            "status": "NOT_PRUNED_REPLACEMENT_READINESS_UNVERIFIED",
        }
        if verified_readiness.get("readiness_verified") is True:
            try:
                snapshot_retention = {
                    "status": "INITIAL_AND_LATEST_ROLLBACK_SNAPSHOTS_RETAINED",
                    **archive.prune_verified_source_snapshots(
                        source_key=COUNTERFACTUAL_KEY,
                    ),
                }
            except Exception as exc:  # noqa: BLE001 - post-write audit status
                snapshot_retention = {
                    "status": "SNAPSHOT_RETENTION_PRUNE_FAILED",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:240],
                }
        status[
            "redis_counterfactual_string_replaced_with_bounded_hot_working_set"
        ] = cache_replace_verified
        archive_status["redis_hot_cache_write_attempted"] = cache_publish_allowed
        archive_status["redis_hot_cache_write_succeeded"] = cache_write_succeeded
        archive_status["redis_hot_cache_readback_rows"] = cache_readback_rows
        archive_status["redis_hot_cache_readback_ordered_rows_sha256"] = (
            cache_readback_digest
        )
        archive_status["redis_hot_cache_readback_digest_verified"] = (
            cache_readback_verified
        )
        archive_status["redis_hot_cache_replace_verified"] = cache_replace_verified
        archive_status["stable_source_guard"] = replacement_result
        archive_status["replacement_intent_receipt_durable"] = bool(
            replacement_intent_result.get("durable") is True
        )
        archive_status["replacement_intent_receipt_sha256"] = (
            replacement_intent_result.get("receipt_sha256")
        )
        archive_status["replacement_intent_receipt_error"] = (
            replacement_intent_error
        )
        archive_status["replacement_outcome_receipt_durable"] = bool(
            replacement_outcome_result.get("durable") is True
        )
        archive_status["replacement_outcome_receipt_sha256"] = (
            replacement_outcome_result.get("receipt_sha256")
        )
        archive_status["replacement_outcome_receipt_error"] = (
            replacement_outcome_error
        )
        archive_status["rollback_status"] = rollback_status
        archive_status["no_data_loss_proven"] = no_data_loss_proven
        archive_status["verified_replacement_readiness"] = verified_readiness
        archive_status["verified_replacement_readiness_verified"] = (
            verified_readiness.get("readiness_verified") is True
        )
        archive_status["source_snapshot_retention"] = snapshot_retention
        status["redis_publish_results"] = {
            COUNTERFACTUAL_KEY: cache_replace_verified,
            COUNTERFACTUAL_STATUS_KEY: client.set_json(COUNTERFACTUAL_STATUS_KEY, trainer_consumption),
            EDGE_FACTORY_STATUS_KEY: client.set_json(EDGE_FACTORY_STATUS_KEY, status),
            EDGE_FACTORY_SCOREBOARD_KEY: client.set_json(EDGE_FACTORY_SCOREBOARD_KEY, scoreboard),
        }
        (output_dir / "phase3_historical_replay_edge_factory_status.json").write_text(
            json.dumps(status, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (
            output_dir / "phase3_replay_to_trainer_consumption_status.json"
        ).write_text(
            json.dumps(trainer_consumption, indent=2, sort_keys=True) + "\n",
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
    counterfactual_archive_path: Path = DEFAULT_COUNTERFACTUAL_ARCHIVE_PATH,
    trainer_hot_max_rows: int = DEFAULT_MAX_TRAINING_ROWS_PER_CYCLE,
) -> None:
    while True:
        run_once(
            output_dir=output_dir,
            publish_redis=publish_redis,
            min_hold_seconds=min_hold_seconds,
            max_rows=max_rows,
            counterfactual_archive_path=counterfactual_archive_path,
            trainer_hot_max_rows=trainer_hot_max_rows,
        )
        time.sleep(max(1.0, sleep_seconds))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("goal_state") / GOAL_ID / "phase3_edge_replay_factory")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--publish-redis", action="store_true")
    parser.add_argument("--min-hold-seconds", type=int, default=900)
    parser.add_argument("--max-rows", type=int, default=500)
    parser.add_argument(
        "--counterfactual-archive-path",
        type=Path,
        default=Path(
            os.getenv(
                COUNTERFACTUAL_ARCHIVE_PATH_ENV,
                str(DEFAULT_COUNTERFACTUAL_ARCHIVE_PATH),
            )
        ),
        help="Durable SQLite archive written before the bounded Redis trainer hot set.",
    )
    parser.add_argument(
        "--trainer-hot-max-rows",
        type=int,
        default=int(os.getenv(TRAINER_HOT_MAX_ROWS_ENV, str(DEFAULT_MAX_TRAINING_ROWS_PER_CYCLE))),
        help="Operational Redis working-set cap; this is not a market admission threshold.",
    )
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
            counterfactual_archive_path=Path(args.counterfactual_archive_path),
            trainer_hot_max_rows=int(args.trainer_hot_max_rows),
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
        counterfactual_archive_path=Path(args.counterfactual_archive_path),
        trainer_hot_max_rows=int(args.trainer_hot_max_rows),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
