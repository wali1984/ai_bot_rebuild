"""
Trainer runtime healthcheck.

Usage:
    python -m rl.scripts.healthcheck_trainer_runtime

Checks:
    - Redis connectivity/latency
    - Presence + freshness of portfolio:state
    - Presence + freshness of prediction:{symbol}:{tf} for configured symbols/TFs
    - Streams signals:trading and signals:debug have recent events

Exit codes:
    0 = PASS
    1 = FAIL
"""

import json
import sys
import time
from datetime import datetime, timezone
from typing import List, Tuple

try:
    from config import SYMBOLS, TIMEFRAMES
except Exception:
    SYMBOLS = ["BTCUSDT"]
    TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h"]

try:
    from utils.redis_client import get_redis
except Exception:
    get_redis = None  # type: ignore


def fmt_ts(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except Exception:
        return "n/a"


def check_redis() -> Tuple[bool, str, float]:
    rc = get_redis() if get_redis else None
    if rc is None:
        return False, "redis_client_unavailable", 0.0
    try:
        t0 = time.time()
        pong = rc.ping()
        latency = (time.time() - t0) * 1000
        return bool(pong), "redis_ok", latency
    except Exception as e:
        return False, f"redis_error:{e}", 0.0


def check_portfolio(rc, max_age_s: int = 20) -> Tuple[bool, str]:
    try:
        keys = []
        for k in rc.scan_iter(match="portfolio:state*"):
            ks = k.decode() if isinstance(k, (bytes, bytearray)) else str(k)
            if ks.endswith("stream"):
                continue
            kt = rc.type(k)
            kt = kt.decode() if isinstance(kt, (bytes, bytearray)) else str(kt)
            if kt != "hash":
                continue  # skip pointer or other non-hash types
            keys.append(k)
        if not keys:
            return False, "portfolio_missing"
        freshest = None
        for k in keys:
            data = rc.hgetall(k)
            if not data:
                continue
            ts = float(data.get("timestamp", 0) or data.get("ts_ms", 0) / 1000)
            age = time.time() - ts if ts else 1e9
            if freshest is None or age < freshest:
                freshest = age
        if freshest is None:
            return False, "portfolio_missing"
        if freshest > max_age_s:
            return False, f"portfolio_stale:{freshest:.1f}s"
        return True, "portfolio_ok"
    except Exception as e:
        return False, f"portfolio_error:{e}"


def check_predictions(rc, symbols: List[str], tfs: List[str], max_age_s: int = 300) -> Tuple[bool, str]:
    missing = []
    stale = []
    for sym in symbols:
        for tf in tfs:
            key = f"prediction:{sym}:{tf}"
            data = rc.hgetall(key)
            if not data:
                missing.append(key)
                continue
            try:
                ts_raw = data.get("timestamp", 0) or data.get("ts_ms", 0)
                ts = float(ts_raw) / (1000 if float(ts_raw) > 1e10 else 1)  # heuristic: if ms -> divide by 1000
            except Exception:
                ts = 0.0
            if ts == 0 or (time.time() - ts) > max_age_s:
                stale.append(key)
    if missing:
        return False, f"pred_missing:{len(missing)}"
    if stale:
        return False, f"pred_stale:{len(stale)}"
    return True, "predictions_ok"


def check_stream(rc, stream: str, max_age_s: int = 300) -> Tuple[bool, str]:
    try:
        entries = rc.xrevrange(stream, count=1)
        if not entries:
            return False, f"{stream}_empty"
        _, fields = entries[0]
        raw = fields.get(b"data") or fields.get("data")
        ts = None
        if raw:
            try:
                payload = json.loads(raw if isinstance(raw, str) else raw.decode())
                ts = float(payload.get("ts_ms", payload.get("timestamp_ms", payload.get("timestamp", 0)))) / (
                    1000 if payload.get("ts_ms") or payload.get("timestamp_ms") else 1
                )
            except Exception:
                ts = None
        if ts is None:
            return True, f"{stream}_ok_no_ts"
        age = time.time() - ts
        if age > max_age_s:
            return False, f"{stream}_stale:{age:.1f}s"
        return True, f"{stream}_ok"
    except Exception as e:
        return False, f"{stream}_error:{e}"


def main() -> int:
    ok = True
    rc = get_redis() if get_redis else None
    if rc is None:
        print("HEALTHCHECK FAIL: redis_client_unavailable")
        return 1

    redis_ok, redis_msg, redis_latency = check_redis()
    ok &= redis_ok

    portfolio_ok, portfolio_msg = check_portfolio(rc)
    ok &= portfolio_ok

    preds_ok, preds_msg = check_predictions(rc, SYMBOLS, TIMEFRAMES)
    ok &= preds_ok

    trading_ok, trading_msg = check_stream(rc, "signals:trading")
    debug_ok, debug_msg = check_stream(rc, "signals:debug")
    ok &= trading_ok and debug_ok

    status = "PASS" if ok else "FAIL"
    print(
        f"HEALTHCHECK {status}: redis={redis_msg} ({redis_latency:.1f}ms) "
        f"portfolio={portfolio_msg} preds={preds_msg} streams={trading_msg},{debug_msg}"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
