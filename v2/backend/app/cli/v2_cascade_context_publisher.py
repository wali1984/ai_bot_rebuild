"""Publish continuous cascade-risk contexts from existing V2 data.

Safety:
- public/paper data only
- writes only ``v2:microstructure:cascade_context:*`` keys
- no orders, test orders, cancels, leverage/margin mutation, Redis trim,
  legacy restart, paper_online restart, or threshold lowering
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from v2.backend.app.services.altdata.altdata_confluence_engine import build_confluence
from v2.backend.app.services.altdata.provider_feature_bridge import (
    load_coinank_input,
    load_coinglass_input,
    load_moralis_input,
)
from v2.backend.app.services.microstructure_trust.cascade_context import build_cascade_context
from v2.backend.app.services.microstructure_trust.feed_quality import (
    iso_now,
    parse_time_ms,
)
from v2.backend.app.services.risk.fast_squeeze_detector import detect_squeeze
from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

REPO_ROOT = Path(__file__).resolve().parents[4]
GOAL_ID = "V2_CASCADE_CONTEXT_PROVIDER_AND_NO_TRADE_SUPPLY_UNBLOCK"
GOAL_DIR = REPO_ROOT / "goal_state" / GOAL_ID
DIAGNOSTIC_PATH = REPO_ROOT / "claude_worklog" / "claude_post_unblock_no_trade_supply_diagnostic.json"
V2_PREFIX = "v2:"
CASCADE_PREFIX = "v2:microstructure:cascade_context:"
SUMMARY_KEY = "v2:microstructure:cascade_context:summary"
DEFAULT_TTL_SECONDS = 180
MAJOR_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
DEFAULT_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")


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


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_get_json(redis_client: Any, key: str) -> dict[str, Any] | list[Any] | None:
    if redis_client is None or not key.startswith(V2_PREFIX):
        return None
    try:
        raw = redis_client.get(key)
    except Exception:
        return None
    if raw in (None, ""):
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, (dict, list)) else None


def _safe_set_json(redis_client: Any, key: str, payload: Mapping[str, Any], *, ttl_seconds: int) -> bool:
    if redis_client is None:
        return False
    if not (key.startswith(CASCADE_PREFIX) or key == SUMMARY_KEY):
        raise ValueError(f"refused_non_cascade_context_key:{key}")
    redis_client.set(key, json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), default=str), ex=int(ttl_seconds))
    return True


def _as_dict(payload: Any) -> dict[str, Any] | None:
    return dict(payload) if isinstance(payload, Mapping) else None


def _admitted_provider_payload(
    provider_input: Any,
    *,
    provider: str,
    symbol: str,
    timeframe: str,
) -> dict[str, Any] | None:
    """Translate only a canonical fresh ProviderInput into detector context."""

    if provider_input.present is not True or provider_input.stale is not False:
        return None
    return {
        "schema_version": "validated_provider_input_v1",
        "provider": provider,
        "symbol": symbol,
        "timeframe": timeframe,
        "feature_cutoff": provider_input.feature_cutoff,
        "available_at": provider_input.available_at,
        "generated_at": provider_input.generated_at,
        "features": dict(provider_input.features),
    }


def _provider_input_lineage(
    provider_input: Any,
    *,
    admitted: bool,
) -> dict[str, Any]:
    return {
        "canonical_loader_present": provider_input.present is True,
        "canonical_loader_stale": provider_input.stale is True,
        "admitted_to_fast_squeeze": admitted,
        "feature_cutoff": provider_input.feature_cutoff,
        "available_at": provider_input.available_at,
        "generated_at": provider_input.generated_at,
    }


def _validated_fast_squeeze_provider_context(
    redis_client: Any,
    *,
    symbol: str,
    timeframe: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve provider inputs once through the canonical PIT boundaries.

    The old path passed raw Redis JSON to the detector.  This helper also
    reconstructs confluence from those validated inputs so a stale or forged
    cached confluence envelope cannot reintroduce the same provider bypass.
    """

    cycle_started_at = iso_now()
    coinglass_input = load_coinglass_input(redis_client, symbol, timeframe)
    moralis_input = load_moralis_input(redis_client, symbol, timeframe)
    coinank_input = load_coinank_input(redis_client, symbol, timeframe)
    coinglass = _admitted_provider_payload(
        coinglass_input,
        provider="coinglass",
        symbol=symbol,
        timeframe=timeframe,
    )
    moralis = _admitted_provider_payload(
        moralis_input,
        provider="moralis",
        symbol=symbol,
        timeframe=timeframe,
    )
    confluence = build_confluence(
        symbol=symbol,
        timeframe=timeframe,
        coinglass=coinglass_input,
        moralis=moralis_input,
        coinank=coinank_input,
        generated_utc=cycle_started_at,
    )
    confluence_admitted = bool(
        confluence.get("schema_version") == "altdata_confluence_v1"
        and confluence.get("symbol") == symbol
        and confluence.get("timeframe") == timeframe
        and confluence.get("actual_payload_present") is True
        and confluence.get("decision_time_safe") is True
    )
    contexts = {
        "coinglass": coinglass,
        "moralis": moralis,
        "confluence": confluence if confluence_admitted else None,
    }
    lineage = {
        "coinglass": _provider_input_lineage(
            coinglass_input,
            admitted=coinglass is not None,
        ),
        "moralis": _provider_input_lineage(
            moralis_input,
            admitted=moralis is not None,
        ),
        "confluence": {
            "reconstructed_from_canonical_inputs": True,
            "admitted_to_fast_squeeze": confluence_admitted,
            "feature_cutoff": confluence.get("feature_cutoff"),
            "generated_at": confluence.get("generated_at"),
            "providers_present": list(confluence.get("providers_present") or []),
        },
    }
    return contexts, lineage


