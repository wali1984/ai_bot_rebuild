"""Outcome memory updater — updates 12 Redis outcome memory stores from closed paper trades.

Reads closed paper events from paper_events.jsonl and writes outcome memory
buckets to Redis using the v2: prefix. Each bucket tracks rolling stats that
entry_gate and high_precision_gate read to make dynamic allow/block decisions.

12 memory store types (per symbol/TF bucket):
1.  total_trades
2.  win_count
3.  loss_count
4.  rolling_win_rate (last 30 trades)
5.  rolling_ev_bps (expected value per trade)
6.  avg_winner_bps
7.  avg_loser_bps
8.  max_drawdown_bps
9.  consecutive_losses
10. last_trade_ts
11. degraded (bool: rolling WR < 40% or rolling EV < -5bps)
12. soak_count (total trades ever seen in this bucket)

All writes: v2:paper:outcome_memory prefix.
No exchange mutation. No legacy Redis writes.
Live gate: blocked_human_only.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .outcome_memory import (
    OutcomeMemoryBucket,
    OutcomeMemoryThresholds,
    evaluate_outcome_memory_bucket,
)

SCHEMA_VERSION = "v2_outcome_memory_updater_v2"
LIVE_GATE = "blocked_human_only"
ROLLING_WINDOW = 30
OUTCOME_MEMORY_PREFIX = "v2:paper:outcome_memory:"
TRUST_VALIDATION_VERSION = "OUTCOME_MEMORY_TRUST_PIT_V2"
TRUST_REQUIRED_FIELDS = (
    "prediction_id",
    "signal_id",
    "risk_decision_id",
    "orchestrator_decision_id",
    "feature_snapshot_id",
    "mtf_snapshot_id",
    "feature_cutoff",
    "decision_time",
    "available_at",
    "symbol",
    "timeframe",
    "selected_action",
    "model_version",
    "checkpoint_id",
    "source_hashes",
)
_TRUST_IDENTIFIER_FIELDS = (
    "prediction_id",
    "signal_id",
    "risk_decision_id",
    "orchestrator_decision_id",
    "feature_snapshot_id",
    "mtf_snapshot_id",
    "model_version",
    "checkpoint_id",
)
_INVALID_IDENTIFIER_TOKENS = frozenset(
    {"none", "null", "unknown", "missing", "n/a", "na", "undefined"}
)
_REQUIRED_CANONICAL_SOURCE_HASH_KEYS = ("feature_vector_hash",)
_CLOSE_EVENT_TIME_FIELDS = (
    "exit_price_utc",
    "exit_time",
    "close_execution_time",
    "exit_execution_time",
    "closed_utc",
    "closed_at",
)
_OUTCOME_AVAILABLE_AT_FIELDS = (
    "outcome_available_at",
    "close_available_at",
    "exit_available_at",
    "closed_available_at",
)


def _coerce(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _float_or_none(v: Any) -> float | None:
    try:
        if isinstance(v, bool) or v is None or v == "":
            return None
        parsed = float(v)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def _bool_or_none(v: Any) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        lowered = v.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _parse_aware_utc(value: Any) -> datetime | None:
    """Parse an explicitly timezone-aware timestamp and normalize it to UTC."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _event_close_time(event: Mapping[str, Any]) -> tuple[datetime | None, str | None]:
    for field in _CLOSE_EVENT_TIME_FIELDS:
        raw = event.get(field)
        if raw not in (None, ""):
            return _parse_aware_utc(raw), field
    return None, None


def _event_outcome_available_at(
    event: Mapping[str, Any],
    *,
    close_time: datetime | None = None,
) -> tuple[datetime | None, str | None]:
    for field in _OUTCOME_AVAILABLE_AT_FIELDS:
        raw = event.get(field)
        if raw not in (None, ""):
            return _parse_aware_utc(raw), field
    # The canonical close producer currently emits the synchronous close
    # execution timestamp but no separate outcome-availability field.  That
    # timestamp is the earliest honest availability bound.  Keep it in a
    # distinct field and source label; never substitute rebuild/generated time.
    if close_time is None:
        close_time, _source = _event_close_time(event)
    return close_time, "CLOSE_EVENT_TIME_SYNCHRONOUS_AVAILABILITY_FALLBACK"


