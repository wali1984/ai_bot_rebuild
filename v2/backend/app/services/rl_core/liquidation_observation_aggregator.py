"""V2-native liquidation observation aggregator (paper-only).

Computes the 12-slot ``liquidations`` subfamily for each symbol from
V2 runtime data only. Reads:

- ``v2:features:latest:{symbol}:{timeframe}.features.last_liq_bps_24h``
  for the only true per-symbol liquidation signal V2 carries today.
- ``v2/frontend/public/operator_runtime/coinank_market_intelligence/latest/
  coinank_market_intelligence_status.json`` for V2-side aggregator state
  (``liquidations_persisted_total``,
  ``global_aggregate_result.total_liquidations``,
  ``freshness_seconds``).

The remainder of the 12 slots are explicitly classified
``MISSING_FROM_V2_LIQUIDATION_AGGREGATOR`` — a per-symbol
liquidation time-series aggregator does NOT exist in V2 today. The
service does NOT zero-fill those slots. It writes the explicit
0.0 probe flag at slot 12 (``v2_liquidation_source_available``)
because that *is* the measured source-availability value.

Never imports torch. Never deserializes any blob. Never modifies
legacy.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

COINANK_INTEL_PATH = Path(
    "v2/frontend/public/operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json"
)


def _coerce_float(value: Any) -> float | None:
    import math
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if isinstance(value, str):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_coinank_intelligence(path: Path | None = None) -> dict[str, Any]:
    p = path if path is not None else COINANK_INTEL_PATH
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def read_v2_liquidation_per_symbol_from(
    redis_client: Any,
    symbol: str,
) -> dict[str, Any]:
    """Read V2-native per-symbol liquidation keys through an existing client.

    Only ``v2:*`` keys are read. Missing/unparseable values return explicit
    empty state rather than fabricated liquidation fields.
    """
    out: dict[str, Any] = {
        "latest": None,
        "aggregate": None,
        "any_populated": False,
        "v2_per_symbol_aggregator_present": False,
    }
    if redis_client is None:
        return out
    try:
        raw_latest = redis_client.get(f"v2:market:liquidations:latest:{symbol}")
    except Exception:
        raw_latest = None
    try:
        raw_aggregate = redis_client.get(f"v2:market:liquidations:aggregate:{symbol}")
    except Exception:
        raw_aggregate = None
    if raw_latest:
        try:
            out["latest"] = json.loads(raw_latest)
        except (ValueError, TypeError):
            out["latest"] = None
    if raw_aggregate:
        try:
            out["aggregate"] = json.loads(raw_aggregate)
        except (ValueError, TypeError):
            out["aggregate"] = None
    out["any_populated"] = bool(out["latest"] or out["aggregate"])
    out["v2_per_symbol_aggregator_present"] = out["any_populated"]
    return out


def _read_v2_liquidation_per_symbol(symbol: str) -> dict[str, Any]:
    """Read V2-native per-symbol liquidation keys with a local Redis client."""
    try:
        import redis  # type: ignore

        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
    except Exception:
        return read_v2_liquidation_per_symbol_from(None, symbol)
    return read_v2_liquidation_per_symbol_from(r, symbol)


def build_liquidation_subfamily(
    symbol: str,
    v2_features: Mapping[str, Any] | None,
    coinank_intel: Mapping[str, Any] | None,
    v2_liquidation_per_symbol: Mapping[str, Any] | None = None,
) -> list[tuple[str, float | None, str]]:
    """Return the 12-slot liquidation subfamily as
    ``(name, value, source)`` tuples (12 entries always)."""
    size = 12
    out: list[tuple[str, float | None, str]] = [
        (f"liquidations[{i}]", None, "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR")
        for i in range(size)
    ]
    feats = v2_features or {}
    intel = coinank_intel or {}
    gar = intel.get("global_aggregate_result") or {}
    last_liq = _coerce_float(feats.get("last_liq_bps_24h"))
    liq_abs = abs(last_liq) if last_liq is not None else None
    liq_direction = (
        None
        if last_liq is None
        else (1.0 if last_liq > 0 else (-1.0 if last_liq < 0 else 0.0))
    )
    total_liquidations = _coerce_float(gar.get("total_liquidations"))
    persisted_total = _coerce_float(intel.get("liquidations_persisted_total"))
    coinank_freshness_seconds = _coerce_float(intel.get("freshness_seconds"))
    liq_notional_24h_proxy = last_liq
    liq_direction_bias = liq_direction
    # V2 per-symbol liquidation aggregator (operator-decision-gated). When
    # ``v2:market:liquidations:latest:{sym}`` and
    # ``v2:market:liquidations:aggregate:{sym}`` are populated by a future
    # V2-owned WSS client, fill the 4 currently-missing slots from them.
    ls = v2_liquidation_per_symbol or {}
    latest_per_sym = (ls.get("latest") or {}) if isinstance(ls.get("latest"), dict) else {}
    aggregate_per_sym = (
        (ls.get("aggregate") or {}) if isinstance(ls.get("aggregate"), dict) else {}
    )
    latest_notional = _coerce_float(latest_per_sym.get("notional"))
    latest_side_raw = (
        (latest_per_sym.get("side") or "").lower() if latest_per_sym else ""
    )
    latest_side_long = (
        1.0
        if latest_side_raw in ("long", "buy")
        else (0.0 if latest_per_sym else None)
    )
    latest_side_short = (
        1.0
        if latest_side_raw in ("short", "sell")
        else (0.0 if latest_per_sym else None)
    )
    aggregate_1h_notional = _coerce_float(aggregate_per_sym.get("notional_1h"))
    v2_liq_source_available = (
        1.0 if ls.get("v2_per_symbol_aggregator_present") else 0.0
    )
    per_symbol_source_flag_src = (
        "V2_MARKET_LIQUIDATIONS_PER_SYMBOL_PRESENT"
        if ls.get("v2_per_symbol_aggregator_present")
        else "V2_PROBE_FLAG_NO_PER_SYMBOL_LIQUIDATION_AGGREGATOR_PRESENT"
    )
    rows: list[tuple[str, float | None, str]] = [
        ("latest_liquidation_notional", latest_notional,
         "V2_MARKET_LIQUIDATIONS_LATEST"
         if latest_notional is not None
         else "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR"),
        ("latest_liquidation_side_long", latest_side_long,
         "V2_MARKET_LIQUIDATIONS_LATEST"
         if latest_side_long is not None
         else "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR"),
        ("latest_liquidation_side_short", latest_side_short,
         "V2_MARKET_LIQUIDATIONS_LATEST"
         if latest_side_short is not None
         else "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR"),
        ("last_liq_bps_24h", last_liq,
         "V2_NATIVE_FEATURE_SNAPSHOT"
         if last_liq is not None
         else "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR"),
        ("last_liq_bps_24h_abs", liq_abs,
         "V2_DERIVED_FROM_FEATURES"
         if liq_abs is not None
         else "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR"),
        ("last_liq_direction", liq_direction,
         "V2_DERIVED_FROM_FEATURES"
         if liq_direction is not None
         else "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR"),
        ("liquidation_count_proxy_global", total_liquidations,
         "V2_COINANK_GLOBAL_AGGREGATE_NOT_PER_SYMBOL"
         if total_liquidations is not None
         else "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR"),
        ("liquidation_notional_1h_proxy", aggregate_1h_notional,
         "V2_MARKET_LIQUIDATIONS_AGGREGATE"
         if aggregate_1h_notional is not None
         else "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR"),
        ("liquidation_notional_24h_proxy", liq_notional_24h_proxy,
         "V2_NATIVE_FEATURE_SNAPSHOT"
         if liq_notional_24h_proxy is not None
         else "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR"),
        ("liquidation_direction_bias", liq_direction_bias,
         "V2_DERIVED_FROM_FEATURES"
         if liq_direction_bias is not None
         else "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR"),
        ("liquidation_freshness_seconds", coinank_freshness_seconds,
         "V2_COINANK_MARKET_INTELLIGENCE"
         if coinank_freshness_seconds is not None
         else "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR"),
        ("v2_liquidation_source_available", v2_liq_source_available,
         per_symbol_source_flag_src),
    ]
    _ = persisted_total
    for i, (nm, val, src) in enumerate(rows[:size]):
        if val is None:
            out[i] = (f"liquidations.{nm}", None,
                      "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR")
        else:
            out[i] = (f"liquidations.{nm}", val, src)
    return out


def build_aggregator_status(
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT"),
    timeframe: str = "1m",
) -> dict[str, Any]:
    intel = load_coinank_intelligence()
    try:
        import redis  # type: ignore

        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
    except Exception:
        r = None
    per_symbol: list[dict[str, Any]] = []
    total_present = 0
    total_target = 0
    any_per_symbol_source = False
    for sym in symbols:
        feats = None
        if r is not None:
            try:
                raw = r.get(f"v2:features:latest:{sym}:{timeframe}")
                if raw:
                    feats = (json.loads(raw) or {}).get("features")
            except Exception:
                feats = None
        per_symbol_data = _read_v2_liquidation_per_symbol(sym)
        any_per_symbol_source = any_per_symbol_source or bool(
            per_symbol_data.get("v2_per_symbol_aggregator_present")
        )
        rows = build_liquidation_subfamily(sym, feats, intel, per_symbol_data)
        present = sum(1 for (_, v, _s) in rows if v is not None)
        missing = sum(1 for (_, v, _s) in rows if v is None)
        total_present += present
        total_target += len(rows)
        per_symbol.append(
            {
                "symbol": sym,
                "subfamily_target": len(rows),
                "subfamily_present": present,
                "subfamily_missing": missing,
                "fields": [
                    {"name": nm, "value": val, "source": src}
                    for (nm, val, src) in rows
                ],
            }
        )
    return {
        "schema_version": "v2_liquidation_observation_aggregator_status_v1",
        "generated_utc": _utc_iso(),
        "target_per_symbol": 12,
        "symbols": list(symbols),
        "per_symbol": per_symbol,
        "subfamily_total_present_across_symbols": total_present,
        "subfamily_total_target_across_symbols": total_target,
        "v2_liquidation_aggregator_per_symbol_source_available": any_per_symbol_source,
        "v2_coinank_intelligence_payload_present": bool(intel),
        "no_zero_fill_for_unknown_fields": True,
        "no_torch_imported": True,
        "no_pickle_loaded": True,
        "no_legacy_filesystem_read": True,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }
