"""Audit recent trade attribution events.

Reads the latest entries from the attribution stream and summarizes
loss-realization behavior. Exits non-zero when red-close rate breaches
the configured threshold or when no loss-block events are observed.
"""
import argparse
import json
import sys
from typing import Any, Dict, List

import redis


def _decode_entry(raw: Dict[bytes, bytes]) -> Dict[str, Any]:
    try:
        if b"data" in raw:
            return json.loads(raw[b"data"].decode("utf-8"))
    except Exception:
        pass

    decoded = {}
    for k, v in raw.items():
        key = k.decode("utf-8") if isinstance(k, (bytes, bytearray)) else str(k)
        try:
            decoded[key] = json.loads(v) if isinstance(v, (bytes, bytearray)) else v
        except Exception:
            decoded[key] = v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else v
    return decoded


def audit(stream: str, host: str, port: int, count: int, red_threshold: float) -> int:
    r = redis.Redis(host=host, port=port, decode_responses=False)
    entries = r.xrevrange(stream, count=count)
    if not entries:
        print(f"No entries found in stream {stream}; skipping checks.")
        return 0

    decoded: List[Dict[str, Any]] = []
    for _, data in entries:
        decoded.append(_decode_entry(data))

    red = 0
    total_closes = 0
    source_counts: Dict[str, int] = {}
    reason_counts: Dict[str, int] = {}
    loss_blocks = 0

    for entry in decoded:
        source = str(entry.get("source", "unknown"))
        source_counts[source] = source_counts.get(source, 0) + 1

        reasons = entry.get("reason_codes") or entry.get("reasons") or []
        if isinstance(reasons, str):
            reasons = [reasons]
        for reason in reasons:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        if any("loss_block" in str(reason) for reason in reasons):
            loss_blocks += 1

        pnl = entry.get("realized_pnl_usd")
        if pnl is None:
            pnl = entry.get("pnl_usd")
        if pnl is None:
            continue

        try:
            pnl_val = float(pnl)
        except Exception:
            continue

        total_closes += 1
        if pnl_val < 0:
            red += 1

    red_rate = (red / total_closes) if total_closes else 0.0

    print(f"Stream: {stream} | samples: {len(decoded)} | closes: {total_closes} | red: {red} ({red_rate:.1%})")
    print(f"Sources: {source_counts}")
    print(f"Reasons: {reason_counts}")
    print(f"Loss blocks observed: {loss_blocks}")

    if total_closes and red_rate > red_threshold:
        print(f"Red close rate {red_rate:.1%} exceeds threshold {red_threshold:.1%}")
        return 1
    if total_closes and loss_blocks == 0:
        print("No loss-realization blocks observed; guard may be inactive.")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit trade attribution stream")
    parser.add_argument("--stream", default="trades:attribution", help="Redis stream name")
    parser.add_argument("--host", default="localhost", help="Redis host")
    parser.add_argument("--port", type=int, default=6379, help="Redis port")
    parser.add_argument("--count", type=int, default=200, help="Number of entries to inspect")
    parser.add_argument("--red-threshold", type=float, default=0.55, help="Maximum acceptable red close rate")
    args = parser.parse_args()

    try:
        return audit(args.stream, args.host, args.port, args.count, args.red_threshold)
    except Exception as exc:
        print(f"Audit failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
