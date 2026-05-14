"""
CoinAnk Signal Adapter (freshness-aware)
========================================

Single place to read CoinAnk-derived features in a consistent, staleness-aware way.

Why:
- CoinAnk data can arrive via multiple paths:
  - Flattened `coinank_*` fields inside `unified_features:{symbol}:{tf}` (preferred)
  - Aggregated global keys `features:global_coinank:*:latest` (written by aggregator)
- Downstream modules historically mixed legacy keys and suffered silent-zero bugs.

This adapter provides:
- Best-effort extraction of key derivatives signals (OI, funding, long/short, liq, orderflow)
- Freshness checks using timestamps inside payloads / unified feature ts fields

NOTE:
- This does not add static decision thresholds; it only returns data + quality metadata.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        if isinstance(x, (bytes, bytearray)):
            x = x.decode("utf-8", errors="ignore")
        return float(x)
    except Exception:
        return default


def _first_float(h: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[float]:
    for k in keys:
        if k in h:
            try:
                v = _safe_float(h.get(k), None)  # type: ignore[arg-type]
            except Exception:
                v = None
            if v is not None:
                return float(v)
    return None


def _safe_json_loads(raw: Any) -> Dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="ignore")
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


@dataclass
class CoinAnkSignalSet:
    symbol: str
    tf: str
    ts_ms: int
    freshness_ms: float
    ok: bool
    signals: Dict[str, float]


class CoinAnkSignalAdapter:
    def __init__(self, redis_client, *, default_tf: str = "15m"):
        self.redis = redis_client
        self.default_tf = default_tf

    # ---------------------------------------------------------------------
    # Unified per-symbol signals
    # ---------------------------------------------------------------------
    def get_symbol_signals(self, symbol: str, tf: Optional[str] = None) -> CoinAnkSignalSet:
        tf = (tf or self.default_tf or "15m").strip()
        now_ms = int(time.time() * 1000)

        h: Dict[str, Any] = {}
        try:
            h = self.redis.hgetall(f"unified_features:{symbol}:{tf}") or {}
        except Exception:
            h = {}

        # unified hash may be bytes; normalize values lazily via _safe_float
        ts_ms = 0
        try:
            ts_ms = int(_safe_float(h.get("ts_epoch_ms", h.get("timestamp", 0)), 0.0))
        except Exception:
            ts_ms = 0
        if 0 < ts_ms < 1_000_000_000_000:
            ts_ms *= 1000
        freshness_ms = float(now_ms - ts_ms) if ts_ms > 0 else 9e9

        signals: Dict[str, float] = {}

        # Funding
        fr = _first_float(
            h,
            (
                "funding_rate",
                "coinank_fundingRate_kline_data_0_close",
                "coinank_fundingRate_kline_data_0_open",
                "coinank_fundingRate_indicator_data_0_fundingRate",
                "coinank_fundingRate_indicator_data_0_fr",
            ),
        )
        if fr is not None:
            signals["funding_rate"] = float(fr)

        # OI total + change (kline open/close)
        oi_total = _first_float(
            h,
            (
                "open_interest",
                "coinank_openInterest_kline_data_0_close",
                "coinank_openInterest_symbol_Chart_data_0_close",
            ),
        )
        if oi_total is not None:
            signals["oi_total"] = float(oi_total)

        oi_open = _first_float(h, ("coinank_openInterest_kline_data_0_open",))
        oi_close = _first_float(h, ("coinank_openInterest_kline_data_0_close",))
        if oi_open is not None and oi_close is not None and float(oi_open) > 0:
            signals["oi_change"] = (float(oi_close) - float(oi_open)) / float(oi_open)

        # Long/short ratio
        lsr = _first_float(
            h,
            (
                "coinank_ls_global_account_ratio_longShortRatio_mean",
                "coinank_ls_toptrader_accounts_longShortRatio_first",
                "coinank_ls_toptrader_accounts_longShortRatio_mean",
            ),
        )
        if lsr is not None:
            signals["long_short_ratio"] = float(lsr)

        # Liquidations (USD turnover preferred)
        long_liq = _first_float(h, ("coinank_liquidation_history_data_0_longTurnover", "liq_long_usd"))
        short_liq = _first_float(h, ("coinank_liquidation_history_data_0_shortTurnover", "liq_short_usd"))
        if long_liq is not None or short_liq is not None:
            signals["liq_long_usd"] = float(long_liq or 0.0)
            signals["liq_short_usd"] = float(short_liq or 0.0)
            signals["liq_total_usd"] = float(long_liq or 0.0) + float(short_liq or 0.0)

        # Orderflow buy/sell value (proxy for volume + sentiment)
        buy_v = _first_float(h, ("coinank_marketOrder_getBuySellValue_data_col1_last", "coinank_marketOrder_getBuySellValue_data_col1_mean"))
        sell_v = _first_float(h, ("coinank_marketOrder_getBuySellValue_data_col2_last", "coinank_marketOrder_getBuySellValue_data_col2_mean"))
        if buy_v is not None or sell_v is not None:
            b = float(buy_v or 0.0)
            s = float(sell_v or 0.0)
            signals["buy_value_usd"] = b
            signals["sell_value_usd"] = s
            denom = max(1e-9, b + s)
            signals["orderflow_sentiment"] = (b - s) / denom  # -1..+1
            signals["orderflow_total_value_usd"] = b + s

        ok = bool(signals)
        return CoinAnkSignalSet(symbol=symbol, tf=tf, ts_ms=ts_ms, freshness_ms=freshness_ms, ok=ok, signals=signals)

    # ---------------------------------------------------------------------
    # Global signals (from aggregator keys)
    # ---------------------------------------------------------------------
    def get_global_signals(self) -> Dict[str, Any]:
        keys = {
            "total_oi": "features:global_coinank:total_oi:latest",
            "total_volume": "features:global_coinank:total_volume:latest",
            "total_liquidations": "features:global_coinank:total_liquidations:latest",
            "long_short_ratio": "features:global_coinank:long_short_ratio:latest",
            "funding_rate_avg": "features:global_coinank:funding_rate_avg:latest",
            "btc_dominance": "features:global_coinank:btc_dominance:latest",
            "eth_dominance": "features:global_coinank:eth_dominance:latest",
            "alt_season_index": "features:global_coinank:alt_season_index:latest",
            "fear_greed": "features:global_coinank:fear_greed:latest",
            "market_sentiment": "features:global_coinank:market_sentiment:latest",
            "volatility_index": "features:global_coinank:volatility_index:latest",
        }
        out: Dict[str, Any] = {"ts_ms": 0, "freshness_ms": 9e9, "ok": False, "signals": {}}
        now_ms = int(time.time() * 1000)

        best_ts = 0
        sig: Dict[str, float] = {}
        for name, key in keys.items():
            raw = None
            try:
                raw = self.redis.get(key)
            except Exception:
                raw = None
            rec = _safe_json_loads(raw)
            v = rec.get("value")
            if v is None:
                continue
            try:
                sig[name] = float(v)
            except Exception:
                continue
            try:
                ts = int(float(rec.get("ts_ms") or rec.get("timestamp") or 0))
            except Exception:
                ts = 0
            if ts > best_ts:
                best_ts = ts

        out["signals"] = sig
        out["ok"] = bool(sig)
        out["ts_ms"] = int(best_ts)
        out["freshness_ms"] = float(now_ms - best_ts) if best_ts > 0 else 9e9
        return out


def get_coinank_adapter(redis_client) -> CoinAnkSignalAdapter:
    return CoinAnkSignalAdapter(redis_client)