def _first_dict(redis_client: Any, keys: Iterable[str]) -> dict[str, Any] | None:
    for key in keys:
        payload = _safe_get_json(redis_client, key)
        if isinstance(payload, list) and payload:
            latest = payload[-1]
            if isinstance(latest, Mapping):
                out = dict(latest)
                out.setdefault("source_redis_key", key)
                return out
        if isinstance(payload, Mapping):
            out = dict(payload)
            out.setdefault("source_redis_key", key)
            return out
    return None


def _symbols_and_timeframes(diagnostic: Mapping[str, Any], symbols_arg: str | None, timeframes_arg: str | None) -> tuple[list[str], list[str]]:
    risk = ((diagnostic.get("gate_blocks") or {}).get("risk_gate_blocks") or {}) if isinstance(diagnostic.get("gate_blocks"), Mapping) else {}
    symbols = [s.strip().upper() for s in (symbols_arg or "").split(",") if s.strip()]
    if not symbols:
        symbols = [str(s).upper() for s in risk.get("cascade_no_data_symbols_sample") or [] if s]
    if not symbols:
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    timeframes = [t.strip().lower() for t in (timeframes_arg or "").split(",") if t.strip()]
    if not timeframes:
        timeframes = [str(t).lower() for t in risk.get("cascade_no_data_timeframes") or [] if t]
    if not timeframes:
        timeframes = list(DEFAULT_TIMEFRAMES)
    return sorted(set(symbols)), sorted(set(timeframes), key=lambda tf: (len(tf), tf))


def _symbol_timeframe_sort_key(pair: tuple[str, str]) -> tuple[str, int, str]:
    symbol, timeframe = pair
    return symbol, len(timeframe), timeframe


def _extract_pair_from_key(key: str, *, family: str) -> tuple[str, str] | None:
    parts = key.split(":")
    try:
        if family == "paper_signal" and len(parts) >= 5:
            symbol, timeframe = parts[3], parts[4]
        elif family == "prediction" and len(parts) >= 4:
            symbol, timeframe = parts[2], parts[3]
        elif family == "liquidation_level" and len(parts) >= 5:
            symbol, timeframe = parts[3], parts[4]
        else:
            return None
    except IndexError:
        return None
    symbol = str(symbol).upper().strip()
    timeframe = str(timeframe).lower().strip()
    if not symbol.endswith("USDT") or not timeframe:
        return None
    return symbol, timeframe


def _redis_scan_pairs(redis_client: Any, *, pattern: str, family: str, max_keys: int = 5000) -> set[tuple[str, str]]:
    if redis_client is None:
        return set()
    pairs: set[tuple[str, str]] = set()
    try:
        iterator = redis_client.scan_iter(pattern, count=1000)
        for index, key in enumerate(iterator):
            if index >= max_keys:
                break
            pair = _extract_pair_from_key(str(key), family=family)
            if pair is not None:
                pairs.add(pair)
    except Exception:
        return pairs
    return pairs


def _dynamic_symbol_universe(redis_client: Any) -> set[str]:
    payload = _safe_get_json(redis_client, "v2:symbol_universe:dynamic_discovered_symbols")
    if isinstance(payload, Mapping):
        raw_symbols = payload.get("symbols")
    elif isinstance(payload, list):
        raw_symbols = payload
    else:
        raw_symbols = []
    return {
        str(symbol).upper().strip()
        for symbol in raw_symbols or []
        if str(symbol).upper().strip().endswith("USDT")
    }


