#!/usr/bin/env python3
"""
Why-Hedged Timeline (read-only)
===============================
Print a concise timeline explaining *why* hedge legs were opened, per account,
using only Redis streams:

- signals:trading:{account}   (trainer decisions)
- signals:execution:skips     (why a decision was blocked/skipped)

This is designed to quickly answer:
  "Why did we open protective hedges and what triggered them?"

Usage examples:
  python3 scripts/why_hedged_timeline.py --account primary --hours 6
  python3 scripts/why_hedged_timeline.py --account asjad --hours 24 --limit 50
  python3 scripts/why_hedged_timeline.py --account all --hours 2 --context 1
  python3 scripts/why_hedged_timeline.py --account primary --hours 12 --symbols BTCUSDT,FOLKSUSDT

Notes:
- Read-only; makes no Binance API calls.
- If per-account streams are disabled, it will fall back to `signals:trading`
  and rely on `account_id` inside payloads.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from bisect import bisect_left
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import redis

# Ensure project root is importable (so `import config` works when running from scripts/)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _utc(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


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


def _safe_bool(x: Any) -> bool:
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return bool(x)
    s = str(x or "").strip().lower()
    return s in ("1", "true", "yes", "y", "on")


def _safe_json_loads(raw: Any) -> Dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="ignore")
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _redis_client(redis_url: str) -> redis.Redis:
    url = (redis_url or os.getenv("REDIS_URL") or "redis://localhost:6379/0").strip()
    return redis.Redis.from_url(url, decode_responses=True)


def _detect_signal_streams(rc: redis.Redis) -> List[Tuple[str, str]]:
    """
    Detect active signal streams without importing `config` (which can be heavy/noisy).

    Preference order:
    1) Per-account streams if they exist as Redis streams:
       - signals:trading:primary
       - signals:trading:asjad
    2) Fallback: env SIGNAL_OUTPUT_STREAM or "signals:trading"
    """
    def _is_stream(key: str) -> bool:
        try:
            return str(rc.type(key) or "").lower() == "stream"
        except Exception:
            return False

    per_acct = [("signals:trading:primary", "primary"), ("signals:trading:asjad", "asjad")]
    if any(_is_stream(k) for k, _ in per_acct):
        return per_acct

    signal_output_stream = str(os.getenv("SIGNAL_OUTPUT_STREAM") or "signals:trading").strip()
    return [(signal_output_stream, "global")]


def _read_stream_json(
    rc: redis.Redis,
    stream: str,
    cutoff_ms: int,
    max_count: int,
) -> List[Tuple[int, Dict[str, Any]]]:
    """
    Read stream via XREVRANGE (newest->oldest), stop when stream_id < cutoff.
    Returns sorted list (oldest->newest) of (ts_ms, payload_dict).
    """
    out: List[Tuple[int, Dict[str, Any]]] = []
    try:
        entries = rc.xrevrange(stream, count=max_count)
    except Exception:
        entries = []

    for sid, fields in entries:
        sid_ts = _id_ms(sid)
        if sid_ts and sid_ts < cutoff_ms:
            break
        raw = (fields or {}).get("data") or "{}"
        payload = _safe_json_loads(raw)
        ts_ms = _safe_int(payload.get("ts_ms"), sid_ts)
        if ts_ms < cutoff_ms:
            continue
        payload["_stream_id"] = sid
        out.append((ts_ms, payload))

    out.sort(key=lambda x: x[0])
    return out


def _is_hedge_open_signal(p: Dict[str, Any]) -> bool:
    action = str(p.get("action_name") or p.get("action") or "").upper()
    action_cat = str(p.get("action_category") or "").upper()
    hedge_intent = _safe_bool(p.get("hedge_intent"))

    # Direct hedge category or action name includes hedge.
    if action_cat == "HEDGE":
        return True
    if "OPEN_HEDGE" in action:
        return True
    if action in ("ADAPTIVE_HEDGE_OPEN", "ADAPTIVE_HEDGE"):
        return True

    # Forced hedge-v2 flips: treat as hedge-opening if hedge_intent + contains OPEN.
    if hedge_intent and ("OPEN" in action) and ("CLOSE" in action):
        return True

    return False


def _is_tradeable_signal(p: Dict[str, Any]) -> bool:
    # Signals stream contains trade actions only. Still, be defensive.
    action = str(p.get("action_name") or p.get("action") or "").strip()
    return bool(action)


def _extract_account_from_signal(stream_account_hint: str, p: Dict[str, Any]) -> str:
    # If stream is global, rely on payload account_id. Otherwise trust stream hint.
    if stream_account_hint and stream_account_hint != "global":
        return stream_account_hint
    aid = str(p.get("account_id") or p.get("_routed_account_id") or "").strip().lower()
    return aid or "unknown"


def _format_trigger_metrics(p: Dict[str, Any]) -> str:
    tm = p.get("trigger_metrics")
    if not isinstance(tm, dict) or not tm:
        return ""

    # Keep this intentionally compact.
    def f(k: str, scale: float = 1.0, digits: int = 2) -> Optional[str]:
        if k not in tm:
            return None
        v = tm.get(k)
        try:
            vv = float(v) * scale
        except Exception:
            return None
        return f"{k}={vv:.{digits}f}"

    parts: List[str] = []
    for k in ("fast_move_score", "spoof_score", "snapback_score", "churn_score"):
        s = f(k, 1.0, 2)
        if s:
            parts.append(s)

    # Returns as percent.
    for k in ("ret_15s", "ret_60s"):
        s = f(k, 100.0, 2)
        if s:
            parts.append(s + "%")

    for k in ("volatility_30s", "micro_quality_score", "data_quality"):
        s = f(k, 1.0, 2)
        if s:
            parts.append(s)

    # Hedge sizing hints (from proactive).
    for k in ("hedge_size_pct", "hedge_notional_usd"):
        s = f(k, 1.0, 2)
        if s:
            parts.append(s)

    return " ".join(parts)


def _format_margin_snapshot(p: Dict[str, Any]) -> str:
    # These are embedded in many trainer payloads.
    equity = _safe_float(p.get("total_margin_balance") or p.get("portfolio_balance") or p.get("equity_snapshot") or 0.0)
    used = _safe_float(p.get("used_margin") or 0.0)
    util = _safe_float(p.get("margin_utilization") or 0.0)
    avail = _safe_float(p.get("available_margin") or 0.0)
    margin_usd = _safe_float(p.get("margin_usd") or 0.0)
    notional_usd = _safe_float(p.get("notional_usd") or 0.0)

    parts = []
    if margin_usd > 0:
        parts.append(f"margin=${margin_usd:.2f}")
    if notional_usd > 0:
        parts.append(f"notional=${notional_usd:.2f}")
    if util > 0:
        parts.append(f"util={util:.1f}%")
    if used > 0:
        parts.append(f"used=${used:.2f}")
    if equity > 0:
        parts.append(f"equity=${equity:.2f}")
    if avail > 0:
        parts.append(f"avail=${avail:.2f}")
    return " ".join(parts)


def _signal_summary(ts_ms: int, account_id: str, p: Dict[str, Any]) -> str:
    sym = str(p.get("symbol") or "").upper() or "UNKNOWN"
    tf = str(p.get("timeframe") or p.get("tf") or "").strip() or "?"
    action = str(p.get("action_name") or p.get("action") or "").upper()
    src = str(p.get("source") or p.get("producer") or "").strip() or "unknown"
    confidence = p.get("confidence")
    conf = None
    try:
        # Trainer uses 0-1; some payloads use 0-100.
        vv = float(confidence)
        conf = vv * 100.0 if vv <= 1.0 else vv
    except Exception:
        conf = None

    proactive = str(p.get("proactive_signal") or "").strip()
    urgency = str(p.get("proactive_urgency") or p.get("urgency") or "").strip()
    forced_reason = str(p.get("_hedge_v2_forced_reason") or "").strip()

    parts = [f"{_utc(ts_ms)}Z", f"acct={account_id}", f"{sym}", f"{tf}", action]
    if conf is not None:
        parts.append(f"conf={conf:.1f}%")
    parts.append(f"src={src}")
    if proactive:
        parts.append(f"proactive={proactive}")
    if urgency:
        parts.append(f"urgency={urgency}")
    if forced_reason:
        parts.append(f"forced={forced_reason}")

    tm = _format_trigger_metrics(p)
    if tm:
        parts.append(f"[{tm}]")

    ms = _format_margin_snapshot(p)
    if ms:
        parts.append(f"({ms})")

    sid = str(p.get("signal_id") or "").strip()
    if sid:
        parts.append(f"sid={sid[:8]}")

    return " ".join(parts)


def _skip_summary(ts_ms: int, s: Dict[str, Any]) -> str:
    sym = str(s.get("symbol") or "").upper() or "UNKNOWN"
    action = str(s.get("action_name") or s.get("action") or "").upper() or "UNKNOWN_ACTION"
    rc = str(s.get("reason_code") or "").strip() or "UNKNOWN"
    detail = str(s.get("reason_detail") or "").strip()
    trader = str(s.get("consumer") or s.get("trader_instance") or "").strip()
    suffix = f" detail={detail}" if detail else ""
    return f"  ↳ {_utc(ts_ms)}Z SKIP {sym} {action} reason={rc}{suffix} ({trader})"


def _index_skips(skips: List[Tuple[int, Dict[str, Any]]]) -> Tuple[Dict[str, List[Tuple[int, Dict[str, Any]]]], Dict[Tuple[str, str], List[Tuple[int, Dict[str, Any]]]]]:
    by_sid: Dict[str, List[Tuple[int, Dict[str, Any]]]] = {}
    by_acct_sym: Dict[Tuple[str, str], List[Tuple[int, Dict[str, Any]]]] = {}
    for ts_ms, s in skips:
        sid = str(s.get("signal_id") or "").strip()
        if sid:
            by_sid.setdefault(sid, []).append((ts_ms, s))
        acct = str(s.get("account") or s.get("account_id") or "").strip().lower() or "unknown"
        sym = str(s.get("symbol") or "").strip().upper() or "UNKNOWN"
        by_acct_sym.setdefault((acct, sym), []).append((ts_ms, s))
    return by_sid, by_acct_sym


def _find_related_skips(
    *,
    signal_ts_ms: int,
    account_id: str,
    symbol: str,
    signal_id: str,
    by_sid: Dict[str, List[Tuple[int, Dict[str, Any]]]],
    by_acct_sym: Dict[Tuple[str, str], List[Tuple[int, Dict[str, Any]]]],
) -> List[Tuple[int, Dict[str, Any]]]:
    related: List[Tuple[int, Dict[str, Any]]] = []
    if signal_id and signal_id in by_sid:
        related.extend(by_sid.get(signal_id, []))
    # Time-based fallback: within +/- 2 minutes for same account+symbol.
    key = (account_id.lower(), symbol.upper())
    bucket = by_acct_sym.get(key, [])
    if bucket:
        for ts_ms, s in bucket:
            if abs(ts_ms - signal_ts_ms) <= 120_000:
                related.append((ts_ms, s))
    # Dedupe by (ts_ms, reason_code, action_name)
    seen = set()
    out: List[Tuple[int, Dict[str, Any]]] = []
    for ts_ms, s in sorted(related, key=lambda x: x[0]):
        k = (ts_ms, str(s.get("reason_code") or ""), str(s.get("action_name") or ""))
        if k in seen:
            continue
        seen.add(k)
        out.append((ts_ms, s))
    return out


def _prev_context_events(
    events: List[Tuple[int, Dict[str, Any]]],
    ts_ms: int,
    symbol: str,
    n: int,
) -> List[Tuple[int, Dict[str, Any]]]:
    if n <= 0:
        return []
    # events is sorted by ts_ms
    sym = symbol.upper()
    sym_events = [(t, p) for t, p in events if str(p.get("symbol") or "").upper() == sym]
    if not sym_events:
        return []
    ts_list = [t for t, _ in sym_events]
    i = bisect_left(ts_list, ts_ms)
    # Take previous n events
    start = max(0, i - n)
    return sym_events[start:i]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", type=str, default="all", choices=["primary", "asjad", "all"], help="Account scope (default: all)")
    ap.add_argument("--hours", type=float, default=6.0, help="Lookback window in hours (default: 6)")
    ap.add_argument("--limit", type=int, default=200, help="Max hedge events to print per account (default: 200)")
    ap.add_argument("--max-entries", type=int, default=50000, help="Max stream entries to scan (default: 50000)")
    ap.add_argument("--context", type=int, default=1, help="Show N previous signals for the same symbol (default: 1)")
    ap.add_argument("--symbols", type=str, default="", help="Comma-separated symbols filter (e.g. BTCUSDT,ETHUSDT)")
    ap.add_argument("--redis-url", type=str, default=os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    args = ap.parse_args()

    now_ms = int(time.time() * 1000)
    cutoff_ms = now_ms - int(max(60_000, args.hours * 3600_000))

    symbol_filter = {s.strip().upper() for s in str(args.symbols or "").split(",") if s.strip()}

    rc = _redis_client(args.redis_url)
    streams = _detect_signal_streams(rc)

    # Select streams for requested accounts
    wanted_accounts = {"primary", "asjad"} if args.account == "all" else {args.account}
    chosen_streams: List[Tuple[str, str]] = []
    for stream_name, hint in streams:
        if hint == "global":
            chosen_streams.append((stream_name, hint))
        elif hint in wanted_accounts:
            chosen_streams.append((stream_name, hint))

    skips = _read_stream_json(rc, "signals:execution:skips", cutoff_ms=cutoff_ms, max_count=args.max_entries)
    by_sid, by_acct_sym = _index_skips(skips)

    print("=== WHY-HEDGED TIMELINE (read-only) ===")
    print(f"window: last {args.hours:.2f}h | cutoff={_utc(cutoff_ms)}Z | now={_utc(now_ms)}Z")
    if symbol_filter:
        print(f"symbols: {','.join(sorted(symbol_filter))}")
    print("")

    # Collect hedge events per account
    per_account_events: Dict[str, List[Tuple[int, Dict[str, Any]]]] = {"primary": [], "asjad": [], "unknown": []}

    for stream_name, hint in chosen_streams:
        rows = _read_stream_json(rc, stream_name, cutoff_ms=cutoff_ms, max_count=args.max_entries)
        for ts_ms, payload in rows:
            if not _is_tradeable_signal(payload):
                continue
            account_id = _extract_account_from_signal(hint, payload)
            if account_id in ("primary", "asjad") and (account_id not in wanted_accounts):
                continue
            sym = str(payload.get("symbol") or "").upper()
            if symbol_filter and sym not in symbol_filter:
                continue
            if _is_hedge_open_signal(payload):
                per_account_events.setdefault(account_id, []).append((ts_ms, payload))

    for account_id in (["primary", "asjad"] if args.account == "all" else [args.account]):
        events = sorted(per_account_events.get(account_id, []), key=lambda x: x[0])
        print(f"--- account: {account_id} | hedge_events={len(events)} ---")
        if not events:
            print("  (none)")
            print("")
            continue

        # For context lookups we also need the full signal list for this account.
        # Re-read account stream(s) but keep it bounded and simple.
        all_signals: List[Tuple[int, Dict[str, Any]]] = []
        for stream_name, hint in chosen_streams:
            if hint not in ("global", account_id):
                continue
            all_signals.extend(_read_stream_json(rc, stream_name, cutoff_ms=cutoff_ms, max_count=args.max_entries))
        all_signals.sort(key=lambda x: x[0])

        printed = 0
        for ts_ms, p in events:
            if printed >= args.limit:
                break
            sym = str(p.get("symbol") or "").upper() or "UNKNOWN"
            sid = str(p.get("signal_id") or "").strip()
            print(_signal_summary(ts_ms, account_id, p))

            # Optional previous-context events for chain visibility.
            if args.context > 0:
                ctx = _prev_context_events(all_signals, ts_ms, sym, n=args.context)
                for cts, cp in ctx:
                    ca = str(cp.get("action_name") or cp.get("action") or "").upper()
                    if not ca:
                        continue
                    # Keep context lines short.
                    csrc = str(cp.get("source") or cp.get("producer") or "").strip() or "unknown"
                    cconf = cp.get("confidence")
                    cconf_s = ""
                    try:
                        vv = float(cconf)
                        cconf_s = f" conf={(vv*100.0 if vv <= 1.0 else vv):.1f}%"
                    except Exception:
                        cconf_s = ""
                    print(f"  ↳ prev {_utc(cts)}Z {sym} {ca}{cconf_s} src={csrc}")

            related_skips = _find_related_skips(
                signal_ts_ms=ts_ms,
                account_id=account_id,
                symbol=sym,
                signal_id=sid,
                by_sid=by_sid,
                by_acct_sym=by_acct_sym,
            )
            for sts, s in related_skips:
                print(_skip_summary(sts, s))

            printed += 1

        if printed < len(events):
            print(f"  ... truncated: printed {printed}/{len(events)} (use --limit to change)")
        print("")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


