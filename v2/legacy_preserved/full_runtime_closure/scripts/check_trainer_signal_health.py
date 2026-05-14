#!/usr/bin/env python3
"""
Trainer Signal Health Check (Redis-only; no Binance calls)
=========================================================

This script answers two operational questions quickly:
1) Is the trainer *alive* (heartbeat + prediction loop running)?
2) Are model-driven signals (source=trainer with PPO/MASA fields) being published,
   or are they currently gated (e.g., MIN_CONF_ENTRY too high, portfolio caps, etc.)?

It reads:
- signals:trainer:heartbeat
- trainer:predict:last_summary (written by rl/hybrid_trainer.py)
- signals:trading:{account} streams (primary/asjad)
- signals:execution:skips (optional summary)

Usage:
  python3 scripts/check_trainer_signal_health.py
  python3 scripts/check_trainer_signal_health.py --hours 2 --max 2000 --show-skips
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import redis


def _utc(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _id_ms(stream_id: str) -> int:
    try:
        return int(str(stream_id).split("-", 1)[0])
    except Exception:
        return 0


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(float(x))
    except Exception:
        return default


def _redis_client() -> redis.Redis:
    url = os.getenv("REDIS_URL")
    if url:
        return redis.Redis.from_url(url, decode_responses=True)
    return redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)


def _load_json_field(fields: Dict[str, Any]) -> Dict[str, Any]:
    raw = fields.get("data") or "{}"
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _last_stream_entry(rc: redis.Redis, stream: str) -> Tuple[Optional[str], Dict[str, Any]]:
    try:
        rows = rc.xrevrange(stream, count=1)
    except Exception:
        rows = []
    if not rows:
        return None, {}
    sid, fields = rows[0]
    payload = _load_json_field(fields if isinstance(fields, dict) else {})
    payload["_stream_id"] = sid
    payload["_ts_ms"] = _safe_int(payload.get("ts_ms"), _id_ms(sid))
    return sid, payload


def _iter_stream_json(
    rc: redis.Redis,
    stream: str,
    start_ms: int,
    max_count: int,
) -> Iterable[Tuple[int, str, Dict[str, Any]]]:
    # Read newest->oldest and stop when we cross start_ms
    try:
        rows = rc.xrevrange(stream, count=max_count)
    except Exception:
        rows = []
    for sid, fields in rows:
        ts = _id_ms(sid)
        if ts and ts < start_ms:
            break
        payload = _load_json_field(fields if isinstance(fields, dict) else {})
        ts_ms = _safe_int(payload.get("ts_ms"), ts)
        if ts_ms < start_ms:
            continue
        payload["_stream_id"] = sid
        payload["_ts_ms"] = ts_ms
        yield ts_ms, sid, payload


def _find_recent(
    rc: redis.Redis,
    stream: str,
    pred,
    max_scan: int = 5000,
) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    for ts_ms, _sid, payload in _iter_stream_json(rc, stream, start_ms=0, max_count=max_scan):
        # iter_stream_json yields newest->oldest when start_ms=0
        if pred(payload):
            return ts_ms, payload
    return None, None


def _print_signal_line(prefix: str, payload: Dict[str, Any]):
    sym = payload.get("symbol", "UNKNOWN")
    act = payload.get("action_name") or payload.get("final_action") or payload.get("action") or "UNKNOWN"
    src = payload.get("source") or payload.get("producer") or "unknown"
    conf = payload.get("model_confidence", payload.get("confidence", 0.0))
    ppo = payload.get("ppo_confidence")
    masa = payload.get("masa_confidence")
    model = payload.get("model") or "UNKNOWN"
    ts_ms = _safe_int(payload.get("_ts_ms"), 0)
    print(
        f"{prefix} {_utc(ts_ms)} | {sym:12s} | {str(act):24s} | src={src:28s} | "
        f"conf={_safe_float(conf):.3f} | ppo={('%.3f'%_safe_float(ppo)) if ppo is not None else 'N/A':>6s} | "
        f"masa={('%.3f'%_safe_float(masa)) if masa is not None else 'N/A':>6s} | model={model}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=2.0, help="Lookback window for counts (default: 2h)")
    ap.add_argument("--max", type=int, default=3000, help="Max stream scan per stream (default: 3000)")
    ap.add_argument("--show-skips", action="store_true", help="Summarize signals:execution:skips in the lookback window")
    args = ap.parse_args()

    rc = _redis_client()
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - int(args.hours * 3600 * 1000)

    print(f"now_utc: {_utc(now_ms)}")
    print(f"window: last {args.hours:.1f}h (since {_utc(start_ms)})")
    print()

    # ------------------------------------------------------------------
    # Trainer heartbeat
    # ------------------------------------------------------------------
    hb_id, hb = _last_stream_entry(rc, "signals:trainer:heartbeat")
    if not hb_id:
        print("trainer_heartbeat: MISSING (signals:trainer:heartbeat empty)")
    else:
        age_s = (now_ms - _safe_int(hb.get("_ts_ms"), now_ms)) / 1000.0
        print(
            f"trainer_heartbeat: OK age={age_s:.0f}s "
            f"pid={hb.get('trainer_pid')} instance={hb.get('trainer_instance')} model_loaded={hb.get('model_loaded')}"
        )
    print()

    # ------------------------------------------------------------------
    # Last prediction summary (telemetry key)
    # ------------------------------------------------------------------
    raw_summary = rc.get("trainer:predict:last_summary") or ""
    if not raw_summary:
        print("trainer:predict:last_summary: MISSING (trainer not updated/restarted yet, or telemetry disabled)")
    else:
        try:
            summ = json.loads(raw_summary)
        except Exception:
            summ = {}
        ts_ms = _safe_int(summ.get("ts_ms"), 0)
        age_s = (now_ms - ts_ms) / 1000.0 if ts_ms else -1
        dbg = (summ.get("dbg") or {}) if isinstance(summ.get("dbg"), dict) else {}
        th = (summ.get("thresholds") or {}) if isinstance(summ.get("thresholds"), dict) else {}
        print(
            f"predict_summary: age={age_s:.0f}s exit_reason={summ.get('exit_reason')} "
            f"produced={summ.get('produced')} published={dbg.get('published')} checked={dbg.get('total_checked')}"
        )
        print(
            f"thresholds: MIN_CONF_ENTRY={th.get('MIN_CONF_ENTRY')} "
            f"SIGNAL_CONFIDENCE_MIN={th.get('SIGNAL_CONFIDENCE_MIN')} MIN_CONF_EXIT={th.get('MIN_CONF_EXIT')}"
        )
        print(
            "dbg:",
            f"low_conf={dbg.get('low_conf')} hold={dbg.get('hold')} cooldown={dbg.get('cooldown')} "
            f"pos_blocked={dbg.get('pos_blocked')} regime_blocked={dbg.get('regime_blocked')} "
            f"no_features={dbg.get('no_features')} nan_conf={dbg.get('nan_conf')} dupe={dbg.get('dupe_suppressed')}",
        )
    print()

    # ------------------------------------------------------------------
    # Signal streams
    # ------------------------------------------------------------------
    streams = {"primary": "signals:trading:primary", "asjad": "signals:trading:asjad"}
    for acct, stream in streams.items():
        try:
            xlen = int(rc.xlen(stream))
        except Exception:
            xlen = -1
        print(f"=== {acct} ({stream}) len={xlen} ===")

        last_id, last = _last_stream_entry(rc, stream)
        if not last_id:
            print("  last_signal: MISSING")
        else:
            _print_signal_line("  last_signal:       ", last)

        # last model signal
        ts_ms, p = _find_recent(rc, stream, lambda x: (x.get("source") == "trainer"), max_scan=args.max)
        if p:
            _print_signal_line("  last_source=trainer", p)
        else:
            print("  last_source=trainer: NONE in scan window")

        # last trainer OPEN (new exposure)
        def _is_trainer_open(x: Dict[str, Any]) -> bool:
            if x.get("source") != "trainer":
                return False
            cat = str(x.get("action_category") or "").upper()
            at = str(x.get("action_type") or "").lower()
            return cat == "OPEN_RISK" or at == "open"

        ts_ms, p = _find_recent(rc, stream, _is_trainer_open, max_scan=args.max)
        if p:
            _print_signal_line("  last_trainer_open: ", p)
        else:
            print("  last_trainer_open:  NONE in scan window")

        # last with PPO/MASA fields
        ts_ms, p = _find_recent(
            rc,
            stream,
            lambda x: ("ppo_confidence" in x) or ("masa_confidence" in x),
            max_scan=args.max,
        )
        if p:
            _print_signal_line("  last_with_ppo_masa:", p)
        else:
            print("  last_with_ppo_masa: NONE in scan window")

        # lookback source counts
        src_counts = Counter()
        n_rows = 0
        for _ts, _sid, payload in _iter_stream_json(rc, stream, start_ms=start_ms, max_count=args.max):
            n_rows += 1
            src_counts[str(payload.get("source") or "unknown")] += 1
        print(f"  recent_sources(last {args.hours:.1f}h, scanned={n_rows}): {dict(src_counts.most_common(8))}")
        print()

    # ------------------------------------------------------------------
    # Skips summary (optional)
    # ------------------------------------------------------------------
    if args.show_skips:
        skip_counts = Counter()
        producer_counts = Counter()
        n = 0
        for _ts, _sid, payload in _iter_stream_json(rc, "signals:execution:skips", start_ms=start_ms, max_count=max(2000, args.max)):
            n += 1
            skip_counts[str(payload.get("reason_code") or "UNKNOWN")] += 1
            producer_counts[str(payload.get("trader_instance") or payload.get("producer") or "unknown")] += 1
        print(f"=== skips (signals:execution:skips) last {args.hours:.1f}h scanned={n} ===")
        print("top_reasons:", dict(skip_counts.most_common(15)))
        print("by_producer:", dict(producer_counts.most_common(10)))
        print()

    # Environment hints (no secrets)
    print("env_hints:")
    for k in ("MIN_CONF_ENTRY", "SIGNAL_CONFIDENCE_MIN", "MIN_TRADING_CONFIDENCE", "PRA_EXECUTE", "PRA_ENABLED"):
        if os.getenv(k) is not None:
            print(f"  {k}={os.getenv(k)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