def _source_hashes(event: Mapping[str, Any]) -> Mapping[str, Any] | None:
    source_hashes = event.get("source_hashes")
    if isinstance(source_hashes, str):
        try:
            source_hashes = json.loads(source_hashes)
        except (TypeError, ValueError):
            source_hashes = None
    return source_hashes if isinstance(source_hashes, Mapping) else None


def _trust_values(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "prediction_id": _first_present(
            event.get("prediction_id"), event.get("entry_prediction_id")
        ),
        "signal_id": _first_present(
            event.get("signal_id"), event.get("entry_signal_id")
        ),
        "risk_decision_id": _first_present(
            event.get("risk_decision_id"), event.get("risk_id")
        ),
        "orchestrator_decision_id": _first_present(
            event.get("orchestrator_decision_id"), event.get("decision_id")
        ),
        "feature_snapshot_id": _first_present(
            event.get("feature_snapshot_id"),
            event.get("entry_feature_snapshot_id"),
        ),
        "mtf_snapshot_id": event.get("mtf_snapshot_id"),
        "feature_cutoff": event.get("feature_cutoff"),
        "decision_time": event.get("decision_time"),
        "available_at": event.get("available_at"),
        "symbol": event.get("symbol"),
        "timeframe": event.get("timeframe"),
        "selected_action": _first_present(
            event.get("selected_action"), event.get("action"), event.get("side")
        ),
        "model_version": event.get("model_version"),
        "checkpoint_id": event.get("checkpoint_id"),
        "source_hashes": _source_hashes(event),
    }


