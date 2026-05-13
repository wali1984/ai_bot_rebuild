#!/usr/bin/env python3
"""
Live CoinAnk Global Aggregator
==============================

Problem (CoinAnk gap):
`rl/hybrid_trainer.py::_load_global_features()` expects 11 keys:
  - features:global_coinank:total_oi:latest
  - features:global_coinank:total_volume:latest
  - features:global_coinank:total_liquidations:latest
  - features:global_coinank:long_short_ratio:latest
  - features:global_coinank:funding_rate_avg:latest
  - features:global_coinank:btc_dominance:latest
  - features:global_coinank:eth_dominance:latest
  - features:global_coinank:alt_season_index:latest
  - features:global_coinank:fear_greed:latest
  - features:global_coinank:market_sentiment:latest
  - features:global_coinank:volatility_index:latest

But `ingest/live_coinank.py` only writes:
  - features:global_coinank:{endpoint}:latest

This service bridges the gap by computing dynamic, freshness-aware *universe-level*
metrics from `unified_features:{symbol}:15m` (and CoinAnk-derived fields inside it),
then writing the 11 keys in the simple `{value: ...}` contract expected by the trainer.

Design notes:
- This is NOT a static-threshold system; it computes dynamic aggregates from the live universe.
- Dominance is computed as *derivatives OI share* inside our traded universe (not marketcap).
- Writes are lightweight (17 symbols × 1 hash read each cycle in typical configs).
"""

from __future__ import annotations

import json
import os
import sys
import time
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import redis

# Ensure project root is importable (so `import config` works when running from ingest/)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


logger = logging.getLogger("coinank_global_aggregator")


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        if isinstance(x, (bytes, bytearray)):
            x = x.decode("utf-8", errors="ignore")
        return float(x)
    except Exception:
        return default


def _first_float(h: Dict[str, Any], keys: Iterable[str]) -> Optional[float]:
    for k in keys:
        if k in h:
            try:
                return _safe_float(h.get(k), None)  # type: ignore[arg-type]
            except Exception:
                continue
    return None


