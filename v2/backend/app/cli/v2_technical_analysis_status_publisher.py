"""V2 technical analysis status publisher — reads live v2:technical_analysis:*
keys from Redis and writes a public JSON payload for the frontend TA page.

Writes V2 namespace ONLY. No legacy Redis writes. No exchange mutation.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

V2_REDIS_PREFIX = "v2:"
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PAYLOAD_PATH = (
    REPO_ROOT
    / "v2/frontend/public/operator_runtime/v2_technical_analysis_status/latest/v2_technical_analysis_status.json"
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _connect_redis():
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def run_once() -> dict:
    r = _connect_redis()
    ta_keys: list[str] = []
    ta_fresh: list[str] = []
    sample_btc: dict | None = None

    if r:
        try:
            # Bounded SCAN (never blocking KEYS) + a single pipelined TTL batch,
            # not N sequential round-trips, on the ~634K-key shared store.
            cursor = 0
            while True:
                cursor, batch = r.scan(
                    cursor=cursor, match=f"{V2_REDIS_PREFIX}technical_analysis:*", count=1000
                )
                ta_keys.extend(batch)
                if cursor == 0 or len(ta_keys) >= 5000:
                    break
            if ta_keys:
                _pipe = r.pipeline()
                for _k in ta_keys:
                    _pipe.ttl(_k)
                ta_fresh = [k for k, ttl in zip(ta_keys, _pipe.execute()) if (ttl or 0) > 0]
            raw_btc = r.get(f"{V2_REDIS_PREFIX}technical_analysis:BTCUSDT:1m")
            if raw_btc:
                try:
                    sample_btc = json.loads(raw_btc)
                except (ValueError, TypeError):
                    sample_btc = None
        except Exception:
            pass

    symbols_covered = len({k.split(":")[2] for k in ta_keys if len(k.split(":")) >= 3})
    symbols_fresh = len({k.split(":")[2] for k in ta_fresh if len(k.split(":")) >= 3})

    classification = (
        "TA_LIVE_OK" if len(ta_fresh) > 0 else
        ("TA_STALE_NO_FRESH_KEYS" if ta_keys else "TA_MISSING_NO_KEYS")
    )

    return {
        "schema_version": "v2_technical_analysis_status_v1",
        "worker_id": "v2_technical_analysis_status_publisher",
        "generated_utc": _utc_iso(),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "classification": classification,
        "ta_keys_total": len(ta_keys),
        "ta_keys_fresh": len(ta_fresh),
        "symbols_covered": symbols_covered,
        "symbols_fresh": symbols_fresh,
        "sample_btc_1m": sample_btc,
        "source_label": "V2_NATIVE_FEATURE_PIPELINE_LIVE",
        "note": "v2:technical_analysis:* keys written by v2_feature_pipeline_native_loop with 600s TTL",
    }


def write_payload(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_technical_analysis_status_publisher")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--out", type=Path, default=DEFAULT_PAYLOAD_PATH)
    args = parser.parse_args(argv)
    if args.loop:
        while True:
            payload = run_once()
            write_payload(payload, args.out)
            time.sleep(max(5, args.interval_seconds))
    payload = run_once()
    write_payload(payload, args.out)
    print(json.dumps({"classification": payload["classification"], "ta_keys_fresh": payload["ta_keys_fresh"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