def _valid_identifier(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    return value.strip().lower() not in _INVALID_IDENTIFIER_TOKENS


def _event_trust_rejection_reasons(
    event: Mapping[str, Any],
    *,
    close_time: datetime | None,
) -> list[str]:
    values = _trust_values(event)
    reasons: list[str] = []
    for field in TRUST_REQUIRED_FIELDS:
        if values.get(field) in (None, "", [], {}):
            reasons.append(f"MISSING_TRUST_FIELD:{field}")
    for field in _TRUST_IDENTIFIER_FIELDS:
        value = values.get(field)
        if value not in (None, "") and not _valid_identifier(value):
            reasons.append(f"INVALID_TRUST_IDENTIFIER:{field}")

    source_hashes = values.get("source_hashes")
    if source_hashes not in (None, {}):
        if not isinstance(source_hashes, Mapping):
            reasons.append("SOURCE_HASHES_NOT_MAPPING")
        else:
            for required_hash_key in _REQUIRED_CANONICAL_SOURCE_HASH_KEYS:
                if not _valid_identifier(source_hashes.get(required_hash_key)):
                    reasons.append(
                        f"MISSING_CANONICAL_SOURCE_HASH:{required_hash_key}"
                    )
            for key, value in source_hashes.items():
                if not _valid_identifier(key) or not _valid_identifier(value):
                    reasons.append("SOURCE_HASHES_INVALID_KEY_OR_VALUE")
                    break
                top_level_value = event.get(str(key))
                if top_level_value not in (None, "") and str(top_level_value) != str(value):
                    reasons.append(f"SOURCE_HASH_CONFLICT:{key}")

    action = str(values.get("selected_action") or "").strip().lower()
    if action not in {"long", "short"}:
        reasons.append("SELECTED_ACTION_NOT_DIRECTIONAL")
    side = str(event.get("side") or "").strip().lower()
    if side in {"long", "short"} and action in {"long", "short"} and side != action:
        reasons.append("SELECTED_ACTION_SIDE_MISMATCH")

    feature_cutoff = _parse_aware_utc(values.get("feature_cutoff"))
    feature_available_at = _parse_aware_utc(values.get("available_at"))
    decision_time = _parse_aware_utc(values.get("decision_time"))
    for field, parsed in (
        ("feature_cutoff", feature_cutoff),
        ("available_at", feature_available_at),
        ("decision_time", decision_time),
    ):
        if values.get(field) not in (None, "") and parsed is None:
            reasons.append(f"TRUST_TIMESTAMP_NOT_AWARE_UTC:{field}")
    if feature_available_at is not None and decision_time is not None:
        if feature_available_at > decision_time:
            reasons.append("FEATURE_AVAILABLE_AT_AFTER_DECISION_TIME")
    if feature_cutoff is not None and decision_time is not None:
        if feature_cutoff > decision_time:
            reasons.append("FEATURE_CUTOFF_AFTER_DECISION_TIME")
    if decision_time is not None and close_time is not None and decision_time > close_time:
        reasons.append("DECISION_TIME_AFTER_CLOSE_EVENT")

    entry_time_raw = _first_present(
        event.get("entry_time"),
        event.get("entry_execution_time"),
    )
    if entry_time_raw not in (None, ""):
        entry_time = _parse_aware_utc(entry_time_raw)
        if entry_time is None:
            reasons.append("ENTRY_EXECUTION_TIME_NOT_AWARE_UTC")
        else:
            if decision_time is not None and decision_time > entry_time:
                reasons.append("DECISION_TIME_AFTER_ENTRY_EXECUTION_TIME")
            if close_time is not None and entry_time > close_time:
                reasons.append("ENTRY_EXECUTION_TIME_AFTER_CLOSE_EVENT")
    return sorted(set(reasons))


def _event_rejection_reasons(
    event: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> list[str]:
    reasons: list[str] = []
    if not str(event.get("symbol") or "").strip():
        reasons.append("MISSING_SYMBOL")
    if not str(event.get("timeframe") or "").strip():
        reasons.append("MISSING_TIMEFRAME")
    pnl_usd = _event_pnl_usd(dict(event))
    return_bps = _event_return_bps(dict(event))
    if pnl_usd is None:
        reasons.append("MISSING_OR_NONFINITE_REALIZED_PNL_USD")
    if return_bps is None:
        reasons.append("MISSING_OR_NONFINITE_REALIZED_RETURN_BPS")
    if pnl_usd is not None and return_bps is not None and pnl_usd * return_bps < 0.0:
        reasons.append("REALIZED_PNL_RETURN_SIGN_MISMATCH")

    close_time, close_source = _event_close_time(event)
    if close_source is None:
        reasons.append("MISSING_ACTUAL_CLOSE_EVENT_TIME")
    elif close_time is None:
        reasons.append("CLOSE_EVENT_TIME_NOT_AWARE_UTC")
    outcome_available_at, outcome_available_source = _event_outcome_available_at(
        event,
        close_time=close_time,
    )
    if outcome_available_source is None:
        reasons.append("MISSING_OUTCOME_AVAILABLE_AT")
    elif outcome_available_at is None:
        reasons.append("OUTCOME_AVAILABLE_AT_NOT_AWARE_UTC")
    if close_time is not None and outcome_available_at is not None:
        if outcome_available_at < close_time:
            reasons.append("OUTCOME_AVAILABLE_AT_BEFORE_CLOSE_EVENT")
        effective_now = (now or datetime.now(UTC)).astimezone(UTC)
        if close_time > effective_now:
            reasons.append("CLOSE_EVENT_TIME_IN_FUTURE")
        if outcome_available_at > effective_now:
            reasons.append("OUTCOME_AVAILABLE_AT_IN_FUTURE")

    reasons.extend(_event_trust_rejection_reasons(event, close_time=close_time))
    return sorted(set(reasons))


def _event_has_trust_evidence(event: dict[str, Any]) -> bool:
    return not _event_rejection_reasons(event)


def _event_pnl_usd(event: dict[str, Any]) -> float | None:
    return _float_or_none(
        _first_present(
            event.get("realized_delta_usdt"),
            event.get("realized_pnl_usd"),
            event.get("realized_pnl_usdt"),
            event.get("net_realized_pnl_usd"),
            event.get("net_pnl_usd"),
            event.get("realized_pnl"),
        )
    )


def _event_return_bps(event: dict[str, Any]) -> float | None:
    return _float_or_none(
        _first_present(
            event.get("current_return_bps"),
            event.get("realized_pnl_bps"),
            event.get("return_bps"),
            event.get("net_return_bps"),
        )
    )


def _event_ts(event: dict[str, Any]) -> str:
    close_time, _source = _event_close_time(event)
    return _utc_iso(close_time) if close_time is not None else ""


def _event_sort_key(event: dict[str, Any]) -> tuple[int, datetime, str]:
    close_time, _source = _event_close_time(event)
    if close_time is None:
        return (1, datetime.max.replace(tzinfo=UTC), repr(sorted(event.keys())))
    return (
        0,
        close_time,
        str(_first_present(event.get("close_id"), event.get("position_id"), "")),
    )


def _event_slippage_failure(event: dict[str, Any]) -> bool | None:
    expected = _float_or_none(
        _first_present(
            event.get("expected_slippage_bps"),
            event.get("expected_slippage_estimate_bps"),
        )
    )
    realized = _float_or_none(
        _first_present(
            event.get("realized_slippage_bps"),
            event.get("actual_slippage_bps"),
        )
    )
    if expected is None or realized is None:
        return None
    return realized > expected


def _event_reversal_after_entry(event: dict[str, Any]) -> bool | None:
    return _bool_or_none(
        _first_present(
            event.get("reversal_after_entry"),
            event.get("reversed_after_entry"),
            event.get("reversal_after_entry_within_2_candles"),
        )
    )


def _event_missed_tp_then_stop(event: dict[str, Any]) -> bool | None:
    return _bool_or_none(
        _first_present(
            event.get("missed_tp_then_stop"),
            event.get("missed_take_profit_then_stop"),
            event.get("near_tp_then_stop"),
        )
    )


def _load_closed_events(jsonl_path: Path) -> list[dict]:
    events = []
    try:
        with jsonl_path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    ev = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if ev.get("paper_result") == "POSITION_CLOSED_PAPER_ONLY":
                    events.append(ev)
    except OSError:
        pass
    events.sort(key=_event_sort_key)
    return events


def _bucket_key(symbol: str, timeframe: str) -> str:
    return f"{OUTCOME_MEMORY_PREFIX}{symbol.upper()}:{timeframe.lower()}"


def _empty_bucket() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "symbol": "",
        "timeframe": "",
        "trade_count": 0,
        "total_trades": 0,
        "win_count": 0,
        "loss_count": 0,
        "rolling_win_rate": None,
        "rolling_ev_bps": None,
        "avg_winner_bps": None,
        "avg_loser_bps": None,
        "drawdown_contribution_usd": 0.0,
        "max_drawdown_bps": 0.0,
        "slippage_failure_rate": None,
        "reversal_after_entry_rate": None,
        "missed_tp_then_stop_rate": None,
        "consecutive_losses": 0,
        "last_trade_ts": None,
        "last_outcome_event_time": None,
        "last_outcome_event_time_source": None,
        "last_outcome_available_at": None,
        "last_outcome_available_at_source": None,
        "last_updated": "",
        "last_updated_source": "OUTCOME_MEMORY_PROCESSING_TIME_NOT_EVIDENCE_FRESHNESS",
        "block_reason": None,
        "degraded": False,
        "degraded_since": None,
        "data_source": "REDIS",
        "trust_evidence_status": "NO_OUTCOME_ROWS",
        "outcome_memory_can_block_entries": False,
        "trusted_trade_count": 0,
        "untrusted_trade_count": 0,
        "trust_validation_version": TRUST_VALIDATION_VERSION,
        "baseline_advisory_reasons": [],
        "baseline_evidence_date": None,
        "baseline_trade_count": 0,
        "soak_count": 0,
        "recent_bps": [],
        "recent_outcomes": [],
        "recent_pnl_usd": [],
        "recent_slippage_failures": [],
        "recent_reversal_after_entry": [],
        "recent_missed_tp_then_stop": [],
    }


def _load_bucket(redis_client: Any, key: str) -> dict:
    default = _empty_bucket()
    try:
        raw = redis_client.get(key)
        if raw:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                bucket = {**default, **loaded}
                bucket["trade_count"] = int(
                    bucket.get("trade_count")
                    if bucket.get("trade_count") is not None
                    else bucket.get("total_trades")
                    or 0
                )
                bucket["total_trades"] = int(bucket.get("total_trades") or bucket["trade_count"])
                return bucket
    except Exception:  # noqa: BLE001
        pass
    return default


def _append_window(bucket: dict[str, Any], key: str, value: float | int | bool) -> list:
    values = list(bucket.get(key) or [])
    values.append(value)
    if len(values) > ROLLING_WINDOW:
        values = values[-ROLLING_WINDOW:]
    bucket[key] = values
    return values


def _rate(values: list[int]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _update_bucket(bucket: dict, event: dict) -> dict:
    rejection_reasons = _event_rejection_reasons(event)
    if rejection_reasons:
        raise ValueError("INVALID_OUTCOME_EVENT:" + ",".join(rejection_reasons))
    pnl = _event_pnl_usd(event)
    return_bps = _event_return_bps(event)
    # Validation above makes these assertions data-contract facts. Required
    # economic values are never zero-filled because zero is a real outcome.
    assert pnl is not None
    assert return_bps is not None
    pnl_value = pnl
    return_bps_value = return_bps
    close_time, close_time_source = _event_close_time(event)
    assert close_time is not None
    outcome_available_at, outcome_available_at_source = _event_outcome_available_at(
        event,
        close_time=close_time,
    )
    assert outcome_available_at is not None
    ts = _utc_iso(close_time)
    outcome_available_ts = _utc_iso(outcome_available_at)
    generated_at = _now_iso()
    trusted_event = _event_has_trust_evidence(event)

    bucket["trade_count"] = int(bucket.get("trade_count") or bucket.get("total_trades") or 0) + 1
    bucket["total_trades"] = bucket["trade_count"]
    bucket["soak_count"] = bucket.get("soak_count", 0) + 1
    bucket["last_trade_ts"] = ts
    bucket["last_outcome_event_time"] = ts
    bucket["last_outcome_event_time_source"] = close_time_source
    bucket["last_outcome_available_at"] = outcome_available_ts
    bucket["last_outcome_available_at_source"] = outcome_available_at_source
    bucket["last_updated"] = generated_at
    bucket["last_updated_source"] = (
        "OUTCOME_MEMORY_PROCESSING_TIME_NOT_EVIDENCE_FRESHNESS"
    )
    bucket["data_source"] = "REDIS"
    bucket["trust_validation_version"] = TRUST_VALIDATION_VERSION
    if trusted_event:
        bucket["trusted_trade_count"] = int(bucket.get("trusted_trade_count") or 0) + 1
    else:
        bucket["untrusted_trade_count"] = int(bucket.get("untrusted_trade_count") or 0) + 1
    trusted_count = int(bucket.get("trusted_trade_count") or 0)
    untrusted_count = int(bucket.get("untrusted_trade_count") or 0)
    if trusted_count > 0 and untrusted_count == 0:
        bucket["trust_evidence_status"] = "TRUSTED_OUTCOME_MEMORY"
        bucket["outcome_memory_can_block_entries"] = True
    elif trusted_count > 0:
        bucket["trust_evidence_status"] = "MIXED_TRUST_OUTCOME_MEMORY_ADVISORY"
        bucket["outcome_memory_can_block_entries"] = False
    else:
        bucket["trust_evidence_status"] = "UNVERIFIED_CLOSED_TRADE_OUTCOMES_ADVISORY"
        bucket["outcome_memory_can_block_entries"] = False

    is_win = pnl_value > 0
    if is_win:
        bucket["win_count"] = bucket.get("win_count", 0) + 1
        bucket["consecutive_losses"] = 0
    else:
        bucket["loss_count"] = bucket.get("loss_count", 0) + 1
        bucket["consecutive_losses"] = bucket.get("consecutive_losses", 0) + 1

    recent_bps = _append_window(bucket, "recent_bps", return_bps_value)
    recent_outcomes = _append_window(bucket, "recent_outcomes", 1 if is_win else 0)
    recent_pnl_usd = _append_window(bucket, "recent_pnl_usd", pnl_value)

    # Compatibility field, now an honest rolling peak-to-trough drawdown
    # rather than a lifetime sum of every losing trade. A profitable bucket
    # can recover as its rolling equity curve makes new highs.
    pnl_cumulative = 0.0
    pnl_peak = 0.0
    rolling_max_drawdown_usd = 0.0
    for realized_pnl in recent_pnl_usd:
        pnl_cumulative += float(realized_pnl)
        pnl_peak = max(pnl_peak, pnl_cumulative)
        rolling_max_drawdown_usd = max(
            rolling_max_drawdown_usd,
            pnl_peak - pnl_cumulative,
        )
    bucket["drawdown_contribution_usd"] = round(-rolling_max_drawdown_usd, 8)
    bucket["rolling_max_drawdown_usd"] = round(rolling_max_drawdown_usd, 8)
    bucket["drawdown_evidence_policy"] = (
        "ROLLING_PEAK_TO_TROUGH_DIAGNOSTIC_NO_LIFETIME_USD_HARD_BLOCK"
    )

    if recent_outcomes:
        bucket["rolling_win_rate"] = round(sum(recent_outcomes) / len(recent_outcomes), 4)

    if recent_bps:
        bucket["rolling_ev_bps"] = round(sum(recent_bps) / len(recent_bps), 4)

    winners_bps = [
        b for b, o in zip(recent_bps, recent_outcomes, strict=False) if o == 1
    ]
    losers_bps = [
        b for b, o in zip(recent_bps, recent_outcomes, strict=False) if o == 0
    ]
    bucket["avg_winner_bps"] = (
        round(sum(winners_bps) / len(winners_bps), 4) if winners_bps else None
    )
    bucket["avg_loser_bps"] = (
        round(sum(losers_bps) / len(losers_bps), 4) if losers_bps else None
    )

    slippage_failed = _event_slippage_failure(event)
    if slippage_failed is not None:
        failures = _append_window(bucket, "recent_slippage_failures", 1 if slippage_failed else 0)
        bucket["slippage_failure_rate"] = _rate([int(v) for v in failures])

    reversed_after_entry = _event_reversal_after_entry(event)
    if reversed_after_entry is not None:
        reversals = _append_window(
            bucket,
            "recent_reversal_after_entry",
            1 if reversed_after_entry else 0,
        )
        bucket["reversal_after_entry_rate"] = _rate([int(v) for v in reversals])

    missed_tp = _event_missed_tp_then_stop(event)
    if missed_tp is not None:
        missed = _append_window(bucket, "recent_missed_tp_then_stop", 1 if missed_tp else 0)
        bucket["missed_tp_then_stop_rate"] = _rate([int(v) for v in missed])

    # Max drawdown over the rolling window
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for b in recent_bps:
        cum += b
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd
    bucket["max_drawdown_bps"] = round(max_dd, 4)

    prior_degraded_since = bucket.get("degraded_since")
    bucket["degraded"] = False
    bucket["block_reason"] = None
    bucket["degraded_since"] = None

    # Compute degraded status directly from rolling stats when enough trades exist.
    # This runs regardless of outcome_memory_can_block_entries so that untrusted
    # (advisory) buckets with clear WR/EV failures still surface as degraded.
    thresholds = OutcomeMemoryThresholds()
    trade_count = int(bucket.get("trade_count") or 0)
    if trade_count >= thresholds.min_trade_count_for_dynamic:
        block_parts: list[str] = []
        wr = bucket.get("rolling_win_rate")
        if wr is not None and wr < thresholds.min_win_rate:
            block_parts.append(f"WIN_RATE_DEGRADED:{wr:.2%}<{thresholds.min_win_rate:.2%}")
        ev = bucket.get("rolling_ev_bps")
        if ev is not None and ev < thresholds.min_rolling_ev_bps:
            block_parts.append(f"ROLLING_EV_DEGRADED:{ev:.2f}<{thresholds.min_rolling_ev_bps:.2f}")
        if block_parts:
            bucket["degraded"] = True
            bucket["block_reason"] = ";".join(block_parts)
            bucket["degraded_since"] = prior_degraded_since or outcome_available_ts

    # Call evaluator as secondary confirmation (honours pre-set degraded state).
    evaluation = evaluate_outcome_memory_bucket(
        OutcomeMemoryBucket.from_dict(bucket),
        thresholds,
    )
    if evaluation.get("blocked") and not bucket["degraded"]:
        bucket["degraded"] = True
        bucket["block_reason"] = ";".join(str(r) for r in evaluation.get("reasons", []))
        bucket["degraded_since"] = prior_degraded_since or outcome_available_ts

    return bucket


def _safe_load_json(raw: Any) -> Any:
    if raw in (None, ""):
        return None
    if isinstance(raw, dict | list):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _rows_from_payload(payload: Any, keys: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    if not keys:
        keys = ("closed_trades", "closed", "closes", "closed_positions", "outcome_labels", "rows")
    for key in keys:
        rows = payload.get(key)
        if isinstance(rows, list):
            return [dict(row) for row in rows if isinstance(row, dict)]
    return []


def _row_identity(row: dict[str, Any]) -> str:
    return str(
        _first_present(
            row.get("close_id"),
            row.get("outcome_label_id"),
            row.get("trainer_feedback_id"),
            row.get("position_id"),
            row.get("fill_id"),
            row.get("ledger_row_id"),
            f"{row.get('symbol')}|{row.get('timeframe')}|{row.get('side')}|"
            f"{row.get('entry_price')}|{row.get('exit_price')}|{_event_ts(row)}",
        )
    )


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        identity = _row_identity(row)
        if identity in seen:
            continue
        seen.add(identity)
        out.append(row)
    return out


def load_closed_trade_rows_from_redis(redis_client: Any) -> list[dict[str, Any]]:
    """Read current V2 paper closed-trade evidence from Redis.

    This is for runtime outcome-memory recovery only. It is not a replay/training
    data loader and must not be used to construct historical PIT samples.
    """
    rows: list[dict[str, Any]] = []
    try:
        rows.extend(_rows_from_payload(_safe_load_json(redis_client.get("v2:paper:closed_trades"))))
    except Exception:  # noqa: BLE001
        pass
    try:
        ledger = _safe_load_json(redis_client.get("v2:paper:ledger"))
        rows.extend(
            _rows_from_payload(
                ledger,
                keys=("closed_trades", "closed", "closes", "closed_positions", "outcome_labels"),
            )
        )
    except Exception:  # noqa: BLE001
        pass
    rows = _dedupe_rows(rows)
    rows.sort(key=_event_sort_key)
    return rows


def build_outcome_memory_buckets_from_closed_trades(
    closed_trade_rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build canonical entry-gate-readable buckets from already-closed paper trades."""
    grouped: dict[str, dict[str, Any]] = {}
    for row in sorted(closed_trade_rows, key=_event_sort_key):
        if _event_rejection_reasons(row):
            continue
        symbol = str(row.get("symbol") or "").upper().strip()
        timeframe = str(row.get("timeframe") or "").lower().strip()
        for bucket_symbol, scope in (
            (symbol, "symbol_timeframe"),
            ("__ALL__", "timeframe_aggregate"),
        ):
            key = _bucket_key(bucket_symbol, timeframe)
            bucket = grouped.get(key)
            if bucket is None:
                bucket = _empty_bucket()
                bucket["symbol"] = bucket_symbol
                bucket["timeframe"] = timeframe
                bucket["bucket_scope"] = scope
                grouped[key] = bucket
            _update_bucket(bucket, row)
    return grouped


def rebuild_outcome_memory_from_closed_trades(
    *,
    closed_trade_rows: list[dict[str, Any]],
    redis_client: Any | None = None,
    write: bool = False,
) -> dict[str, Any]:
    """Rebuild paper outcome-memory buckets from closed trades.

    The default is a dry-run summary. Write mode only writes
    v2:paper:outcome_memory:{symbol}:{timeframe}; it never touches exchange
    paths or legacy Redis prefixes.
    """
    buckets = build_outcome_memory_buckets_from_closed_trades(closed_trade_rows)
    errors: list[str] = []
    rejection_reason_counts: Counter[str] = Counter()
    events_processed = 0
    for row in closed_trade_rows:
        rejection_reasons = _event_rejection_reasons(row)
        if rejection_reasons:
            rejection_reason_counts.update(rejection_reasons)
        else:
            events_processed += 1
    if write:
        if redis_client is None:
            errors.append("WRITE_REQUESTED_WITHOUT_REDIS_CLIENT")
        else:
            for key, bucket in buckets.items():
                try:
                    redis_client.set(key, json.dumps(bucket))
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{key}: {exc}")

    degraded = [
        bucket
        for bucket in buckets.values()
        if bucket.get("degraded") or bucket.get("block_reason")
    ]
    trade_counts = {key: int(bucket.get("trade_count") or 0) for key, bucket in buckets.items()}
    quarantined_rows = max(0, len(closed_trade_rows) - events_processed)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "source": "v2:paper:closed_trades+v2:paper:ledger",
        "closed_trade_rows_seen": len(closed_trade_rows),
        "events_processed": events_processed,
        "skipped_rows": quarantined_rows,
        "quarantined_rows": quarantined_rows,
        "trust_coverage_complete": quarantined_rows == 0,
        "governance_evidence_policy": "STRICT_PIT_VALID_ROWS_ONLY",
        "rejection_reason_counts": dict(sorted(rejection_reason_counts.items())),
        "trust_validation_version": TRUST_VALIDATION_VERSION,
        "buckets_updated": len(buckets) if write and not errors else 0,
        "bucket_count": len(buckets),
        "degraded_bucket_count": len(degraded),
        "bucket_keys": list(buckets.keys()),
        "trade_counts_per_bucket": trade_counts,
        "sample_degraded_buckets": degraded[:10],
        "dry_run": not write,
        "writes_redis": bool(write and not errors),
        "mutates_exchange": False,
        "places_real_order": False,
        "writes_old_redis": False,
        "live_gate": LIVE_GATE,
        "errors": errors,
    }


def rebuild_outcome_memory_from_redis(
    *,
    redis_client: Any,
    write: bool = False,
) -> dict[str, Any]:
    rows = load_closed_trade_rows_from_redis(redis_client)
    return rebuild_outcome_memory_from_closed_trades(
        closed_trade_rows=rows,
        redis_client=redis_client,
        write=write,
    )


def update_outcome_memory(
    *,
    jsonl_path: Path,
    redis_client: Any,
    since_ts: float | None = None,
) -> dict[str, Any]:
    """Read closed events from jsonl_path and update Redis outcome memory buckets.

    Returns a summary of what was updated.
    """
    events = _load_closed_events(jsonl_path)
    if since_ts is not None:
        events = [
            event
            for event in events
            if not _event_ts(event) or _parse_ts_float(_event_ts(event)) >= since_ts
        ]

    buckets_updated: dict[str, int] = {}
    errors: list[str] = []
    rejection_reason_counts: Counter[str] = Counter()
    events_processed = 0

    for event in events:
        rejection_reasons = _event_rejection_reasons(event)
        if rejection_reasons:
            rejection_reason_counts.update(rejection_reasons)
            continue
        sym = str(event.get("symbol") or "").upper()
        tf = str(event.get("timeframe") or "").lower()

        key = _bucket_key(sym, tf)
        try:
            bucket = _load_bucket(redis_client, key)
            bucket["symbol"] = sym
            bucket["timeframe"] = tf
            bucket = _update_bucket(bucket, event)
            redis_client.set(key, json.dumps(bucket))
            buckets_updated[key] = buckets_updated.get(key, 0) + 1
            events_processed += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{key}: {exc}")

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "events_seen": len(events),
        "events_processed": events_processed,
        "quarantined_rows": len(events) - events_processed - len(errors),
        "trust_coverage_complete": not rejection_reason_counts and not errors,
        "governance_evidence_policy": "STRICT_PIT_VALID_ROWS_ONLY",
        "rejection_reason_counts": dict(sorted(rejection_reason_counts.items())),
        "trust_validation_version": TRUST_VALIDATION_VERSION,
        "buckets_updated": len(buckets_updated),
        "bucket_keys": list(buckets_updated.keys()),
        "trade_counts_per_bucket": buckets_updated,
        "errors": errors,
        "live_gate": LIVE_GATE,
        "mutates_exchange": False,
        "writes_old_redis": False,
    }


def get_bucket_summary(*, redis_client: Any, symbol: str, timeframe: str) -> dict:
    """Return a single bucket's current state (for diagnostics/GUI)."""
    key = _bucket_key(symbol, timeframe)
    return _load_bucket(redis_client, key)


def _parse_ts_float(text: str) -> float:
    parsed = _parse_aware_utc(text)
    return parsed.timestamp() if parsed is not None else 0.0


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
