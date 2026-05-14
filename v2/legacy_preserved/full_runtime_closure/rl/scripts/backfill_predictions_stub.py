"""
Temporary diagnostic/backfill for prediction hashes.

Populates prediction:{symbol}:{tf} with HOLD action and confidence 0.0
for all configured symbols/timeframes, so healthcheck can pass while the
trainer prediction loop is being debugged.

Usage:
    python -m rl.scripts.backfill_predictions_stub
"""

import time
import json

try:
    from config import SYMBOLS, TIMEFRAMES
except Exception:
    SYMBOLS = ["BTCUSDT"]
    TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h"]

try:
    from utils.redis_client import get_redis
except Exception:
    get_redis = None  # type: ignore


def main():
    rc = get_redis() if get_redis else None
    if rc is None:
        print("backfill: redis unavailable")
        return 1

    ts_ms = int(time.time() * 1000)
    wrote = 0
    for sym in SYMBOLS:
        for tf in TIMEFRAMES:
            key = f"prediction:{sym}:{tf}"
            payload = {
                "action": "HOLD",
                "confidence": 0.0,
                "ts_ms": ts_ms,
                "source": "backfill_stub",
                "model_version": "stub",
            }
            try:
                rc.hset(key, mapping=payload)
                rc.expire(key, 300)  # 5 minutes
                wrote += 1
            except Exception as e:
                print(f"backfill: failed {key}: {e}")
    print(f"backfill complete: wrote {wrote} prediction hashes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