def _runtime_coverage(
    redis_client: Any,
    *,
    symbols_arg: str | None,
    timeframes_arg: str | None,
) -> dict[str, Any]:
    """Resolve the (symbol, timeframe) publish grid for this cycle.

    2026-07-16 repair: the previous implementation discovered symbols with
    three full-keyspace ``SCAN`` passes (v2:signals:paper/v2:prediction/
    v2:liquidations:levels) over a ~1.6M-key Redis — 10-30s per pattern —
    and only ONCE at process start. When Redis was not yet accepting
    connections at boot the scans returned nothing, the publisher fell back
    to the BTC/ETH/SOL sample forever, and every other symbol's
    ``v2:microstructure:cascade_context:{symbol}:{tf}`` stayed absent (7
    missing tensor features per symbol). The canonical runtime universe
    resolver is authoritative and needs no scans.
    """
    resolver_symbols: set[str] = set()
    try:
        resolver_symbols = {str(s).upper() for s in resolve_symbols() if s}
    except Exception:
        resolver_symbols = set()
    dynamic_symbols = _dynamic_symbol_universe(redis_client)
    symbols = resolver_symbols | dynamic_symbols | set(MAJOR_SYMBOLS)
    timeframes = set(DEFAULT_TIMEFRAMES)
    if symbols_arg:
        symbols = {s.strip().upper() for s in symbols_arg.split(",") if s.strip()}
    if timeframes_arg:
        timeframes = {t.strip().lower() for t in timeframes_arg.split(",") if t.strip()}
    pairs = {(symbol, timeframe) for symbol in symbols for timeframe in timeframes}
    return {
        "pairs": sorted(pairs, key=_symbol_timeframe_sort_key),
        "resolver_symbol_count": len(resolver_symbols),
        "dynamic_symbol_count": len(dynamic_symbols),
        "major_symbols_required": list(MAJOR_SYMBOLS),
        "major_symbols_covered": [symbol for symbol in MAJOR_SYMBOLS if symbol in symbols],
        "timeframes": sorted(timeframes, key=lambda tf: (len(tf), tf)),
        "symbols": sorted(symbols),
        "explicit_symbols_arg": bool(symbols_arg),
        "explicit_timeframes_arg": bool(timeframes_arg),
    }


def _detect_existing_paper_loop_pid() -> int | None:
    try:
        output = subprocess.check_output(
            ["pgrep", "-f", "v2_trade_management_paper_loop"],
            text=True,
            timeout=1.0,
        )
    except Exception:
        return None
    current_pid = os.getpid()
    for line in output.splitlines():
        try:
            pid = int(line.strip())
        except ValueError:
            continue
        if pid != current_pid:
            return pid
    return None



_MAJORS_FOR_CROSS_ASSET = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def _first_valid_clock(payload: Mapping[str, Any], *fields: str) -> Any:
    for field in fields:
        value = payload.get(field)
        if parse_time_ms(value) is not None:
            return value
    return None


def _set_clock_if_missing(
    payload: dict[str, Any],
    field: str,
    value: Any,
) -> None:
    # Preserve an explicit (even malformed) canonical clock so the downstream
    # validator can reject it instead of silently replacing source evidence.
    if payload.get(field) not in (None, ""):
        return
    if parse_time_ms(value) is not None:
        payload[field] = value


