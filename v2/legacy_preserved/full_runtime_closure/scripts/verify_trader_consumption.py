#!/usr/bin/env python3
"""
Health check for trader signal consumption and skip reasons.

- Checks Redis markers set by traders:
    trader:{account}:last_consumed_ts_ms
    trader:{account}:last_consumed_id
- Reads last 20 skip entries from signals:execution:skips.
- Exits non-zero if any trader stalled (>60s since last consume).
"""
import os
import sys
import json
import time
import redis
from typing import List


def read_int(val, default=0):
    try:
        return int(val)
    except Exception:
        return default


def main():
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    r = redis.Redis.from_url(redis_url, decode_responses=True)

    accounts = os.getenv("TRADER_ACCOUNTS", "primary,asjad").split(",")
    accounts = [a.strip() for a in accounts if a.strip()]
    now_ms = int(time.time() * 1000)

    stalled = []
    print("=== Trader Consumption Health ===")
    for acct in accounts:
        ts_key = f"trader:{acct}:last_consumed_ts_ms"
        id_key = f"trader:{acct}:last_consumed_id"
        last_ts = read_int(r.get(ts_key))
        last_id = r.get(id_key)
        age_ms = now_ms - last_ts if last_ts else None
        status = "OK"
        if not last_ts:
            status = "NO_DATA"
        elif age_ms > 60_000:
            status = "STALED"
            stalled.append(acct)
        print(f"account={acct} status={status} age_ms={age_ms} last_id={last_id}")

    print("\n=== Recent Skip Reasons (signals:execution:skips) ===")
    try:
        entries = r.xrevrange("signals:execution:skips", count=20)
        for stream_id, data in entries:
            payload_raw = data.get("data")
            try:
                payload = json.loads(payload_raw) if payload_raw else {}
            except Exception:
                payload = {"_raw": payload_raw}
            ts_ms = payload.get("ts_ms") or 0
            age_ms = now_ms - int(ts_ms) if ts_ms else None
            print(f"{stream_id} age_ms={age_ms} account={payload.get('account')} symbol={payload.get('symbol')} action={payload.get('action_name')} reason={payload.get('reason_code')} detail={payload.get('reason_detail')}")
    except Exception as e:
        print(f"Could not read skips stream: {e}")

    if stalled:
        print(f"\nStalled traders: {stalled}")
        sys.exit(1)

    print("\nAll traders healthy")


if __name__ == "__main__":
    main()