def get_redis() -> redis.Redis:
    url = (os.getenv("REDIS_URL") or "").strip()
    if url:
        return redis.Redis.from_url(url, decode_responses=True)
    return redis.Redis(
        host=os.getenv("REDIS_HOST", "127.0.0.1"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        db=int(os.getenv("REDIS_DB", "0")),
        decode_responses=True,
    )


def _acquire_lock(r: redis.Redis, lock_key: str, ttl_sec: int) -> bool:
    try:
        # Best-effort single-instance lock.
        return bool(r.set(lock_key, str(time.time()), nx=True, ex=max(5, int(ttl_sec))))
    except Exception:
        return False


def _refresh_lock(r: redis.Redis, lock_key: str, ttl_sec: int) -> None:
    try:
        r.expire(lock_key, max(5, int(ttl_sec)))
    except Exception:
        pass


def _write_value(r: redis.Redis, key: str, value: float, now_ms: int, ttl_sec: int, extra: Optional[Dict[str, Any]] = None) -> None:
    payload: Dict[str, Any] = {
        "ts_ms": now_ms,
        "timestamp": now_ms,
        "value": float(value),
        "source": "coinank_global_aggregator",
    }
    if extra:
        payload.update(extra)
    r.set(key, json.dumps(payload))
    if ttl_sec > 0:
        r.expire(key, int(ttl_sec))


def compute_and_persist(r: redis.Redis, symbols: List[str], tf: str, ttl_sec: int) -> Dict[str, float]:
    now_ms = int(time.time() * 1000)

    # Pull per-symbol unified features (CoinAnk-derived fields live inside these hashes).
    feats_by_sym: Dict[str, Dict[str, Any]] = {}
    for sym in symbols:
        try:
            h = r.hgetall(f"unified_features:{sym}:{tf}") or {}
        except Exception:
            h = {}
        feats_by_sym[sym] = h

    # --- Open interest (universe-level) ---
    oi_by_sym: Dict[str, float] = {}
    for sym, h in feats_by_sym.items():
        oi = _first_float(
            h,
            (
                "open_interest",
                "coinank_openInterest_kline_data_0_close",
                "coinank_openInterest_symbol_Chart_data_0_close",
                "coinank_openInterest_v2_chart_data_0_close",
            ),
        )
        if oi is None or oi <= 0:
            continue
        oi_by_sym[sym] = float(oi)

    total_oi = float(sum(oi_by_sym.values()))

    btc_oi = float(oi_by_sym.get("BTCUSDT", 0.0))
    eth_oi = float(oi_by_sym.get("ETHUSDT", 0.0))

    btc_dom = (btc_oi / total_oi * 100.0) if total_oi > 0 else 0.0
    eth_dom = (eth_oi / total_oi * 100.0) if total_oi > 0 else 0.0

    # --- Funding (avg across universe) ---
    funding_vals: List[float] = []
    for _, h in feats_by_sym.items():
        fr = _first_float(
            h,
            (
                "funding_rate",
                "coinank_fundingRate_kline_data_0_close",
                "coinank_fundingRate_kline_data_0_open",
                "coinank_fundingRate_indicator_data_0_fundingRate",
                "coinank_fundingRate_indicator_data_0_fr",
                "coinank_fundingRate_getWeiFr_data_0_weightedFundingRate",
                "coinank_fundingRate_getWeiFr_data_0_fr",
            ),
        )
        if fr is None:
            continue
        # Funding can be tiny; keep it even if near zero.
        funding_vals.append(float(fr))
    funding_avg = float(sum(funding_vals) / len(funding_vals)) if funding_vals else 0.0

    # --- Long/short ratio (avg across universe) ---
    lsr_vals: List[float] = []
    for _, h in feats_by_sym.items():
        lsr = _first_float(
            h,
            (
                "coinank_ls_global_account_ratio_longShortRatio_mean",
                "coinank_ls_toptrader_accounts_longShortRatio_first",
                "coinank_ls_toptrader_accounts_longShortRatio_mean",
                "coinank_ls_toptrader_positions_longShortRatio_first",
                "coinank_ls_toptrader_positions_longShortRatio_mean",
                "coinank_ls_buy_sell_data_0_longShortRatio",
                "coinank_ls_buy_sell_data_0_longRatio",
            ),
        )
        if lsr is None or lsr <= 0:
            continue
        lsr_vals.append(float(lsr))
    long_short_ratio = float(sum(lsr_vals) / len(lsr_vals)) if lsr_vals else 0.0

    # --- Liquidations (universe total; USD turnover preferred) ---
    liq_total = 0.0
    for _, h in feats_by_sym.items():
        long_turn = _first_float(h, ("coinank_liquidation_history_data_0_longTurnover", "liq_long_usd"))
        short_turn = _first_float(h, ("coinank_liquidation_history_data_0_shortTurnover", "liq_short_usd"))
        if long_turn is None and short_turn is None:
            continue
        liq_total += float(long_turn or 0.0) + float(short_turn or 0.0)

    # --- Volume (universe total; CoinAnk buy/sell value preferred) ---
    buy_total = 0.0
    sell_total = 0.0
    for _, h in feats_by_sym.items():
        buy_v = _first_float(
            h,
            (
                "coinank_marketOrder_getBuySellValue_data_col1_last",
                "coinank_marketOrder_getBuySellValue_data_col1_mean",
                "coinank_marketOrder_getAggBuySellValue_data_col1_last",
                "coinank_marketOrder_getAggBuySellValue_data_col1_mean",
                "coinank_marketOrder_getCvd_data_col1_last",
                "coinank_marketOrder_getAggCvd_data_col1_last",
            ),
        )
        sell_v = _first_float(
            h,
            (
                "coinank_marketOrder_getBuySellValue_data_col2_last",
                "coinank_marketOrder_getBuySellValue_data_col2_mean",
                "coinank_marketOrder_getAggBuySellValue_data_col2_last",
                "coinank_marketOrder_getAggBuySellValue_data_col2_mean",
            ),
        )
        if buy_v is None and sell_v is None:
            continue
        buy_total += float(buy_v or 0.0)
        sell_total += float(sell_v or 0.0)
    total_volume = float(buy_total + sell_total)

    # --- Market sentiment (orderflow ratio -1..+1) ---
    denom = max(1e-9, buy_total + sell_total)
    market_sentiment = float((buy_total - sell_total) / denom)

    # --- Volatility index (avg NATR; scaled to ~0..100 range) ---
    natr_vals: List[float] = []
    for _, h in feats_by_sym.items():
        natr = _first_float(
            h,
            (
                "ind_ta_NATR_28_15m",
                "ind_ta_NATR_21_15m",
            ),
        )
        if natr is None:
            continue
        natr_vals.append(float(natr))
    volatility_index = float(sum(natr_vals) / len(natr_vals) * 100.0) if natr_vals else 0.0

    # --- Fear/Greed (avg RSI across universe; already 0..100) ---
    rsi_vals: List[float] = []
    for _, h in feats_by_sym.items():
        rsi = _first_float(h, ("ind_ta_RSI_14_15m", "ind_ta_RSI_21_15m", "ind_ta_RSI_28_15m"))
        if rsi is None:
            continue
        rsi_vals.append(float(rsi))
    fear_greed = float(sum(rsi_vals) / len(rsi_vals)) if rsi_vals else 0.0

    # --- Alt season index (alts outperform BTC over 15m; 0..100) ---
    btc_ret = _safe_float(feats_by_sym.get("BTCUSDT", {}).get("ccxt_price_change_15m_pct"), 0.0)
    alts = [s for s in symbols if s not in ("BTCUSDT",)]
    outperf = 0
    outperf_n = 0
    for sym in alts:
        ret = _safe_float(feats_by_sym.get(sym, {}).get("ccxt_price_change_15m_pct"), None)  # type: ignore[arg-type]
        if ret is None:
            continue
        outperf_n += 1
        if float(ret) > float(btc_ret):
            outperf += 1
    alt_season_index = float(outperf / outperf_n * 100.0) if outperf_n > 0 else 0.0

    # Write keys (trainer contract: prefers data['value']).
    _write_value(r, "features:global_coinank:total_oi:latest", total_oi, now_ms, ttl_sec, {"n": len(oi_by_sym)})
    _write_value(r, "features:global_coinank:total_volume:latest", total_volume, now_ms, ttl_sec)
    _write_value(r, "features:global_coinank:total_liquidations:latest", liq_total, now_ms, ttl_sec)
    _write_value(r, "features:global_coinank:long_short_ratio:latest", long_short_ratio, now_ms, ttl_sec, {"n": len(lsr_vals)})
    _write_value(r, "features:global_coinank:funding_rate_avg:latest", funding_avg, now_ms, ttl_sec, {"n": len(funding_vals)})
    _write_value(r, "features:global_coinank:btc_dominance:latest", btc_dom, now_ms, ttl_sec)
    _write_value(r, "features:global_coinank:eth_dominance:latest", eth_dom, now_ms, ttl_sec)
    _write_value(r, "features:global_coinank:alt_season_index:latest", alt_season_index, now_ms, ttl_sec, {"n": outperf_n})
    _write_value(r, "features:global_coinank:fear_greed:latest", fear_greed, now_ms, ttl_sec, {"n": len(rsi_vals)})
    _write_value(r, "features:global_coinank:market_sentiment:latest", market_sentiment, now_ms, ttl_sec)
    _write_value(r, "features:global_coinank:volatility_index:latest", volatility_index, now_ms, ttl_sec, {"n": len(natr_vals)})

    try:
        r.set("meta:coinank_global:last_update", str(now_ms))
        if ttl_sec > 0:
            r.expire("meta:coinank_global:last_update", int(ttl_sec))
    except Exception:
        pass

    return {
        "total_oi": total_oi,
        "total_volume": total_volume,
        "total_liquidations": liq_total,
        "long_short_ratio": long_short_ratio,
        "funding_rate_avg": funding_avg,
        "btc_dominance": btc_dom,
        "eth_dominance": eth_dom,
        "alt_season_index": alt_season_index,
        "fear_greed": fear_greed,
        "market_sentiment": market_sentiment,
        "volatility_index": volatility_index,
    }


def main() -> int:
    logging.basicConfig(
        level=os.getenv("COINANK_GLOBAL_AGG_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )

    interval_sec = int(os.getenv("COINANK_GLOBAL_AGG_INTERVAL_SEC", "30"))
    ttl_sec = int(os.getenv("COINANK_GLOBAL_AGG_TTL_SEC", str(max(60, interval_sec * 4))))
    tf = str(os.getenv("COINANK_GLOBAL_AGG_TF", "15m")).strip() or "15m"

    # Symbols from dynamic symbol manager or config fallback
    try:
        from utils.symbol_manager import get_symbols_cached
        symbols = get_symbols_cached()
    except ImportError:
        try:
            from config import get_live_config
            cfg = get_live_config()
            symbols = list(getattr(cfg, "SYMBOLS", []) or [])
        except Exception:
            symbols = []

    if not symbols:
        logger.error("No symbols configured; cannot aggregate")
        return 2

    r = get_redis()
    r.ping()

    lock_key = os.getenv("COINANK_GLOBAL_AGG_LOCK_KEY", "lock:live_coinank_global_aggregator")
    if not _acquire_lock(r, lock_key, ttl_sec=max(60, interval_sec * 4)):
        logger.warning(f"Lock held: {lock_key} (another instance running?)")
        return 0

    logger.info(
        f"✅ CoinAnk global aggregator started | symbols={len(symbols)} tf={tf} | "
        f"interval={interval_sec}s ttl={ttl_sec}s"
    )

    loops = 0
    while True:
        loops += 1
        t0 = time.time()
        try:
            stats = compute_and_persist(r, symbols, tf=tf, ttl_sec=ttl_sec)
            if loops % max(1, int(os.getenv("COINANK_GLOBAL_AGG_LOG_EVERY", "10"))) == 0:
                logger.info(
                    "GLOBAL_COINANK | "
                    f"oi={stats['total_oi']:.2f} vol={stats['total_volume']:.2f} liq={stats['total_liquidations']:.2f} "
                    f"lsr={stats['long_short_ratio']:.3f} fund={stats['funding_rate_avg']:+.6f} "
                    f"btc_dom={stats['btc_dominance']:.1f}% eth_dom={stats['eth_dominance']:.1f}% "
                    f"alt={stats['alt_season_index']:.1f} fear_greed={stats['fear_greed']:.1f} "
                    f"sent={stats['market_sentiment']:+.3f} vol_idx={stats['volatility_index']:.2f}"
                )
        except Exception as e:
            logger.exception(f"Global aggregation failed: {e}")

        _refresh_lock(r, lock_key, ttl_sec=max(60, interval_sec * 4))

        dt = time.time() - t0
        sleep_s = max(1.0, float(interval_sec) - float(dt))
        time.sleep(sleep_s)


if __name__ == "__main__":
    raise SystemExit(main())


