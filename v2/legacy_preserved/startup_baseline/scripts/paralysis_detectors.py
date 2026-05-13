#!/usr/bin/env python3
"""
Paralysis Detectors (Audit-Jan5-Fixes D1)
========================================
Read-only Redis health check that flags "system paralysis" patterns when sustained.

Alerts if sustained over the last N minutes (default: 5):
- MICROSTRUCTURE_FAIL_CLOSED spikes (trainer skip stream)
- PORTFOLIO_BUDGET_BLOCK spikes (trainer skip stream)
- Margin is insufficient / -2019 spikes (executed_signals)
- Missing or stale portfolio:equity:{account} snapshots
- DISABLE_BINANCE_OHLCV=1 (runbook redundancy contract drift)

Usage:
  python3 scripts/paralysis_detectors.py
  python3 scripts/paralysis_detectors.py --minutes 10

Notes:
- This script does NOT start/stop any services.
- It uses stream timestamps (ts_ms) and buckets into 1-minute slices to approximate "sustained" behavior.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import redis

# Ensure project root is importable (so `import config` works when running from scripts/)
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


def _safe_json_loads(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _id_ms(stream_id: str) -> int:
    try:
        return int(str(stream_id).split("-", 1)[0])
    except Exception:
        return 0


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(float(x))
    except Exception:
        return default


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


@dataclass
class WindowStats:
    total: int
    per_minute_buckets: int
    per_reason: Counter


def _read_stream_window(
    rc: redis.Redis,
    stream: str,
    cutoff_ms: int,
    max_count: int,
) -> List[Tuple[int, Dict[str, Any]]]:
    out: List[Tuple[int, Dict[str, Any]]] = []
    try:
        entries = rc.xrevrange(stream, count=max_count)
    except Exception:
        entries = []

    for sid, fields in entries:
        ts = _id_ms(sid)
        if ts and ts < cutoff_ms:
            break
        raw = fields.get("data") or "{}"
        payload = _safe_json_loads(raw)
        ts_ms = _safe_int(payload.get("ts_ms"), ts)
        if ts_ms < cutoff_ms:
            continue
        out.append((ts_ms, payload))

    out.reverse()
    return out


def _bucket_minutes(ts_ms: int) -> int:
    return int(ts_ms // 60_000)


def _window_reason_stats(events: List[Tuple[int, Dict[str, Any]]], reason_field: str) -> WindowStats:
    per_reason: Counter = Counter()
    buckets_by_reason: Dict[str, set] = defaultdict(set)
    all_buckets = set()
    for ts_ms, payload in events:
        b = _bucket_minutes(ts_ms)
        all_buckets.add(b)
        r = str(payload.get(reason_field) or "").strip()
        if not r:
            r = "UNKNOWN"
        per_reason[r] += 1
        buckets_by_reason[r].add(b)
    return WindowStats(total=len(events), per_minute_buckets=len(all_buckets), per_reason=per_reason)


def _bucket_coverage(events: List[Tuple[int, Dict[str, Any]]], reason_field: str, reason: str) -> int:
    buckets = set()
    for ts_ms, payload in events:
        r = str(payload.get(reason_field) or "").strip()
        if r == reason:
            buckets.add(_bucket_minutes(ts_ms))
    return len(buckets)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=5.0, help="Window size in minutes (default: 5)")
    ap.add_argument("--max-entries", type=int, default=50000, help="Max stream entries to scan (default: 50000)")
    ap.add_argument("--redis-url", type=str, default=os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    args = ap.parse_args()

    now_ms = int(time.time() * 1000)
    window_ms = int(max(60_000, args.minutes * 60_000))
    cutoff_ms = now_ms - window_ms

    rc = redis.Redis.from_url(args.redis_url, decode_responses=True)

    # ----------------------------------------------------------------------------
    # D1a) Skips stream: MICROSTRUCTURE_FAIL_CLOSED / PORTFOLIO_BUDGET_BLOCK
    # ----------------------------------------------------------------------------
    skips = _read_stream_window(rc, "signals:execution:skips", cutoff_ms=cutoff_ms, max_count=args.max_entries)
    skip_stats = _window_reason_stats(skips, reason_field="reason_code")

    # ----------------------------------------------------------------------------
    # D1b) Executed signals: margin insufficient spikes
    # ----------------------------------------------------------------------------
    execs = _read_stream_window(rc, "executed_signals", cutoff_ms=cutoff_ms, max_count=args.max_entries)
    margin_err_buckets = set()
    margin_err_count = 0
    for ts_ms, payload in execs:
        err = str(payload.get("error") or payload.get("err") or "")
        if ("Margin is insufficient" in err) or ("code=-2019" in err) or ("-2019" in err):
            margin_err_count += 1
            margin_err_buckets.add(_bucket_minutes(ts_ms))

    # ----------------------------------------------------------------------------
    # D1c) Equity snapshots per account
    # ----------------------------------------------------------------------------
    try:
        from config import PORTFOLIO_EQUITY_MAX_AGE_MS
        equity_max_age_ms = int(PORTFOLIO_EQUITY_MAX_AGE_MS)
    except Exception:
        equity_max_age_ms = 120_000

    accounts = ["primary", "asjad"]
    equity_alerts: List[str] = []
    for aid in accounts:
        raw = rc.get(f"portfolio:equity:{aid}")
        if not raw:
            equity_alerts.append(f"portfolio:equity:{aid}:missing")
            continue
        eq = _safe_json_loads(raw)
        ts = _safe_float(eq.get("timestamp", 0.0) or 0.0, 0.0)
        age_ms = int((time.time() - ts) * 1000) if ts > 0 else 10**9
        if age_ms > equity_max_age_ms:
            equity_alerts.append(f"portfolio:equity:{aid}:stale({age_ms/1000:.0f}s>{equity_max_age_ms/1000:.0f}s)")

    # ----------------------------------------------------------------------------
    # D1d) Config drift: DISABLE_BINANCE_OHLCV
    # ----------------------------------------------------------------------------
    disable_binance_ohlcv = os.getenv("DISABLE_BINANCE_OHLCV", "")
    config_drift = []
    if str(disable_binance_ohlcv).strip() == "1":
        config_drift.append("DISABLE_BINANCE_OHLCV=1")

    # ----------------------------------------------------------------------------
    # Alerts (sustained = present in all minute buckets in window)
    # ----------------------------------------------------------------------------
    expected_buckets = max(1, int(args.minutes))  # approx number of 1-min buckets
    sustained_micro = _bucket_coverage(skips, "reason_code", "MICROSTRUCTURE_FAIL_CLOSED") >= expected_buckets
    sustained_budget = _bucket_coverage(skips, "reason_code", "PORTFOLIO_BUDGET_BLOCK") >= expected_buckets
    sustained_margin = len(margin_err_buckets) >= expected_buckets

    alerts: List[str] = []
    if sustained_micro and skip_stats.per_reason.get("MICROSTRUCTURE_FAIL_CLOSED", 0) > 0:
        alerts.append(f"MICROSTRUCTURE_FAIL_CLOSED sustained (count={skip_stats.per_reason.get('MICROSTRUCTURE_FAIL_CLOSED', 0)})")
    if sustained_budget and skip_stats.per_reason.get("PORTFOLIO_BUDGET_BLOCK", 0) > 0:
        alerts.append(f"PORTFOLIO_BUDGET_BLOCK sustained (count={skip_stats.per_reason.get('PORTFOLIO_BUDGET_BLOCK', 0)})")
    if sustained_margin and margin_err_count > 0:
        alerts.append(f"Margin insufficient sustained (count={margin_err_count})")
    alerts.extend(equity_alerts)
    alerts.extend(config_drift)

    print("=== Paralysis Detectors (Audit-Jan5-Fixes D1) ===")
    print(f"Redis: {args.redis_url}")
    print(f"Window: last {args.minutes:.1f} minutes | cutoff_ms={cutoff_ms}")
    print("")

    print(f"[skips] total={skip_stats.total} | unique_reasons={len(skip_stats.per_reason)}")
    top_skips = skip_stats.per_reason.most_common(8)
    for r, c in top_skips:
        print(f"  - {r}: {c}")
    print("")

    print(f"[executed_signals] total={len(execs)} | margin_insufficient={margin_err_count}")
    print("")

    if alerts:
        print("❌ ALERTS:")
        for a in alerts:
            print(f"- {a}")
        return 1

    print("✅ OK: No sustained paralysis patterns detected in this window.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


