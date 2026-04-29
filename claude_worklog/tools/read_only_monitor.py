#!/usr/bin/env python3
"""
Read-only Redis / legacy monitor for AI BOT REBUILD.
Writes JSONL snapshots + final monitoring_summary.md. No Redis writes.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
_REDIS_BASE = ["redis-cli", "-u", REDIS_URL] if REDIS_URL else ["redis-cli"]

STREAMS = (
    "executed_signals",
    "signals:trading",
    "signals:trading:primary",
    "signals:trading:asjad",
    "signals:execution:skips",
    "wma:proposals",
)

HEARTBEAT_KEYS = (
    "orchestrator:heartbeat_ms",
    "heartbeat:FeaturePipeline",
    "heartbeat:trainer",
    "heartbeat:Trainer",
    "signals:trainer:heartbeat",
)

SECRETISH = re.compile(
    r"(api[_-]?key|secret|password|token)\s*[:=]\s*['\"]?[a-zA-Z0-9_\-]{16,}",
    re.I,
)


def _redact(obj: Any) -> Any:
    if isinstance(obj, str):
        return SECRETISH.sub(r"\1=<redacted>", obj)
    if isinstance(obj, dict):
        return {k: _redact(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(x) for x in obj[:200]]
    return obj


def redis_cmd(*args: str) -> Tuple[bool, str]:
    try:
        p = subprocess.run(
            [*_REDIS_BASE, *args],
            capture_output=True,
            text=True,
            timeout=120,
        )
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode == 0, out.strip()
    except Exception as e:
        return False, str(e)


def xlen(name: str) -> Optional[int]:
    ok, out = redis_cmd("XLEN", name)
    if not ok:
        return None
    try:
        return int(out)
    except ValueError:
        return None


def xrevrange_json(stream: str, count: int = 200) -> List[Dict[str, Any]]:
    ok, out = redis_cmd("XREVRANGE", stream, "+", "-", "COUNT", str(count))
    if not ok or not out:
        return []
    lines = out.splitlines()
    rows: List[Dict[str, Any]] = []
    i = 0
    while i + 2 < len(lines):
        _rid = lines[i].strip()
        if lines[i + 1].strip() != "data":
            i += 1
            continue
        blob = lines[i + 2]
        try:
            rows.append(json.loads(blob))
        except json.JSONDecodeError:
            pass
        i += 3
    return rows


def analyze_executed(rows: List[Dict[str, Any]], now_ms: int) -> Dict[str, Any]:
    null_sid = sum(1 for r in rows if r.get("signal_id") in (None, "", "null"))
    null_conf = sum(1 for r in rows if r.get("confidence") is None)
    oids: List[str] = []
    for r in rows:
        oid = r.get("exchange_order_id")
        if oid is not None and str(oid).strip():
            oids.append(str(oid))
    dup = sum(1 for c in Counter(oids).values() if c > 1)
    cross = 0
    high_lev = 0
    latencies: List[int] = []
    risk_addish = 0
    stale_exec = 0
    adj_in_stream = 0

    for r in rows:
        act = str(r.get("action") or r.get("action_name") or "").upper()
        if any(x in act for x in ("OPEN_", "INCREASE_", "ADD_")) and r.get("success"):
            risk_addish += 1
        if "ADJUST_LEVERAGE" in act:
            adj_in_stream += 1
        pb = r.get("pos_before") or {}
        if isinstance(pb, dict):
            mt = str(pb.get("margin_type") or "").lower()
            if mt == "cross":
                cross += 1
            try:
                lv = float(pb.get("leverage") or 0)
                if lv >= 25:
                    high_lev += 1
            except (TypeError, ValueError):
                pass
        lm = r.get("latency_ms")
        if lm is not None:
            try:
                latencies.append(int(lm))
            except (TypeError, ValueError):
                pass
        ts = r.get("ts_ms")
        if ts is not None:
            try:
                age = now_ms - int(ts)
                if age > 300_000:
                    stale_exec += 1
            except (TypeError, ValueError):
                pass

    lat_buckets = Counter()
    for ms in latencies:
        if ms <= 0:
            lat_buckets["0"] += 1
        elif ms <= 5_000:
            lat_buckets["1-5s"] += 1
        elif ms <= 30_000:
            lat_buckets["5-30s"] += 1
        elif ms <= 300_000:
            lat_buckets["30-300s"] += 1
        else:
            lat_buckets[">300s"] += 1

    return {
        "executed_sample_size": len(rows),
        "missing_signal_id": null_sid,
        "missing_confidence": null_conf,
        "duplicate_exchange_order_id_rows": dup,
        "cross_margin_pos_before_hits": cross,
        "high_leverage_pos_ge_25": high_lev,
        "latency_buckets": dict(lat_buckets),
        "risk_add_like_success_rows": risk_addish,
        "adjust_leverage_rows": adj_in_stream,
        "stale_executed_ts_ms_gt_5m": stale_exec,
    }


def sample_primary_signals(rows: List[Dict[str, Any]], now_ms: int) -> Dict[str, Any]:
    stale = 0
    missing_sid = 0
    for r in rows:
        if not r.get("signal_id"):
            missing_sid += 1
        ts = r.get("ts_ms") or r.get("published_ts_ms") or r.get("_received_ts_ms")
        if ts is not None:
            try:
                if now_ms - int(ts) > 120_000:
                    stale += 1
            except (TypeError, ValueError):
                pass
    return {"primary_sample": len(rows), "primary_missing_signal_id": missing_sid, "primary_stale_gt_2m": stale}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration-hours", type=float, default=12.0)
    ap.add_argument("--interval-seconds", type=int, default=60)
    ap.add_argument("--output-dir", default="./claude_worklog/monitoring")
    args = ap.parse_args()

    out_dir = os.path.abspath(args.output_dir)
    os.makedirs(out_dir, exist_ok=True)
    jsonl_path = os.path.join(out_dir, "snapshots.jsonl")
    summary_path = os.path.join(out_dir, "..", "monitoring_summary.md")
    summary_path = os.path.normpath(summary_path)

    end = time.time() + float(args.duration_hours) * 3600.0
    tick = 0

    def write_summary(reason: str) -> None:
        lines = [
            "# Read-only monitoring summary",
            "",
            f"- **Finished:** {datetime.now(timezone.utc).isoformat()}",
            f"- **Reason:** {reason}",
            f"- **REDIS_URL:** set (not printed)",
            "",
            "See `monitoring/snapshots.jsonl` for per-tick JSON.",
            "",
            "To analyze counts across ticks, use `jq` or a small Python script.",
        ]
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def handle_stop(*_a):
        write_summary("signal")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    while time.time() < end:
        tick += 1
        now_ms = int(time.time() * 1000)
        rec: Dict[str, Any] = {
            "tick": tick,
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "redis_url_set": bool(os.environ.get("REDIS_URL")),
        }

        ok_ping, ping_out = redis_cmd("PING")
        rec["redis_ping_ok"] = ok_ping
        if not ok_ping:
            rec["redis_error"] = _redact(ping_out[:500])

        lengths = {}
        for s in STREAMS:
            lengths[s] = xlen(s)
        rec["stream_xlen"] = lengths

        hb = {}
        for k in HEARTBEAT_KEYS:
            ok, v = redis_cmd("GET", k)
            hb[k] = {"ok": ok, "value": _redact(v[:500] if v else "")}
        rec["heartbeats"] = hb

        exec_rows = xrevrange_json("executed_signals", 400)
        rec["executed_analysis"] = analyze_executed(exec_rows, now_ms)

        prim = xrevrange_json("signals:trading:primary", 80)
        rec["primary_signal_analysis"] = sample_primary_signals(prim, now_ms)

        skips = xrevrange_json("signals:execution:skips", 40)
        rec["recent_skips_sample"] = len(skips)

        with open(jsonl_path, "a", encoding="utf-8") as jf:
            jf.write(json.dumps(_redact(rec), separators=(",", ":")) + "\n")

        time.sleep(max(5, int(args.interval_seconds)))

    write_summary("duration_complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
