#!/usr/bin/env python3
"""
Validate real-time Redis data coverage for the configured trading universe.

Focus:
- Ensures BOTH legacy + newly-added symbols have the required real-time keys.
- Checks freshness (staleness) with TF-aware thresholds.
- Read-only: does not start/stop services.

Usage:
    python3 scripts/validate_symbol_universe_data.py

Env overrides:
    REDIS_URL=redis://localhost:6379/0
    VALIDATE_ORDERBOOK_STALE_SEC=10
    VALIDATE_FAST_TF_MAX_AGE_SEC=90
    VALIDATE_SLOW_TF_MAX_AGE_SEC=600
    VALIDATE_TA=1
    VALIDATE_OHLCV_LIST=1
    VALIDATE_MIN_CANDLES=50
    VALIDATE_EXIT_NONZERO=1
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import redis


def _safe_json_loads(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _parse_ts_ms(val: Any) -> Optional[int]:
    """Parse ts that may be seconds or milliseconds."""
    if val is None:
        return None
    try:
        if isinstance(val, str) and val.strip() == "":
            return None
        ts = float(val)
        # If seconds, upgrade to ms
        if ts < 1e12:
            ts = ts * 1000.0
        return int(ts)
    except Exception:
        return None


def _age_ms(ts_ms: Optional[int], now_ms: int) -> Optional[int]:
    if not ts_ms:
        return None
    return max(0, now_ms - ts_ms)


def main() -> int:
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    orderbook_stale_sec = float(os.getenv("VALIDATE_ORDERBOOK_STALE_SEC", "10"))
    fast_tf_max_age_sec = float(os.getenv("VALIDATE_FAST_TF_MAX_AGE_SEC", "90"))
    slow_tf_max_age_sec = float(os.getenv("VALIDATE_SLOW_TF_MAX_AGE_SEC", "600"))
    validate_ta = os.getenv("VALIDATE_TA", "1").lower() in ("1", "true", "yes", "on")
    validate_ohlcv_list = os.getenv("VALIDATE_OHLCV_LIST", "1").lower() in ("1", "true", "yes", "on")
    min_candles = int(os.getenv("VALIDATE_MIN_CANDLES", "50"))
    exit_nonzero = os.getenv("VALIDATE_EXIT_NONZERO", "1").lower() in ("1", "true", "yes", "on")

    tf_seconds = {
        "1m": 60,
        "5m": 5 * 60,
        "15m": 15 * 60,
        "1h": 60 * 60,
        "4h": 4 * 60 * 60,
    }

    # Ensure project root is importable when running as a script
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    # Load configured universe
    try:
        from config import SYMBOLS, TIMEFRAMES
    except Exception as e:
        print(f"ERROR: failed to import config SYMBOLS/TIMEFRAMES: {e}")
        return 2

    r = redis.Redis.from_url(redis_url, decode_responses=True)
    now_ms = int(time.time() * 1000)

    # CoinAPI OHLCV health (optional but useful)
    coinapi_connected = r.get("metrics:coinapi:v1:connected")
    coinapi_last_ts_s = r.get("metrics:coinapi:v1:last_ohlcv_ts")
    coinapi_age_s = None
    try:
        if coinapi_last_ts_s:
            coinapi_age_s = int(time.time() - float(coinapi_last_ts_s))
    except Exception:
        coinapi_age_s = None

    print("=== Universe Data Validation ===")
    print(f"Redis: {redis_url}")
    print(f"Symbols: {len(SYMBOLS)} | Timeframes: {TIMEFRAMES}")
    print(
        f"CoinAPI v1 connected={coinapi_connected} last_ohlcv_age_s={coinapi_age_s}"
    )
    print(
        f"Thresholds: orderbook<= {orderbook_stale_sec:.0f}s, "
        f"fast_tfs<= {fast_tf_max_age_sec:.0f}s, slow_tfs<= {slow_tf_max_age_sec:.0f}s"
    )
    print(f"Checks: ta={validate_ta} ohlcv_list(binance|coinapi)={validate_ohlcv_list} min_candles={min_candles}")
    print("")

    failures: List[Tuple[str, List[str]]] = []

    for sym in SYMBOLS:
        issues: List[str] = []

        # Orderbook (JSON) freshness
        ob_key = f"orderbook:top:{sym}"
        ob_raw = r.get(ob_key)
        if not ob_raw:
            issues.append("orderbook:missing")
        else:
            ob = _safe_json_loads(ob_raw)
            ob_ts_ms = _parse_ts_ms(ob.get("ts") or ob.get("ts_ms") or ob.get("timestamp"))
            ob_age = _age_ms(ob_ts_ms, now_ms)
            if ob_age is None:
                issues.append("orderbook:bad_ts")
            elif ob_age > int(orderbook_stale_sec * 1000):
                issues.append(f"orderbook:stale({ob_age/1000:.1f}s)")

        # Unified features per timeframe (hash) freshness
        for tf in TIMEFRAMES:
            # TF-aware freshness: allow up to ~2 candles (plus operator-configured floors)
            period = tf_seconds.get(tf)
            base_floor = fast_tf_max_age_sec if tf in ("1m", "5m") else slow_tf_max_age_sec
            max_age = max(base_floor, float(period) * 2.0) if period else base_floor

            # Market OHLCV (JSON) freshness - primary OHLCV input for feature pipeline
            mkt_key = f"market:{sym}:{tf}"
            mkt_raw = r.get(mkt_key)
            if not mkt_raw:
                issues.append(f"market:{tf}:missing")
            else:
                mkt = _safe_json_loads(mkt_raw)
                mkt_ts_ms = _parse_ts_ms(mkt.get("timestamp") or mkt.get("ts") or mkt.get("ts_ms"))
                mkt_age = _age_ms(mkt_ts_ms, now_ms)
                if mkt_age is None:
                    issues.append(f"market:{tf}:bad_ts")
                elif mkt_age > int(max_age * 1000):
                    issues.append(f"market:{tf}:stale({mkt_age/1000:.0f}s)")

            key = f"unified_features:{sym}:{tf}"
            if r.exists(key) != 1:
                issues.append(f"unified:{tf}:missing")
                continue
            ts_field = r.hget(key, "ts_ms") or r.hget(key, "timestamp") or r.hget(key, "ts")
            ts_ms = _parse_ts_ms(ts_field)
            age = _age_ms(ts_ms, now_ms)
            if age is None:
                issues.append(f"unified:{tf}:bad_ts")
                continue
            if age > int(max_age * 1000):
                issues.append(f"unified:{tf}:stale({age/1000:.0f}s)")

            # Unified orderbook-derived fields (critical for ~2000+ feature completeness).
            # Validate on a representative fast TF to avoid duplicating the same check across TFs.
            if tf == "5m":
                mid = r.hget(key, "ob_ob_mid_price")
                spread_bps = r.hget(key, "ob_ob_spread_bps")
                best_bid = r.hget(key, "ob_best_bid")
                best_ask = r.hget(key, "ob_best_ask")
                if not (mid and spread_bps and best_bid and best_ask):
                    issues.append("unified:ob_fields:missing(ob_ob_mid_price/ob_ob_spread_bps/ob_best_bid/ob_best_ask)")

            # TA indicators freshness (hash) - produced by ingest/live_technical_analysis.py
            ta_ok = False
            if validate_ta:
                ta_key = f"ta:{sym}:{tf}"
                if r.exists(ta_key) != 1:
                    issues.append(f"ta:{tf}:missing")
                else:
                    ta_ts_field = r.hget(ta_key, "timestamp") or r.hget(ta_key, "ts_ms") or r.hget(ta_key, "ts")
                    ta_ts_ms = _parse_ts_ms(ta_ts_field)
                    ta_age = _age_ms(ta_ts_ms, now_ms)
                    if ta_age is None:
                        issues.append(f"ta:{tf}:bad_ts")
                    else:
                        # Use same TF-aware budget as unified_features (TA cycle may be slower than 60s overall)
                        if ta_age > int(max_age * 1000):
                            issues.append(f"ta:{tf}:stale({ta_age/1000:.0f}s)")
                        else:
                            ta_ok = True
            else:
                # If TA validation is disabled, treat TA as not OK so OHLCV list becomes the primary
                # health signal for technical analysis inputs.
                ta_ok = False

            # OHLCV rolling lists (Binance preferred, CoinAPI fallback)
            if validate_ohlcv_list:
                ok_any = False
                last_err = None
                for src in ("binance", "coinapi"):
                    lk = f"ohlcv:list:{src}:{sym}:{tf}"
                    if r.exists(lk) != 1:
                        last_err = f"{src}:missing"
                        continue
                    try:
                        n = r.llen(lk)
                        if n < min_candles:
                            last_err = f"{src}:short({n})"
                            continue
                        last_raw = r.lindex(lk, -1)
                        last = _safe_json_loads(last_raw)
                        lts = _parse_ts_ms(last.get("timestamp") or last.get("ts") or last.get("ts_ms"))
                        lage = _age_ms(lts, now_ms)
                        if lage is None:
                            last_err = f"{src}:bad_ts"
                            continue
                        if lage > int(max_age * 1000):
                            last_err = f"{src}:stale({lage/1000:.0f}s)"
                            continue
                        ok_any = True
                        break
                    except Exception as e:
                        last_err = f"{src}:err"
                        continue
                # Only fail on missing/short OHLCV lists when TA is NOT healthy.
                # If TA is healthy, it already implies a usable OHLCV source exists (Redis lists, JSONL, or backfill).
                if (not ok_any) and (not ta_ok):
                    issues.append(f"ohlcv_list:{tf}:{last_err or 'missing'}")

        if issues:
            failures.append((sym, issues))

    if not failures:
        print("✅ PASS: All symbols have fresh orderbook + unified_features coverage")
        return 0

    print(f"❌ FAIL: {len(failures)}/{len(SYMBOLS)} symbols have issues")
    for sym, issues in failures:
        print(f"- {sym}: {', '.join(issues)}")

    return 1 if exit_nonzero else 0


if __name__ == "__main__":
    raise SystemExit(main())