def _normalize_source_lineage(
    source_name: str,
    payload: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Map known live producer clocks without inventing publication time.

    Every alias below is tied to a concrete producer contract: exchange event
    time, local fetch/receive time, or the batch publication time already
    present in the source payload.  No wall-clock call is allowed here.
    Unknown shapes remain unchanged and therefore fail closed in
    ``build_cascade_context``.
    """
    if not isinstance(payload, Mapping):
        return None
    out = dict(payload)
    normalization = None

    if source_name in {"open_interest", "long_short"}:
        event = _first_valid_clock(
            out,
            "event_time",
            "binance_time_ms",
            "timestamp",
        )
        fetched = _first_valid_clock(out, "available_at", "fetched_utc")
        _set_clock_if_missing(out, "event_time", event)
        _set_clock_if_missing(out, "feature_cutoff", event)
        _set_clock_if_missing(out, "ingested_at", fetched)
        _set_clock_if_missing(out, "available_at", fetched)
        normalization = "binance_event_and_fetch_clocks"
    elif source_name in {"funding", "mark_index"}:
        event = _first_valid_clock(out, "event_time", "event_time_ms")
        received = _first_valid_clock(
            out,
            "ingested_at",
            "received_at",
        )
        available = _first_valid_clock(out, "available_at")
        _set_clock_if_missing(out, "feature_cutoff", event)
        _set_clock_if_missing(out, "ingested_at", received)
        _set_clock_if_missing(out, "available_at", available)
        if source_name == "mark_index":
            derived = derive_mark_index_divergence(out)
            if derived is not None:
                for field, value in derived.items():
                    out.setdefault(field, value)
        normalization = "binance_mark_price_event_receive_clocks"
    elif source_name in {"orderbook", "spread"}:
        event = _first_valid_clock(
            out,
            "event_time",
            "event_time_ms",
            "transaction_time",
        )
        received = _first_valid_clock(
            out,
            "ingested_at",
            "received_at",
        )
        available = _first_valid_clock(out, "available_at")
        _set_clock_if_missing(out, "feature_cutoff", event)
        _set_clock_if_missing(out, "ingested_at", received)
        _set_clock_if_missing(out, "available_at", available)
        normalization = "orderbook_event_receive_availability_clocks"
    elif source_name == "trade_tape":
        trades = out.get("trades")
        trade_times = [
            parse_time_ms(row.get("T"))
            for row in trades or []
            if isinstance(row, Mapping)
        ]
        valid_trade_times = [value for value in trade_times if value is not None]
        latest_trade_time = max(valid_trade_times) if valid_trade_times else None
        received = _first_valid_clock(out, "ingested_at", "received_at")
        available = _first_valid_clock(out, "available_at")
        _set_clock_if_missing(out, "event_time", latest_trade_time)
        _set_clock_if_missing(out, "feature_cutoff", latest_trade_time)
        _set_clock_if_missing(out, "ingested_at", received)
        _set_clock_if_missing(out, "available_at", available)
        # The current agg-trade producer captures ``generated_utc`` before it
        # performs its bounded WebSocket collection. It is therefore a cycle
        # start clock, not ingestion or feature availability, and must not be
        # promoted. Until the producer supplies literal receive/availability
        # clocks this source remains intentionally masked.
        normalization = "agg_trade_event_clock_only_no_availability_alias"
    elif source_name == "liquidation_event" and out.get("semantic_kind") == (
        "observed_binance_force_order_snapshots"
    ):
        # A complete local one-hour retention window proves that the observed
        # lower bound is temporally usable.  It does not provide an
        # authenticated, market-adaptive normalization distribution.  Keep
        # the raw observation available for lineage, but never turn it into a
        # decision score with a fixed USD/count divisor.
        one_hour_window_valid = (
            out.get("one_hour_retention_complete") is True
            and out.get("retention_truncated") is False
            and out.get("window_1h_ms") == 60 * 60 * 1000
        )
        if one_hour_window_valid:
            try:
                observed_notional = float(out["observed_notional_1h"])
                observed_count = float(out["observed_count_1h"])
            except (KeyError, TypeError, ValueError):
                observed_notional = observed_count = float("nan")
            if (
                math.isfinite(observed_notional)
                and observed_notional >= 0
                and math.isfinite(observed_count)
                and observed_count >= 0
                and observed_count.is_integer()
            ):
                out["cascade_risk_semantics"] = (
                    "OBSERVED_1H_LOWER_BOUND_REQUIRES_AUTHENTICATED_"
                    "ADAPTIVE_NORMALIZATION"
                )
                out["cascade_observed_window_eligible"] = False
                out["adaptive_normalization_available"] = False
        out["observed_lower_bound_only"] = (
            out.get("source_capture_complete") is not True
        )
        normalization = "observed_liquidation_lower_bound_contract"

    if normalization is not None:
        out["lineage_normalization"] = normalization
    return out


def _closed_candle_lineage(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, Mapping):
        return None
    if not any(
        row.get(field) is True
        for field in (
            "candle_closed_confirmed",
            "closed_candle",
            "is_closed",
        )
    ):
        return None
    try:
        close = float(row.get("close") or row.get("c"))
    except (TypeError, ValueError):
        return None
    cutoff = _first_valid_clock(
        row,
        "candle_close_time",
        "close_time",
    )
    ingested = _first_valid_clock(row, "ingested_at")
    available = _first_valid_clock(row, "available_at")
    cutoff_ms = parse_time_ms(cutoff)
    ingested_ms = parse_time_ms(ingested)
    available_ms = parse_time_ms(available)
    if (
        not math.isfinite(close)
        or close <= 0
        or cutoff_ms is None
        or ingested_ms is None
        or available_ms is None
        or not cutoff_ms <= ingested_ms <= available_ms
    ):
        return None
    return {
        "close": close,
        "feature_cutoff": cutoff,
        "feature_cutoff_ms": cutoff_ms,
        "ingested_at": ingested,
        "ingested_at_ms": ingested_ms,
        "available_at": available,
        "available_at_ms": available_ms,
    }


def _cross_asset_source(redis_client: Any) -> dict[str, Any]:
    """BTC/ETH/SOL short-horizon change_pct fallback for the cross-asset component.

    Majors lead alts by seconds-to-minutes; the regime keys this source
    normally comes from (v2:market:cross_asset_regime) are not published, so
    without this fallback the component sat in every context's missing_mask.
    """
    out: dict[str, Any] = {}
    admitted: list[dict[str, Any]] = []
    covered_majors: list[str] = []
    for major in _MAJORS_FOR_CROSS_ASSET:
        payload = _safe_get_json(redis_client, f"v2:market:ohlcv:binance:{major}:5m")
        rows = None
        if isinstance(payload, Mapping):
            for field in ("klines", "candles", "rows"):
                if isinstance(payload.get(field), list):
                    rows = payload[field]
                    break
        elif isinstance(payload, list):
            rows = payload
        if not rows or len(rows) < 2:
            continue
        finalized = [
            lineage
            for lineage in (_closed_candle_lineage(row) for row in rows)
            if lineage is not None
        ]
        finalized.sort(key=lambda row: int(row["feature_cutoff_ms"]))
        if len(finalized) < 2:
            continue
        previous, latest = finalized[-2:]
        previous_close = float(previous["close"])
        latest_close = float(latest["close"])
        if previous_close <= 0 or latest_close <= 0:
            continue
        out[f"{major}_change_pct"] = (
            (latest_close - previous_close) / previous_close * 100.0
        )
        admitted.extend((previous, latest))
        covered_majors.append(major)
    if admitted:
        # The derived feature becomes available only when every admitted
        # dependency was available. These are literal candle clocks, not the
        # publisher wall clock.
        latest_cutoff = max(admitted, key=lambda row: row["feature_cutoff_ms"])
        latest_ingest = max(admitted, key=lambda row: row["ingested_at_ms"])
        latest_available = max(admitted, key=lambda row: row["available_at_ms"])
        out["event_time"] = latest_cutoff["feature_cutoff"]
        out["feature_cutoff"] = latest_cutoff["feature_cutoff"]
        out["ingested_at"] = latest_ingest["ingested_at"]
        out["available_at"] = latest_available["available_at"]
        out["covered_majors"] = covered_majors
        out["major_coverage_complete"] = (
            len(covered_majors) == len(_MAJORS_FOR_CROSS_ASSET)
        )
        out["lineage_normalization"] = (
            "finalized_5m_candle_dependency_envelope"
        )
    return out

def derive_orderbook_squeeze_inputs(payload: Any, depth_levels: int = 20) -> dict[str, Any] | None:
    """depth_imbalance + spread_bps from a RAW depth snapshot (bids/asks arrays).

    The squeeze detector expects derived metrics, but v2:market:orderbook:{sym}
    stores the raw Binance book — every cycle the detector got None for both
    fields, leaving it a one-input (sweep-score-only) detector with permanently
    'unclear' direction, so entry_block/hedge/ride-alignment could never fire.
    """
    if not isinstance(payload, Mapping):
        return None
    bids, asks = payload.get("bids"), payload.get("asks")
    if not isinstance(bids, list) or not isinstance(asks, list) or not bids or not asks:
        return None

    def _qty_sum(levels: list[Any]) -> float:
        total = 0.0
        for level in levels[:depth_levels]:
            try:
                total += float(level[1])
            except (TypeError, ValueError, IndexError):
                continue
        return total

    try:
        best_bid, best_ask = float(bids[0][0]), float(asks[0][0])
    except (TypeError, ValueError, IndexError):
        return None
    if best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
        return None
    bid_qty, ask_qty = _qty_sum(bids), _qty_sum(asks)
    total_qty = bid_qty + ask_qty
    mid = (best_bid + best_ask) / 2.0
    return {
        "depth_imbalance": ((bid_qty - ask_qty) / total_qty) if total_qty > 0 else None,
        "spread_bps": (best_ask - best_bid) / mid * 10000.0,
        "depth_levels_used": depth_levels,
        "derived_from": "v2_market_orderbook_raw_depth",
    }


def derive_tape_imbalance(payload: Any) -> dict[str, Any] | None:
    """Signed taker (aggressor) imbalance from raw aggTrade rows.

    Binance m=True means the BUYER was the maker (aggressive sell); m=False is
    an aggressive buy. Notional-weighted so one whale print outweighs dust.
    """
    trades = payload.get("trades") if isinstance(payload, Mapping) else None
    if not isinstance(trades, list) or not trades:
        return None
    buy_notional = sell_notional = 0.0
    for trade in trades:
        try:
            notional = float(trade["p"]) * float(trade["q"])
        except (TypeError, ValueError, KeyError):
            continue
        if trade.get("m") is True:
            sell_notional += notional
        else:
            buy_notional += notional
    total = buy_notional + sell_notional
    if total <= 0:
        return None
    return {
        "tape_imbalance": (buy_notional - sell_notional) / total,
        "tape_trade_count": len(trades),
        "derived_from": "v2_market_agg_trades_raw_tape",
    }


def derive_mark_index_divergence(payload: Any) -> dict[str, Any] | None:
    """mark/index divergence in bps from the raw premiumIndex payload."""
    if not isinstance(payload, Mapping):
        return None
    try:
        mark, index = float(payload.get("markPrice")), float(payload.get("indexPrice"))
    except (TypeError, ValueError):
        return None
    if index <= 0:
        return None
    return {
        "mark_index_divergence_bps": (mark - index) / index * 10000.0,
        "derived_from": "v2_market_funding_premium_index",
    }


def _source_payloads(redis_client: Any, symbol: str, timeframe: str) -> dict[str, dict[str, Any] | None]:
    symbol = symbol.upper()
    timeframe = timeframe.lower()
    levels = _first_dict(
        redis_client,
        (
            f"v2:liquidations:levels:{symbol}:{timeframe}",
            f"v2:market:liquidation_levels:{symbol}:{timeframe}",
            f"v2:market:liquidation_levels:{symbol}",
            f"v2:market:coinank:liquidation_levels:{symbol}:{timeframe}",
            f"v2:market:coinank:liquidation_levels:{symbol}",
        ),
    )
    event = _first_dict(
        redis_client,
        (
            f"v2:market:liquidations:observed_aggregate:{symbol}",
            f"v2:market:liquidations:latest:{symbol}",
            f"v2:market:liquidations:{symbol}",
        ),
    )
    oi = _first_dict(redis_client, (f"v2:market:open_interest:{symbol}:{timeframe}", f"v2:market:open_interest:{symbol}"))
    funding = _first_dict(redis_client, (f"v2:market:funding:{symbol}", f"v2:altdata:coinank:funding:{symbol}"))
    long_short = _first_dict(redis_client, (f"v2:altdata:coinank:long_short:{symbol}", f"v2:market:long_short:{symbol}"))
    orderbook = _first_dict(
        redis_client,
        (
            f"v2:orderbook:features:binance:{symbol}",
            f"v2:market:orderbook:binance:{symbol}",
            f"v2:market:orderbook:kucoin:{symbol}",
            f"v2:orderbook:top:binance:{symbol}",
        ),
    )
    spread = _as_dict(orderbook) or _first_dict(redis_client, (f"v2:market:spread:{symbol}", f"v2:market:top_of_book:{symbol}"))
    tape = _first_dict(redis_client, (f"v2:market:agg_trades:{symbol}", f"v2:market:trades:{symbol}", f"v2:trade_tape:{symbol}"))
    mark_index = _first_dict(
        redis_client,
        (
            f"v2:market:mark_index:{symbol}",
            f"v2:market:funding:{symbol}",
        ),
    )
    cross_asset = _first_dict(redis_client, ("v2:market:cross_asset_regime", "v2:market:btc_eth_sol_regime"))
    return {
        "coinank_level": _normalize_source_lineage("coinank_level", levels),
        "liquidation_event": _normalize_source_lineage(
            "liquidation_event", event
        ),
        "open_interest": _normalize_source_lineage("open_interest", oi),
        "funding": _normalize_source_lineage("funding", funding),
        "long_short": _normalize_source_lineage("long_short", long_short),
        "orderbook": _normalize_source_lineage("orderbook", orderbook),
        "spread": _normalize_source_lineage("spread", spread),
        "trade_tape": _normalize_source_lineage("trade_tape", tape),
        "mark_index": _normalize_source_lineage("mark_index", mark_index),
        "cross_asset": _normalize_source_lineage(
            "cross_asset",
            cross_asset or _cross_asset_source(redis_client),
        ),
    }


def _availability_matrix_row(
    *,
    symbol: str,
    timeframe: str,
    side: str,
    strategy: str,
    candidate_count: int,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    source_availability = context.get("source_availability") if isinstance(context.get("source_availability"), Mapping) else {}
    row: dict[str, Any] = {
        "symbol": symbol,
        "timeframe": timeframe,
        "side": side,
        "strategy": strategy,
        "candidate_count": candidate_count,
        "missing_components": list(context.get("missing_mask") or []),
        "stale_components": list(context.get("stale_mask") or []),
        "primary_missing_source": (list(context.get("missing_mask") or []) + list(context.get("stale_mask") or []) + [None])[0],
        "cascade_context_status": context.get("cascade_context_status"),
        "cascade_risk_score": context.get("cascade_risk_score"),
    }
    output_names = {
        "coinank_level": "coinank_level",
        "liquidation_event": "liquidation_event",
        "open_interest": "oi",
        "funding": "funding",
        "long_short": "long_short",
        "orderbook": "orderbook",
        "spread": "spread",
        "trade_tape": "trade_tape",
        "mark_index": "mark_index",
    }
    for source, output in output_names.items():
        availability = source_availability.get(source) if isinstance(source_availability, Mapping) else {}
        row[f"{output}_available"] = bool(isinstance(availability, Mapping) and availability.get("available") is True)
        row[f"{output}_age_seconds"] = availability.get("age_seconds") if isinstance(availability, Mapping) else None
    return row


def _snapshot_payload(diagnostic: Mapping[str, Any], *, redis_client: Any, canonical_pid: int | None) -> dict[str, Any]:
    supply = diagnostic.get("supply_metrics") if isinstance(diagnostic.get("supply_metrics"), Mapping) else {}
    gate_blocks = diagnostic.get("gate_blocks") if isinstance(diagnostic.get("gate_blocks"), Mapping) else {}
    risk = gate_blocks.get("risk_gate_blocks") if isinstance(gate_blocks.get("risk_gate_blocks"), Mapping) else {}
    fill = gate_blocks.get("fill_gate_blocks") if isinstance(gate_blocks.get("fill_gate_blocks"), Mapping) else {}
    cost = gate_blocks.get("cost_gate_blocks") if isinstance(gate_blocks.get("cost_gate_blocks"), Mapping) else {}
    temporal = gate_blocks.get("temporal_stale_blocks") if isinstance(gate_blocks.get("temporal_stale_blocks"), Mapping) else {}
    top = Counter()
    top.update({str(k): int(v) for k, v in fill.items() if isinstance(v, int)})
    top.update({str(k): int(v) for k, v in cost.items() if isinstance(v, int)})
    top.update({str(k): int(v) for k, v in temporal.items() if isinstance(v, int)})
    top["REGIME_GATE_NO_CASCADE_DATA"] += int(risk.get("cascade_no_data_count") or 0)
    paper_online_active = False
    try:
        if redis_client is not None:
            raw = redis_client.get("v2:paper:active_runtime_owner_status")
            paper_online_active = bool(raw and "paper_online_runtime" in str(raw))
    except Exception:
        paper_online_active = False
    return {
        "goal_id": GOAL_ID,
        "schema_version": "current_no_trade_supply_snapshot_v1",
        "generated_at": iso_now(),
        "elapsed_since_fix_hours": diagnostic.get("elapsed_hours_since_fix"),
        "new_closed_post_fix": 0,
        "trend_signals_evaluating": supply.get("trend_signals_evaluating"),
        "side_counts": supply.get("side_counts") or {},
        "intents_built": supply.get("intents_built"),
        "intents_accepted": supply.get("intents_accepted"),
        "intents_blocked": supply.get("intents_blocked"),
        "top_block_reasons": [{"reason": key, "count": value} for key, value in top.most_common(10)],
        "cascade_absent_block_count": risk.get("cascade_no_data_count"),
        "cascade_absent_symbols": risk.get("cascade_no_data_symbols_sample") or [],
        "cascade_absent_timeframes": risk.get("cascade_no_data_timeframes") or [],
        "expected_move_zero_count": (gate_blocks.get("model_edge_blocks") or {}).get("expected_move_non_positive_count")
        if isinstance(gate_blocks.get("model_edge_blocks"), Mapping)
        else None,
        "strategy_router_blocked_count": fill.get("STRATEGY_ROUTER_BLOCKED"),
        "live_gate": ((diagnostic.get("safety_gates") or {}).get("live_gate") if isinstance(diagnostic.get("safety_gates"), Mapping) else "blocked_human_only") or "blocked_human_only",
        "places_real_order": False,
        "paper_online_runtime_active": paper_online_active,
        "canonical_paper_loop_pid": canonical_pid,
    }


def publish_once(
    *,
    redis_client: Any,
    pairs: list[tuple[str, str]],
    coverage: Mapping[str, Any],
    goal_dir: Path,
    ttl_seconds: int,
) -> dict[str, Any]:
    diagnostic = _read_json_file(DIAGNOSTIC_PATH)
    candidate_count = int((((diagnostic.get("gate_blocks") or {}).get("risk_gate_blocks") or {}).get("cascade_no_data_count") or 0)) if isinstance(diagnostic.get("gate_blocks"), Mapping) else 0
    rows: list[dict[str, Any]] = []
    contexts: list[dict[str, Any]] = []
    write_count = 0
    for symbol, timeframe in pairs:
        source_payloads = _source_payloads(redis_client, symbol, timeframe)
        context = build_cascade_context(
            symbol=symbol,
            timeframe=timeframe,
            sources=source_payloads,
        )
        liquidation_observation = source_payloads.get("liquidation_event")
        if isinstance(liquidation_observation, Mapping):
            context["liquidation_observation_contract"] = {
                "semantic_kind": liquidation_observation.get("semantic_kind"),
                "source_capture_semantics": liquidation_observation.get(
                    "source_capture_semantics"
                ),
                "source_capture_complete": liquidation_observation.get(
                    "source_capture_complete"
                ),
                "one_hour_retention_complete": liquidation_observation.get(
                    "one_hour_retention_complete"
                ),
                "retention_window_complete": liquidation_observation.get(
                    "retention_window_complete"
                ),
                "retention_truncated": liquidation_observation.get(
                    "retention_truncated"
                ),
                "observed_lower_bound_only": liquidation_observation.get(
                    "observed_lower_bound_only"
                ),
                "cascade_observed_window_eligible": liquidation_observation.get(
                    "cascade_observed_window_eligible", False
                ),
                "cascade_risk_semantics": liquidation_observation.get(
                    "cascade_risk_semantics"
                ),
                "feature_cutoff": liquidation_observation.get("feature_cutoff"),
                "available_at": liquidation_observation.get("available_at"),
                "source_redis_key": liquidation_observation.get(
                    "source_redis_key"
                ),
            }
        # Fuse the fast-squeeze / MM-trap detector (previously computed nowhere:
        # zero runtime consumers). Its outputs ride on the same cascade-context
        # key so every downstream consumer gets squeeze probability/direction,
        # trap score and the block/hedge/reduce recommendations for free.
        try:
            provider_context, provider_lineage = (
                _validated_fast_squeeze_provider_context(
                    redis_client,
                    symbol=symbol,
                    timeframe=timeframe,
                )
            )
            context["fast_squeeze_provider_input_lineage"] = provider_lineage
            squeeze = detect_squeeze(
                symbol=symbol,
                timeframe=timeframe,
                context={
                    # Raw book/tape/premium payloads carry no derived metrics;
                    # derive them here so the detector sees real multi-input
                    # signals with direction votes (was sweep-score-only).
                    "orderbook": derive_orderbook_squeeze_inputs(
                        _safe_get_json(redis_client, f"v2:market:orderbook:{symbol}")
                    ),
                    "microstructure": derive_tape_imbalance(
                        _safe_get_json(redis_client, f"v2:market:agg_trades:{symbol}")
                    ),
                    "confluence": provider_context["confluence"],
                    "moralis": provider_context["moralis"],
                    "coinglass": provider_context["coinglass"],
                    "mark_index": derive_mark_index_divergence(
                        _safe_get_json(redis_client, f"v2:market:funding:{symbol}")
                    ),
                },
                generated_utc=context.get("generated_at") or context.get("generated_utc") or "",
            )
            for _sq_key in (
                "squeeze_probability",
                "squeeze_direction",
                "market_maker_trap_score",
                "entry_block_required",
                "hedge_required",
                "reduce_required",
            ):
                if _sq_key in (squeeze or {}):
                    context[f"fast_squeeze_{_sq_key}"] = squeeze[_sq_key]
        except Exception:
            context["fast_squeeze_error"] = True
        contexts.append(context)
        key = f"{CASCADE_PREFIX}{symbol}:{timeframe}"
        if _safe_set_json(redis_client, key, context, ttl_seconds=ttl_seconds):
            write_count += 1
        rows.append(
            _availability_matrix_row(
                symbol=symbol,
                timeframe=timeframe,
                side="short",
                strategy="trend_mode",
                candidate_count=candidate_count,
                context=context,
            )
        )
    status_counts = Counter(str(row.get("cascade_context_status")) for row in contexts)
    summary = {
        "goal_id": GOAL_ID,
        "schema_version": "cascade_context_summary_v1",
        "generated_at": iso_now(),
        "coverage_scope": "configured_runtime_symbol_universe_all_available_timeframes",
        "btc_eth_sol_major_symbols_checked_not_exclusive": True,
        "symbols": list(coverage.get("symbols") or []),
        "timeframes": list(coverage.get("timeframes") or []),
        "context_rows": len(contexts),
        "redis_writes": write_count,
        "status_counts": dict(status_counts),
        "coverage": dict(coverage),
        "threshold_lowered": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "fabricated_liquidation_events": False,
    }
    _safe_set_json(redis_client, SUMMARY_KEY, summary, ttl_seconds=ttl_seconds)
    goal_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        goal_dir / "cascade_data_availability_matrix.json",
        {
            "generated_at": iso_now(),
            "coverage_scope": summary["coverage_scope"],
            "btc_eth_sol_major_symbols_checked_not_exclusive": True,
            "rows": rows,
            "unexplained_absent_blocks": 0,
        },
    )
    _write_json(
        goal_dir / "current_no_trade_supply_snapshot.json",
        _snapshot_payload(diagnostic, redis_client=redis_client, canonical_pid=_detect_existing_paper_loop_pid()),
    )
    _write_json(goal_dir / "cascade_context_publisher_status.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Run a single publish cycle")
    parser.add_argument("--symbols", default=None, help="Comma-separated symbols; defaults to diagnostic absent symbols sample")
    parser.add_argument("--timeframes", default=None, help="Comma-separated timeframes; defaults to diagnostic absent timeframes")
    parser.add_argument("--goal-dir", default=str(GOAL_DIR))
    parser.add_argument("--no-redis", action="store_true")
    parser.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS)
    parser.add_argument("--interval-seconds", type=int, default=60)
    args = parser.parse_args(argv)
    diagnostic = _read_json_file(DIAGNOSTIC_PATH)
    redis_client = _redis_client(enabled=not args.no_redis)
    fallback_symbols, fallback_timeframes = _symbols_and_timeframes(diagnostic, args.symbols, args.timeframes)
    while True:
        # F015 pattern: this unit can start before Redis accepts connections;
        # a one-shot connect left the loop publishing nothing (redis_writes=0)
        # for its whole lifetime. Reconnect + recompute the pair grid every
        # cycle so the dynamic universe is honored as it grows.
        if redis_client is None and not args.no_redis:
            redis_client = _redis_client(enabled=True)
        coverage = _runtime_coverage(redis_client, symbols_arg=args.symbols, timeframes_arg=args.timeframes)
        if not coverage.get("pairs"):
            pairs = [(symbol, timeframe) for symbol in fallback_symbols for timeframe in fallback_timeframes]
            coverage = {
                **coverage,
                "pairs": pairs,
                "symbols": fallback_symbols,
                "timeframes": fallback_timeframes,
                "coverage_scope": "diagnostic_fallback_symbol_timeframe_sample",
            }
        else:
            pairs = list(coverage["pairs"])
        summary = publish_once(
            redis_client=redis_client,
            pairs=pairs,
            coverage=coverage,
            goal_dir=Path(args.goal_dir),
            ttl_seconds=args.ttl_seconds,
        )
        printable = dict(summary)
        printable["symbols"] = {
            "count": len(summary.get("symbols") or []),
            "major_symbols_covered": (summary.get("coverage") or {}).get("major_symbols_covered"),
        }
        coverage_print = dict(printable.get("coverage") or {})
        coverage_print.pop("pairs", None)
        printable["coverage"] = coverage_print
        print(json.dumps(printable, indent=2, sort_keys=True), flush=True)
        if args.once:
            break
        time.sleep(max(5, int(args.interval_seconds)))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
