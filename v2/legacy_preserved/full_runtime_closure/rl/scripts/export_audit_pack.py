"""
Export an audit pack containing configs, recent signals, and health events.

Usage:
    python -m rl.scripts.export_audit_pack --limit 500 --out audit_pack.json
"""
import argparse
import json
import time
from pathlib import Path

try:
    from utils.redis_client import get_redis
except Exception:
    get_redis = None  # type: ignore


def xread_latest(rc, stream, limit):
    try:
        entries = rc.xrevrange(stream, count=limit)
        return [
            {"id": k.decode() if isinstance(k, bytes) else k, "data": v.get(b"data", v.get("data", b"")).decode() if isinstance(v.get(b"data", b""), bytes) else v.get("data", "")}
            for k, v in entries
        ]
    except Exception:
        return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--out", type=str, default="audit_pack.json")
    args = parser.parse_args()

    rc = get_redis() if get_redis else None
    if rc is None:
        print("redis unavailable")
        return 1

    # Prefer per-account signal streams when enabled
    try:
        import config as cfg
        enable_per_account = bool(getattr(cfg, "ENABLE_PER_ACCOUNT_STREAMS", False))
        stream_per_account = dict(getattr(cfg, "SIGNAL_STREAM_PER_ACCOUNT", {}) or {})
        signal_output_stream = str(getattr(cfg, "SIGNAL_OUTPUT_STREAM", "signals:trading"))
    except Exception:
        enable_per_account = False
        stream_per_account = {}
        signal_output_stream = "signals:trading"

    pack = {
        "ts": time.time(),
        "config_snapshot": {},
        "signals_trading": {},
        "signals_debug": xread_latest(rc, "signals:debug", args.limit),
        "health": xread_latest(rc, "signals:health", args.limit),
        "signals_skips": xread_latest(rc, "signals:execution:skips", args.limit),
        "executed_signals": xread_latest(rc, "executed_signals", args.limit),
        "execution_feedback": xread_latest(rc, "wma:trader:execution_feedback", args.limit),
    }

    try:
        import config as cfg
        pack["config_snapshot"] = {k: getattr(cfg, k) for k in dir(cfg) if k.isupper()}
    except Exception:
        pack["config_snapshot"] = {}

    if enable_per_account and stream_per_account:
        pack["signals_trading"] = {
            acct: xread_latest(rc, stream, args.limit) for acct, stream in stream_per_account.items()
        }
    else:
        pack["signals_trading"] = xread_latest(rc, signal_output_stream, args.limit)

    Path(args.out).write_text(json.dumps(pack, indent=2))
    print(f"audit pack written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
