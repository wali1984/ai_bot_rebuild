"""Adversarial microstructure feed-quality and trust monitor.

Public market data only. Writes only ``v2:microstructure:*`` keys when Redis
output is enabled. It never places, tests, cancels, or modifies exchange orders.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Mapping

from v2.backend.app.services.microstructure_trust.cross_venue_confirmation import (
    evaluate_cross_venue_confirmation,
)
from v2.backend.app.services.microstructure_trust.feed_quality import (
    evaluate_feed_quality,
    iso_now,
    summarize_feed_quality,
)
from v2.backend.app.services.microstructure_trust.liquidation_sweep_detector import (
    detect_liquidation_sweep,
)
from v2.backend.app.services.microstructure_trust.orderbook_adversarial_features import (
    compute_orderbook_adversarial_features,
)
from v2.backend.app.services.microstructure_trust.status import (
    GOAL_ID,
    LIVE_GATE,
    public_orderbook_trust_policy_status,
    write_status_artifacts,
)
from v2.backend.app.services.microstructure_trust.trade_tape_confirmation import (
    evaluate_trade_tape_confirmation,
)
from v2.backend.app.services.microstructure_trust.trust_score import score_microstructure_trust
from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_REPLAY_ROOT = REPO_ROOT / "v2/runtime/orderbook_replay"
MICROSTRUCTURE_SUPERVISOR_STATUS_PATH = (
    REPO_ROOT
    / "v2/frontend/public/operator_runtime/v2_microstructure_runtime_supervisor/latest/status.json"
)
V2_REDIS_PREFIX = "v2:"
MICROSTRUCTURE_REDIS_PREFIX = f"{V2_REDIS_PREFIX}microstructure:"
STATUS_WORKER_ID = "v2_microstructure_feed_quality_monitor"
REDIS_TTL_SECONDS = 60


def _float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and out not in (float("inf"), float("-inf")) else None


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _load_provider_symbol_support() -> dict[str, Any]:
    try:
        payload = json.loads(MICROSTRUCTURE_SUPERVISOR_STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    candidates: list[Any] = [
        payload.get("provider_filter_status"),
        payload.get("kucoin_provider_filter_status"),
    ]
    plan = payload.get("plan")
    if isinstance(plan, Mapping):
        candidates.extend(
            [
                plan.get("provider_filter_status"),
                plan.get("kucoin_provider_filter_status"),
            ]
        )
    merged: dict[str, Any] = {}
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        support = candidate.get("provider_symbol_support")
        if not isinstance(support, Mapping):
            continue
        for exchange, rows in support.items():
            if not isinstance(rows, Mapping):
                continue
            exchange_rows = merged.setdefault(str(exchange).lower(), {})
            if isinstance(exchange_rows, dict):
                exchange_rows.update(rows)
    return merged


def _venue_unavailability_reason(
    *,
    exchange: str,
    symbol: str,
    payload: Any,
    provider_symbol_support: Mapping[str, Any] | None,
) -> tuple[str | None, dict[str, Any] | None]:
    exchange_l = str(exchange).lower()
    provider_rows = (
        provider_symbol_support.get(exchange_l)
        if isinstance(provider_symbol_support, Mapping)
        else None
    )
    provider_row = (
        provider_rows.get(symbol.upper())
        if isinstance(provider_rows, Mapping)
        else None
    )
    detail = dict(provider_row) if isinstance(provider_row, Mapping) else None
    if isinstance(provider_row, Mapping) and provider_row.get("orderbook_supported") is False:
        status = str(provider_row.get("status") or "UNSUPPORTED")
        provider_symbol = str(provider_row.get("provider_symbol") or symbol.upper())
        return (
            f"{exchange_l.upper()}_DIRECT_ORDERBOOK_UNSUPPORTED:{status}:{provider_symbol}",
            detail,
        )
    if isinstance(payload, Mapping):
        if payload.get("source_is_direct_orderbook") is True:
            return None, detail
        return f"{exchange_l.upper()}_PAYLOAD_PRESENT_NOT_DIRECT_ORDERBOOK", detail
    return f"{exchange_l.upper()}_DIRECT_ORDERBOOK_PAYLOAD_MISSING", detail


def _venue_unavailability_status(
    *,
    symbol: str,
    exchanges: list[str],
    books: Mapping[str, Any],
    provider_symbol_support: Mapping[str, Any] | None,
) -> dict[str, Any]:
    reasons: dict[str, str] = {}
    provider_details: dict[str, Any] = {}
    for exchange in exchanges:
        reason, detail = _venue_unavailability_reason(
            exchange=exchange,
            symbol=symbol,
            payload=books.get(exchange),
            provider_symbol_support=provider_symbol_support,
        )
        if reason:
            reasons[str(exchange).lower()] = reason
        if detail:
            provider_details[str(exchange).lower()] = detail
    return {
        "venue_unavailable_reasons": reasons,
        "provider_symbol_support_details": provider_details,
    }


def _redis_client(enabled: bool = True) -> Any:
    if not enabled:
        return None
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        url = os.environ.get("V2_REDIS_URL") or os.environ.get("REDIS_URL") or "redis://127.0.0.1:6379/0"
        client = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=1.0, socket_timeout=1.0)
        client.ping()
        return client
    except Exception:
        return None


def _safe_get_json(redis_client: Any, key: str) -> dict[str, Any] | list[Any] | None:
    if redis_client is None or not key.startswith(V2_REDIS_PREFIX):
        return None
    try:
        raw = redis_client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if isinstance(payload, (dict, list)):
        return payload
    return None


def _safe_set_json(redis_client: Any, key: str, payload: Mapping[str, Any], *, ttl_seconds: int = REDIS_TTL_SECONDS) -> bool:
    if redis_client is None:
        return False
    if not key.startswith(MICROSTRUCTURE_REDIS_PREFIX):
        raise ValueError(f"refused_non_microstructure_redis_key:{key}")
    redis_client.set(key, json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), default=str), ex=int(ttl_seconds))
    return True


def _book_payload(redis_client: Any, exchange: str, symbol: str) -> dict[str, Any] | None:
    normalized = symbol.upper()
    exchange = str(exchange or "").strip().lower()
    keys = [
        f"{V2_REDIS_PREFIX}orderbook:features:{exchange}:{normalized}",
        f"{V2_REDIS_PREFIX}orderbook:depth:{exchange}:{normalized}",
        f"{V2_REDIS_PREFIX}orderbook:top:{exchange}:{normalized}",
        f"{V2_REDIS_PREFIX}market:orderbook:{exchange}:{normalized}",
    ]
    if exchange == "binance":
        keys.append(f"{V2_REDIS_PREFIX}market:orderbook:{normalized}")
    for key in keys:
        payload = _safe_get_json(redis_client, key)
        if isinstance(payload, dict):
            out = dict(payload)
            out.setdefault("source_redis_key", key)
            out.setdefault("source_exchange", exchange)
            out.setdefault("source_is_direct_orderbook", key.startswith(f"{V2_REDIS_PREFIX}orderbook:"))
            out.setdefault("source_is_market_orderbook_fallback", key.startswith(f"{V2_REDIS_PREFIX}market:orderbook:"))
            return out
    return None


def _read_replay_snapshots(replay_root: Path, exchange: str, symbol: str, *, max_rows: int = 24) -> list[dict[str, Any]]:
    root = replay_root / exchange / symbol.upper()
    if not root.exists():
        return []
    files = sorted(root.rglob("features.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
    rows: list[dict[str, Any]] = []
    for path in files[:4]:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in reversed(lines[-max_rows:]):
            try:
                row = json.loads(line)
            except ValueError:
                continue
            payload = row.get("payload") if isinstance(row, dict) else None
            if isinstance(payload, dict):
                rows.append(dict(payload))
            if len(rows) >= max_rows:
                return list(reversed(rows))
    return list(reversed(rows))


def _as_trade_list(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("trades", "aggTrades", "rows", "data", "items"):
            raw = payload.get(key)
            if isinstance(raw, list):
                return [row for row in raw if isinstance(row, Mapping)]
        return [payload]
    return []


def _read_trades(redis_client: Any, symbol: str) -> list[Mapping[str, Any]]:
    normalized = symbol.upper()
    for key in (
        f"{V2_REDIS_PREFIX}market:agg_trades:{normalized}",
        f"{V2_REDIS_PREFIX}market:trades:{normalized}",
        f"{V2_REDIS_PREFIX}trades:{normalized}",
    ):
        payload = _safe_get_json(redis_client, key)
        trades = _as_trade_list(payload)
        if trades:
            return trades[-250:]
    return []


def _open_interest_hist_change_pct(payload: Any) -> float | None:
    if isinstance(payload, Mapping):
        direct = _float(
            _first_present(
                payload.get("change_pct"),
                payload.get("oi_change_pct"),
                payload.get("open_interest_change_pct"),
            )
        )
        if direct is not None:
            return direct
        rows = payload.get("rows") or payload.get("data") or payload.get("items")
    else:
        rows = payload
    if not isinstance(rows, list) or len(rows) < 2:
        return None
    first = next((row for row in rows if isinstance(row, Mapping)), None)
    last = next((row for row in reversed(rows) if isinstance(row, Mapping)), None)
    if first is None or last is None:
        return None
    first_oi = _float(
        _first_present(
            first.get("sumOpenInterest"),
            first.get("openInterest"),
            first.get("open_interest"),
            first.get("sumOpenInterestValue"),
        )
    )
    last_oi = _float(
        _first_present(
            last.get("sumOpenInterest"),
            last.get("openInterest"),
            last.get("open_interest"),
            last.get("sumOpenInterestValue"),
        )
    )
    if first_oi is None or last_oi is None or first_oi <= 0:
        return None
    return (last_oi - first_oi) / first_oi


def _read_context(redis_client: Any, symbol: str, timeframe: str) -> dict[str, Any]:
    normalized = symbol.upper()
    liquidation = {}
    for key in (
        f"{V2_REDIS_PREFIX}liquidations:levels:{normalized}:{timeframe}",
        f"{V2_REDIS_PREFIX}market:liquidations:aggregate:{normalized}",
        f"{V2_REDIS_PREFIX}coinank:liquidations:{normalized}",
    ):
        payload = _safe_get_json(redis_client, key)
        if isinstance(payload, dict):
            liquidation = payload
            break
    long_short_payload = _safe_get_json(redis_client, f"{V2_REDIS_PREFIX}market:long_short:{normalized}")
    funding_payload = _safe_get_json(redis_client, f"{V2_REDIS_PREFIX}market:funding:{normalized}")
    oi_payload = _safe_get_json(redis_client, f"{V2_REDIS_PREFIX}market:open_interest:{normalized}")
    oi_hist_payload = _safe_get_json(redis_client, f"{V2_REDIS_PREFIX}market:open_interest_hist:{normalized}:5m")
    price_payload = _safe_get_json(redis_client, f"{V2_REDIS_PREFIX}market:prices:{normalized}")
    coinglass_payload = _safe_get_json(redis_client, f"{V2_REDIS_PREFIX}features:coinglass:{normalized}:1m")
    coinglass_features = (
        coinglass_payload.get("features")
        if isinstance(coinglass_payload, Mapping) and isinstance(coinglass_payload.get("features"), Mapping)
        else {}
    )
    long_short_ratio = _float(
        _first_present(
            (long_short_payload or {}).get("long_short_ratio") if isinstance(long_short_payload, dict) else None,
            (long_short_payload or {}).get("longShortRatio") if isinstance(long_short_payload, dict) else None,
        )
    )
    if long_short_ratio is None:
        cg_long = _float(coinglass_features.get("coinglass_long_ratio"))
        cg_short = _float(coinglass_features.get("coinglass_short_ratio"))
        if cg_long is not None and cg_short is not None and cg_short > 0:
            long_short_ratio = cg_long / cg_short
    funding_rate = _float(
        _first_present(
            (funding_payload or {}).get("funding_rate") if isinstance(funding_payload, dict) else None,
            (funding_payload or {}).get("lastFundingRate") if isinstance(funding_payload, dict) else None,
            (funding_payload or {}).get("fundingRate") if isinstance(funding_payload, dict) else None,
        )
    )
    if funding_rate is None:
        cg_funding = _float(coinglass_features.get("coinglass_funding_rate"))
        if cg_funding is not None:
            funding_rate = cg_funding / 100.0 if abs(cg_funding) > 0.01 else cg_funding
    oi_change = _float(
        _first_present(
            (oi_payload or {}).get("open_interest_change_pct") if isinstance(oi_payload, dict) else None,
            (oi_payload or {}).get("openInterestChangePct") if isinstance(oi_payload, dict) else None,
            coinglass_features.get("coinglass_open_interest_change_pct"),
            coinglass_features.get("coinglass_open_interest_delta_pct_5m"),
            coinglass_features.get("coinglass_open_interest_delta_pct_1h"),
        )
    )
    if oi_change is None:
        oi_change = _open_interest_hist_change_pct(oi_hist_payload)
    if oi_change is None:
        oi_delta = _float(
            _first_present(
                coinglass_features.get("coinglass_open_interest_delta_usd_5m"),
                coinglass_features.get("coinglass_open_interest_delta_usd_1h"),
            )
        )
        oi_usd = _float(coinglass_features.get("coinglass_open_interest_usd"))
        if oi_delta is not None and oi_usd is not None and oi_usd > 0:
            oi_change = oi_delta / oi_usd
    return {
        "liquidation": liquidation if isinstance(liquidation, dict) else {},
        "long_short_ratio": long_short_ratio,
        "funding_rate": funding_rate,
        "open_interest_change_pct": oi_change,
        "mark_price": _float((price_payload or {}).get("mark_price") if isinstance(price_payload, dict) else None),
        "index_price": _float((price_payload or {}).get("index_price") if isinstance(price_payload, dict) else None),
        "basis_bps": _float((price_payload or {}).get("basis_bps") if isinstance(price_payload, dict) else None),
    }


def _book_imbalance(payload: Mapping[str, Any] | None) -> float | None:
    if not isinstance(payload, Mapping):
        return None
    return _float(_first_present(payload.get("depth_imbalance"), payload.get("orderbook_imbalance")))


_HARD_COMBINED_FEED_FAIL_REASONS = {
    "AVAILABLE_AT_AFTER_DECISION_TIME",
    "UNREPAIRED_SEQUENCE_GAP",
    "OUT_OF_ORDER_UPDATES_PRESENT",
}


def _combine_feed_quality(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        row = evaluate_feed_quality(exchange="none", symbol="UNKNOWN", update_count=0)
        row["fail_reasons"] = sorted(set(list(row.get("fail_reasons") or []) + ["NO_EXCHANGE_FEED_ROWS"]))
        row["fail_closed"] = True
        return row
    usable_rows = [row for row in rows if row.get("fail_closed") is not True]
    hard_fail_rows = [
        row
        for row in rows
        if any(str(reason) in _HARD_COMBINED_FEED_FAIL_REASONS for reason in (row.get("fail_reasons") or []))
    ]
    scoring_rows = usable_rows if usable_rows and not hard_fail_rows else rows
    scores = [_float(row.get("feed_quality_score")) for row in scoring_rows]
    scores = [score for score in scores if score is not None]
    latencies = [_float(row.get("latency_ms")) for row in scoring_rows]
    latencies = [latency for latency in latencies if latency is not None]
    all_fail_reasons = sorted({str(reason) for row in rows for reason in (row.get("fail_reasons") or [])})
    warning_reasons = sorted(
        {
            f"{row.get('exchange') or 'unknown'}:{reason}"
            for row in rows
            if row not in scoring_rows
            for reason in (row.get("fail_reasons") or [])
        }
    )
    fail_closed = bool(hard_fail_rows) or not bool(usable_rows)
    combined = dict(rows[0])
    combined.update(
        {
            "schema_version": "microstructure_feed_quality_combined_v1",
            "exchange": "multi",
            "source_exchanges": [row.get("exchange") for row in rows],
            "usable_source_exchanges": [row.get("exchange") for row in usable_rows],
            "combined_fail_policy": "hard_temporal_or_all_venues_failed",
            "feed_quality_score": min(scores) if scores else 0.0,
            "latency_ms": max(latencies) if latencies else None,
            "local_latency_ms": max(latencies) if latencies else None,
            "sequence_gap_count": sum(int(row.get("sequence_gap_count") or 0) for row in rows),
            "fail_closed": fail_closed,
            "fail_reasons": all_fail_reasons if fail_closed else [],
            "secondary_feed_warning_reasons": warning_reasons,
            "all_feed_fail_reasons": all_fail_reasons,
            "generated_at": iso_now(),
        }
    )
    return combined


def _combine_adversarial(rows: list[Mapping[str, Any]], *, symbol: str) -> dict[str, Any]:
    if not rows:
        return compute_orderbook_adversarial_features(exchange="none", symbol=symbol, snapshots=[])
    out = dict(rows[0])
    for field in (
        "cancel_burst_score",
        "quote_stuffing_score",
        "book_flip_rate",
        "top_book_pull_rate",
        "depth_collapse_bps",
        "spread_expansion_rate",
        "bid_wall_pull_score",
        "ask_wall_pull_score",
        "imbalance_flip_score",
        "book_trade_divergence_score",
        "price_impact_instability_score",
    ):
        values = [_float(row.get(field)) for row in rows]
        out[field] = max([value for value in values if value is not None], default=out.get(field))
    # Depth persistence combines only rows that carry actual book evidence: a
    # venue with no recorded window (INSUFFICIENT/MISSING reasons) must be
    # reported as unavailable, not allowed to zero out another venue's
    # evidence via min() (F-0010).
    evidenced = [
        row
        for row in rows
        if row.get("depth_persistence_reason")
        in (None, "STABLE_DEPTH_WINDOW", "DEPTH_UNSTABLE")
    ]
    pool = evidenced or rows
    persistence = [_float(row.get("depth_persistence_ms")) for row in pool]
    persistence = [value for value in persistence if value is not None]
    if persistence:
        out["depth_persistence_ms"] = min(persistence)
        worst = min(
            pool, key=lambda row: _float(row.get("depth_persistence_ms")) or 0.0
        )
        out["depth_persistence_reason"] = worst.get("depth_persistence_reason") or out.get(
            "depth_persistence_reason"
        )
        out["depth_series_stratum"] = worst.get("depth_series_stratum") or out.get(
            "depth_series_stratum"
        )
    out["depth_persistence_unavailable_exchanges"] = [
        row.get("exchange")
        for row in rows
        if row not in evidenced
    ]
    out["exchange"] = "multi"
    out["source_exchanges"] = [row.get("exchange") for row in rows]
    out["generated_at"] = iso_now()
    return out


def _build_symbol_rows(
    *,
    redis_client: Any,
    symbol: str,
    timeframe: str,
    exchanges: list[str],
    replay_root: Path,
    decision_time: str,
    provider_symbol_support: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    books = {exchange: _book_payload(redis_client, exchange, symbol) for exchange in exchanges}
    # The monitor's decision timestamp must be after the Redis feature snapshot
    # has been read; otherwise a concurrently refreshed book can look like
    # look-ahead leakage even when it was available to this evaluation.
    decision_time = iso_now()
    book_for_tape = next((payload for payload in books.values() if isinstance(payload, Mapping)), None)
    context = _read_context(redis_client, symbol, timeframe)
    trades = _read_trades(redis_client, symbol)
    tape = evaluate_trade_tape_confirmation(
        symbol=symbol,
        trades=list(trades),
        book_imbalance=_book_imbalance(book_for_tape),
        mark_price=context["mark_price"],
        index_price=context["index_price"],
        basis_bps=context["basis_bps"],
    )
    feed_rows: list[dict[str, Any]] = []
    missing_feed_rows: list[dict[str, Any]] = []
    adversarial_rows: list[dict[str, Any]] = []
    for exchange in exchanges:
        payload = books.get(exchange)
        sequence_gap_count = int(
            _float(
                _first_present(
                    (payload or {}).get("sequence_gap_count") if isinstance(payload, Mapping) else None,
                    1 if isinstance(payload, Mapping) and _bool(payload.get("sequence_gap")) else 0,
                )
            )
            or 0
        )
        feed = evaluate_feed_quality(
            exchange=exchange,
            symbol=symbol,
            event_time=_first_present(
                (payload or {}).get("event_time") if isinstance(payload, Mapping) else None,
                (payload or {}).get("E") if isinstance(payload, Mapping) else None,
                (payload or {}).get("time") if isinstance(payload, Mapping) else None,
            ),
            transaction_time=_first_present(
                (payload or {}).get("transaction_time") if isinstance(payload, Mapping) else None,
                (payload or {}).get("T") if isinstance(payload, Mapping) else None,
            ),
            received_at=_first_present(
                (payload or {}).get("received_at") if isinstance(payload, Mapping) else None,
                (payload or {}).get("available_at") if isinstance(payload, Mapping) else None,
                (payload or {}).get("generated_at") if isinstance(payload, Mapping) else None,
                (payload or {}).get("generated_utc") if isinstance(payload, Mapping) else None,
                (payload or {}).get("generated_at_ms") if isinstance(payload, Mapping) else None,
            ),
            available_at=_first_present(
                (payload or {}).get("available_at") if isinstance(payload, Mapping) else None,
                (payload or {}).get("received_at") if isinstance(payload, Mapping) else None,
                (payload or {}).get("generated_at") if isinstance(payload, Mapping) else None,
                (payload or {}).get("generated_utc") if isinstance(payload, Mapping) else None,
                (payload or {}).get("generated_at_ms") if isinstance(payload, Mapping) else None,
            ),
            decision_time=decision_time,
            observed_local_latency_ms=_first_present(
                (payload or {}).get("source_latency_ms") if isinstance(payload, Mapping) else None,
                (payload or {}).get("local_latency_ms") if isinstance(payload, Mapping) else None,
                (payload or {}).get("latency_ms") if isinstance(payload, Mapping) else None,
            ),
            sequence_gap_count=sequence_gap_count,
            unrepaired_sequence_gap=sequence_gap_count > 0,
            snapshot_repair_count=int(_float((payload or {}).get("snapshot_repair_count") if isinstance(payload, Mapping) else None) or 0),
            update_count=1 if isinstance(payload, Mapping) else 0,
            trade_update_count=len(trades),
            book_ticker_update_count=1 if isinstance(payload, Mapping) else 0,
        )
        if isinstance(payload, Mapping):
            feed_rows.append(feed)
        else:
            missing_feed_rows.append(feed)
        snapshots = _read_replay_snapshots(replay_root, exchange, symbol)
        if isinstance(payload, Mapping):
            snapshots.append(dict(payload))
        adversarial_rows.append(
            compute_orderbook_adversarial_features(
                exchange=exchange,
                symbol=symbol,
                snapshots=snapshots,
                trade_imbalance=_float(tape.get("trade_imbalance")),
            )
        )
    cross = evaluate_cross_venue_confirmation(
        symbol=symbol,
        binance=books.get("binance"),
        kucoin=books.get("kucoin"),
        coinank_liquidation_context=context["liquidation"],
        trade_tape_confirmation_score=_float(tape.get("trade_tape_confirmation_score")),
    )
    depth_collapse = max((_float(row.get("depth_collapse_bps")) or 0.0 for row in adversarial_rows), default=0.0)
    sweep = detect_liquidation_sweep(
        symbol=symbol,
        timeframe=timeframe,
        liquidation_context=context["liquidation"],
        long_short_ratio=context["long_short_ratio"],
        funding_rate=context["funding_rate"],
        open_interest_change_pct=context["open_interest_change_pct"],
        mark_index_divergence_bps=context["basis_bps"],
        depth_collapse_bps=depth_collapse,
        trade_tape_acceleration=_float(tape.get("volume_acceleration")),
        trade_imbalance=_float(tape.get("trade_imbalance")),
        cross_venue_basis_bps=_float(cross.get("price_divergence_bps")),
    )
    combined_feed = _combine_feed_quality(feed_rows)
    combined_adversarial = _combine_adversarial(adversarial_rows, symbol=symbol)
    active_orderbook_sources = [
        exchange for exchange, payload in books.items() if isinstance(payload, Mapping)
    ]
    direct_orderbook_sources = [
        exchange
        for exchange, payload in books.items()
        if isinstance(payload, Mapping) and payload.get("source_is_direct_orderbook") is True
    ]
    venue_unavailability = _venue_unavailability_status(
        symbol=symbol,
        exchanges=exchanges,
        books=books,
        provider_symbol_support=provider_symbol_support,
    )
    trust = score_microstructure_trust(
        symbol=symbol,
        timeframe=timeframe,
        feed_quality=combined_feed,
        adversarial_features=combined_adversarial,
        trade_tape=tape,
        cross_venue=cross,
        sweep_risk=sweep,
    )
    trust.update(
        {
            "orderbook_latency_ms": trust.get("feed_latency_ms"),
            "book_sequence_gap": bool(trust.get("sequence_gap_flag")),
            "book_depth_persistence_score": trust.get("depth_persistence"),
            "book_depth_persistence_reason": trust.get("depth_persistence_reason"),
            "book_depth_series_stratum": trust.get("depth_series_stratum"),
            "book_cancel_pressure_score": trust.get("cancel_pressure"),
            "trade_tape_confirmation_score": tape.get("trade_tape_confirmation_score"),
            "cross_venue_confirmation_score": cross.get("cross_venue_confirmation_score"),
            "liquidation_zone_risk_score": max(
                _float(sweep.get("long_liquidation_sweep_risk")) or 0.0,
                _float(sweep.get("short_liquidation_sweep_risk")) or 0.0,
            ),
            "sweep_risk_score": sweep.get("sweep_risk"),
            "available_at": combined_feed.get("available_at"),
            "decision_time": decision_time,
            "orderbook_sources": active_orderbook_sources,
            "direct_orderbook_sources": direct_orderbook_sources,
            "direct_binance_kucoin_active": bool(direct_orderbook_sources),
            "feed_quality_fail_closed": bool(combined_feed.get("fail_closed")),
            "feed_quality_fail_reasons": combined_feed.get("fail_reasons") or [],
            "all_feed_fail_reasons": combined_feed.get("all_feed_fail_reasons") or [],
            "secondary_feed_warning_reasons": combined_feed.get("secondary_feed_warning_reasons") or [],
            "usable_source_exchanges": combined_feed.get("usable_source_exchanges") or [],
            "combined_feed_fail_policy": combined_feed.get("combined_fail_policy"),
            **venue_unavailability,
            "source_availability": {
                "direct_binance_or_kucoin": bool(direct_orderbook_sources),
                "binance": isinstance(books.get("binance"), Mapping),
                "kucoin": isinstance(books.get("kucoin"), Mapping),
                "binance_direct_orderbook": isinstance(books.get("binance"), Mapping)
                and books["binance"].get("source_is_direct_orderbook") is True,
                "kucoin_direct_orderbook": isinstance(books.get("kucoin"), Mapping)
                and books["kucoin"].get("source_is_direct_orderbook") is True,
                "coinank_liquidation_context": bool(context["liquidation"]),
                "trade_tape": bool(trades),
            },
        }
    )
    return {
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "books": books,
        "feed_rows": feed_rows,
        "missing_feed_rows": missing_feed_rows,
        "adversarial_rows": adversarial_rows,
        "trade_tape": tape,
        "cross_venue": cross,
        "sweep_risk": sweep,
        "trust_score": trust,
    }


def _write_redis_outputs(redis_client: Any, rows: list[dict[str, Any]], *, ttl_seconds: int) -> list[str]:
    keys: list[str] = []
    feed_rows = [feed for row in rows for feed in row["feed_rows"]]
    for row in rows:
        symbol = row["symbol"]
        timeframe = row["timeframe"]
        for feed in row["feed_rows"]:
            key = f"{MICROSTRUCTURE_REDIS_PREFIX}feed_quality:{feed['exchange']}:{symbol}"
            if _safe_set_json(redis_client, key, feed, ttl_seconds=ttl_seconds):
                keys.append(key)
        for adversarial in row["adversarial_rows"]:
            key = f"{MICROSTRUCTURE_REDIS_PREFIX}adversarial_features:{adversarial['exchange']}:{symbol}"
            if _safe_set_json(redis_client, key, adversarial, ttl_seconds=ttl_seconds):
                keys.append(key)
        for suffix, payload in (
            (f"trade_tape_confirmation:{symbol}", row["trade_tape"]),
            (f"cross_venue_confirmation:{symbol}", row["cross_venue"]),
            (f"sweep_risk:{symbol}:{timeframe}", row["sweep_risk"]),
            (f"trust_score:{symbol}:{timeframe}", row["trust_score"]),
        ):
            key = f"{MICROSTRUCTURE_REDIS_PREFIX}{suffix}"
            if _safe_set_json(redis_client, key, payload, ttl_seconds=ttl_seconds):
                keys.append(key)
    summary = summarize_feed_quality(feed_rows)
    if _safe_set_json(redis_client, f"{MICROSTRUCTURE_REDIS_PREFIX}feed_quality:summary", summary, ttl_seconds=ttl_seconds):
        keys.append(f"{MICROSTRUCTURE_REDIS_PREFIX}feed_quality:summary")
    trust_summary = {
        "schema_version": "microstructure_trust_score_summary_redis_v1",
        "generated_at": iso_now(),
        "rows": len(rows),
        "symbols": [row["symbol"] for row in rows],
        "low_trust_rows": sum(
            1
            for row in rows
            if (_float(row["trust_score"].get("microstructure_trust_score")) or 0.0)
            < (_float(row["trust_score"].get("adaptive_minimum")) or 0.65)
        ),
        "public_book_can_approve_trade_alone": False,
    }
    if _safe_set_json(redis_client, f"{MICROSTRUCTURE_REDIS_PREFIX}trust_score:summary", trust_summary, ttl_seconds=ttl_seconds):
        keys.append(f"{MICROSTRUCTURE_REDIS_PREFIX}trust_score:summary")
    return keys


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=STATUS_WORKER_ID)
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--timeframe", default="1m")
    parser.add_argument("--exchanges", default="binance,kucoin")
    parser.add_argument("--write-redis", action="store_true")
    parser.add_argument("--write-status", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    parser.add_argument("--loop-max-runs", type=int, default=0)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--ttl-seconds", type=int, default=REDIS_TTL_SECONDS)
    parser.add_argument("--replay-root", default=str(DEFAULT_REPLAY_ROOT))
    return parser.parse_args(argv)


def run_once(
    *,
    symbols: list[str],
    timeframe: str,
    exchanges: list[str],
    replay_root: Path,
    write_redis: bool = False,
    write_status: bool = False,
    plan_only: bool = False,
    ttl_seconds: int = REDIS_TTL_SECONDS,
    redis_client_override: Any | None = None,
) -> dict[str, Any]:
    started_at = iso_now()
    redis_client = redis_client_override if redis_client_override is not None else _redis_client(enabled=not plan_only or write_redis)
    provider_symbol_support = _load_provider_symbol_support()
    rows = [] if plan_only else [
        _build_symbol_rows(
            redis_client=redis_client,
            symbol=symbol,
            timeframe=timeframe,
            exchanges=exchanges,
            replay_root=replay_root,
            decision_time="",
            provider_symbol_support=provider_symbol_support,
        )
        for symbol in symbols
    ]
    keys_written = _write_redis_outputs(redis_client, rows, ttl_seconds=ttl_seconds) if write_redis and not plan_only else []
    feed_summary = summarize_feed_quality([feed for row in rows for feed in row["feed_rows"]])
    trust_rows = [row["trust_score"] for row in rows]
    status_written: dict[str, Path] = {}
    if write_status or plan_only:
        status_written = write_status_artifacts(
            repo_root=REPO_ROOT,
            trust_rows=trust_rows,
            feed_summary=feed_summary,
            extra_artifacts={
                "microstructure_runtime_rows.json": {
                    "schema_version": "microstructure_runtime_rows_v1",
                    "goal_id": GOAL_ID,
                    "generated_at": iso_now(),
                    "symbols": symbols,
                    "rows": rows,
                    "public_orderbook_policy": public_orderbook_trust_policy_status(),
                }
            },
        )
    return {
        "schema_version": "v2_microstructure_feed_quality_monitor_run_v1",
        "worker_id": STATUS_WORKER_ID,
        "goal_id": GOAL_ID,
        "started_at": started_at,
        "finished_at": iso_now(),
        "plan_only": bool(plan_only),
        "symbols": [symbol.upper() for symbol in symbols],
        "timeframe": timeframe,
        "exchanges": exchanges,
        "redis_enabled": bool(write_redis),
        "redis_available": redis_client is not None,
        "redis_keys_written": keys_written,
        "redis_key_prefix": MICROSTRUCTURE_REDIS_PREFIX,
        "status_files_written": sorted(status_written.keys()),
        "trust_rows": trust_rows,
        "feed_summary": feed_summary,
        "live_gate": LIVE_GATE,
        "places_real_order": False,
        "test_orders": False,
        "cancel_or_modify_order": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "transfer_or_withdrawal": False,
        "old_redis_writes": False,
        "redis_trim": False,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    symbols = resolve_symbols(explicit=args.symbols, smoke_test=args.smoke_test, include_baseline=True)
    exchanges = [part.strip().lower() for part in str(args.exchanges or "").split(",") if part.strip()]
    exchanges = [exchange for exchange in exchanges if exchange in {"binance", "kucoin"}] or ["binance", "kucoin"]
    run_index = 0
    max_runs = int(args.loop_max_runs)
    interval_seconds = max(0.0, float(args.interval_seconds))
    while True:
        run_index += 1
        payload = run_once(
            symbols=symbols,
            timeframe=str(args.timeframe or "1m"),
            exchanges=exchanges,
            replay_root=Path(args.replay_root),
            write_redis=bool(args.write_redis),
            write_status=bool(args.write_status),
            plan_only=bool(args.plan_only),
            ttl_seconds=int(args.ttl_seconds),
        )
        payload["loop"] = bool(args.loop)
        payload["loop_run_index"] = run_index if args.loop else None
        payload["interval_seconds"] = float(args.interval_seconds)
        payload["loop_max_runs"] = max_runs
        if args.loop:
            print(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str), flush=True)
        else:
            print(json.dumps(payload, indent=2, sort_keys=True, default=str))
            break
        if max_runs > 0 and run_index >= max_runs:
            break
        time.sleep(interval_seconds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
