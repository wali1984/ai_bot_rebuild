"""V2 native opportunity tracker publisher.

Ports legacy trading/opportunity_tracker.py to V2.

Reads v2:paper:position_history:{sym} keys for all active symbols,
computes per-symbol opportunity scores (shadow observations, favorable
excursions, unrealized bps, position state), ranks symbols by
opportunity quality, and writes:

  v2:opportunity:{sym}           (TTL=900s)
  v2:opportunity:summary         (TTL=900s)
  v2/frontend/public/operator_runtime/v2_opportunity_tracker/latest/
    v2_opportunity_tracker_status.json

No live trading, no order placement, no old Redis writes.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

V2_REDIS_PREFIX = "v2:"
OPPORTUNITY_TTL_S = 900
PAYLOAD_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_opportunity_tracker/latest/"
    "v2_opportunity_tracker_status.json"
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _connect_redis():
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        r = redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=3,
        )
        r.ping()
        return r
    except Exception:
        return None


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def _score_opportunity(pos: dict) -> float:
    """Compute a simple opportunity quality score (0-100).

    Higher = more favorable paper shadow signal.
    Inputs: mfe_bps, shadow_observation_count, source_freshness_seconds.
    """
    mfe = _safe_float(pos.get("mfe_bps"), 0.0)
    shadow = _safe_float(pos.get("shadow_observation_count"), 0)
    freshness = _safe_float(pos.get("source_freshness_seconds"), 9999)

    # Freshness penalty: older than 300s is stale
    freshness_factor = max(0.0, 1.0 - (freshness / 600.0))
    score = (mfe * 0.5) + (shadow * 5.0 * freshness_factor)
    return round(min(100.0, max(0.0, score)), 2)


def run_once(write_redis: bool = True) -> dict:
    r = _connect_redis()
    now_utc = _utc_iso()

    symbols_scanned = 0
    symbols_active = 0
    opportunity_rows: list[dict] = []
    redis_write_errors: list[str] = []

    if r:
        # Bounded, cursor-based scan — never a blocking KEYS on the ~1.58M-key
        # shared store (this loop runs every 300s and KEYS freezes the
        # single-threaded server for the full O(N) keyspace, stalling the paper
        # loop / trainer / feature pipeline that share the instance).
        pos_keys: list[str] = []
        _cursor = 0
        while True:
            _cursor, _batch = r.scan(cursor=_cursor, match="v2:paper:position_history:*", count=1000)
            pos_keys.extend(_batch)
            if _cursor == 0 or len(pos_keys) >= 20000:
                break
        symbols_scanned = len(pos_keys)

        for key in pos_keys:
            sym = key.split("v2:paper:position_history:")[-1]
            raw = r.get(key)
            if not raw:
                continue
            try:
                pos = json.loads(raw)
            except Exception:
                continue

            score = _score_opportunity(pos)
            position_state = pos.get("position_state", "none")
            shadow_count = int(_safe_float(pos.get("shadow_observation_count"), 0))
            mfe_bps = _safe_float(pos.get("mfe_bps"), 0.0)
            mae_bps = _safe_float(pos.get("mae_bps"), 0.0)
            unrealized_bps = _safe_float(pos.get("unrealized_bps"), 0.0)
            freshness_s = _safe_float(pos.get("source_freshness_seconds"), 9999.0)
            side = pos.get("side", "unknown")

            row = {
                "symbol": sym,
                "score": score,
                "position_state": position_state,
                "side": side,
                "shadow_observation_count": shadow_count,
                "mfe_bps": mfe_bps,
                "mae_bps": mae_bps,
                "unrealized_bps": unrealized_bps,
                "source_freshness_seconds": freshness_s,
                "opportunity_class": (
                    "HIGH" if score >= 10
                    else "MEDIUM" if score >= 3
                    else "LOW"
                ),
                "generated_utc": now_utc,
            }
            opportunity_rows.append(row)

            if shadow_count > 0 or position_state not in ("none", ""):
                symbols_active += 1

            if write_redis and r:
                opp_key = f"{V2_REDIS_PREFIX}opportunity:{sym}"
                try:
                    r.setex(opp_key, OPPORTUNITY_TTL_S, json.dumps(row))
                except Exception as exc:
                    redis_write_errors.append(f"{sym}: {exc}")

    # Sort by score descending
    opportunity_rows.sort(key=lambda x: x["score"], reverse=True)
    top_symbols = [row["symbol"] for row in opportunity_rows[:5]]
    high_count = sum(1 for row in opportunity_rows if row["opportunity_class"] == "HIGH")
    medium_count = sum(1 for row in opportunity_rows if row["opportunity_class"] == "MEDIUM")

    classification = (
        "OPPORTUNITY_TRACKER_OK" if symbols_scanned > 0
        else "OPPORTUNITY_TRACKER_NO_DATA"
    )

    summary = {
        "schema_version": "v2_native_opportunity_tracker_v1",
        "classification": classification,
        "generated_utc": now_utc,
        "symbols_scanned": symbols_scanned,
        "symbols_active": symbols_active,
        "high_opportunity_count": high_count,
        "medium_opportunity_count": medium_count,
        "top_symbols": top_symbols,
        "opportunity_rows": opportunity_rows[:10],  # top 10 for payload
        "redis_write_errors": redis_write_errors,
        "live_safety": {
            "live_gate_status": "blocked_human_only",
            "live_symbols": [],
            "writes_exchange_orders": False,
            "writes_legacy_redis": False,
        },
    }

    if write_redis and r:
        try:
            r.setex(
                f"{V2_REDIS_PREFIX}opportunity:summary",
                OPPORTUNITY_TTL_S,
                json.dumps(summary),
            )
        except Exception as exc:
            redis_write_errors.append(f"summary: {exc}")

    PAYLOAD_PATH.parent.mkdir(parents=True, exist_ok=True)
    PAYLOAD_PATH.write_text(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="V2 opportunity tracker publisher")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--loop", action="store_true", help="Run in loop")
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--no-redis", action="store_true")
    args = parser.parse_args()

    write_redis = not args.no_redis

    if args.loop:
        while True:
            try:
                result = run_once(write_redis=write_redis)
                print(
                    f"v2_opportunity_tracker_written classification={result['classification']}"
                    f" symbols_scanned={result['symbols_scanned']}"
                    f" high={result['high_opportunity_count']}"
                    f" top={result['top_symbols'][:3]}"
                )
            except Exception as exc:
                print(f"v2_opportunity_tracker_error: {exc}", file=sys.stderr)
            time.sleep(args.interval_seconds)
    else:
        result = run_once(write_redis=write_redis)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
