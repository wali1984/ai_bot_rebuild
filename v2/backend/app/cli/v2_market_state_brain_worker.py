"""V2 Market State Brain Worker — classify every active symbol/timeframe.

Runs every 30 seconds. For each symbol/TF in the active feature universe,
reads the feature snapshot from Redis and produces a market state classification.
Writes results to:
  v2:market_brain:state:{symbol}:{tf}   (per-symbol-TF result)
  v2:market_brain:overview              (aggregated summary for dashboard)

Never places orders. Never reads live credentials. Read-only from feature Redis.
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
BRAIN_STATE_KEY_PREFIX = f"{V2_REDIS_PREFIX}market_brain:state:"
BRAIN_OVERVIEW_KEY = f"{V2_REDIS_PREFIX}market_brain:overview"
BRAIN_TTL_SECONDS = 120  # Keys expire after 2 minutes if worker stops
STATUS_OUTPUT_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_market_state_brain/latest/v2_market_state_brain_status.json"
)
ACTIVE_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h"]
PRIORITY_TIMEFRAMES = ["1h", "4h", "15m"]


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _connect_redis() -> Any:
    import os
    import redis  # type: ignore
    url = os.getenv("V2_REDIS_URL") or os.getenv("REDIS_URL") or "redis://127.0.0.1:6379/0"
    r = redis.Redis.from_url(url, decode_responses=True, socket_timeout=2.0)
    r.ping()
    return r


def _get_active_symbols(r: Any) -> list[str]:
    """Get the active feature symbol universe from Redis keys."""
    keys = r.keys(f"{V2_REDIS_PREFIX}features:latest:*:1h")
    symbols = []
    for k in keys:
        parts = k.split(":")
        if len(parts) >= 4:
            symbols.append(parts[3].upper())
    return sorted(set(symbols))


def _read_feature_snapshot(r: Any, symbol: str, timeframe: str) -> dict[str, Any] | None:
    key = f"{V2_REDIS_PREFIX}features:latest:{symbol}:{timeframe}"
    raw = r.get(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _read_active_hedge_locks(r: Any) -> set[str]:
    """Return set of symbols that have active hedge locks."""
    pattern = f"{V2_REDIS_PREFIX}paper:hedge_locks:*"
    locked = set()
    for key in r.keys(pattern):
        try:
            raw = r.get(key)
            if raw:
                data = json.loads(raw)
                if data.get("status") == "LOCKED":
                    locked.add(str(data.get("symbol", "")).upper())
        except Exception:
            pass
    return locked


def run_once(r: Any) -> dict[str, Any]:
    from v2.backend.app.services.market_state_brain import classify_market_state

    started = _utc_iso()
    symbols = _get_active_symbols(r)
    hedge_locked_symbols = _read_active_hedge_locks(r)

    state_counts: dict[str, int] = {}
    all_results: list[dict[str, Any]] = []
    processed = 0
    errors = 0

    for symbol in symbols:
        for tf in PRIORITY_TIMEFRAMES:
            feature = _read_feature_snapshot(r, symbol, tf)
            if not feature:
                continue
            try:
                result = classify_market_state(
                    symbol=symbol,
                    timeframe=tf,
                    feature=feature.get("features") or feature,
                    hedge_lock_active=(symbol in hedge_locked_symbols),
                )
                result_dict = result.to_dict()
                result_dict["generated_utc"] = _utc_iso()

                # Write per-symbol-TF key to Redis
                state_key = f"{BRAIN_STATE_KEY_PREFIX}{symbol}:{tf}"
                r.set(state_key, json.dumps(result_dict), ex=BRAIN_TTL_SECONDS)

                state_counts[result.state.value] = state_counts.get(result.state.value, 0) + 1
                all_results.append(result_dict)
                processed += 1
            except Exception as exc:
                errors += 1
                all_results.append({
                    "symbol": symbol, "timeframe": tf,
                    "state": "NO_TRADE", "evidence_score": 0.0,
                    "reasons": [f"CLASSIFIER_ERROR:{exc}"],
                    "allowed_actions": [],
                    "error": str(exc),
                })

    # Write overview
    overview = {
        "generated_utc": _utc_iso(),
        "started_utc": started,
        "symbols_processed": len(symbols),
        "classifications_computed": processed,
        "errors": errors,
        "state_distribution": state_counts,
        "hedge_locked_symbols": sorted(hedge_locked_symbols),
        "results_sample": all_results[:20],  # First 20 for overview
        "places_real_order": False,
    }
    r.set(BRAIN_OVERVIEW_KEY, json.dumps(overview), ex=BRAIN_TTL_SECONDS)

    # Write operator_runtime status file
    STATUS_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_OUTPUT_PATH.write_text(json.dumps({
        **overview,
        "worker": "v2_market_state_brain_worker",
        "status": "RUNNING",
        "cycle_interval_seconds": 30,
    }, indent=2))

    return overview


def main() -> None:
    parser = argparse.ArgumentParser(description="V2 Market State Brain Worker")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    parser.add_argument("--interval", type=int, default=30, help="Cycle interval seconds")
    args = parser.parse_args()

    r = _connect_redis()
    print(f"[market_brain] Worker started at {_utc_iso()}", flush=True)

    if args.once:
        result = run_once(r)
        print(f"[market_brain] Cycle complete: {result['classifications_computed']} classified, "
              f"{result['errors']} errors", flush=True)
        return

    while True:
        try:
            result = run_once(r)
            print(
                f"[market_brain] {_utc_iso()} — {result['classifications_computed']} states, "
                f"dist={result['state_distribution']}",
                flush=True,
            )
        except Exception as exc:
            print(f"[market_brain] ERROR in cycle: {exc}", file=sys.stderr, flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
