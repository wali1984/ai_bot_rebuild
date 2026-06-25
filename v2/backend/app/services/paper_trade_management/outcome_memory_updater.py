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
from pathlib import Path
from typing import Any

from .outcome_memory import (
    OutcomeMemoryBucket,
    OutcomeMemoryThresholds,
    evaluate_outcome_memory_bucket,
)

SCHEMA_VERSION = "v2_outcome_memory_updater_v1"
LIVE_GATE = "blocked_human_only"
ROLLING_WINDOW = 30
OUTCOME_MEMORY_PREFIX = "v2:paper:outcome_memory:"
TRUST_REQUIRED_FIELDS = (
    "prediction_id",
    "signal_id",
    "decision_id",
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
        return parsed if parsed == parsed else None
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


def _event_has_trust_evidence(event: dict[str, Any]) -> bool:
    source_hashes = event.get("source_hashes")
    if isinstance(source_hashes, str):
        try:
            source_hashes = json.loads(source_hashes)
        except (TypeError, ValueError):
            source_hashes = None
    values = {
        "prediction_id": _first_present(event.get("prediction_id"), event.get("entry_prediction_id")),
        "signal_id": _first_present(event.get("signal_id"), event.get("entry_signal_id")),
        "decision_id": _first_present(event.get("decision_id"), event.get("orchestrator_decision_id")),
        "feature_snapshot_id": _first_present(event.get("feature_snapshot_id"), event.get("entry_feature_snapshot_id")),
        "mtf_snapshot_id": event.get("mtf_snapshot_id"),
        "feature_cutoff": event.get("feature_cutoff"),
        "decision_time": event.get("decision_time"),
        "available_at": event.get("available_at"),
        "symbol": event.get("symbol"),
        "timeframe": event.get("timeframe"),
        "selected_action": _first_present(event.get("selected_action"), event.get("action"), event.get("side")),
        "model_version": event.get("model_version"),
        "checkpoint_id": event.get("checkpoint_id"),
        "source_hashes": source_hashes,
    }
    return all(values[field] not in (None, "", [], {}) for field in TRUST_REQUIRED_FIELDS) and isinstance(source_hashes, dict)


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
    return str(
        _first_present(
            event.get("generated_at"),
            event.get("generated_utc"),
            event.get("exit_price_utc"),
            event.get("exit_time"),
            event.get("closed_utc"),
        )
        or ""
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
    events.sort(key=lambda e: str(e.get("generated_at") or ""))
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
        "last_updated": "",
        "block_reason": None,
        "degraded": False,
        "degraded_since": None,
        "data_source": "REDIS",
        "trust_evidence_status": "NO_OUTCOME_ROWS",
        "outcome_memory_can_block_entries": False,
        "trusted_trade_count": 0,
        "untrusted_trade_count": 0,
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
    pnl = _event_pnl_usd(event)
    return_bps = _event_return_bps(event)
    pnl_value = 0.0 if pnl is None else pnl
    return_bps_value = 0.0 if return_bps is None else return_bps
    ts = _event_ts(event)
    generated_at = _now_iso()
    trusted_event = _event_has_trust_evidence(event)

    bucket["trade_count"] = int(bucket.get("trade_count") or bucket.get("total_trades") or 0) + 1
    bucket["total_trades"] = bucket["trade_count"]
    bucket["soak_count"] = bucket.get("soak_count", 0) + 1
    bucket["last_trade_ts"] = ts
    bucket["last_updated"] = generated_at
    bucket["data_source"] = "REDIS"
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

    bucket["drawdown_contribution_usd"] = round(
        _coerce(bucket.get("drawdown_contribution_usd")) + min(0.0, pnl_value),
        8,
    )

    recent_bps = _append_window(bucket, "recent_bps", return_bps_value)
    recent_outcomes = _append_window(bucket, "recent_outcomes", 1 if is_win else 0)
    _append_window(bucket, "recent_pnl_usd", pnl_value)

    if recent_outcomes:
        bucket["rolling_win_rate"] = round(sum(recent_outcomes) / len(recent_outcomes), 4)

    if recent_bps:
        bucket["rolling_ev_bps"] = round(sum(recent_bps) / len(recent_bps), 4)

    winners_bps = [b for b, o in zip(recent_bps, recent_outcomes) if o == 1]
    losers_bps = [b for b, o in zip(recent_bps, recent_outcomes) if o == 0]
    bucket["avg_winner_bps"] = round(sum(winners_bps) / len(winners_bps), 4) if winners_bps else None
    bucket["avg_loser_bps"] = round(sum(losers_bps) / len(losers_bps), 4) if losers_bps else None

    slippage_failed = _event_slippage_failure(event)
    if slippage_failed is not None:
        failures = _append_window(bucket, "recent_slippage_failures", 1 if slippage_failed else 0)
        bucket["slippage_failure_rate"] = _rate([int(v) for v in failures])

    reversed_after_entry = _event_reversal_after_entry(event)
    if reversed_after_entry is not None:
        reversals = _append_window(bucket, "recent_reversal_after_entry", 1 if reversed_after_entry else 0)
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
    evaluation = evaluate_outcome_memory_bucket(
        OutcomeMemoryBucket.from_dict(bucket),
        OutcomeMemoryThresholds(),
    )
    if evaluation.get("blocked"):
        bucket["degraded"] = True
        bucket["block_reason"] = ";".join(str(r) for r in evaluation.get("reasons", []))
        bucket["degraded_since"] = prior_degraded_since or generated_at

    return bucket


def _safe_load_json(raw: Any) -> Any:
    if raw in (None, ""):
        return None
    if isinstance(raw, (dict, list)):
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
    rows.sort(key=_event_ts)
    return rows


def build_outcome_memory_buckets_from_closed_trades(
    closed_trade_rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build canonical entry-gate-readable buckets from already-closed paper trades."""
    grouped: dict[str, dict[str, Any]] = {}
    for row in sorted(closed_trade_rows, key=_event_ts):
        symbol = str(row.get("symbol") or "").upper().strip()
        timeframe = str(row.get("timeframe") or "1m").lower().strip()
        if not symbol or _event_pnl_usd(row) is None:
            continue
        for bucket_symbol, scope in ((symbol, "symbol_timeframe"), ("__ALL__", "timeframe_aggregate")):
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
    events_processed = sum(
        1
        for row in closed_trade_rows
        if str(row.get("symbol") or "").strip() and _event_pnl_usd(row) is not None
    )
    if write:
        if redis_client is None:
            errors.append("WRITE_REQUESTED_WITHOUT_REDIS_CLIENT")
        else:
            for key, bucket in buckets.items():
                try:
                    redis_client.set(key, json.dumps(bucket))
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{key}: {exc}")

    degraded = [bucket for bucket in buckets.values() if bucket.get("degraded") or bucket.get("block_reason")]
    trade_counts = {key: int(bucket.get("trade_count") or 0) for key, bucket in buckets.items()}
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "source": "v2:paper:closed_trades+v2:paper:ledger",
        "closed_trade_rows_seen": len(closed_trade_rows),
        "events_processed": events_processed,
        "skipped_rows": max(0, len(closed_trade_rows) - events_processed),
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
        events = [e for e in events if _parse_ts_float(str(e.get("generated_at") or "")) >= since_ts]

    buckets_updated: dict[str, int] = {}
    errors: list[str] = []

    for event in events:
        sym = str(event.get("symbol") or "").upper()
        tf = str(event.get("timeframe") or "1m").lower()
        if not sym:
            continue

        key = _bucket_key(sym, tf)
        try:
            bucket = _load_bucket(redis_client, key)
            bucket["symbol"] = sym
            bucket["timeframe"] = tf
            bucket = _update_bucket(bucket, event)
            redis_client.set(key, json.dumps(bucket))
            buckets_updated[key] = buckets_updated.get(key, 0) + 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{key}: {exc}")

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "events_processed": len(events),
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
    if not text:
        return 0.0
    try:
        import datetime as dt
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = dt.datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.timestamp()
    except Exception:  # noqa: BLE001
        return 0.0


def _now_iso() -> str:
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
